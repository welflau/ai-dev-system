"""
ReadRepoFileAction — 读取项目仓库内文件（供 OpenSpec Apply 等 SkillRunner 使用）。

相对 repo_path 读文本；禁止凭证类文件；内容截断。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.read_repo_file")

MAX_CHARS = 16000
_BLOCKED_NAMES = {
    ".env", ".env.local", ".env.production",
    "credentials", "secrets", "id_rsa", "id_ed25519",
}
_BLOCKED_SUFFIXES = {".pem", ".key", ".pfx", ".p12", ".cer"}


class ReadRepoFileAction(ActionBase):

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return ("读取仓库内文件内容。path 相对仓库根，如 openspec/changes/c-xxx/tasks.md "
                "或 Source/Foo.cpp。用于 Apply 前阅读规范/现有代码。")

    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对仓库根的路径"},
                },
                "required": ["path"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        repo = context.get("repo_path")
        if not repo or not Path(repo).is_dir():
            return ActionResult(success=False, error="缺少有效 repo_path")
        rel = (context.get("path") or "").strip().replace("\\", "/").lstrip("/")
        if not rel or ".." in rel.split("/"):
            return ActionResult(success=False, error="非法 path")

        root = Path(repo).resolve()
        target = (root / rel).resolve()
        try:
            target.relative_to(root)
        except ValueError:
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
