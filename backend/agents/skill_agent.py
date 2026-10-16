"""
SkillAgent — 通用 skill 执行 Agent（Role）。

职责：把工单流程里声明的可执行 skill（SOP stage config.skill_id）跑起来。
不绑定任何具体 skill —— skill_id 由 SOP/context 提供，SkillAgent 负责：
  解析 skill_id → 注入上游产物 → 校验可用性 → SkillRunner.execute
  → 登记产出到产物总线 → 回传状态给 orchestrator

这样"接新工具集 = 加一个 SKILL.md"，彻底不用再写 Python
（对比原先 architect 硬编码 _run_openspec_propose）。

触发：orchestrator 按 SOP rule 分派 → agent.execute(action, context)，
context["sop_config"]["skill_id"] 或 context["skill_id"] 指定要跑哪个 skill。

v0.20 产物总线接入：
  - 跑之前：按 sop_config["_consumes"] 把上游产物注入 run_ctx
    （SkillRunner._build_system 会渲染成 prompt 片段）
  - 跑之后：把 ArtifactOut 登记进 artifacts 表，回传 artifacts 给 orchestrator
  - 回传 success_status —— orchestrator 的 SkillAgent 分支据此推进状态，
    省掉一次 _sop_stage_for 的 DB 查询 + compose_sop

方案文档：docs/20261015_01_能力自描述与动态组装框架方案.md §3.6
"""
import logging
from dataclasses import asdict
from typing import Any, Dict, List

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

    @staticmethod
    def _skipped(sop: Dict[str, Any], skill_id: str, reason: str) -> Dict[str, Any]:
        """availability 不满足 → skipped。

        必须带上 success_status：orchestrator 对 skipped 的处理是「直接跳到
        成功态，别卡流水线」。没有它 orchestrator 只能靠 action 名反查 SOP，
        多一次 compose_sop（53ms）且在 skill 已被卸载时查不到。
        """
        return {
            "status": "skipped",
            "skill_id": skill_id,
            "skill_status": "skipped",
            "success_status": sop.get("_success_status") or "",
            "sop_config": sop,
            "message": reason,
        }

    async def _run_skill(self, context: Dict[str, Any]) -> Dict[str, Any]:
        project_id = context.get("project_id", "")
        ticket_id = context.get("ticket_id", "")
        requirement_id = context.get("requirement_id", "") or ""
        sop = context.get("sop_config") or {}
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
            return self._skipped(sop, skill_id, f"skill {skill_id} 当前不可用")

        run_ctx = {**context, "repo_path": repo_path,
                   "project_id": project_id, "ticket_id": ticket_id}

        # ── 跑之前：天然源 + 上游产物注入 ──
        consume_ctx = await self._prepare_inputs(
            sop, project_id=project_id, ticket_id=ticket_id,
            requirement_id=requirement_id, repo_path=repo_path,
        )
        run_ctx.update(consume_ctx)

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

        # ── 跑之后：产出登记进产物总线 ──
        artifacts = await self._register_outputs(
            result, skill_id=skill_id, project_id=project_id,
            ticket_id=ticket_id, requirement_id=requirement_id,
            repo_path=repo_path, rounds=result.rounds,
        )

        return {
            "status": "success" if result.status in ("success", "partial") else result.status,
            "skill_id": skill_id,
            "skill_status": result.status,
            "outputs": result.output_paths,
            # 下面三个是 orchestrator 的 SkillAgent 分支要读的
            "success_status": sop.get("_success_status") or "",
            "sop_config": sop,
            "artifacts": artifacts,
            "rounds": result.rounds,
            "message": result.message or f"skill {skill_id} 执行完成（{result.status}）",
        }

    # ──────────────────────── 输入侧 ────────────────────────

    async def _prepare_inputs(
        self, sop: Dict[str, Any], *, project_id: str, ticket_id: str,
        requirement_id: str, repo_path: str,
    ) -> Dict[str, Any]:
        """确保天然源就位，再把 consumes 声明的上游产物查出来注入。

        天然源（ticket_brief）必须先产出：它在 kinds.yaml 标了 builtin，
        组装器视为「已就绪」才没把以它为源的 skill 判缺源剔除。但**没人会
        自动创建它** —— 不在这里补，第一个 skill 的 consumes 就落空。

        任何异常都降级为「不注入」：产物注入是增强，拿不到上游时 LLM 仍能
        按 skill body 的指示工作（prompt 里会显示缺了什么）。
        """
        consumes = sop.get("_consumes") or []
        if not consumes or not repo_path:
            return {}

        try:
            from artifacts.injector import build_consume_context
            from artifacts.store import artifact_store

            # 只在真的有人要 ticket_brief 时才产出，避免给无关 skill 造垃圾文件
            wants_brief = any(
                (c.get("kind") if isinstance(c, dict) else c) == "ticket_brief"
                for c in consumes
            )
            if wants_brief:
                await artifact_store.put_ticket_brief(
                    project_id=project_id, ticket_id=ticket_id,
                    requirement_id=requirement_id, repo_path=repo_path,
                )

            return await build_consume_context(
                consumes, project_id=project_id, ticket_id=ticket_id,
                repo_path=repo_path, requirement_id=requirement_id,
            )
        except Exception as e:
            logger.warning("注入上游产物失败（skill 仍会执行）: %s", e, exc_info=True)
            return {}

    # ──────────────────────── 输出侧 ────────────────────────

    async def _register_outputs(
        self, result, *, skill_id: str, project_id: str, ticket_id: str,
        requirement_id: str, repo_path: str, rounds: int,
    ) -> List[Dict[str, Any]]:
        """把 SkillRunner 回收到的 ArtifactOut 登记进 artifacts 表。

        只登记**声明了 kind** 的产出：kind 为空意味着这个文件没出现在
        x-workflow.produces 里（如 openspec-* 这类老 skill 的四件套），
        它们不属于产物总线，硬塞进去会撞 kinds.yaml 的未注册校验。

        单条失败不影响其余 —— 一个文件登记不上不该让整个 stage 判失败，
        产物总线的记录缺失由下游 consumes 的 _artifacts_missing 自然暴露。
        """
        outs = [o for o in (result.outputs or []) if o.kind]
        if not outs or not repo_path:
            return []

        registered: List[Dict[str, Any]] = []
        try:
            from artifacts.store import artifact_store
        except Exception as e:
            logger.warning("产物总线不可用，跳过登记: %s", e)
            return []

        for o in outs:
            try:
                ref = await artifact_store.put(
                    project_id=project_id, ticket_id=ticket_id,
                    requirement_id=requirement_id,
                    kind=o.kind, repo_path=repo_path, src_path=o.abs_path,
                    filename=o.name, produced_by=skill_id,
                    metadata={"skill_id": skill_id, "rounds": rounds,
                              "rel_path_in_skill_output": o.rel_path},
                )
                registered.append({
                    "artifact_id": ref.id, "kind": ref.kind,
                    "path": ref.rel_path, "mime": ref.mime, "size": ref.size,
                })
            except Exception as e:
                logger.warning("登记产物失败 kind=%s path=%s: %s",
                               o.kind, o.rel_path, e)

        if registered:
            logger.info("📦 SkillAgent 登记 %d 个产物: %s",
                        len(registered), [r["kind"] for r in registered])
        return registered
