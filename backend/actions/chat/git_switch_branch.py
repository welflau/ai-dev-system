"""
GitSwitchBranchAction — 切换到指定分支
"""
import logging
from typing import Any, Dict

from actions.base import ActionBase, ActionResult
from actions.chat._git_base import ensure_git_ready

logger = logging.getLogger("actions.chat.git_switch_branch")


class GitSwitchBranchAction(ActionBase):

    @property
    def name(self) -> str:
        return "git_switch_branch"

    @property
    def description(self) -> str:
        return "切换到指定的 git 分支"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": "切换到指定的 git 分支。用户说『切换到 XX 分支』『checkout XX』时调用。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "branch": {
                        "type": "string",
                        "description": "要切换到的分支名",
                    },
                },
                "required": ["branch"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        from git_manager import git_manager

        project_id = context.get("project_id")
        if not project_id:
            return ActionResult(success=False, error="缺少 project_id")

        branch = (context.get("branch") or "").strip()
        if not branch:
            return ActionResult(success=False, data={"type": "error", "message": "分支名不能为空"})

        ready, err = await ensure_git_ready(project_id)
        if not ready:
            return err

        try:
            ok = await git_manager.switch_branch(project_id, branch)
        except Exception as e:
            logger.error("git_switch_branch 失败: %s", e)
            return ActionResult(
                success=False,
                data={"type": "error", "message": f"Git 操作失败: {str(e)}"},
            )

        if ok:
            return ActionResult(
                success=True,
                data={"type": "git_result", "action": "switch_branch", "message": f"已切换到分支: {branch}"},
            )
        return ActionResult(
            success=False,
            data={"type": "error", "message": f"切换分支失败: {branch}"},
        )
