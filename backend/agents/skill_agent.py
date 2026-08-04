"""
SkillAgent — 通用 skill 执行 Agent（Role）。

职责：把工单流程里声明的可执行 skill（SOP stage config.skill_id）跑起来。
不绑定任何具体 skill —— skill_id 由 SOP/context 提供，SkillAgent 只负责：
  加载 skill → 校验可用性 → SkillRunner.execute → 每步工具调用写 react_tool 时间轴。

这样"接新工具集 = 加一个 SKILL.md + 一个 SOP fragment 声明 skill_id"，
彻底不用再写 Python（对比原先 architect 硬编码 _run_openspec_propose）。

触发：orchestrator 按 SOP rule 分派 → agent.execute(action, context)，
context["sop_config"]["skill_id"] 或 context["skill_id"] 指定要跑哪个 skill。
"""
import logging
from typing import Any, Dict

from agents.base import BaseAgent, ReactMode

logger = logging.getLogger("skill_agent")


class SkillAgent(BaseAgent):

    action_classes = []            # 不用 Action 组合，自己驱动 SkillRunner
    react_mode = ReactMode.SINGLE

    @property
    def agent_type(self) -> str:
        return "SkillAgent"

    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """task_name 兼容任意值；真正要跑的 skill 由 context 决定。"""
        return await self._run_skill(context)

    def _resolve_skill_id(self, context: Dict[str, Any]) -> str:
        sop = context.get("sop_config") or {}
        return (context.get("skill_id")
                or sop.get("skill_id")
                or "")

    async def _run_skill(self, context: Dict[str, Any]) -> Dict[str, Any]:
        project_id = context.get("project_id", "")
        ticket_id = context.get("ticket_id", "")
        skill_id = self._resolve_skill_id(context)
        if not skill_id:
            return {"status": "error", "message": "SkillAgent 未指定 skill_id（SOP stage.config.skill_id）"}

        repo_path = context.get("repo_path", "")
        if not repo_path:
            try:
                from capability_check import _get_repo_path
                repo_path = await _get_repo_path(project_id)
            except Exception:
                repo_path = ""

        from skills.executable_loader import load_executable_skill
        from skills.runner import SkillRunner
        skill = load_executable_skill(skill_id, repo_path=repo_path)
        if not skill:
            return {"status": "error", "message": f"skill 未找到: {skill_id}"}

        runner = SkillRunner(skill)
        if not await runner.is_available({"project_id": project_id, "repo_path": repo_path}):
            logger.info("SkillAgent 跳过：skill %s 不可用（availability 未满足）", skill_id)
            return {"status": "skipped", "message": f"skill {skill_id} 当前不可用"}

        run_ctx = {**context, "repo_path": repo_path, "project_id": project_id, "ticket_id": ticket_id}

        async def on_tool(ev):
            try:
                await self._emit_react_tool(
                    project_id, context.get("requirement_id"), ticket_id,
                    ev.tool, ev.args_hint, ev.duration_ms,
                    output_summary=(ev.result or "")[:500], summary=ev.summary or "",
                )
            except Exception:
                pass

        logger.info("⚙️ SkillAgent 执行 skill=%s (ticket=%s)", skill_id, ticket_id[:12] if ticket_id else "-")
        result = await runner.execute(run_ctx, on_tool=on_tool)

        return {
            "status": "success" if result.status in ("success", "partial") else result.status,
            "skill_id": skill_id,
            "skill_status": result.status,
            "outputs": list(result.outputs.keys()),
            "rounds": result.rounds,
            "message": result.message or f"skill {skill_id} 执行完成（{result.status}）",
        }
