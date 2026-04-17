"""
GitListBranchesAction — 查看分支列表（含当前分支）
"""
import logging
from typing import Any, Dict

from actions.base import ActionBase, ActionResult
from actions.chat._git_base import ensure_git_ready

logger = logging.getLogger("actions.chat.git_list_branches")


class GitListBranchesAction(ActionBase):

    @property
    def name(self) -> str:
        return "git_list_branches"

    @property
    def description(self) -> str:
        return "列出当前仓库的所有分支，标记出当前所在分支"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": "列出所有 Git 分支并标记当前分支。用户问『有哪些分支』『当前在哪个分支』时调用。",
            "input_schema": {
                "type": "object",
                "properties": {},
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

        try:
            branches = await git_manager.list_branches(project_id)
            current = await git_manager.get_current_branch(project_id)
        except Exception as e:
            logger.error("git_list_branches 失败: %s", e)
            return ActionResult(
                success=False,
                data={"type": "error", "message": f"Git 操作失败: {str(e)}"},
            )

        branch_list = "\n".join(f"  {'* ' if b == current else '  '}{b}" for b in branches)
        return ActionResult(
            success=True,
            data={
                "type": "git_result",
                "action": "list_branches",
                "message": f"当前分支: **{current}**\n\n所有分支:\n{branch_list}",
                "data": {"current": current, "branches": branches},
            },
        )
