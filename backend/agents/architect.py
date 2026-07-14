"""
ArchitectAgent — 架构设计 Agent (Role)
Actions: DesignArchitectureAction
Mode: SINGLE (单步执行)
Watch: 无（由 orchestrator 触发）
"""
import time
from typing import Any, Dict
from agents.base import BaseAgent, ReactMode
from actions.design_architecture import DesignArchitectureAction


class ArchitectAgent(BaseAgent):
    action_classes = [DesignArchitectureAction]
    react_mode = ReactMode.SINGLE
    watch_actions = set()

    @property
    def agent_type(self) -> str:
        return "ArchitectAgent"

    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if task_name != "design_architecture":
            return await super().execute(task_name, context)

        step_total = 2
        # 步骤 1：读取项目上下文（调用前）
        await self.emit_step("读取项目上下文", context, phase="start", step_index=1, step_total=step_total)
        t0 = time.monotonic()
        await self.emit_step("读取项目上下文", context, phase="done", step_index=1, step_total=step_total,
                             duration_ms=int((time.monotonic() - t0) * 1000))

        # 步骤 2：AI 生成架构方案
        t1 = time.monotonic()
        await self.emit_step("AI 生成架构方案", context, phase="start", step_index=2, step_total=step_total)
        result = await self.run_action("design_architecture", context)
        await self.emit_step("AI 生成架构方案", context, phase="done", step_index=2, step_total=step_total,
                             duration_ms=int((time.monotonic() - t1) * 1000))
        return result
