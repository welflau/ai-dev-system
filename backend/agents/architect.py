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
            logger.warning("架构里程碑通知失败: %s", e, exc_info=True)

        # OpenSpec Propose（规范层，可选增强）
        await self._run_openspec_propose(context)

    async def _run_openspec_propose(self, context: Dict[str, Any]) -> None:
        """
        触发 opsx:propose，生成 proposal/specs/design/tasks 四件套。
        项目未安装 OpenSpec 时静默跳过，不影响主流程。
        """
        try:
            project_id = context.get("project_id", "")
            ticket_id = context.get("ticket_id", "")
            if not project_id or not ticket_id:
                logger.debug("_run_openspec_propose 跳过：缺 project_id 或 ticket_id")
                return

            from capability_check import has_openspec, get_openspec_cli, _get_repo_path
            repo_path = context.get("repo_path") or await _get_repo_path(project_id)
            if not repo_path:
                logger.info("_run_openspec_propose 跳过：项目无 repo_path（未设置本地路径）")
                return

            openspec_ok = await has_openspec(project_id, repo_path)
            logger.info(
                "OpenSpec 检测：repo=%s cli=%s initialized=%s",
                repo_path, get_openspec_cli(), openspec_ok,
            )
            if not openspec_ok:
                logger.info("_run_openspec_propose 跳过：OpenSpec 未安装或未初始化（请先执行 openspec init）")
                return

            cli = get_openspec_cli()
            if not cli:
                return

            ticket_title = context.get("ticket_title", "")
            ticket_desc = (context.get("ticket_description") or "")[:150]
            propose_arg = f"{ticket_title}: {ticket_desc}".strip(": ")

            logger.info("📐 [规范层] OpenSpec Propose: %s", propose_arg[:60])

            import asyncio
            import sys
            cmd = f'{cli} propose "{propose_arg}"' if sys.platform == "win32" else None
            proc = await asyncio.create_subprocess_shell(
                cmd or f'{cli} propose "{propose_arg}"',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=repo_path,
                stdin=asyncio.subprocess.PIPE,
            )
            if proc.stdin:
                proc.stdin.write(b"\n\n\n\n\n")
                await proc.stdin.drain()
                proc.stdin.close()

            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
                output = stdout.decode("utf-8", errors="replace")[:500] if stdout else ""
                rc = proc.returncode
            except asyncio.TimeoutError:
                proc.kill()
                output = "(超时)"
                rc = -1

            from orchestrator import Orchestrator
            orch = Orchestrator()

            if rc == 0:
                # 更新工单 openspec_stage
                from database import db
                from utils import now_iso
                await db.execute(
                    "UPDATE tickets SET openspec_stage='proposed', updated_at=? WHERE id=?",
                    (now_iso(), ticket_id),
                )
                await orch.post_milestone_comment(
                    ticket_id, project_id,
                    f"📐 [规范层] **OpenSpec Propose 完成** — specs/design/tasks 已生成。\n"
                    f"文件位置：`openspec/changes/{ticket_id}/`",
                )
                await orch._add_layer_log(
                    ticket_id, project_id, action="openspec_propose",
                    layer="spec", detail={"rc": rc, "output": output[:200]},
                )
                logger.info("📐 OpenSpec Propose 成功（ticket=%s）", ticket_id[:12])
            else:
                logger.warning("📐 OpenSpec Propose 失败 rc=%d: %s", rc, output[:200])
                await orch._add_layer_log(
                    ticket_id, project_id, action="openspec_propose_failed",
                    layer="spec", detail={"rc": rc, "output": output[:200]},
                )
        except Exception as e:
            logger.warning("_run_openspec_propose 异常: %s", e, exc_info=True)

