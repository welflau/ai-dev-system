"""
Harness Phase 2 自动化测试：QueryEngine 统一循环

覆盖：
  T2-1  QueryEngine 单轮无工具调用 → MessageDoneEvent
  T2-2  QueryEngine 工具调用循环 → ToolStartEvent + ToolDoneEvent + MessageDoneEvent
  T2-3  QueryEngine Budget 超限 → BudgetExceededEvent（不再继续）
  T2-4  QueryEngine PRE Hook blocking 阻断工具执行
  T2-5  ChatToolExecutorAdapter 透传 thinking_steps 和 primary_action_result
  T2-6  OrchestratorToolExecutorAdapter 正确合并 context 调用 action

使用 Mock LLM，无需真实 API 调用。

运行：cd backend && python -m pytest _test_harness_p2.py -v
"""
import asyncio
import sys
import pytest
import pytest_asyncio

sys.path.insert(0, ".")


# ─────────────────────────────────────────────────────────────────────────────
# Mock LLM：可编程的 _call_anthropic_tools_stream
# ─────────────────────────────────────────────────────────────────────────────

def _make_mock_llm(rounds):
    """
    rounds: list of round_spec
    每个 round_spec 是 {"text": str, "tools": [{"id","name","input"}]}
    无 tools 字段或空列表 → 该轮结束循环
    """
    class _MockLLM:
        is_configured = True

        async def _call_anthropic_tools_stream(self, messages, tools, system,
                                                temperature=0.7, max_tokens=4000):
            if not rounds:
                yield {"type": "stop", "stop_reason": "end_turn", "usage": {}}
                return

            spec = rounds.pop(0)
            if spec.get("text"):
                yield {"type": "text_delta", "delta": spec["text"]}

            for tc in spec.get("tools", []):
                yield {"type": "tool_use_block",
                       "id": tc["id"], "name": tc["name"], "input": tc["input"]}

            stop_reason = "tool_use" if spec.get("tools") else "end_turn"
            yield {"type": "stop", "stop_reason": stop_reason,
                   "usage": {"input_tokens": 100, "output_tokens": 50}}

    return _MockLLM()


class _EchoExecutor:
    """简单 executor：直接 echo tool_name 作为结果"""
    thinking_steps = []
    primary_action_result = None
    all_confirm_results = []

    async def execute(self, tool_name, tool_input, context):
        return f"result:{tool_name}", None


# ─────────────────────────────────────────────────────────────────────────────
# T2-1  单轮无工具调用
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_query_engine_no_tools():
    from query_engine.engine import QueryEngine
    from query_engine.events import TextDeltaEvent, MessageDoneEvent

    llm = _make_mock_llm([{"text": "Hello, world!"}])
    engine = QueryEngine(llm, _EchoExecutor())

    events = []
    async for ev in engine.run([], "", [], {}):
        events.append(ev)

    types = [type(e).__name__ for e in events]
    assert "TextDeltaEvent" in types
    assert types[-1] == "MessageDoneEvent"

    done = events[-1]
    assert done.full_text == "Hello, world!"
    assert done.rounds == 1


# ─────────────────────────────────────────────────────────────────────────────
# T2-2  工具调用循环
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_query_engine_tool_call_loop():
    from query_engine.engine import QueryEngine
    from query_engine.events import ToolStartEvent, ToolDoneEvent, MessageDoneEvent

    rounds = [
        {"text": "让我搜索一下...", "tools": [{"id": "t1", "name": "glob", "input": {"pattern": "*.py"}}]},
        {"text": "搜索完成，结果是..."},
    ]
    llm = _make_mock_llm(rounds)
    engine = QueryEngine(llm, _EchoExecutor())

    events = []
    async for ev in engine.run([], "", [{"name": "glob"}], {}):
        events.append(ev)

    types = [type(e).__name__ for e in events]
    assert "ToolStartEvent" in types
    assert "ToolDoneEvent" in types
    assert types[-1] == "MessageDoneEvent"

    # 确认 ToolStartEvent 信息正确
    start = next(e for e in events if isinstance(e, ToolStartEvent))
    assert start.tool == "glob"
    assert start.tool_use_id == "t1"

    done = events[-1]
    assert done.rounds == 2


