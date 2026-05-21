"""AICREngine — 两场景代码审查引擎

AutoAICR: 编辑完成后轻量检查（行为约束）
PreCommit: 提交前完整 bug pattern 扫描
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .scene import AICRScene, AICRResult, AICRIssue

logger = logging.getLogger("aicr")

_RULES_DIR = Path(__file__).parent.parent / "skills" / "rules" / "workflow"

_AUTOAICR_SYSTEM = """你是一个代码质量检查助手。请对下面的代码变更做轻量自检，只关注以下几类行为问题：

{rules}

## 输出格式

如果发现问题，用 JSON 输出：
{{
  "issues": [
    {{"rule": "keep-scope", "message": "具体描述", "severity": "warning"}},
    ...
  ],
  "suggestions": []
}}

如果没有发现问题，输出：
{{"issues": [], "suggestions": []}}

不要解释，只输出 JSON。"""

_PRECOMMIT_SYSTEM = """你是一个代码安全和质量审查专家。请对下面的 staged diff 做完整扫描，检查常见 bug pattern：

{rules}

## 输出格式

用 JSON 输出：
{{
  "issues": [
    {{"rule": "null-deref", "message": "src/foo.cpp:42 — GetComponent 返回值未检查", "severity": "error"}},
    ...
  ],
  "suggestions": [
    {{"rule": "test-coverage", "message": "新增函数缺少测试", "severity": "suggestion"}}
  ]
}}

没有问题时对应列表为空。不要解释，只输出 JSON。"""


class AICREngine:
    """AICR 审查引擎（stateless，可复用）"""

    def __init__(self) -> None:
        self._autoaicr_rules = self._load_rules("autoaicr.md")
        self._precommit_rules = self._load_rules("precommit.md")

    def _load_rules(self, filename: str) -> str:
        path = _RULES_DIR / filename
        if not path.exists():
            return ""
        from skills.loader import _parse_frontmatter
        text = path.read_text(encoding="utf-8")
        _, body = _parse_frontmatter(text)
        return body.strip()

    async def run_autoaicr(
        self,
        diff: str,
        file_paths: list[str] | None = None,
        project_traits: list[str] | None = None,
        project_id: Optional[str] = None,
    ) -> AICRResult:
        """AutoAICR：diff + 行为约束规则 → 轻量 LLM 审查"""
        if not diff or not diff.strip():
            return AICRResult(scene=AICRScene.AUTOAICR, passed=True)

        extra_rules = await self._load_project_rules("autoaicr", project_id)
        rules_text = "\n\n".join(filter(None, [self._autoaicr_rules, extra_rules]))

        system = _AUTOAICR_SYSTEM.format(rules=rules_text or "（使用默认行为约束）")
        files_hint = f"\n\n变更文件：{', '.join(file_paths)}" if file_paths else ""
        user_msg = f"请审查以下代码变更：{files_hint}\n\n```diff\n{diff[:8000]}\n```"

        return await self._call_llm(AICRScene.AUTOAICR, system, user_msg)

    async def run_precommit(
        self,
        staged_diff: str,
        project_traits: list[str] | None = None,
        project_id: Optional[str] = None,
    ) -> AICRResult:
        """PreCommit：staged diff + 完整规则集 → 深度审查"""
        if not staged_diff or not staged_diff.strip():
            return AICRResult(scene=AICRScene.PRECOMMIT, passed=True)

        extra_rules = await self._load_project_rules("precommit", project_id)
        rules_text = "\n\n".join(filter(None, [self._precommit_rules, extra_rules]))

        system = _PRECOMMIT_SYSTEM.format(rules=rules_text or "（使用默认 bug pattern 检查）")
        user_msg = f"请审查以下 staged diff：\n\n```diff\n{staged_diff[:12000]}\n```"

        return await self._call_llm(AICRScene.PRECOMMIT, system, user_msg)

    async def _load_project_rules(self, scene: str, project_id: Optional[str]) -> str:
        if not project_id:
            return ""
        try:
            from database import db
            row = await db.fetch_one("SELECT git_repo_path FROM projects WHERE id = ?", (project_id,))
            repo_path = row.get("git_repo_path", "") if row else ""
            if not repo_path:
                return ""
            from skills import skill_loader
            return skill_loader.load_project_rules(repo_path, scene=scene)
        except Exception as e:
            logger.debug("加载项目 AICR 规则失败: %s", e)
            return ""

    async def _call_llm(self, scene: AICRScene, system: str, user_msg: str) -> AICRResult:
        try:
            from llm_client import llm_client
            import json as _json

            messages = [
                {"role": "user", "content": user_msg},
            ]
            raw = await llm_client.chat(
                messages,
                system=system,
                temperature=0.1,
                max_tokens=2048,
            )
            raw = raw.strip()
            # 去掉可能的 markdown 代码块
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1]
                if raw.endswith("```"):
                    raw = raw[:-3].rstrip()

            data = _json.loads(raw)
            issues = [AICRIssue(**i) for i in data.get("issues", [])]
            suggestions = [AICRIssue(**s) for s in data.get("suggestions", [])]
            passed = not any(i.severity == "error" for i in issues)
            return AICRResult(
                scene=scene,
                issues=issues,
                suggestions=suggestions,
                passed=passed,
                raw_response=raw,
            )
        except Exception as e:
            logger.warning("AICR LLM 调用失败 (scene=%s): %s", scene, e)
            return AICRResult(scene=scene, passed=True, raw_response=str(e))
