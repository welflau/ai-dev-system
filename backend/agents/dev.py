"""
DevAgent — 开发 Agent (Role)
职责：接单开发代码 → 自测 → 开发笔记
Actions: PlanCodeChangeAction (增量) / WriteCodeAction (全新) + SelfTestAction
Mode: BY_ORDER
Watch: design_architecture
"""
import json
import logging
from typing import Any, Dict
from agents.base import BaseAgent, ReactMode
from actions.write_code import WriteCodeAction
from actions.plan_code_change import PlanCodeChangeAction
from actions.self_test import SelfTestAction

logger = logging.getLogger("dev_agent")


class DevAgent(BaseAgent):

    action_classes = [WriteCodeAction, PlanCodeChangeAction, SelfTestAction]
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
        """返工：注入打回原因"""
        rejection_reason = context.get("rejection_reason", "")
        context["ticket_description"] = f"{context.get('ticket_description', '')} [返工原因] {rejection_reason}"
        return await self._do_develop(context)

    async def _do_fix_issues(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """修复：注入测试问题"""
        test_issues = context.get("test_issues", [])
        context["ticket_description"] = f"{context.get('ticket_description', '')} [测试问题] {json.dumps(test_issues, ensure_ascii=False)}"
        return await self._do_develop(context)
