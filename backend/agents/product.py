"""
ProductAgent — 产品需求 Agent (Role)
Actions: SummarizeCodeAction → DecomposeAction (拆单) + AcceptanceReviewAction (验收)
拆单前先读懂项目，避免过度拆分和忽略已有功能
"""
from typing import Any, Dict
from agents.base import BaseAgent, ReactMode
from actions.summarize_code import SummarizeCodeAction
from actions.decompose import DecomposeAction
from actions.acceptance_review import AcceptanceReviewAction


class ProductAgent(BaseAgent):

    action_classes = [SummarizeCodeAction, DecomposeAction, AcceptanceReviewAction]
    react_mode = ReactMode.SINGLE
    watch_actions = {"write_code"}

    @property
    def agent_type(self) -> str:
        return "ProductAgent"

    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if task_name == "analyze_and_decompose":
            return await self._analyze_and_decompose(context)
        elif task_name == "acceptance_review":
            return await self.run_action("acceptance_review", context)
        return {"status": "error", "message": f"未知任务: {task_name}"}

    async def _analyze_and_decompose(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """先理解项目 → 再拆单"""
        # Step 1: 读懂项目（如果有已有代码）
        existing_files = context.get("existing_files", [])
        if existing_files:
            summary_result = await self.run_action("summarize_code", context)
            project_summary = summary_result.get("project_summary", {})
            context["project_summary"] = project_summary

        # Step 2: 基于理解拆单
        result = await self.run_action("decompose", context)
        return result
