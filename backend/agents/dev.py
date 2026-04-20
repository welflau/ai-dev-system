"""
DevAgent — 开发 Agent (Role)
职责：接单开发代码 → 自测 → 开发笔记
Actions: PlanCodeChangeAction (增量) / WriteCodeAction (全新) + SelfTestAction + ReflectionAction
Mode: BY_ORDER
Watch: design_architecture

rework / fix_issues 会先调用 ReflectionAction 做结构化反思，反思结果注入
后续代码生成 Action 的 prompt（见 plan_code_change.py / write_code.py）。
详见 docs/20260419_01_Reflexion反思框架实现方案.md
"""
import json
import logging
from typing import Any, Dict
from agents.base import BaseAgent, ReactMode
from actions.write_code import WriteCodeAction
from actions.plan_code_change import PlanCodeChangeAction
from actions.self_test import SelfTestAction
from actions.reflection import ReflectionAction

logger = logging.getLogger("dev_agent")


class DevAgent(BaseAgent):

    action_classes = [WriteCodeAction, PlanCodeChangeAction, SelfTestAction, ReflectionAction]
    react_mode = ReactMode.SINGLE  # 自己控制流程，不用 BY_ORDER
    watch_actions = {"design_architecture"}

    @property
    def agent_type(self) -> str:
        return "DevAgent"

    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if task_name == "develop":
            return await self._do_develop(context)
        elif task_name == "rework":
            return await self._do_rework(context)
        elif task_name == "fix_issues":
            return await self._do_fix_issues(context)
        return {"status": "error", "message": f"未知任务: {task_name}"}

    async def _do_develop(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """开发：根据是否有已有代码选择策略"""
        existing_code = context.get("existing_code", {})

        # 有已有代码 → 用 PlanCodeChange（精准增量）
        # 空项目 → 用 WriteCode（全新生成）
        if existing_code:
            logger.info("📋 检测到已有代码，使用 PlanCodeChange 精准增量")
            code_result = await self.run_action("plan_code_change", context)
        else:
            logger.info("📝 空项目，使用 WriteCode 全新生成")
            code_result = await self.run_action("write_code", context)

        # 注入 files 到 context，供 SelfTest 使用
        files = code_result.get("files", {})
        context["_files"] = files
        context["dev_result"] = code_result.get("dev_result", {"files": files})

        # 自测
        test_result = await self.run_action("self_test", context)

        # 合并结果
        result = {**code_result}
        result.setdefault("files", {}).update(test_result.get("files", {}))
        result["self_test"] = test_result.get("self_test", {})
        if "dev_result" not in result:
            result["dev_result"] = {"files": files, "notes": ""}
        result["estimated_hours"] = result.get("estimated_hours", 4)

        return result

    async def _do_rework(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """返工（Reflexion）：先反思失败根因 → 再按反思策略重开发"""
        context["failure_type"] = "acceptance_rejected"
        return await self._do_retry_with_reflection(context)

    async def _do_fix_issues(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """测试失败修复（Reflexion）：先反思失败根因 → 再按反思策略重开发"""
        context["failure_type"] = "testing_failed"
        return await self._do_retry_with_reflection(context)

    async def _do_retry_with_reflection(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """通用重试流程：拉历次反思 → 反思当次失败 → 注入 context → 重开发"""
        # 1. 拉重试上下文（retry_count + 历次反思 + 上次代码）
        await self._enrich_retry_context(context)

        # 2. SOP config 允许关掉反思做 A/B
        sop_cfg = context.get("sop_config") or {}
        enable_reflection = sop_cfg.get("enable_reflection", True)

        if enable_reflection and self.has_action("reflect"):
            refl_result = await self.run_action("reflect", context)
            reflection = refl_result.get("reflection") or {}
            # 把 retry_count 附到 reflection dict，方便下游（orchestrator 日志/前端）取用
            reflection["retry_count"] = context.get("retry_count", 1)
            context["reflection"] = reflection
            logger.info(
                "🔍 Reflection 已注入（retry=%d, confidence=%.2f）",
                reflection["retry_count"],
                float(reflection.get("confidence", 0.0) or 0.0),
            )
        else:
            # 降级到旧逻辑：只拼 rejection_reason / test_issues 到描述
            reflection = None
            if context.get("failure_type") == "acceptance_rejected":
                rr = context.get("rejection_reason", "")
                if rr:
                    context["ticket_description"] = (
                        f"{context.get('ticket_description', '')} [返工原因] {rr}"
                    )
            else:
                ti = context.get("test_issues", [])
                if ti:
                    context["ticket_description"] = (
                        f"{context.get('ticket_description', '')} "
                        f"[测试问题] {json.dumps(ti, ensure_ascii=False)}"
                    )

        # 3. 执行开发
        result = await self._do_develop(context)

        # 4. 带出反思，供 orchestrator 写入 ticket_logs
        if reflection:
            result["last_reflection"] = reflection
        return result

    async def _enrich_retry_context(self, context: Dict[str, Any]):
        """从 DB 拉取重试所需上下文：retry_count + previous_reflections + previous_code"""
        from database import db

        ticket_id = context.get("ticket_id")
        if not ticket_id:
            context.setdefault("retry_count", 1)
            context.setdefault("previous_reflections", [])
            context.setdefault("previous_code", context.get("existing_code") or {})
            return

        # 重试次数：历史上这个工单被 reject 过几次，本次就是第 N+1 次
        try:
            row = await db.fetch_one(
                "SELECT COUNT(*) AS c FROM ticket_logs WHERE ticket_id = ? AND action = 'reject'",
                (ticket_id,),
            )
            context["retry_count"] = (row["c"] if row else 0) + 1
        except Exception as e:
            logger.warning("查询 retry_count 失败: %s", e)
            context["retry_count"] = 1

        # 历次反思（按时间正序，最多 3 条）
        try:
            refl_logs = await db.fetch_all(
                """SELECT detail FROM ticket_logs
                   WHERE ticket_id = ? AND action = 'reflection'
                   ORDER BY created_at DESC LIMIT 3""",
                (ticket_id,),
            )
            prevs = []
            for log in reversed(refl_logs):  # DB 降序 → 反转成时间正序
                try:
                    parsed = json.loads(log["detail"])
                    # detail 里可能直接是 reflection dict，也可能包了一层
                    refl = parsed.get("reflection", parsed) if isinstance(parsed, dict) else {}
                    if refl:
                        prevs.append(refl)
                except Exception:
                    pass
            context["previous_reflections"] = prevs
        except Exception as e:
            logger.warning("查询 previous_reflections 失败: %s", e)
            context["previous_reflections"] = []

        # 上次代码（简化：用 existing_code；完整实现应该从 feat 分支 git read）
        context["previous_code"] = context.get("existing_code") or {}
