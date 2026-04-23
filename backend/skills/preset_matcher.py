"""
PresetMatcher — 用关键词评分从用户对话推荐 preset

借鉴自 MagicAI 的 match_template_by_description()（godot_models.py:286）。
评分规则在 backend/skills/rules/presets.yaml 里显式声明（不 hardcode）。

典型用法：
    from skills import preset_matcher
    matches = preset_matcher.match("帮我做个 UE5 平台跳跃游戏")
    # [PresetMatch(preset_id='ue5-game', score=25, ...), ...]

调用来源：
- ChatAssistantAgent.chat_global() —— 预计算 top-3 注入到 system prompt，给 LLM 作为推荐候选
- Preview Assembly API —— 用户直接通过 API 查询推荐
- 前端新建项目卡片（可选）—— 在用户描述框旁实时显示匹配的 preset
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

import yaml

logger = logging.getLogger("skills.preset_matcher")


# CJK 字符正则（粗粒度判断 keyword 是中文还是拉丁）
_CJK_RE = re.compile(r"[㐀-鿿豈-﫿]")


def _is_cjk(text: str) -> bool:
    """包含任一 CJK 字符就视为 CJK 关键词"""
    return bool(_CJK_RE.search(text))


@dataclass
class PresetMatch:
    """单次 preset 匹配结果"""
    preset_id: str
    label: str
    score: int
    traits: List[str]
    matched_keywords: List[str] = field(default_factory=list)  # 命中的关键词
    conflict_penalties: List[str] = field(default_factory=list)  # 触发的冲突规则描述

    def to_dict(self) -> Dict[str, Any]:
        return {
            "preset_id": self.preset_id,
            "label": self.label,
            "score": self.score,
            "traits": self.traits,
            "matched_keywords": self.matched_keywords,
            "conflict_penalties": self.conflict_penalties,
        }


class PresetMatcher:
    """单例，启动时加载 presets.yaml 一次"""

    def __init__(self, presets_path: Optional[Path] = None):
        self.presets_path = presets_path or (
            Path(__file__).parent / "rules" / "presets.yaml"
        )
        self.presets: Dict[str, Dict[str, Any]] = {}
        self.conflict_rules: List[Dict[str, Any]] = []
        self.matching_config: Dict[str, Any] = {
            "min_score": 5,
            "cjk_keyword_score": 5,
            "latin_keyword_word_boundary": 5,
            "latin_keyword_substring": 3,
            "label_fragment_score": 3,
        }
        self._load()

    def _load(self) -> None:
        if not self.presets_path.exists():
            logger.info("presets.yaml 不存在，PresetMatcher 未启用")
            return

        try:
            data = yaml.safe_load(self.presets_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("加载 presets.yaml 失败: %s", e)
            return

        self.presets = data.get("presets", {}) or {}
        self.conflict_rules = data.get("conflict_rules", []) or []
        if "matching" in data:
            self.matching_config.update(data["matching"])

        logger.info(
            "✅ PresetMatcher 已加载: %d 个 preset, %d 条冲突规则",
            len(self.presets),
            len(self.conflict_rules),
        )

    def match(self, user_text: str, top_n: int = 3) -> List[PresetMatch]:
        """用 user_text 评分所有 preset，返回 score ≥ min_score 的 top_n"""
        if not user_text or not self.presets:
            return []

        text_lower = user_text.lower()
        min_score = self.matching_config["min_score"]

        results: List[PresetMatch] = []
        for pid, cfg in self.presets.items():
            score, matched, conflicts = self._score_preset(
                user_text, text_lower, pid, cfg
            )
            if score >= min_score:
                results.append(PresetMatch(
                    preset_id=pid,
                    label=cfg.get("label", pid),
                    score=score,
                    traits=list(cfg.get("traits", [])),
                    matched_keywords=matched,
                    conflict_penalties=conflicts,
                ))

        results.sort(key=lambda m: m.score, reverse=True)
        return results[:top_n]

    def _score_preset(
        self,
        user_text: str,
        text_lower: str,
        preset_id: str,
        preset_cfg: Dict[str, Any],
    ) -> tuple[int, List[str], List[str]]:
        """对单个 preset 打分。返回 (score, matched_keywords, conflict_penalties)"""
        cfg = self.matching_config
        cjk_score = cfg["cjk_keyword_score"]
        latin_wb_score = cfg["latin_keyword_word_boundary"]
        latin_sub_score = cfg["latin_keyword_substring"]
        label_frag_score = cfg["label_fragment_score"]

        score = 0
        matched: List[str] = []

        # 1. keywords 命中
        for kw in preset_cfg.get("keywords", []):
            kw_str = str(kw).strip()
            if not kw_str:
                continue

            if _is_cjk(kw_str):
                # CJK 子串精确匹配
                if kw_str in user_text:
                    score += cjk_score
                    matched.append(f"{kw_str} (+{cjk_score})")
            else:
                # 拉丁：先试 word boundary，再试 substring
                # 注意：word boundary 正则对纯字母数字串有意义；对包含空格/符号的关键词
                # （如 "web game"）用子串更合适
                kw_low = kw_str.lower()
                if " " in kw_low or "-" in kw_low:
                    # 含分隔符的短语，只做 substring
                    if kw_low in text_lower:
                        score += latin_wb_score
                        matched.append(f"{kw_str} (+{latin_wb_score})")
                else:
                    pattern_wb = r"\b" + re.escape(kw_low) + r"\b"
                    if re.search(pattern_wb, text_lower):
                        score += latin_wb_score
                        matched.append(f"{kw_str} (+{latin_wb_score})")
                    elif len(kw_low) >= 2 and kw_low in text_lower:
                        # 门槛 2（支持 H5 / UE / UI / AI 这类短技术缩写）
                        score += latin_sub_score
                        matched.append(f"{kw_str} (+{latin_sub_score}, substr)")

        # 2. label 分词命中（按空格 / 逗号 / 破折号切）
        label = preset_cfg.get("label", "")
        for frag in re.split(r"[\s,，、\-_/（）()]+", label):
            frag = frag.strip()
            if len(frag) < 2:
                continue
            if _is_cjk(frag):
                if frag in user_text:
                    score += label_frag_score
                    matched.append(f"label:{frag} (+{label_frag_score})")
            else:
                if frag.lower() in text_lower:
                    score += label_frag_score
                    matched.append(f"label:{frag} (+{label_frag_score})")

        # 3. 冲突规则扣分
        conflicts: List[str] = []
        for rule in self.conflict_rules:
            if self._rule_applies(rule, user_text, text_lower, preset_id, preset_cfg):
                penalty = rule.get("penalty", 0)
                score += penalty  # penalty 是负数
                conflicts.append(
                    f"{rule.get('user_mentions', '?')} × {preset_id} ({penalty:+d})"
                )

        return score, matched, conflicts

    def _rule_applies(
        self,
        rule: Dict[str, Any],
        user_text: str,
        text_lower: str,
        preset_id: str,
        preset_cfg: Dict[str, Any],
    ) -> bool:
        """判断冲突规则是否触发（用户提到了 A，preset 符合 B）"""
        mentions = rule.get("user_mentions", []) or []
        if not mentions:
            return False

        # 防 blanket penalty：必须至少有一个 preset 侧条件
        has_preset_cond = any(rule.get(k) for k in (
            "preset_traits_has_all",
            "preset_traits_has_any",
            "preset_traits_has_none",
            "preset_has_keywords_like",
        ))
        if not has_preset_cond:
            logger.warning("Conflict rule 缺 preset 侧条件，跳过: %s", rule)
            return False

        # user_mentions 命中（任一）
        hit = False
        for m in mentions:
            m_str = str(m).strip()
            if not m_str:
                continue
            if _is_cjk(m_str):
                if m_str in user_text:
                    hit = True
                    break
            else:
                if m_str.lower() in text_lower:
                    hit = True
                    break
        if not hit:
            return False

        traits_set = set(preset_cfg.get("traits", []))

        # preset_traits_has_all：preset 必须包含这些 trait
        has_all = rule.get("preset_traits_has_all", []) or []
        if has_all and not all(t in traits_set for t in has_all):
            return False

        # preset_traits_has_any：preset 包含任一
        has_any = rule.get("preset_traits_has_any", []) or []
        if has_any and not any(t in traits_set for t in has_any):
            return False

        # preset_traits_has_none：preset 不能包含任一
        has_none = rule.get("preset_traits_has_none", []) or []
        if has_none and any(t in traits_set for t in has_none):
            return False

        # preset_has_keywords_like：preset 的 keywords 里某个包含这些子串
        has_kw_like = rule.get("preset_has_keywords_like", []) or []
        if has_kw_like:
            preset_keywords_concat = " ".join(str(k) for k in preset_cfg.get("keywords", []))
            preset_label = str(preset_cfg.get("label", ""))
            preset_text = (preset_keywords_concat + " " + preset_label).lower()
            if not any(str(k).lower() in preset_text for k in has_kw_like):
                return False

        return True

    def reload(self) -> None:
        """重新加载 presets.yaml（供调试 / 热更新）"""
        self.presets = {}
        self.conflict_rules = []
        self._load()


# 单例：进程启动时加载一次
preset_matcher = PresetMatcher()
