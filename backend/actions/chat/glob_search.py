"""
GlobAction — 用 glob 通配符在项目目录里查找文件
GrepAction — 用正则表达式搜索文件内容
ListDirectoryAction — 列出目录树结构
"""
import asyncio
import fnmatch
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.chat.glob_search")

MAX_RESULTS = 100
MAX_CONTENT_CHARS = 8000
FILE_IO_TIMEOUT = 20  # 秒，网络盘超时保护
_IGNORE_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv",
                "dist", "build", "DerivedDataCache", "Binaries", "Intermediate"}


async def _get_project_base(project_id: str) -> Path | None:
    """获取项目 git_repo_path，失败返回 None。"""
    if not project_id:
        return None
    try:
        from database import db
        row = await db.fetch_one("SELECT git_repo_path FROM projects WHERE id=?", (project_id,))
        if row and row.get("git_repo_path"):
            return Path(row["git_repo_path"])
    except Exception:
        pass
    return None


def _is_safe_path(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


# ── GlobAction ──────────────────────────────────────────────────────────────

class GlobAction(ActionBase):

    @property
    def name(self) -> str:
        return "glob"

    @property
    def description(self) -> str:
        return "用 glob 通配符在项目目录中查找文件"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "用 glob 通配符查找文件。支持任意绝对路径（如 G:/A_Works/... 或 C:/Users/...）。\n"
                "示例：pattern='**/*.py' 找所有 Python 文件，pattern='*.log' 找日志文件。\n"
                "path 可传绝对路径（如 G:/A_Works/OG2/BUG/2026-05-14_Crash），不传则用项目根目录。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "glob 通配符，如 **/*.py、Source/**/*.h、**/config*.json",
                    },
                    "base_dir": {
                        "type": "string",
                        "description": "搜索起始目录（相对项目根），默认为项目根目录",
                    },
                },
                "required": ["pattern"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        project_id = context.get("project_id")
        pattern    = (context.get("pattern") or "").strip()
        base_rel   = (context.get("base_dir") or "").strip()

        if not pattern:
            return ActionResult(success=False, error="pattern 不能为空")

        base = await _get_project_base(project_id)

        # 无项目时：若 base_dir 是绝对路径则直接使用
        if (not base or not base.exists()) and base_rel:
            abs_base = Path(base_rel)
            if abs_base.is_absolute() and abs_base.exists():
                base = abs_base
                base_rel = ""

        if not base or not base.exists():
            return ActionResult(success=False, error="未找到目录，请提供绝对路径（base_dir）或在项目内使用")

        search_dir = (base / base_rel).resolve() if base_rel else base.resolve()
        if not _is_safe_path(search_dir, base):
            return ActionResult(success=False, error="base_dir 超出项目目录范围")

        def _do_glob():
            matches = []
            for p in sorted(search_dir.rglob(pattern),
                            key=lambda x: x.stat().st_mtime if x.exists() else 0,
                            reverse=True):
                if any(part in _IGNORE_DIRS for part in p.parts):
                    continue
                if p.is_file():
                    try:
                        matches.append(str(p.relative_to(base)))
                    except ValueError:
                        matches.append(str(p))
                if len(matches) >= MAX_RESULTS:
                    break
            return matches

        loop = asyncio.get_event_loop()
        try:
            matches = await asyncio.wait_for(
                loop.run_in_executor(None, _do_glob),
                timeout=FILE_IO_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return ActionResult(success=False, error=f"Glob 搜索超时（>{FILE_IO_TIMEOUT}s），目录可能在慢速网络盘上")
        except Exception as e:
            return ActionResult(success=False, error=f"glob 搜索失败: {e}")

        if not matches:
            return ActionResult(
                success=True,
                data={"type": "glob_result", "files": [], "pattern": pattern},
                message=f"没有找到匹配 `{pattern}` 的文件",
            )

        return ActionResult(
            success=True,
            data={"type": "glob_result", "files": matches, "pattern": pattern,
                  "total": len(matches)},
            message=f"找到 {len(matches)} 个文件（匹配 `{pattern}`）",
        )


# ── GrepAction ──────────────────────────────────────────────────────────────

class GrepAction(ActionBase):

    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return "用正则表达式搜索项目文件内容"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "用正则表达式搜索项目文件中的文本内容。\n"
                "返回匹配行（文件名 + 行号 + 内容），最多 100 条。\n"
                "示例：搜索函数定义 `def.*chat`，搜索类名 `class.*Agent`"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "正则表达式，如 def.*chat、UCLASS|USTRUCT",
                    },
                    "path": {
                        "type": "string",
                        "description": "搜索路径（相对项目根，可以是目录或文件），默认项目根",
                    },
                    "include": {
                        "type": "string",
                        "description": "文件名通配过滤，如 *.py、*.cpp、*.ts",
                    },
                    "case_sensitive": {
                        "type": "boolean",
                        "description": "是否大小写敏感，默认 false",
                    },
                },
                "required": ["pattern"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        project_id = context.get("project_id")
        pattern    = (context.get("pattern") or "").strip()
        path_rel   = (context.get("path") or "").strip()
        include    = (context.get("include") or "").strip()
        case_sens  = bool(context.get("case_sensitive", False))

        if not pattern:
            return ActionResult(success=False, error="pattern 不能为空")

        base = await _get_project_base(project_id)

        # 无项目时：若 path 是绝对路径则直接使用
        if (not base or not base.exists()) and path_rel:
            abs_path = Path(path_rel)
            if abs_path.is_absolute() and abs_path.exists():
                base = abs_path.parent if abs_path.is_file() else abs_path
                path_rel = ""

        if not base or not base.exists():
            return ActionResult(success=False, error="未找到目录，请提供绝对路径（path）或在项目内使用")

        search_path = (base / path_rel).resolve() if path_rel else base.resolve()
        if not _is_safe_path(search_path, base):
            return ActionResult(success=False, error="path 超出项目目录范围")

        try:
            flags = 0 if case_sens else re.IGNORECASE
            regex = re.compile(pattern, flags)
        except re.error as e:
            return ActionResult(success=False, error=f"正则表达式无效: {e}")

        def _do_grep():
            results = []
            files_to_search = []
            if search_path.is_file():
                files_to_search = [search_path]
            else:
                for fp in search_path.rglob("*"):
                    if any(part in _IGNORE_DIRS for part in fp.parts):
                        continue
                    if not fp.is_file():
                        continue
                    if include and not fnmatch.fnmatch(fp.name, include):
                        continue
                    files_to_search.append(fp)

            for fp in files_to_search:
                if len(results) >= MAX_RESULTS:
                    break
                try:
                    text = fp.read_text(encoding="utf-8", errors="replace")
                    for lineno, line in enumerate(text.splitlines(), 1):
                        if regex.search(line):
                            try:
                                rel = str(fp.relative_to(base))
                            except ValueError:
                                rel = str(fp)
                            results.append({"file": rel, "line": lineno, "content": line.rstrip()[:200]})
                            if len(results) >= MAX_RESULTS:
                                break
                except Exception:
                    continue
            return results

        loop = asyncio.get_event_loop()
        try:
            results = await asyncio.wait_for(
                loop.run_in_executor(None, _do_grep),
                timeout=FILE_IO_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return ActionResult(success=False, error=f"Grep 搜索超时（>{FILE_IO_TIMEOUT}s），目录可能在慢速网络盘上")
        except Exception as e:
            return ActionResult(success=False, error=f"grep 搜索失败: {e}")

        if not results:
            return ActionResult(
                success=True,
                data={"type": "grep_result", "matches": [], "pattern": pattern},
                message=f"没有找到匹配 `{pattern}` 的内容",
            )

        return ActionResult(
            success=True,
            data={"type": "grep_result", "matches": results, "pattern": pattern,
                  "total": len(results)},
            message=f"找到 {len(results)} 处匹配（搜索 `{pattern}`）",
        )


# ── ListDirectoryAction ──────────────────────────────────────────────────────

class ListDirectoryAction(ActionBase):

    @property
    def name(self) -> str:
        return "list_directory"

    @property
    def description(self) -> str:
        return "列出项目目录结构（树形）"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "以树形结构列出目录内容。支持任意绝对路径（如 G:/A_Works/... 或 C:/Users/...）。\n"
                "path 不传则用项目根目录；传绝对路径可查看任意本地目录。\n"
                "自动过滤 __pycache__、node_modules、.git 等无关目录。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "目标目录（相对项目根），默认为项目根目录",
                    },
                    "depth": {
                        "type": "integer",
                        "description": "展开深度，默认 2，最大 4",
                    },
                },
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        project_id = context.get("project_id")
        path_rel   = (context.get("path") or "").strip()
        depth      = min(int(context.get("depth") or 2), 4)

        base = await _get_project_base(project_id)

        # 无项目时：若 path 是绝对路径则直接使用
        if (not base or not base.exists()) and path_rel:
            abs_path = Path(path_rel)
            if abs_path.is_absolute() and abs_path.exists():
                base = abs_path
                path_rel = ""

        if not base or not base.exists():
            return ActionResult(success=False, error="未找到目录，请提供绝对路径（path）或在项目内使用")

        target = (base / path_rel).resolve() if path_rel else base.resolve()
        if not _is_safe_path(target, base):
            return ActionResult(success=False, error="path 超出项目目录范围")

        if not target.exists():
            return ActionResult(success=False, error=f"目录不存在: {path_rel}")

        lines = [str(target.relative_to(base)) if path_rel else "."]
        self._build_tree(target, lines, prefix="", current_depth=0, max_depth=depth)

        tree_text = "\n".join(lines)
        if len(tree_text) > MAX_CONTENT_CHARS:
            tree_text = tree_text[:MAX_CONTENT_CHARS] + "\n... (已截断)"

        return ActionResult(
            success=True,
            data={"type": "directory_tree", "tree": tree_text, "path": path_rel or "."},
            message=f"目录结构（深度 {depth}）",
        )

    def _build_tree(self, directory: Path, lines: list, prefix: str,
                    current_depth: int, max_depth: int):
        if current_depth >= max_depth:
            return
        try:
            entries = sorted(directory.iterdir(),
                             key=lambda e: (e.is_file(), e.name.lower()))
        except PermissionError:
            return

        entries = [e for e in entries if e.name not in _IGNORE_DIRS and not e.name.startswith(".")]
        for i, entry in enumerate(entries):
            is_last = (i == len(entries) - 1)
            connector = "└── " if is_last else "├── "
            suffix = "/" if entry.is_dir() else ""
            lines.append(f"{prefix}{connector}{entry.name}{suffix}")
            if entry.is_dir():
                extension = "    " if is_last else "│   "
                self._build_tree(entry, lines, prefix + extension,
                                 current_depth + 1, max_depth)
