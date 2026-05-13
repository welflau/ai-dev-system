"""
QueryEngine — 统一的 LLM 工具调用循环引擎。

职责：
  - 管理"LLM → tool_use → 执行 → 回填"循环
  - 执行预算检查（Token / 轮次 / 时间）
  - 在每次工具执行前后触发 Pre/Post Hooks
  - 规范化消息格式
  - 以标准事件流 (QueryEvent) 对外输出

不负责：
  - HTTP 层（由 api/chat.py 处理）
  - 消息持久化（由调用方决定）
  - Agent 系统提示（由 Agent 自己构建）
  - 工具内部实现（通过 ToolExecutorProtocol 注入）
"""
import logging
import time
from typing import Any, AsyncIterator, Dict, List, Optional

from query_engine.budget import Budget
from query_engine.events import (
    ActionEvent,
    BudgetExceededEvent,
    ErrorEvent,
    MessageDoneEvent,
    TextDeltaEvent,
    ToolDoneEvent,
    ToolErrorEvent,
    ToolStartEvent,
)
from query_engine.executor import ToolExecutorProtocol

logger = logging.getLogger("query_engine.engine")

# args_hint 取值 key 映射（与 _ChatToolExecutor._emit_thinking 保持一致）
_ARGS_HINT_KEY: Dict[str, str] = {
    "search_knowledge": "query", "search_ticket_history": "query",
    "fetch_url": "url", "git_read_file": "path",
    "get_requirement_pipeline": "requirement_id",
    "get_ticket_status": "ticket_id", "get_requirement_logs": "requirement_id",
    "git_log": "branch", "git_switch_branch": "branch",
    "generate_document": "filename", "confirm_save_doc": "filename",
    "confirm_requirement": "title", "confirm_bug": "title",
    "load_skill": "skill_id", "read_local_file": "path", "ue_call": "command",
    "glob": "pattern", "grep": "pattern", "list_directory": "path",
    "shell": "command", "web_search": "query",
    "save_memory": "title", "read_files": "paths",
    "browse_marketplace": "dir_name", "install_project_skill": "dir_name",
}


def _extract_args_hint(tool_name: str, tool_input: dict) -> str:
    key = _ARGS_HINT_KEY.get(tool_name)
    if not key:
        return ""
    val = str(tool_input.get(key, ""))[:60]
    return f"({key}: {val})" if val else ""


