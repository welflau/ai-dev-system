"""
ProductAgent — 产品需求 Agent (Role)
Actions: DecomposeAction (拆单) + AcceptanceReviewAction (验收)
Watch: write_code（关心开发完成）
"""
from typing import Any, Dict
from agents.base import BaseAgent, ReactMode
from actions.decompose import DecomposeAction
from actions.acceptance_review import AcceptanceReviewAction


class ProductAgent(BaseAgent):

    action_classes = [DecomposeAction, AcceptanceReviewAction]
    react_mode = ReactMode.SINGLE
    watch_actions = {"write_code"}

    @property
    def agent_type(self) -> str:
        return "ProductAgent"

    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if task_name == "analyze_and_decompose":
            return await self.run_action("decompose", context)
        elif task_name == "acceptance_review":
            return await self.run_action("acceptance_review", context)
        return {"status": "error", "message": f"未知任务: {task_name}"}
