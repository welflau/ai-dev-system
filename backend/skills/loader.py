"""
SkillLoader — 三层过滤 + rules + 分组压制（v0.17 重构版）

三层过滤：
  1. inject_to: [AgentName]         Agent 级 —— 谁需要这块知识
  2. traits_match: {all_of/any_of/none_of}   项目级 —— 适用于什么项目
  3. paths: [glob, ...]              文件级（可选）—— 处理什么文件时注入

全局 rules：
  backend/skills/rules/*.md 文件（YAML frontmatter 带 alwaysApply / traits_match / paths）
  alwaysApply: true 的 rule 对所有 Agent/项目/文件永远注入
  这里只放**跟技术栈无关**的准则（语言一致性、命名、文档、保密）

分组压制：
  skill.json 里可声明 `group`，同组内只保留 priority 最高的一个
  例：godot-multiplayer (priority high, group:multiplayer-knowledge) 压制
       multiplayer-networking (priority medium, 同 group)

兼容旧 skill.json：无 traits_match/paths/group 字段的 skill 视为"对所有项目/文件可用"
"""
from __future__ import annotations

import fnmatch
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Iterable, Set, Tuple

logger = logging.getLogger("skills")

_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


class SkillLoader:
    """Skills 加载器 —— 单例，进程启动时加载一次"""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or Path(__file__).parent
        self.config_path = self.base_dir / "skills.json"
        self.rules_dir = self.base_dir / "rules"

        self.skills: Dict[str, dict] = {}
        # rules: {rule_id -> {content, alwaysApply, traits_match, paths, priority}}
        self.rules: Dict[str, dict] = {}
        # marketplace_index: skill_id → SKILL.md 绝对路径（scan_dir 扫描时填充）
        self._marketplace_index: Dict[str, Path] = {}

        # 缓存 (agent_type, traits_hash, current_file) -> 拼接后的 prompt
        self._agent_prompt_cache: Dict[Tuple[str, tuple, str], str] = {}
        self._load_config()
        self._load_rules()
        self._scan_marketplace_dirs()

    def _load_config(self) -> None:
        """从 skills.json 读取配置；文件不存在时静默跳过"""
        if not self.config_path.exists():
            logger.info("skills.json 不存在，Skills 系统未启用")
            return

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.skills = json.load(f)
        except Exception as e:
            logger.warning("加载 skills.json 失败: %s", e)
            self.skills = {}
            return

        enabled = [k for k, v in self.skills.items() if v.get("enabled", False)]
        logger.info("✅ Skills 已加载: %d 条（启用 %d）", len(self.skills), len(enabled))

    def _load_rules(self) -> None:
        """从 rules/*.md 扫描全局规则。每个 md 文件的 YAML frontmatter 声明适用范围。"""
        if not self.rules_dir.exists():
            return

        for md_file in sorted(self.rules_dir.glob("*.md")):
            try:
                text = md_file.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning("读取 rules/%s 失败: %s", md_file.name, e)
                continue

            frontmatter, body = _parse_frontmatter(text)
            rule_id = md_file.stem
            self.rules[rule_id] = {
                "content": body.strip(),
                "alwaysApply": bool(frontmatter.get("alwaysApply", False)),
                "traits_match": frontmatter.get("traits_match") or {},
                "paths": frontmatter.get("paths") or [],
                "priority": frontmatter.get("priority", "medium"),
                "description": frontmatter.get("description", ""),
            }
        if self.rules:
            always = [k for k, v in self.rules.items() if v["alwaysApply"]]
            logger.info("✅ Rules 已加载: %d 条（alwaysApply %d）", len(self.rules), len(always))

    # ==================== 三层过滤（核心变动）====================

    def get_skills_for_agent(
        self,
        agent_type: str,
        traits: Optional[Iterable[str]] = None,
        current_file: Optional[str] = None,
    ) -> List[str]:
        """返回适用于指定 Agent + traits + file 的 skill_id 列表。

        三层过滤 + 分组压制 + priority 排序。
        """
        traits_set = set(traits or [])
        applicable: List[str] = []

        for skill_id, cfg in self.skills.items():
            if not cfg.get("enabled", False):
                continue
            # Layer 1: Agent 级
            if agent_type not in cfg.get("inject_to", []):
                continue
            # Layer 2: 项目级（traits_match）
            if not _match_traits(cfg.get("traits_match"), traits_set):
                continue
            # Layer 3: 文件级（paths）
            if current_file and cfg.get("paths"):
                if not _match_paths(current_file, cfg["paths"]):
                    continue
            applicable.append(skill_id)

        # 分组压制：同 group 只保留 priority 最高的一个
        applicable = self._apply_group_suppression(applicable)

        # 按 priority 排序（high → medium → low）
        applicable.sort(
            key=lambda sid: _PRIORITY_ORDER.get(self.skills[sid].get("priority", "medium"), 1),
        )
        return applicable

    def _apply_group_suppression(self, skill_ids: List[str]) -> List[str]:
        """同 group 只保留 priority 最高的一个。无 group 的 skill 不受影响。"""
        by_group: Dict[str, List[str]] = {}
        no_group: List[str] = []

        for sid in skill_ids:
            group = self.skills[sid].get("group")
            if group:
                by_group.setdefault(group, []).append(sid)
            else:
                no_group.append(sid)

        kept = list(no_group)
        for group_name, members in by_group.items():
            # priority 最高 → 数字最小
            winner = min(
                members,
                key=lambda sid: _PRIORITY_ORDER.get(
                    self.skills[sid].get("priority", "medium"), 1
                ),
            )
            losers = [m for m in members if m != winner]
            if losers:
                logger.debug(
                    "分组 %s: %s 压制 %s", group_name, winner, ", ".join(losers)
                )
            kept.append(winner)
        return kept

    def get_rules_for_context(
        self,
        traits: Optional[Iterable[str]] = None,
        current_file: Optional[str] = None,
    ) -> List[str]:
        """返回适用于当前 traits + file 的 rule_id 列表。

        alwaysApply=true 的 rule 对所有场景生效。
        有 traits_match / paths 的 rule 按对应条件过滤。
        """
        traits_set = set(traits or [])
        applicable: List[str] = []
        for rule_id, cfg in self.rules.items():
            if cfg["alwaysApply"]:
                applicable.append(rule_id)
                continue
            # 否则按 traits_match / paths 过滤
            if cfg["traits_match"] and not _match_traits(cfg["traits_match"], traits_set):
                continue
            if current_file and cfg["paths"] and not _match_paths(current_file, cfg["paths"]):
                continue
            applicable.append(rule_id)
        applicable.sort(
            key=lambda rid: _PRIORITY_ORDER.get(self.rules[rid].get("priority", "medium"), 1),
        )
        return applicable

    # ==================== 生成最终 prompt ====================

    def build_prompt_for_agent(
        self,
        agent_type: str,
        traits: Optional[Iterable[str]] = None,
        current_file: Optional[str] = None,
    ) -> str:
        """组合规则 + skills，返回注入 system prompt 的文本。

        空字符串表示这个 Agent 在此上下文下没有任何可注入内容。
        """
        traits_tuple = tuple(sorted(traits or []))
        cache_key = (agent_type, traits_tuple, current_file or "")
        if cache_key in self._agent_prompt_cache:
            return self._agent_prompt_cache[cache_key]

        rule_ids = self.get_rules_for_context(traits, current_file)
        skill_ids = self.get_skills_for_agent(agent_type, traits, current_file)

        sections: List[str] = []
        loaded_rules: List[str] = []
        loaded_skills: List[str] = []

        # Rules 在前（全局约束），Skills 在后（专业知识）
        for rid in rule_ids:
            content = self.rules[rid]["content"]
            if content:
                sections.append(f"<!-- Rule: {rid} -->\n{content}")
                loaded_rules.append(rid)

        for sid in skill_ids:
            content = self.get_skill_prompt(sid)
            if content:
                name = self.skills[sid].get("name", sid)
                sections.append(f"<!-- Skill: {sid} ({name}) -->\n{content}")
                loaded_skills.append(sid)

        if not sections:
            self._agent_prompt_cache[cache_key] = ""
            return ""

        prompt = "\n\n---\n\n".join(sections)
        self._agent_prompt_cache[cache_key] = prompt
        logger.info(
            "🎓 %s 加载: rules=[%s] skills=[%s] (traits=%s file=%s)",
            agent_type,
            ", ".join(loaded_rules) or "-",
            ", ".join(loaded_skills) or "-",
            list(traits or []),
            current_file or "-",
        )
        return prompt

    def build_index_for_agent(
        self,
        agent_type: str,
        traits: Optional[Iterable[str]] = None,
    ) -> str:
        """生成 Skill 索引表（只含名称+描述+触发场景，不含全文）。

        用于主动触发架构：system prompt 只注入索引，AI 按需调用 load_skill 加载全文。
        返回空字符串表示无可用 Skill。
        """
        skill_ids = self.get_skills_for_agent(agent_type, traits)
        if not skill_ids:
            return ""

        rows = []
        for sid in skill_ids:
            cfg = self.skills.get(sid, {})
            if not cfg.get("enabled", True):
                continue
            name = cfg.get("name", sid)
            desc = cfg.get("description", "")
            rows.append(f"| `{sid}` | {name} | {desc} |")

        if not rows:
            return ""

        header = "| Skill ID | 名称 | 适用场景 |\n|---|---|---|"
        return header + "\n" + "\n".join(rows)

    def _scan_marketplace_dirs(self) -> None:
        """扫描所有 scan_dir 条目，将每个 SKILL.md 注册到 _marketplace_index。

        index key = frontmatter 中的 name 字段（或目录名），供 load_skill 按 ID 加载。
        同时把每个 marketplace skill 作为虚拟条目注入 self.skills，
        参与三层过滤和 build_index_for_agent 索引生成。
        """
        for entry_id, cfg in list(self.skills.items()):
            if cfg.get("type") != "scan_dir":
                continue
            scan_rel = cfg.get("scan_dir")
            if not scan_rel:
                continue
            scan_dir = (self.base_dir / scan_rel).resolve()
            if not scan_dir.exists():
                continue

            inject_to = cfg.get("inject_to", ["ChatAssistant"])
            traits_match = cfg.get("traits_match") or {}

            for skill_md in sorted(scan_dir.rglob("SKILL.md")):
                try:
                    text = skill_md.read_text(encoding="utf-8")
                except Exception:
                    continue
                fm, _ = _parse_frontmatter(text)
                skill_name = fm.get("name") or skill_md.parent.name
                desc = fm.get("description") or ""

                # 注册到 _marketplace_index（供 get_skill_prompt 单独加载）
                self._marketplace_index[skill_name] = skill_md

                # 注入 self.skills 作为虚拟条目（参与索引生成和三层过滤）
                if skill_name not in self.skills:
                    self.skills[skill_name] = {
                        "name": skill_name,
                        "description": desc[:200],
                        "type": "marketplace_item",
                        "file_path": str(skill_md),
                        "inject_to": inject_to,
                        "traits_match": traits_match,
                        "priority": cfg.get("priority", "medium"),
                        "enabled": cfg.get("enabled", True),
                        "prompt_file": None,
                        "paths": [],
                        "group": None,
                    }

        if self._marketplace_index:
            logger.info("📦 Marketplace Skills: %d 个已注册 (%s)",
                        len(self._marketplace_index),
                        ", ".join(list(self._marketplace_index.keys())[:5]))

    def get_skill_prompt(self, skill_id: str) -> Optional[str]:
        """读取单个 skill 的 prompt 内容；禁用 / 文件缺失时返回 None。

        支持三种类型：
        - prompt_file（默认）：读取指定 .md 文件
        - type: "scan_dir"  ：扫描目录下所有 SKILL.md，生成技能索引表
        - type: "marketplace_item"：直接读取 SKILL.md 全文（供 load_skill 按需加载）
        """
        config = self.skills.get(skill_id)
        if not config or not config.get("enabled", False):
            # 再查 marketplace_index（不受 skills.json enabled 限制的直接加载）
            if skill_id in self._marketplace_index:
                path = self._marketplace_index[skill_id]
                try:
                    return path.read_text(encoding="utf-8").strip()
                except Exception as e:
                    logger.warning("读取 marketplace Skill '%s' 失败: %s", skill_id, e)
            return None

        if config.get("type") == "scan_dir":
            return self._build_scan_dir_prompt(skill_id, config)

        if config.get("type") == "marketplace_item":
            file_path = config.get("file_path")
            if not file_path:
                return None
            try:
                return Path(file_path).read_text(encoding="utf-8").strip()
            except Exception as e:
                logger.warning("读取 marketplace_item '%s' 失败: %s", skill_id, e)
                return None

        prompt_rel = config.get("prompt_file")
        if not prompt_rel:
            logger.warning("Skill '%s' 未配置 prompt_file", skill_id)
            return None

        prompt_file = self.base_dir / prompt_rel
        if not prompt_file.exists():
            logger.warning("Skill '%s' 的 prompt 文件不存在: %s", skill_id, prompt_file)
            return None

        try:
            return prompt_file.read_text(encoding="utf-8").strip()
        except Exception as e:
            logger.warning("读取 Skill '%s' 失败: %s", skill_id, e)
            return None

    def _build_scan_dir_prompt(self, skill_id: str, config: dict) -> Optional[str]:
        """scan_dir 类型：扫描目录下的 SKILL.md，生成技能索引 + 使用说明。

        每个子目录下的 SKILL.md frontmatter 里需有 name 和 description 字段。
        生成的 prompt 告诉 AI：有哪些 skill 可用、路径是什么、如何按需加载。
        """
        scan_rel = config.get("scan_dir")
        if not scan_rel:
            logger.warning("Skill '%s' scan_dir 未配置", skill_id)
            return None

        scan_dir = (self.base_dir / scan_rel).resolve()
        if not scan_dir.exists():
            logger.warning("Skill '%s' scan_dir 不存在: %s", skill_id, scan_dir)
            return None

        header = config.get("header", "")
        rows: List[str] = []

        for skill_md in sorted(scan_dir.glob("*/SKILL.md")):
            try:
                text = skill_md.read_text(encoding="utf-8")
            except Exception:
                continue
            fm, _ = _parse_frontmatter(text)
            name = fm.get("name") or skill_md.parent.name
            desc = fm.get("description") or ""
            # 截断过长描述
            if len(desc) > 120:
                desc = desc[:117] + "..."
            rows.append(f"| `{name}` | {desc} | `{skill_md}` |")

        if not rows:
            logger.warning("Skill '%s' scan_dir 下未找到任何 SKILL.md", skill_id)
            return None

        lines = []
        if header:
            lines.append(header.strip())
            lines.append("")

        lines += [
            "## 可用 Skill 列表",
            "",
            "| Skill 名称 | 用途描述 | SKILL.md 路径 |",
            "|-----------|---------|--------------|",
        ] + rows + [
            "",
            "## 使用方式",
            "",
            "1. 根据用户意图从上表选择合适的 Skill",
            "2. 调用 `read_local_file` 工具传入对应路径，读取 SKILL.md 完整内容",
            "3. 按 SKILL.md 中的 API 说明，调用 `ue_call` 工具执行操作",
            "",
            "> 无需用户指定路径，AI 根据意图自主选择并加载对应 Skill。",
        ]

        logger.info("Skill '%s' scan_dir: 发现 %d 个 skill", skill_id, len(rows))
        return "\n".join(lines)

    # ==================== 调试 / 查询 ====================

    def get_enabled_skills(self) -> Dict[str, dict]:
        """返回所有启用的 Skills 配置"""
        return {k: v for k, v in self.skills.items() if v.get("enabled", False)}

    def get_all_skills_status(self) -> Dict[str, dict]:
        """每个 Skill 的状态（enabled / prompt 文件存在 / inject_to 列表 / traits_match / group）"""
        status = {}
        for sid, cfg in self.skills.items():
            skill_type = cfg.get("type", "")
            if skill_type == "marketplace_item":
                file_path = cfg.get("file_path")
                prompt_exists = bool(file_path and Path(file_path).exists())
            elif skill_type == "scan_dir":
                prompt_exists = True  # scan_dir 本身不是文件，视为有效
            else:
                prompt_rel = cfg.get("prompt_file", "")
                prompt_file = self.base_dir / prompt_rel if prompt_rel else None
                prompt_exists = bool(prompt_file and prompt_file.exists())

            status[sid] = {
                "name": cfg.get("name", sid),
                "description": cfg.get("description", ""),
                "enabled": cfg.get("enabled", False),
                "inject_to": cfg.get("inject_to", []),
                "priority": cfg.get("priority", "medium"),
                "prompt_exists": prompt_exists,
                "traits_match": cfg.get("traits_match") or {},
                "paths": cfg.get("paths") or [],
                "group": cfg.get("group"),
                "source": "marketplace" if skill_type == "marketplace_item" else "builtin",
            }
        return status

    def reload(self) -> None:
        """重新加载 skills.json + rules/*.md + marketplace（供热更新）"""
        self.skills = {}
        self.rules = {}
        self._marketplace_index = {}
        self._agent_prompt_cache.clear()
        self._load_config()
        self._load_rules()
        self._scan_marketplace_dirs()


