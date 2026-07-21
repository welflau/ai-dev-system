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

        # 里程碑通知（三层融合：编排层）
        await self._post_architecture_milestone(context, result)
        return result

    async def _post_architecture_milestone(
        self, context: Dict[str, Any], result: Dict[str, Any]
    ) -> None:
        """架构完成后推里程碑通知，让人在开发前有机会审查方向。"""
        try:
            ticket_id = context.get("ticket_id", "")
            project_id = context.get("project_id", "")
            if not ticket_id or not project_id:
                return
            from orchestrator import Orchestrator
            orch = Orchestrator()
            # 从产出文件里找架构文档路径
            artifacts = result.get("artifacts") or []
            arch_file = next(
                (a.get("path", "") for a in artifacts if "architecture" in str(a).lower()),
                "",
            )
            msg = "🔧 [里程碑] **架构设计已完成**，请查看产出文档后继续。"
            if arch_file:
                msg += f"\n产出文件：`{arch_file}`"
            await orch.post_milestone_comment(ticket_id, project_id, msg)
            await orch._add_layer_log(ticket_id, project_id, action="milestone_architecture",
                                      layer="harness", detail={"arch_file": arch_file})
        except Exception as e:
            logger.debug("架构里程碑通知失败（忽略）: %s", e)

