"""
GitReadFileAction — 读取仓库里指定文件的内容
"""
import logging
from typing import Any, Dict

from actions.base import ActionBase, ActionResult
from actions.chat._git_base import ensure_git_ready

logger = logging.getLogger("actions.chat.git_read_file")


_MAX_CONTENT_LEN = 5000


class GitReadFileAction(ActionBase):

    @property
    def name(self) -> str:
        return "git_read_file"

    @property
    def description(self) -> str:
        return "读取仓库里指定文件的内容（超过 5000 字符会截断）"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": "读取仓库内某个文件的内容并返回给用户。用户问『看一下 XX 文件的内容』时调用。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件相对路径（相对仓库根目录）",
                    },
                },
                "required": ["path"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        from git_manager import git_manager

        project_id = context.get("project_id")
        if not project_id:
            return ActionResult(success=False, error="缺少 project_id")

        path = (context.get("path") or "").strip()
        if not path:
            return ActionResult(success=False, data={"type": "error", "message": "文件路径不能为空"})

        ready, err = await ensure_git_ready(project_id)
        if not ready:
            return err

        try:
            content = await git_manager.get_file_content(project_id, path)
        except Exception as e:
            logger.error("git_read_file 失败: %s", e)
            return ActionResult(
                success=False,
                data={"type": "error", "message": f"Git 操作失败: {str(e)}"},
            )

        if content is None:
            return ActionResult(
                success=False,
                data={"type": "error", "message": f"文件不存在: {path}"},
            )

        original_len = len(content)
        if original_len > _MAX_CONTENT_LEN:
            content = content[:_MAX_CONTENT_LEN] + f"\n\n... (文件过长，已截断，共 {original_len} 字符)"

        return ActionResult(
            success=True,
            data={
                "type": "git_result",
                "action": "read_file",
                "message": f"**{path}** 内容:\n\n```\n{content}\n```",
            },
        )
