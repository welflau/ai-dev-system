"""
ArchitectAgent — 架构设计 Agent (Role)
职责：增量架构设计，读取已有代码
Actions: DesignArchitectureAction
"""
from typing import Any, Dict
from agents.base import BaseAgent
from actions.design_architecture import DesignArchitectureAction


class ArchitectAgent(BaseAgent):

    action_classes = [DesignArchitectureAction]

    @property
    def agent_type(self) -> str:
        return "ArchitectAgent"

    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if task_name == "design_architecture":
            return await self.run_action("design_architecture", context)
        return {"status": "error", "message": f"未知任务: {task_name}"}
