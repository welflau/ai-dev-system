"""
ReadRepoFileAction — 读取项目仓库内文件（供 OpenSpec Apply 等 SkillRunner 使用）。

相对 repo_path 读文本；禁止凭证类文件；内容截断。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.read_repo_file")

MAX_CHARS = 16000
_BLOCKED_NAMES = {
    ".env", ".env.local", ".env.production",
    "credentials", "secrets", "id_rsa", "id_ed25519",
}
_BLOCKED_SUFFIXES = {".pem", ".key", ".pfx", ".p12", ".cer"}


class ReadRepoFileAction(ActionBase):

    def __init__(self, extra_roots: Optional[List[Path]] = None):
        self._extra_roots = [Path(p).resolve() for p in (extra_roots or [])]

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        extra = (
            " 导演知识用 `director-knowledge/` 前缀，例如 "
            "director-knowledge/modes/animated-explainer/workflow.md。"
            if self._extra_roots else ""
        )
        return ("读取仓库内文件内容。path 相对仓库根，如 openspec/changes/c-xxx/tasks.md "
                "或 Source/Foo.cpp。" + extra)

    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对仓库根的路径，或 director-knowledge/ 下的知识文件"},
                },
                "required": ["path"],
            },
        }

    def _resolve_target(self, rel: str, repo: str) -> Optional[Path]:
        prefix = "director-knowledge/"
        if rel.startswith(prefix) and self._extra_roots:
            target = (self._extra_roots[0] / rel[len(prefix):]).resolve()
            try:
                target.relative_to(self._extra_roots[0])
            except ValueError:
                return None
            return target
        root = Path(repo).resolve()
        target = (root / rel).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return None
        return target

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        repo = context.get("repo_path")
        rel = (context.get("path") or "").strip().replace("\\", "/").lstrip("/")
        if not rel or ".." in rel.split("/"):
            return ActionResult(success=False, error="非法 path")
        knowledge_read = rel.startswith("director-knowledge/")
        if not knowledge_read and (not repo or not Path(repo).is_dir()):
            return ActionResult(success=False, error="缺少有效 repo_path")

        target = self._resolve_target(rel, repo or "")
        if target is None:
            return ActionResult(success=False, error=f"path 越界: {rel}")

        name_lower = target.name.lower()
        if name_lower in _BLOCKED_NAMES or target.suffix.lower() in _BLOCKED_SUFFIXES:
            return ActionResult(success=False, error=f"禁止读取敏感文件: {target.name}")
        if not target.is_file():
            return ActionResult(success=False, error=f"文件不存在: {rel}")

        try:
            text = target.read_text(encoding="utf-8", errors="replace")
            truncated = len(text) > MAX_CHARS
            if truncated:
                text = text[:MAX_CHARS] + f"\n\n…(已截断，共超 {MAX_CHARS} 字符)"
            return ActionResult(
                success=True,
                data={"path": rel, "truncated": truncated, "chars": len(text)},
                message=text,
            )
        except Exception as e:
            return ActionResult(success=False, error=f"读取失败: {e}")
