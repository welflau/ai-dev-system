"""
ReadManyFilesAction — 批量读取多个文件

一次工具调用读多个文件，减少 LLM 轮次，适合代码审查/对比分析场景。
"""
import logging
from pathlib import Path
from typing import Any, Dict

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.chat.read_many_files")

MAX_FILES = 10
MAX_CHARS_PER_FILE = 3000
MAX_TOTAL_CHARS = 20000

_ALLOWED_DIRS: list = []  # 动态从 read_local_file 的白名单复用


class ReadManyFilesAction(ActionBase):

    @property
    def name(self) -> str:
        return "read_files"

    @property
    def description(self) -> str:
        return "批量读取多个文件内容"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "一次性读取多个文件的内容，适合需要同时查看多个文件的场景。\n"
                f"最多 {MAX_FILES} 个文件，每个文件最多 {MAX_CHARS_PER_FILE} 字符。\n"
                "文件路径支持绝对路径或相对于项目根目录的相对路径。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": f"文件路径列表（最多 {MAX_FILES} 个）",
                    },
                },
                "required": ["paths"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        paths      = context.get("paths") or []
        project_id = context.get("project_id")

        if not paths:
            return ActionResult(success=False, error="paths 不能为空")

        paths = [str(p).strip() for p in paths[:MAX_FILES]]

        # 获取项目根目录
        base: Path | None = None
        if project_id:
            try:
                from database import db
                row = await db.fetch_one("SELECT git_repo_path FROM projects WHERE id=?", (project_id,))
                if row and row.get("git_repo_path"):
                    base = Path(row["git_repo_path"])
            except Exception:
                pass

        # 允许读取的目录（复用 read_local_file 白名单 + 项目目录）
        from actions.chat.read_local_file import _build_allowed_roots
        allowed_roots = _build_allowed_roots()
        if base and base.exists():
            allowed_roots.append(base)

        results = {}
        total_chars = 0

        for raw_path in paths:
            p = Path(raw_path)
            # 相对路径 → 相对项目根
            if not p.is_absolute() and base:
                p = base / raw_path

            p = p.resolve()

            # 安全检查
            safe = any(
                _is_under(p, r) for r in allowed_roots
            )
            if not safe:
                results[raw_path] = {"error": "路径不在允许目录范围内"}
                continue

            if not p.exists():
                results[raw_path] = {"error": "文件不存在"}
                continue

            if not p.is_file():
                results[raw_path] = {"error": "不是文件"}
                continue

            try:
                content = p.read_text(encoding="utf-8", errors="replace")
                if len(content) > MAX_CHARS_PER_FILE:
                    content = content[:MAX_CHARS_PER_FILE] + f"\n... (已截断，共 {len(content)} 字符)"
                results[raw_path] = {"content": content, "size": p.stat().st_size}
                total_chars += len(content)
                if total_chars > MAX_TOTAL_CHARS:
                    break
            except Exception as e:
                results[raw_path] = {"error": str(e)}

        success_count = sum(1 for v in results.values() if "content" in v)
        return ActionResult(
            success=True,
            data={"type": "files_content", "files": results,
                  "success_count": success_count, "total": len(paths)},
            message=f"已读取 {success_count}/{len(paths)} 个文件",
        )


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve())
        return True
    except ValueError:
        return False
