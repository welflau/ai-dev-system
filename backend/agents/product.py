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
        on_step = context.get("on_step")

        async def _step(msg: str):
            if on_step:
                await on_step(msg)

        # Step 1: 读懂项目（如果有已有代码）
        existing_files = context.get("existing_files", [])
        if existing_files:
            await _step(f"正在理解现有项目（{len(existing_files)} 个文件）…")
            summary_result = await self.run_action("summarize_code", context)
            project_summary = summary_result.get("project_summary", {})
            context["project_summary"] = project_summary
            await _step("项目理解完成，开始判断复杂度并拆工单。")

        # Step 2: 基于理解拆单
        await _step("正在调用 LLM 拆单，这一步可能要等几分钟…")
        result = await self.run_action("decompose", context)
        tickets = result.get("tickets") if isinstance(result, dict) else None
        n = len(tickets) if isinstance(tickets, list) else 0
        if n:
            await _step(f"拆单完成，共 {n} 个工单。")
        return result