# ==================== helper ====================

def _match_traits(match_cfg: Optional[dict], traits_set: Set[str]) -> bool:
    """判断 skill/rule 的 traits_match 是否适用于 project.traits。
    all_of: 全部命中；any_of: 任一命中；none_of: 都不命中。
    空配置 → 视为永远匹配（兼容旧 skill）。
    """
    if not match_cfg:
        return True
    all_of = match_cfg.get("all_of") or []
    any_of = match_cfg.get("any_of") or []
    none_of = match_cfg.get("none_of") or []

    if all_of and not all(t in traits_set for t in all_of):
        return False
    if any_of and not any(t in traits_set for t in any_of):
        return False
    if none_of and any(t in traits_set for t in none_of):
        return False
    return True


def _match_paths(current_file: str, patterns: List[str]) -> bool:
    """用 fnmatch glob 对 current_file 做匹配（跟 AgentHub paths: 语义一致）。"""
    if not patterns:
        return True
    norm = current_file.replace("\\", "/")
    for pat in patterns:
        p = str(pat).replace("\\", "/")
        if fnmatch.fnmatch(norm, p):
            return True
        # 支持 **/*.ext 这种跨目录匹配
        if fnmatch.fnmatch(norm.split("/")[-1], p):
            return True
    return False


_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def _parse_frontmatter(text: str) -> Tuple[dict, str]:
    """解析 YAML frontmatter + body。没有 frontmatter 时 body 是全文，frontmatter 为 {}。"""
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    fm_text, body = m.group(1), m.group(2)
    try:
        import yaml
        return yaml.safe_load(fm_text) or {}, body
    except Exception as e:
        logger.warning("frontmatter 解析失败: %s", e)
        return {}, body
