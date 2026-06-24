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
    CliSessionIdEvent,
    ErrorEvent,
    MessageDoneEvent,
    RoundStartEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ThinkingDoneEvent,
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


def _format_result_summary(tool_name: str, result_text: str) -> str:
    """J-2: 按工具类型结构化格式化摘要，替代粗暴的 120 字截断。"""
    import json as _json
    if not result_text:
        return ""

    # 尝试解析 JSON
    try:
        data = _json.loads(result_text)
    except Exception:
        # 非 JSON：取前 80 字符
        return result_text[:80].replace("\n", " ")

    try:
        # ── 文件读取类 ────────────────────────────────────────────────────────
        if tool_name in ("read_files", "read_local_file"):
            if isinstance(data, dict):
                files = data.get("files") or {}
                if files:
                    total_lines = sum(
                        len(str(v).splitlines()) for v in files.values()
                    )
                    names = "、".join(list(files.keys())[:2])
                    suffix = f" 等{len(files)}个" if len(files) > 2 else ""
                    return f"{names}{suffix} · {total_lines} 行"
                # read_local_file → {"content": "..."}
                content = str(data.get("content", ""))
                return f"{len(content.splitlines())} 行"
            return result_text[:80].replace("\n", " ")

        # ── 搜索/grep 类 ──────────────────────────────────────────────────────
        if tool_name == "grep":
            if isinstance(data, list):
                n = len(data)
                first = data[0] if data else {}
                loc = f"{first.get('path','')}:{first.get('line','')}" if first else ""
                return f"{n} 处匹配" + (f" · {loc}" if loc else "")
            return result_text[:80]

        if tool_name in ("glob", "list_directory"):
            if isinstance(data, list):
                return f"{len(data)} 个文件"
            if isinstance(data, dict) and "files" in data:
                return f"{len(data['files'])} 个文件"
            return result_text[:80]

        # ── 命令执行 ──────────────────────────────────────────────────────────
        if tool_name == "shell":
            if isinstance(data, dict):
                code = data.get("exit_code", "?")
                out  = str(data.get("stdout", "") or data.get("output", ""))
                lines = len(out.splitlines())
                return f"exit {code} · 输出 {lines} 行"
            return result_text[:80]

        # ── 知识库 / 历史 / 网络搜索 ─────────────────────────────────────────
        if tool_name in ("search_knowledge", "search_ticket_history", "web_search"):
            # web_search 返回 {"type": "web_search_result", "results": [...], "query": "..."}
            if isinstance(data, dict) and data.get("type") == "web_search_result":
                results = data.get("results") or []
                query   = data.get("query", "")
                n = len(results)
                if n == 0:
                    return f"未找到结果 · 查询：{query[:30]}"
                first_title = (results[0].get("title") or "")[:30]
                return f"{n} 条结果 · {first_title}" if first_title else f"{n} 条结果"
            if isinstance(data, list):
                n = len(data)
                first_title = ""
                if data and isinstance(data[0], dict):
                    first_title = (data[0].get("title") or data[0].get("name") or "")[:20]
                return f"{n} 条结果" + (f" · {first_title}" if first_title else "")
            return result_text[:80]

        # ── 记忆 ──────────────────────────────────────────────────────────────
        if tool_name == "get_memory":
            if isinstance(data, list):
                return f"{len(data)} 条记忆"
            if isinstance(data, dict) and "memories" in data:
                return f"{len(data['memories'])} 条记忆"

        if tool_name == "save_memory":
            if isinstance(data, dict):
                return data.get("message") or "已保存"

        # ── 需求 / BUG 确认 ──────────────────────────────────────────────────
        if tool_name in ("confirm_requirement", "confirm_bug"):
            if isinstance(data, dict):
                return data.get("title") or data.get("message") or "已识别"

        # ── 通用 dict：取 message 字段 ───────────────────────────────────────
        if isinstance(data, dict):
            msg = data.get("message") or data.get("summary") or data.get("result")
            if msg:
                return str(msg)[:80]

        # ── 通用 list：条数 ─────────────────────────────────────────────────
        if isinstance(data, list):
            return f"{len(data)} 条"

    except Exception:
        pass

    # 兜底
    return result_text[:80].replace("\n", " ")


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
        enable_thinking: bool = False,   # J-3 Extended Thinking
        thinking_budget: int = 8000,     # API 要求 >= 1024
        resume_session_id: str = "",     # Session Resume: CLI --resume 参数
    ):
        self.llm = llm_client
        self.executor = tool_executor
        self.budget = budget or Budget()
        self.hooks = hooks
        self.max_rounds = max_rounds
        self.enable_thinking = enable_thinking
        self.thinking_budget = max(thinking_budget, 1024)
        self.resume_session_id = resume_session_id

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

        # ── USER_PROMPT_SUBMIT Hook：消息到达，LLM 开始前 ──────────────
        if self.hooks:
            try:
                from hooks.types import HookEvent, ToolHookContext as _HCtx
                # 取最后一条 user 消息作为 user_message
                _last_user = next(
                    (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), ""
                )
                if isinstance(_last_user, list):
                    _last_user = " ".join(b.get("text", "") for b in _last_user if isinstance(b, dict))
                await self.hooks.emit(_HCtx(
                    event=HookEvent.USER_PROMPT_SUBMIT,
                    user_message=str(_last_user)[:500],
                    project_id=context.get("project_id"),
                    agent_type=context.get("agent_type"),
                ))
            except Exception:
                pass

        current_messages = list(messages)
        full_text = ""
        thinking_steps = []
        final_action = None
        all_confirm_results = []
        round_count = 0

        for round_no in range(self.max_rounds):
            # J-3b: 通知前端新一轮开始（用于分组展示）
            yield RoundStartEvent(round=round_no + 1)

            # ── 1. 预算检查 ────────────────────────────────────────────
            if reason := self.budget.check():
                logger.warning("QueryEngine 预算超限（轮 %d）: %s", round_no, reason)
                yield BudgetExceededEvent(reason=reason)
                return

            # ── 2. 流式 LLM 调用 ──────────────────────────────────────
            # CLI 模式：使用 _call_cli_stream 实现真正的流式输出
            if getattr(self.llm, "api_format", "anthropic") == "cli":
                full_cli_text = ""
                _cli_tool_times: dict = {}   # tool_use_id → start_time
                _cli_tool_names: dict = {}   # tool_use_id → tool_name
                _cli_tool_started: set = set()  # 已 yield ToolStartEvent 的 tool_use_id，防重复

                # 把 system prompt 拼入 messages，_messages_to_prompt 会包裹为 <ads_context> 注入 stdin
                cli_messages = current_messages
                if system:
                    cli_messages = [{"role": "system", "content": system}] + current_messages

                async for ev in self.llm._call_cli_stream(
                    cli_messages, temperature=0.7, max_tokens=4000,
                    resume_session_id=self.resume_session_id,
                ):
                    etype = ev.get("type", "")
                    if etype == "text_delta":
                        chunk = ev.get("delta", "")
                        full_cli_text += chunk
                        yield TextDeltaEvent(delta=chunk)
                    elif etype == "thinking_delta":
                        yield ThinkingDeltaEvent(delta=ev.get("delta", ""))
                    elif etype == "cli_session_id":
                        # Session Resume: 上抛给 chat_assistant 存 DB
                        yield CliSessionIdEvent(session_id=ev.get("session_id", ""))
                    elif etype == "cli_tool_start":
                        tid = ev["tool_use_id"]
                        if tid not in _cli_tool_started:
                            _cli_tool_started.add(tid)
                            _cli_tool_times[tid] = __import__("time").time()
                            _cli_tool_names[tid] = ev["name"]
                            yield ToolStartEvent(
                                tool=ev["name"],
                                input=ev.get("input", {}),
                                tool_use_id=tid,
                            )
                    elif etype == "cli_tool_result":
                        tid = ev["tool_use_id"]
                        elapsed = (__import__("time").time() - _cli_tool_times.pop(tid, __import__("time").time())) * 1000
                        tool_name = _cli_tool_names.pop(tid, tid)
                        yield ToolDoneEvent(
                            tool=tool_name,
                            summary="",
                            args_hint="",
                            duration_ms=elapsed,
                            result=ev.get("result", ""),
                        )
                    elif etype == "stop":
                        break

                if full_cli_text:
                    yield ThinkingDoneEvent(text="")  # 折叠思考面板

                # CLI 文本里解析 [ACTION:xxx]...[/ACTION] 标签
                _cli_action = None
                _clean_text = full_cli_text
                import re as _re_act, json as _json_act
                _act_m = _re_act.search(
                    r'\[ACTION:(\w+)\]([\s\S]*?)\[/ACTION\]', full_cli_text
                )
                if _act_m:
                    _act_type = _act_m.group(1)
                    _act_body = _act_m.group(2).strip()
                    # 尝试 JSON 解析，失败则用 key: value 格式解析
                    try:
                        _cli_action = _json_act.loads(_act_body)
                        _cli_action["type"] = _act_type
                    except Exception:
                        _parsed = {"type": _act_type}
                        for _line in _act_body.splitlines():
                            if ':' in _line:
                                _k, _, _v = _line.partition(':')
                                _k, _v = _k.strip(), _v.strip()
                                if _k == "traits":
                                    _parsed[_k] = [t.strip() for t in _v.split(',') if t.strip()]
                                elif _k:
                                    _parsed[_k] = _v
                        _cli_action = _parsed if len(_parsed) > 1 else None
                    # 从显示文本中去掉 action 块
                    _clean_text = _re_act.sub(
                        r'\[ACTION:\w+\][\s\S]*?\[/ACTION\]', '', full_cli_text
                    ).strip()

                if _cli_action:
                    yield ActionEvent(action_data=_cli_action)

                # action だけ出力で本文が空の場合、空吹き出しを防ぐ
                _display_text = _clean_text or ('' if _cli_action else full_cli_text)

                yield MessageDoneEvent(
                    full_text=_display_text,
                    thinking_steps=[],
                    final_action=_cli_action,
                    rounds=1,
                    total_tokens=0,
                )
                return

            text_chunks: List[Dict] = []
            tool_calls: List[Dict] = []
            round_input = 0
            round_output = 0
            round_stop_reason = "end_turn"

            try:
                async for chunk in self.llm._call_anthropic_tools_stream(
                    current_messages, tools, system,
                    temperature=0.7, max_tokens=4000,
                    enable_thinking=self.enable_thinking,
                    thinking_budget=self.thinking_budget,
                ):
                    ctype = chunk.get("type", "")

                    if ctype == "text_delta":
                        full_text += chunk["delta"]
                        text_chunks.append({"type": "text", "text": chunk["delta"]})
                        yield TextDeltaEvent(delta=chunk["delta"])

                    elif ctype == "thinking_delta":
                        # J-3: 推理链流式片段（前端可选显示）
                        yield ThinkingDeltaEvent(delta=chunk["delta"])

                    elif ctype == "thinking_done":
                        # J-3: 完整推理文本（一轮一次）
                        yield ThinkingDoneEvent(text=chunk["text"])

                    elif ctype == "tool_use_block":
                        tool_calls.append(chunk)

                    elif ctype == "stop":
                        usage = chunk.get("usage", {})
                        round_input  = usage.get("input_tokens",  0) or 0
                        round_output = usage.get("output_tokens", 0) or 0
                        round_stop_reason = chunk.get("stop_reason", "end_turn") or "end_turn"

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

                await self._emit_session_end(context, round_count, "done")
                await self._emit_assistant_stop(context, full_text, round_count)
                yield MessageDoneEvent(
                    full_text=full_text,
                    thinking_steps=thinking_steps,
                    final_action=final_action,
                    rounds=round_count,
                    total_tokens=self.budget.used_tokens,
                    all_confirm_results=all_confirm_results,
                    stop_reason=round_stop_reason,
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

                # 权限审批（高风险操作异步挂起等待用户确认）
                try:
                    from permissions.gate import permission_gate
                    await permission_gate.check(tool_name, tool_input, context)
                except Exception as perm_exc:
                    yield ToolErrorEvent(
                        tool=tool_name, error=str(perm_exc), duration_ms=0
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": f"操作被拒绝: {perm_exc}",
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

                    # 收集 thinking_steps（J-2 结构化摘要在此处替换）
                    summary = _format_result_summary(tool_name, result_text)
                    thinking_steps.append({
                        "tool": tool_name,
                        "args_hint": args_hint,
                        "summary": summary,
                        "duration_ms": round(duration_ms),
                    })

                    yield ToolDoneEvent(
                        tool=tool_name,
                        summary=summary,
                        args_hint=args_hint,
                        duration_ms=duration_ms,
                        result=result_text or "",
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
        await self._emit_session_end(context, round_count, "max_rounds")
        yield MessageDoneEvent(
            full_text=full_text,
            thinking_steps=thinking_steps,
            final_action=final_action,
            rounds=round_count,
            total_tokens=self.budget.used_tokens,
            all_confirm_results=all_confirm_results,
        )

    async def _emit_assistant_stop(self, context: dict, full_text: str, rounds: int) -> None:
        """AI 回复完成后 emit ASSISTANT_STOP Hook，用于注入 nudge 消息等后处理"""
        if not self.hooks:
            return
        try:
            from hooks.types import HookEvent, ToolHookContext
            await self.hooks.emit(ToolHookContext(
                event=HookEvent.ASSISTANT_STOP,
                assistant_reply=full_text[:300] if full_text else "",
                rounds=rounds,
                project_id=context.get("project_id"),
                agent_type=context.get("agent_type"),
            ))
        except Exception as e:
            logger.debug("_emit_assistant_stop 失败（非致命）: %s", e)

    async def _emit_session_end(self, context: dict, rounds: int, reason: str) -> None:
        """在 MessageDone 前 emit SESSION_END Hook，用于审计日志记录本次 QueryEngine 运行统计"""
        if not self.hooks:
            return
        try:
            from hooks.types import HookEvent, ToolHookContext
            ctx = ToolHookContext(
                event=HookEvent.SESSION_END,
                tool_name="query_engine",
                input={
                    "rounds":       rounds,
                    "total_tokens": self.budget.used_tokens,
                    "elapsed_s":    round(self.budget.elapsed_seconds, 1),
                    "reason":       reason,          # done / max_rounds
                    "max_tokens":   self.budget.max_tokens,
                    "max_turns":    self.budget.max_turns,
                },
                duration_ms=self.budget.elapsed_seconds * 1000,
                project_id=context.get("project_id"),
                ticket_id=context.get("ticket_id"),
                agent_type=context.get("agent_type"),
            )
            await self.hooks.emit(ctx)
        except Exception as e:
            logger.debug("_emit_session_end 失败（非致命）: %s", e)
