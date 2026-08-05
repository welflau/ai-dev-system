"""
WriteFileAction — 受限写文件工具（供 SkillRunner 里的 LLM 用来落盘产出）。

比让 LLM 用 shell 的 `echo >` 写文件可控得多：
  - skill 产出模式（默认）：只写到 outputs.root（context["_skill_output_root"]），默认仅 .md
  - repo 模式（Apply）：写到仓库根下任意相对路径，扩展名白名单更宽
  - 自动去掉 LLM 偶尔加的 ```lang ... ``` 围栏
  - 路径越界校验（relative_to）
  - 写入内容记入 context["_skill_written_files"] 供 orchestrator commit
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.write_file")

_DEFAULT_EXTS = {".md"}
_REPO_DEFAULT_EXTS = {
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".hxx", ".inl",
    ".cs", ".go", ".rs", ".java", ".kt",
    ".html", ".css", ".scss", ".less",
    ".gd", ".tscn", ".tres",
    ".csproj", ".uproject", ".Build.cs", ".Target.cs",
    ".cmake", ".sh", ".ps1", ".bat", ".cmd",
}


def _strip_fences(md: str) -> str:
    """去掉 LLM 偶尔套的 ```lang ... ``` 围栏。"""
    s = (md or "").strip()
    if s.startswith("```"):
        nl = s.find("\n")
        if nl > 0:
            s = s[nl + 1:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3].rstrip()
    return s


class WriteFileAction(ActionBase):

    def __init__(self, allowed_exts: List[str] = None, write_mode: str = "skill"):
        """
        write_mode:
          - "skill"：写 _skill_output_root（Propose 四件套）
          - "repo"：写 repo_path（Apply 实现代码 + 更新 tasks.md）
        """
        self._write_mode = write_mode or "skill"
        if allowed_exts is not None:
            self._exts: Set[str] = {e if e.startswith(".") else f".{e}" for e in allowed_exts}
        elif self._write_mode == "repo":
            self._exts = set(_REPO_DEFAULT_EXTS)
        else:
            self._exts = set(_DEFAULT_EXTS)

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        if self._write_mode == "repo":
            return ("把内容写入仓库文件。path 相对仓库根（如 Source/Foo.cpp 或 "
                    "openspec/changes/<id>/tasks.md）。完成任务后务必把 tasks.md 对应项改为 - [x]。")
        return ("把内容写入 skill 产出目录下的文件（如 proposal.md）。"
                "path 相对产出目录，只允许写声明的文件类型。")

    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": ("相对仓库根的路径" if self._write_mode == "repo"
                                             else "相对产出目录的文件名，如 proposal.md")},
                    "content": {"type": "string", "description": "文件完整内容"},
                },
                "required": ["path", "content"],
            },
        }

    def _resolve_root(self, context: Dict[str, Any]) -> Optional[Path]:
        if self._write_mode == "repo":
            repo = context.get("repo_path")
            if repo and Path(repo).is_dir():
                return Path(repo).resolve()
            return None
        root_raw = context.get("_skill_output_root")
        return Path(root_raw).resolve() if root_raw else None

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        root = self._resolve_root(context)
        if root is None:
            err = "缺少有效 repo_path" if self._write_mode == "repo" else "缺少产出目录（_skill_output_root）"
            return ActionResult(success=False, error=err)

        rel = (context.get("path") or "").strip().replace("\\", "/").lstrip("/")
        content = context.get("content")
        if not rel or ".." in rel.split("/"):
            return ActionResult(success=False, error="path 不能为空或含 ..")
        if content is None:
            return ActionResult(success=False, error="content 不能为空")

        target = (root / rel).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return ActionResult(success=False, error=f"path 越界: {rel}")

        # Build.cs / Target.cs 等多后缀：用完整后缀链匹配白名单
        suffix = target.suffix.lower()
        name_lower = target.name.lower()
        ok_ext = (
            suffix in self._exts
            or any(name_lower.endswith(e.lower()) for e in self._exts if e.count(".") > 1)
            or name_lower.endswith(".build.cs")
            or name_lower.endswith(".target.cs")
        )
        if not ok_ext:
            return ActionResult(
                success=False,
                error=f"不允许的文件类型 {suffix or name_lower}，仅 {sorted(self._exts)[:20]}…",
            )

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            cleaned = _strip_fences(str(content))
            target.write_text(cleaned, encoding="utf-8")
            # 供 orchestrator / DevAgent 收集 commit 文件
            written = context.setdefault("_skill_written_files", {})
            if isinstance(written, dict):
                written[rel] = cleaned
            logger.info("[write_file/%s] %s (%d 字节)", self._write_mode, rel, len(cleaned))
            return ActionResult(
                success=True,
                data={"type": "write_file", "path": rel, "bytes": len(cleaned), "mode": self._write_mode},
                files={rel: cleaned},
                message=f"已写入 {rel}（{len(cleaned)} 字节）",
            )
        except Exception as e:
            logger.error("[write_file] 写 %s 失败: %s", rel, e)
            return ActionResult(success=False, error=f"写文件失败: {e}")