# ─────────────────────────────────────────────────────────────────────────────
# T2-3  Budget 超限截断
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_query_engine_budget_exceeded():
    from query_engine.engine import QueryEngine
    from query_engine.budget import Budget
    from query_engine.events import BudgetExceededEvent

    # 已用完 2 轮，max_turns=2 → 第 1 轮调用前就超限
    budget = Budget(max_tokens=999999, max_turns=2, max_seconds=999)
    budget.consume(turns=2)

    llm = _make_mock_llm([{"text": "should not appear"}])
    engine = QueryEngine(llm, _EchoExecutor(), budget=budget)

    events = []
    async for ev in engine.run([], "", [], {}):
        events.append(ev)

    assert any(isinstance(e, BudgetExceededEvent) for e in events)
    # 没有 TextDeltaEvent（被截断在第一轮开始前）
    from query_engine.events import TextDeltaEvent
    assert not any(isinstance(e, TextDeltaEvent) for e in events)


# ─────────────────────────────────────────────────────────────────────────────
# T2-4  PRE Hook blocking 阻断工具执行
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_query_engine_pre_hook_blocks_tool():
    from query_engine.engine import QueryEngine
    from query_engine.events import ToolErrorEvent, MessageDoneEvent
    from hooks.registry import HookRegistry
    from hooks.types import HookEvent, ToolHookContext

    fake_reg = HookRegistry()
    async def blocker(ctx):
        if ctx.event == HookEvent.PRE_TOOL_USE:
            raise RuntimeError("rate limit!")
    fake_reg.register(blocker)

    rounds = [
        {"tools": [{"id": "t1", "name": "shell", "input": {"cmd": "echo hi"}}]},
        {"text": "done"},
    ]
    llm = _make_mock_llm(rounds)
    engine = QueryEngine(llm, _EchoExecutor(), hooks=fake_reg)

    events = []
    async for ev in engine.run([], "", [], {}):
        events.append(ev)

    # ToolErrorEvent 应该出现（工具被拦截）
    assert any(isinstance(e, ToolErrorEvent) for e in events)
    err = next(e for e in events if isinstance(e, ToolErrorEvent))
    assert "rate limit" in err.error


# ─────────────────────────────────────────────────────────────────────────────
# T2-5  ChatToolExecutorAdapter 透传 thinking_steps
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_tool_executor_adapter_thinking_steps():
    from query_engine.executor import ChatToolExecutorAdapter

    class _MockInner:
        thinking_steps = [{"tool": "glob", "args_hint": "(*.py)", "summary": "5 files"}]
        primary_action_result = {"type": "git_result", "data": "ok"}
        all_confirm_results = []

        async def execute(self, tool_name, tool_input):
            # _ChatToolExecutor.execute 返回 str（JSON），不是 tuple
            return '{"status":"ok"}'

    adapter = ChatToolExecutorAdapter(_MockInner())
    assert adapter.thinking_steps == _MockInner.thinking_steps
    assert adapter.primary_action_result["type"] == "git_result"

    result_text, action_data = await adapter.execute("glob", {}, {})
    assert result_text == '{"status":"ok"}'


# ─────────────────────────────────────────────────────────────────────────────
# T2-6  OrchestratorToolExecutorAdapter 合并 context
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_orchestrator_executor_merges_context():
    from query_engine.executor import OrchestratorToolExecutorAdapter
    from actions.base import ActionBase, ActionResult

    received_ctx = {}

    class _FakeAction(ActionBase):
        name = "write_code"
        description = "test"
        async def run(self, ctx):
            received_ctx.update(ctx)
            return ActionResult(success=True, message="written")

    adapter = OrchestratorToolExecutorAdapter(
        {"write_code": _FakeAction()},
        base_context={"project_id": "proj-x", "ticket_id": "tk-x"},
    )
    text, action = await adapter.execute(
        "write_code",
        tool_input={"filename": "main.py"},
        context={"extra": "val"},
    )

    assert received_ctx["project_id"] == "proj-x"
    assert received_ctx["ticket_id"] == "tk-x"
    assert received_ctx["filename"] == "main.py"   # tool_input 被合并
    assert received_ctx["extra"] == "val"
    assert text == "written"
    assert action is None


# ─────────────────────────────────────────────────────────────────────────────
# 独立运行入口
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import subprocess, sys
    ret = subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"],
        cwd=str(__file__).rsplit("\\", 1)[0] or ".",
    )
    sys.exit(ret.returncode)
