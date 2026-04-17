"""
GitLogAction — 查看当前分支最近的提交记录
"""
import logging
from typing import Any, Dict

from actions.base import ActionBase, ActionResult
from actions.chat._git_base import ensure_git_ready

logger = logging.getLogger("actions.chat.git_log")


class GitLogAction(ActionBase):

    @property
    def name(self) -> str:
        return "git_log"

    @property
    def description(self) -> str:
        return "查看当前分支最近的 git 提交记录"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": "查看当前分支最近的 git 提交记录。用户问『最近提交了什么』『git log』『开发进展』时调用。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "返回条数，默认 10，上限 20",
                    },
                },
                "required": [],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        from git_manager import git_manager

        project_id = context.get("project_id")
        if not project_id:
            return ActionResult(success=False, error="缺少 project_id")

        ready, err = await ensure_git_ready(project_id)
        if not ready:
            return err

        limit = min(int(context.get("limit") or 10), 20)

        try:
            logs = await git_manager.get_log(project_id, limit)
        except Exception as e:
            logger.error("git_log 失败: %s", e)
            return ActionResult(
                success=False,
                data={"type": "error", "message": f"Git 操作失败: {str(e)}"},
            )

        if not logs:
            return ActionResult(
                success=True,
                data={"type": "git_result", "action": "log", "message": "暂无提交记录"},
            )

        log_lines = [
            f"- `{c.get('short_hash', '?')}` {c.get('message', '')} — {c.get('author', '')} ({c.get('date', '')})"
            for c in logs
        ]
        return ActionResult(
            success=True,
            data={
                "type": "git_result",
                "action": "log",
                "message": f"最近 {len(logs)} 条提交:\n\n" + "\n".join(log_lines),
            },
        )
