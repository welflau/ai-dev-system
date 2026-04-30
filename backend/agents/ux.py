"""
UXAgent — 交互设计 Agent

职责：为有界面的工单产出 UX 设计文档（交互流程/组件线框/状态定义/资产清单初稿）
Position in SOP: planning_done → ux_design (fragment) → ux_design_done → ArchitectAgent

适用范围：platform:web / wechat / mobile / desktop / category:game
通过 SOP fragment ux_design.yaml 按 traits 条件插入，不在 base_stages 里
"""
from typing import Any, Dict
from agents.base import BaseAgent, ReactMode
from actions.write_ux_design import WriteUXDesignAction


class UXAgent(BaseAgent):

    action_classes = [WriteUXDesignAction]
    react_mode = ReactMode.SINGLE

    @property
    def agent_type(self) -> str:
        return "UXAgent"

    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if task_name == "write_ux_design":
            return await self.run_action("write_ux_design", context)
        return {"status": "error", "message": f"UXAgent 未知任务: {task_name}"}
