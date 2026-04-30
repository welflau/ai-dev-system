"""
PlannerAgent — 策划 Agent

职责：为每个工单产出标准化 PRD（用户故事 + 验收标准 + 边界条件 + 资产需求线索）
Position in SOP: pending → planning_in_progress → planning_done → ArchitectAgent

与 ProductAgent 的分工：
- ProductAgent：需求入口 / 代码摘要 / 拆单（需求→工单）/ 产品验收
- PlannerAgent：为每张工单写 PRD（工单→详细规格）
"""
from typing import Any, Dict
from agents.base import BaseAgent, ReactMode
from actions.write_prd import WritePRDAction


class PlannerAgent(BaseAgent):

    action_classes = [WritePRDAction]
    react_mode = ReactMode.SINGLE

    @property
    def agent_type(self) -> str:
        return "PlannerAgent"

    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if task_name == "write_prd":
            return await self.run_action("write_prd", context)
        return {"status": "error", "message": f"PlannerAgent 未知任务: {task_name}"}
