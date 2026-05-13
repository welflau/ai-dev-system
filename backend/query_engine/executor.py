"""
ToolExecutorProtocol — QueryEngine 的工具执行接口。

QueryEngine 不直接依赖任何 Action 类，只通过此协议交互。
两个内置适配器：
  - ChatToolExecutorAdapter     : 包装 _ChatToolExecutor（聊天助手，38+ 个工具）
  - OrchestratorToolExecutorAdapter : 包装 Agent._actions（Orchestrator 工单 Agent）
"""
import json
import logging
from typing import Any, Dict, Optional, Protocol, Tuple, runtime_checkable

logger = logging.getLogger("query_engine.executor")


@runtime_checkable
class ToolExecutorProtocol(Protocol):
    """
    QueryEngine 依赖的工具执行接口。
    返回 (result_text, action_data)：
      result_text : 回填给 LLM 的纯文本结果
      action_data : 非 None 时表示需要前端渲染卡片（confirm_requirement 等）
    """
    async def execute(
        self,
        tool_name: str,
        tool_input: dict,
        context: dict,
    ) -> Tuple[str, Optional[dict]]:
        ...


# ─────────────────────────────────────────────────────────────────
# ChatToolExecutorAdapter
# ─────────────────────────────────────────────────────────────────

class ChatToolExecutorAdapter:
    """
    将 _ChatToolExecutor 适配为 ToolExecutorProtocol。

    _ChatToolExecutor.execute(name, input) → str（JSON）
    适配为：(result_text, action_data) 并透传 thinking_steps。
    """

    def __init__(self, inner):
        """inner: _ChatToolExecutor 实例"""
        self._inner = inner

    @property
    def thinking_steps(self):
        return self._inner.thinking_steps

    @property
    def primary_action_result(self):
        return self._inner.primary_action_result

    @property
    def all_confirm_results(self):
        return self._inner.all_confirm_results

    async def execute(
        self,
        tool_name: str,
        tool_input: dict,
        context: dict,
    ) -> Tuple[str, Optional[dict]]:
        result_text = await self._inner.execute(tool_name, tool_input)
        action_data = self._inner.primary_action_result
        return result_text, action_data


# ─────────────────────────────────────────────────────────────────
# OrchestratorToolExecutorAdapter
# ─────────────────────────────────────────────────────────────────

class OrchestratorToolExecutorAdapter:
    """
    将 Agent._actions（ActionBase 字典）适配为 ToolExecutorProtocol。

    用于让 Orchestrator 工单 Agent 通过 QueryEngine 使用 Anthropic 原生 tool_use 格式，
    替代旧的"LLM 输出文本 → 代码解析 Action 名"文本协议。
    """

    def __init__(self, agent_actions: dict, base_context: dict):
        """
        agent_actions : agent._actions（{name: ActionBase}）
        base_context  : 来自 orchestrator 的基础 context（project_id / ticket_id 等）
        """
        self._actions = agent_actions
        self._base_context = base_context

    async def execute(
        self,
        tool_name: str,
        tool_input: dict,
        context: dict,
    ) -> Tuple[str, Optional[dict]]:
        action = self._actions.get(tool_name)
        if not action:
            return f"未知工具: {tool_name}", None

        # 合并 base_context + QueryEngine 传来的 context + tool_input 参数
        ctx = {**self._base_context, **context, **tool_input}

        try:
            result = await action.run(ctx)
            text = result.message or json.dumps(result.data or {}, ensure_ascii=False)
            return text, None
        except Exception as e:
            logger.warning("OrchestratorToolExecutorAdapter %s 失败: %s", tool_name, e)
            return f"工具执行失败: {e}", None
