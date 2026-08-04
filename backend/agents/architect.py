"""
ArchitectAgent — 架构设计 Agent (Role)
Actions: DesignArchitectureAction
Mode: SINGLE (单步执行)
Watch: 无（由 orchestrator 触发）
"""
import logging
import time
from typing import Any, Dict
from agents.base import BaseAgent, ReactMode
from actions.design_architecture import DesignArchitectureAction

logger = logging.getLogger("agent.architect")


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
            from orchestrator import orchestrator as orch
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
            logger.warning("架构里程碑通知失败: %s", e, exc_info=True)

        # OpenSpec Propose（规范层，可选增强）
        await self._run_openspec_propose(context)

    async def _run_openspec_propose(self, context: Dict[str, Any]) -> None:
        """
        OpenSpec 变更提案：生成 proposal/specs/design/tasks 四件套。

        v0.21：改由通用 SkillRunner 驱动 —— 加载 `openspec-propose` 可执行 skill，
        把 openspec-cn 的 new change / instructions / validate 声明成 LLM 工具 +
        write_file，让 LLM 自主按 skill 步骤跑完。取代原先硬编码的
        `_fill_openspec_4_artifacts`（new→instructions→generate→write→validate 写死）。

        保留全部可见性：openspec_propose_started 日志 + milestone、每次工具调用的
        react_tool 时间轴、write_file → openspec_artifact 日志、partial/完成收尾、
        openspec_stage 更新。项目未安装 OpenSpec 时静默跳过。
        """
        try:
            project_id = context.get("project_id", "")
            ticket_id = context.get("ticket_id", "")
            if not project_id or not ticket_id:
                logger.debug("_run_openspec_propose 跳过：缺 project_id 或 ticket_id")
                return

            from capability_check import get_openspec_cli, _get_repo_path, _short_ticket_id
            repo_path = context.get("repo_path") or await _get_repo_path(project_id)
            if not repo_path:
                logger.info("_run_openspec_propose 跳过：项目无 repo_path")
                return

            from skills.executable_loader import load_executable_skill
            from skills.runner import SkillRunner
            skill = load_executable_skill("openspec-propose", repo_path=repo_path)
            if not skill:
                logger.warning("_run_openspec_propose 跳过：openspec-propose skill 未找到")
                return
            runner = SkillRunner(skill)

            # 可用性检查（skill.availability = [has_openspec]）
            if not await runner.is_available({"project_id": project_id, "repo_path": repo_path}):
                logger.info("_run_openspec_propose 跳过：OpenSpec 未安装或未初始化")
                return

            cli = get_openspec_cli()
            change_id = _short_ticket_id(ticket_id)
            if not cli or not change_id:
                return

            ticket_title = (context.get("ticket_title") or "")[:100]
            ticket_desc = (context.get("ticket_description") or "")[:200]
            goal = f"{ticket_title}: {ticket_desc}".strip(": ")

            # 拿 project traits（供 skill system 里参考）
            from database import db
            from utils import now_iso
            project_traits = []
            try:
                row = await db.fetch_one("SELECT traits FROM projects WHERE id=?", (project_id,))
                if row and row.get("traits"):
                    import json as _json
                    project_traits = _json.loads(row["traits"])
            except Exception:
                pass

            # 预填命令主干参数 + 上下文（LLM 只需填 instructions 的 artifact 槽）
            run_ctx = {
                **context,
                "cli": cli, "change_id": change_id,
                "goal": goal, "desc": ticket_title or change_id,
                "repo_path": repo_path, "project_id": project_id, "ticket_id": ticket_id,
                "ticket_title": ticket_title, "ticket_description": ticket_desc,
                "project_traits": project_traits,
            }

            logger.info("📐 [规范层] OpenSpec Propose (SkillRunner): change=%s", change_id)

            from orchestrator import orchestrator as orch
            # started 记录（不依赖 LLM，先落，保证可见）
            await db.execute(
                "UPDATE tickets SET openspec_stage='proposed', updated_at=? WHERE id=?",
                (now_iso(), ticket_id),
            )
            await orch._add_layer_log(
                ticket_id, project_id, action="openspec_propose_started", layer="spec",
                detail={"change_id": change_id,
                        "message": f"OpenSpec change 目录（{change_id}）Propose 已启动，正在生成 4 件套…"},
            )
            await orch.post_milestone_comment(
                ticket_id, project_id,
                f"📐 [规范层] **OpenSpec Propose 已启动** — 由 SkillRunner 驱动生成 "
                f"proposal/specs/design/tasks 4 件套（change `{change_id}`，需调用 LLM，可能稍候）…",
            )

            # 每次工具调用 → react_tool 时间轴；write_file → 额外 openspec_artifact 日志
            async def on_tool(ev):
                try:
                    await self._emit_react_tool(
                        project_id, context.get("requirement_id"), ticket_id,
                        ev.tool, ev.args_hint, ev.duration_ms,
                        output_summary=(ev.result or "")[:500], summary=ev.summary or "",
                    )
                except Exception:
                    pass
                if ev.tool == "write_file":
                    try:
                        await orch._add_layer_log(
                            ticket_id, project_id, action="openspec_artifact", layer="spec",
                            detail={"change_id": change_id,
                                    "message": f"OpenSpec 产出已写入：{ev.args_hint or ev.summary or ''}"},
                        )
                    except Exception:
                        pass

            result = await runner.execute(run_ctx, on_tool=on_tool)

            # 收尾：按回收到的产出文件判 partial（漏 validate 也如实反映）
            ok_count = len(result.outputs)
            expected = skill.expected_output_count or 4
            is_partial = (result.status != "success") or (ok_count < expected)
            got = set(result.outputs.keys())
            def _mark(fn): return "✅" if fn in got else "❌"
            artifact_summary = (
                f"📐 [规范层] **OpenSpec Propose {'部分完成' if is_partial else '完成'}** — "
                f"{ok_count}/{expected} 件套已生成。\n"
                f"文件位置：`openspec/changes/{change_id}/`\n"
                f"- proposal: {_mark('proposal.md')}\n"
                f"- specs:    {_mark('specs.md')}\n"
                f"- design:   {_mark('design.md')}\n"
                f"- tasks:    {_mark('tasks.md')}\n"
                f"运行状态：{result.status}（{result.rounds} 轮）"
            )
            await orch.post_milestone_comment(ticket_id, project_id, artifact_summary)
            await orch._add_layer_log(
                ticket_id, project_id,
                action="openspec_propose_partial" if is_partial else "openspec_propose",
                layer="spec", level="warning" if is_partial else "info",
                detail={"change_id": change_id, "outputs": list(got),
                        "ok_count": ok_count, "status": result.status, "rounds": result.rounds},
            )
            logger.info("📐 OpenSpec Propose %s（ticket=%s, change=%s, %d/%d, status=%s）",
                        "部分完成" if is_partial else "成功",
                        ticket_id[:12], change_id, ok_count, expected, result.status)
        except Exception as e:
            logger.warning("_run_openspec_propose 异常: %s", e, exc_info=True)
