"""
GitMergeAction — 合并两个分支（源 → 目标）
"""
import logging
from typing import Any, Dict

from actions.base import ActionBase, ActionResult
from actions.chat._git_base import ensure_git_ready

logger = logging.getLogger("actions.chat.git_merge")


class GitMergeAction(ActionBase):

    @property
    def name(self) -> str:
        return "git_merge"

    @property
    def description(self) -> str:
        return "合并源分支到目标分支"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": "合并源分支到目标分支。用户说『合并 develop 到 main』『merge XX into YY』时调用。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "源分支名（将被合并到目标分支的那个）",
                    },
                    "target": {
                        "type": "string",
                        "description": "目标分支名（接受合并的那个）",
                    },
                },
                "required": ["source", "target"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        from git_manager import git_manager

        project_id = context.get("project_id")
        if not project_id:
            return ActionResult(success=False, error="缺少 project_id")

        source = (context.get("source") or "").strip()
        target = (context.get("target") or "").strip()
        if not source or not target:
            return ActionResult(
                success=False,
                data={"type": "error", "message": "源分支和目标分支不能为空"},
            )

        ready, err = await ensure_git_ready(project_id)
        if not ready:
            return err

        try:
            result = await git_manager.merge_branch(project_id, source, target)
        except Exception as e:
            logger.error("git_merge 失败: %s", e)
            return ActionResult(
                success=False,
                data={"type": "error", "message": f"Git 操作失败: {str(e)}"},
            )

        if result.get("success"):
            return ActionResult(
                success=True,
                data={
                    "type": "git_result",
                    "action": "merge",
                    "message": f"合并成功: {source} → {target} (commit: {result.get('commit', '?')})",
                },
            )
        return ActionResult(
            success=False,
            data={"type": "error", "message": f"合并失败: {result.get('error', '未知错误')}"},
        )
