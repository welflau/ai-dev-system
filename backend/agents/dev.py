"""
DevAgent — 开发 Agent (Role)
职责：接单开发代码 → 自测 → 输出开发笔记
Actions: WriteCodeAction → SelfTestAction (BY_ORDER)
Watch: design_architecture（关心架构完成）
"""
import json
import logging
from typing import Any, Dict
from agents.base import BaseAgent, ReactMode
from actions.write_code import WriteCodeAction
from actions.self_test import SelfTestAction

logger = logging.getLogger("dev_agent")


class DevAgent(BaseAgent):

    action_classes = [WriteCodeAction, SelfTestAction]
    react_mode = ReactMode.BY_ORDER  # 先写代码 → 再自测
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
        else:
            return {"status": "error", "message": f"未知任务: {task_name}"}

    async def _do_develop(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """开发：BY_ORDER 执行 WriteCode → SelfTest"""
        result = await self._react_by_order("develop", context)
        # 确保 dev_result 字段存在（兼容 orchestrator）
        if "dev_result" not in result:
            result["dev_result"] = {"files": result.get("files", {}), "notes": result.get("notes", "")}
        result["estimated_hours"] = result.get("estimated_hours", 4)
        return result

    async def _do_rework(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """返工：注入打回原因到 context"""
        rejection_reason = context.get("rejection_reason", "")
        context["ticket_description"] = f"{context.get('ticket_description', '')} [返工原因] {rejection_reason}"
        return await self._do_develop(context)

    async def _do_fix_issues(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """修复：注入测试问题到 context"""
        test_issues = context.get("test_issues", [])
        context["ticket_description"] = f"{context.get('ticket_description', '')} [测试问题] {json.dumps(test_issues, ensure_ascii=False)}"
        return await self._do_develop(context)