class QueryEngine:
    """
    统一的 LLM 工具调用循环引擎。

    用法：
        engine = QueryEngine(llm_client, executor, budget, hooks)
        async for event in engine.run(messages, system, tools, context):
            if isinstance(event, TextDeltaEvent): ...
    """

    def __init__(
        self,
        llm_client,
        tool_executor: ToolExecutorProtocol,
        budget: Optional[Budget] = None,
        hooks=None,        # HookRegistry | None
        max_rounds: int = 10,
    ):
        self.llm = llm_client
        self.executor = tool_executor
        self.budget = budget or Budget()
        self.hooks = hooks
        self.max_rounds = max_rounds

    async def run(
        self,
        messages: List[Dict[str, Any]],
        system: str,
        tools: List[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> AsyncIterator:
        """
        主循环。每个循环节点：
          1. 预算检查
          2. 流式 LLM 调用
          3. 消耗预算
          4. 无工具调用 → 结束
          5. 执行每个工具（带 Pre/Post Hooks）
          6. 回填 tool_result → 进入下一轮
        """
        if not self.llm.is_configured:
            yield TextDeltaEvent(delta="[LLM 未配置，无法回复]")
            yield MessageDoneEvent(
                full_text="[LLM 未配置，无法回复]",
                thinking_steps=[], final_action=None, rounds=0, total_tokens=0,
            )
            return

        current_messages = list(messages)
        full_text = ""
        thinking_steps = []
        final_action = None
        all_confirm_results = []
        round_count = 0

        for round_no in range(self.max_rounds):
            # ── 1. 预算检查 ────────────────────────────────────────────
            if reason := self.budget.check():
                logger.warning("QueryEngine 预算超限（轮 %d）: %s", round_no, reason)
                yield BudgetExceededEvent(reason=reason)
                return

            # ── 2. 流式 LLM 调用 ──────────────────────────────────────
            text_chunks: List[Dict] = []
            tool_calls: List[Dict] = []
            round_input = 0
            round_output = 0

            try:
                async for chunk in self.llm._call_anthropic_tools_stream(
                    current_messages, tools, system,
                    temperature=0.7, max_tokens=4000,
                ):
                    ctype = chunk.get("type", "")

                    if ctype == "text_delta":
                        full_text += chunk["delta"]
                        text_chunks.append({"type": "text", "text": chunk["delta"]})
                        yield TextDeltaEvent(delta=chunk["delta"])

                    elif ctype == "tool_use_block":
                        tool_calls.append(chunk)

                    elif ctype == "stop":
                        usage = chunk.get("usage", {})
                        round_input  = usage.get("input_tokens",  0) or 0
                        round_output = usage.get("output_tokens", 0) or 0

                    elif ctype == "error":
                        yield ErrorEvent(message=chunk.get("message", "LLM 错误"))
                        return

            except Exception as e:
                logger.error("QueryEngine LLM 调用异常: %s", e)
                yield ErrorEvent(message=str(e))
                return

            # ── 3. 消耗预算 ────────────────────────────────────────────
            self.budget.consume(tokens=round_input + round_output, turns=1)
            round_count += 1

            # ── 4. 无工具调用 → 对话结束 ──────────────────────────────
            if not tool_calls:
                # 同步 executor 里可能有的额外 thinking_steps / action
                if hasattr(self.executor, 'thinking_steps'):
                    thinking_steps = self.executor.thinking_steps or thinking_steps
                if hasattr(self.executor, 'primary_action_result') and self.executor.primary_action_result:
                    final_action = self.executor.primary_action_result
                if hasattr(self.executor, 'all_confirm_results'):
                    all_confirm_results = self.executor.all_confirm_results

                yield MessageDoneEvent(
                    full_text=full_text,
                    thinking_steps=thinking_steps,
                    final_action=final_action,
                    rounds=round_count,
                    total_tokens=self.budget.used_tokens,
                    all_confirm_results=all_confirm_results,
                )
                return

            # 把 assistant 回复（含工具调用块）存入历史
            assistant_content: List[Dict] = []
            # 先放文本块
            for chunk in text_chunks:
                assistant_content.append(chunk)
            # 再放工具调用块（重建 Anthropic content block 格式）
            for tc in tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc["input"],
                })
            current_messages.append({"role": "assistant", "content": assistant_content})

            # ── 5. 执行每个工具调用 ───────────────────────────────────
            tool_results = []
            for tc in tool_calls:
                tool_name    = tc["name"]
                tool_input   = tc.get("input", {}) or {}
                tool_use_id  = tc["id"]
                args_hint    = _extract_args_hint(tool_name, tool_input)

                yield ToolStartEvent(
                    tool=tool_name, input=tool_input, tool_use_id=tool_use_id
                )

                # PRE_TOOL_USE Hook（blocking，限流异常向上传播）
                if self.hooks:
                    from hooks.types import HookEvent, ToolHookContext
                    pre_ctx = ToolHookContext(
                        event=HookEvent.PRE_TOOL_USE,
                        tool_name=tool_name,
                        input=tool_input,
                        project_id=context.get("project_id"),
                        ticket_id=context.get("ticket_id"),
                        agent_type=context.get("agent_type"),
                    )
                    try:
                        await self.hooks.emit(pre_ctx, blocking=True)
                    except Exception as hook_exc:
                        # 限流等阻断性 Hook：当作工具错误处理
                        yield ToolErrorEvent(
                            tool=tool_name, error=str(hook_exc), duration_ms=0
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": f"工具被拦截: {hook_exc}",
                            "is_error": True,
                        })
                        continue

                start_ts = time.monotonic()
                try:
                    result_text, action_data = await self.executor.execute(
                        tool_name, tool_input, context
                    )
                    duration_ms = (time.monotonic() - start_ts) * 1000

                    # POST_TOOL_USE Hook（fail-open）
                    if self.hooks:
                        from hooks.types import HookEvent, ToolHookContext
                        post_ctx = ToolHookContext(
                            event=HookEvent.POST_TOOL_USE,
                            tool_name=tool_name,
                            input=tool_input,
                            output=result_text,
                            duration_ms=duration_ms,
                            project_id=context.get("project_id"),
                            ticket_id=context.get("ticket_id"),
                            agent_type=context.get("agent_type"),
                        )
                        await self.hooks.emit(post_ctx)

                    # 收集 thinking_steps
                    summary = result_text[:120] if result_text else ""
                    thinking_steps.append({
                        "tool": tool_name,
                        "args_hint": args_hint,
                        "summary": summary,
                    })

                    yield ToolDoneEvent(
                        tool=tool_name,
                        summary=summary,
                        args_hint=args_hint,
                        duration_ms=duration_ms,
                    )

                    if action_data:
                        final_action = action_data
                        yield ActionEvent(action_data=action_data)

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": result_text,
                    })

                except Exception as e:
                    duration_ms = (time.monotonic() - start_ts) * 1000

                    # TOOL_ERROR Hook（fail-open）
                    if self.hooks:
                        from hooks.types import HookEvent, ToolHookContext
                        err_ctx = ToolHookContext(
                            event=HookEvent.TOOL_ERROR,
                            tool_name=tool_name,
                            input=tool_input,
                            error=e,
                            duration_ms=duration_ms,
                            project_id=context.get("project_id"),
                            ticket_id=context.get("ticket_id"),
                            agent_type=context.get("agent_type"),
                        )
                        await self.hooks.emit(err_ctx)

                    yield ToolErrorEvent(
                        tool=tool_name, error=str(e), duration_ms=duration_ms
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": f"Error: {e}",
                        "is_error": True,
                    })

                # finish 工具：立即结束循环
                if tool_name == "finish":
                    current_messages.append({"role": "user", "content": tool_results})
                    yield MessageDoneEvent(
                        full_text=full_text,
                        thinking_steps=thinking_steps,
                        final_action=final_action,
                        rounds=round_count,
                        total_tokens=self.budget.used_tokens,
                        all_confirm_results=all_confirm_results,
                    )
                    return

            # ── 6. 回填结果，进入下一轮 ──────────────────────────────
            current_messages.append({"role": "user", "content": tool_results})

        # 达到最大轮数
        logger.warning("QueryEngine 达到最大轮数 %d", self.max_rounds)
        yield MessageDoneEvent(
            full_text=full_text,
            thinking_steps=thinking_steps,
            final_action=final_action,
            rounds=round_count,
            total_tokens=self.budget.used_tokens,
            all_confirm_results=all_confirm_results,
        )
