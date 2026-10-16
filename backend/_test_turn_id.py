"""
turn_id 贯通：行为测试
    python backend/_test_turn_id.py

「一次对话」以前没有 ID。msg_group_key 名字对了，但 `req.msg_group_key or _sid`
一回落就退化成整个会话的 ID，而且只有 cli_task_log 用它 —— LLM 调用和工具调用
两张表里根本没有这个字段，事后拼不出一轮对话到底干了什么。

钉住的关键行为：
  1. turn_id 服务端生成，每轮唯一。前端传什么都不影响（旧前端还在传 sess_<ts>，
     那个值现在只当展示标签）。
  2. 一轮里的**所有** LLM 调用共享同一个 turn_id —— 包括 Compaction 这种嵌套
     调用。区分它们靠 action，不靠 turn_id。这正是「压缩那次调用被算成用户
     那次」的反面：同 turn 不等于同 action。
  3. 工具调用从 contextvars 里取 turn_id，调用点不用传。
  4. 三张表能按同一个 turn_id JOIN 出完整一轮。
  5. budget_exceeded / CLI 单轮 / finish 都要留下 query_engine:done 记录。
     以前这三条路径直接 return，最该留痕的结束方式反而一条都没有。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

_pass = _fail = 0


def check(name, cond, detail=""):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"[OK] {name}" + (f" -- {detail}" if detail else ""))
    else:
        _fail += 1
        print(f"[FAIL] {name}" + (f" -- {detail}" if detail else ""))


# ── 1. contextvars 载体 ──────────────────────────────────────────────────
def test_ctx():
    from llm_client import _llm_ctx, set_llm_context, clear_llm_context

    set_llm_context(project_id="P1", agent_type="ChatAssistant",
                    action="chat_stream", turn_id="TURN-x")
    check("set_llm_context 带得动 turn_id", _llm_ctx.turn_id == "TURN-x")
    check("不传 turn_id 时为 None（老调用点不炸）",
          (set_llm_context(action="a"), _llm_ctx.turn_id)[1] is None)
    set_llm_context(turn_id="TURN-y")
    clear_llm_context()
    check("clear_llm_context 清掉 turn_id", _llm_ctx.turn_id is None)


async def test_ctx_isolation():
    """协程隔离：两轮对话并发时 turn_id 不能串台。"""
    from llm_client import _llm_ctx, set_llm_context

    seen = {}

    async def one_turn(tid):
        set_llm_context(turn_id=tid)
        await asyncio.sleep(0.01)          # 让另一个协程插进来
        seen[tid] = _llm_ctx.turn_id

    # 必须各自跑在独立的 Context 里，contextvars 才隔离
    import contextvars
    await asyncio.gather(*[
        asyncio.create_task(one_turn(f"TURN-{i}"), context=contextvars.copy_context())
        for i in range(4)
    ])
    check("并发对话的 turn_id 互不串台", all(k == v for k, v in seen.items()), str(seen))


# ── 2. 落库 + JOIN ──────────────────────────────────────────────────────
async def test_persist_and_join():
    from database import db
    from llm_client import set_llm_context, clear_llm_context, llm_client
    from utils import generate_id, now_iso

    await db.connect()
    try:
        await db.init_tables()   # _auto_migrate 挂在 init_tables，单跑必须显式触发
        cols = {t: [r["name"] for r in await db.fetch_all(f"PRAGMA table_info({t})")]
                for t in ("llm_conversations", "tool_audit_log")}
        check("迁移给 llm_conversations 加上了 turn_id",
              "turn_id" in cols["llm_conversations"])
        check("迁移给 tool_audit_log 加上了 turn_id",
              "turn_id" in cols["tool_audit_log"])
        if not all("turn_id" in c for c in cols.values()):
            return

        turn = generate_id("TURN")
        other_turn = generate_id("TURN")
        check("两次生成的 turn_id 不同（每轮唯一）", turn != other_turn)

        pid = "__global__"
        try:
            await db.execute("DELETE FROM llm_conversations WHERE turn_id IN (?, ?)",
                             (turn, other_turn))
            await db.execute("DELETE FROM tool_audit_log WHERE turn_id IN (?, ?)",
                             (turn, other_turn))
        except Exception:
            pass

        # ── 模拟一轮对话：主调用 + 嵌套的 Compaction 调用 + 两次工具调用 ──
        set_llm_context(project_id=pid, agent_type="ChatAssistant",
                        action="chat_stream", turn_id=turn)
        await llm_client._save_conversation(
            [{"role": "user", "content": "看一下 app.py"}], "看完了",
            {"input_tokens": 120, "output_tokens": 30}, 900,
        )
        # 嵌套调用：同 turn，不同 action —— 这是 turn_id 必须允许的一对多
        set_llm_context(project_id=pid, agent_type="ChatAssistant",
                        action="compact_history", turn_id=turn)
        await llm_client._save_conversation(
            [{"role": "user", "content": "压缩历史"}], "摘要…",
            {"input_tokens": 4000, "output_tokens": 200}, 2100,
        )
        # 工具调用：不显式传 turn_id，靠 contextvars
        set_llm_context(project_id=pid, agent_type="ChatAssistant",
                        action="chat_stream", turn_id=turn)
        from hooks.builtin import audit_log_hook
        from hooks.types import HookEvent, ToolHookContext
        for tool, inp in [("read_files", {"paths": ["app.py"]}),
                          ("grep", {"pattern": "login"})]:
            await audit_log_hook(ToolHookContext(
                event=HookEvent.POST_TOOL_USE, tool_name=tool, input=inp,
                output="ok", duration_ms=12.0, project_id=pid,
                agent_type="ChatAssistant",
            ))

        # 另一轮对话：用来验证 JOIN 不会把别人的记录捞进来
        set_llm_context(project_id=pid, agent_type="ChatAssistant",
                        action="chat_stream", turn_id=other_turn)
        await llm_client._save_conversation(
            [{"role": "user", "content": "另一轮"}], "回复",
            {"input_tokens": 10, "output_tokens": 5}, 100,
        )
        await audit_log_hook(ToolHookContext(
            event=HookEvent.POST_TOOL_USE, tool_name="glob", input={"pattern": "*.py"},
            output="ok", duration_ms=5.0, project_id=pid, agent_type="ChatAssistant",
        ))
        clear_llm_context()

        # ── 断言 ─────────────────────────────────────────────────────
        llms = await db.fetch_all(
            "SELECT action, input_tokens, output_tokens FROM llm_conversations "
            "WHERE turn_id = ? ORDER BY created_at", (turn,))
        check("一轮里的所有 LLM 调用挂同一个 turn_id", len(llms) == 2, f"{len(llms)} 条")
        check("嵌套的 Compaction 调用靠 action 区分，不被当成同一次",
              sorted(r["action"] for r in llms) == ["chat_stream", "compact_history"],
              str([r["action"] for r in llms]))
        check("token 各自独立记账（压缩那 4000 不会记到用户那次上）",
              sorted(r["input_tokens"] for r in llms) == [120, 4000],
              str([r["input_tokens"] for r in llms]))

        tools = await db.fetch_all(
            "SELECT tool_name FROM tool_audit_log WHERE turn_id = ? ORDER BY id", (turn,))
        check("工具调用不用显式传 turn_id 也落到了同一轮",
              [r["tool_name"] for r in tools] == ["read_files", "grep"],
              str([r["tool_name"] for r in tools]))

        # 核心验收：按同一个 key JOIN 出完整一轮
        joined = await db.fetch_all(
            "SELECT c.action AS llm_action, t.tool_name "
            "FROM llm_conversations c LEFT JOIN tool_audit_log t ON c.turn_id = t.turn_id "
            "WHERE c.turn_id = ?", (turn,))
        check("三表能按同一个 turn_id JOIN 出完整一轮",
              len(joined) == 4, f"2 次 LLM × 2 次工具 = 4，实得 {len(joined)}")
        check("JOIN 不串到别的对话",
              not await db.fetch_all(
                  "SELECT 1 FROM llm_conversations WHERE turn_id = ? AND action = 'compact_history'",
                  (other_turn,)))

        await db.execute("DELETE FROM llm_conversations WHERE turn_id IN (?, ?)",
                         (turn, other_turn))
        await db.execute("DELETE FROM tool_audit_log WHERE turn_id IN (?, ?)",
                         (turn, other_turn))
    finally:
        await db.disconnect()   # aiosqlite 的后台线程不断开会吊住进程


# ── 3. 端点生成 turn_id，不听前端的 ─────────────────────────────────────
async def test_endpoint_generates():
    """把 agent 换成假的，只看端点吐出来的 SSE。"""
    import api.chat as C

    captured = {}

    class _FakeAgent:
        async def chat_stream(self, **kw):
            captured["turn_id"] = kw.get("turn_id")
            yield {"type": "text_delta", "delta": "hi"}
            yield {"type": "message_done", "rounds": 2, "total_tokens": 777,
                   "stop_reason": "end_turn", "thinking_steps": []}

    import agent_registry as _ar
    _orig_get = _ar.get_registry
    _ar.get_registry = lambda: {"ChatAssistant": _FakeAgent}
    _orig_save = C._save_chat_message
    _orig_hist = C._load_session_history
    _orig_mcp = C._stream_mcp_status_events

    async def _noop_save(*a, **k): return "MSG-fake"
    async def _noop_hist(*a, **k): return []
    async def _noop_mcp(*a, **k):
        return
        yield  # pragma: no cover
    C._save_chat_message = _noop_save
    C._load_session_history = _noop_hist
    C._stream_mcp_status_events = _noop_mcp

    try:
        req = C.ChatRequest(message="看一下 app.py",
                            chat_session_id="SESS-1",
                            msg_group_key="sess_1700000000")  # 旧前端传的值
        chunks = []
        async for b in C._chat_stream_generator(
            "__global__", {"id": "__global__"}, {}, req,
        ):
            chunks.append(b.decode("utf-8") if isinstance(b, bytes) else str(b))
        blob = "".join(chunks)

        import json as _json
        def _payload(evt):
            for part in blob.split("\n\n"):
                if part.startswith(f"event: {evt}"):
                    for line in part.split("\n"):
                        if line.startswith("data: "):
                            return _json.loads(line[6:])
            return None

        tb = _payload("turn_begin")
        check("端点推 turn_begin 事件（前端才能对上分组 key）", tb is not None)
        tid = (tb or {}).get("turn_id", "")
        check("turn_id 是服务端生成的，不是前端传来的 sess_<ts>",
              tid.startswith("TURN-") and tid != "sess_1700000000", tid)
        check("turn_id 也没回落成 session_id", tid != "SESS-1", tid)
        check("同一个 turn_id 传进了 agent（落库用的就是这个值）",
              captured.get("turn_id") == tid, f'{captured.get("turn_id")} vs {tid}')

        md = _payload("message_done") or {}
        check("message_done 带回 turn_id（前端可据此拉本轮明细）",
              md.get("turn_id") == tid, str(md.get("turn_id")))
        check("total_tokens 不再被丢掉", md.get("total_tokens") == 777,
              str(md.get("total_tokens")))
    finally:
        _ar.get_registry = _orig_get
        C._save_chat_message = _orig_save
        C._load_session_history = _orig_hist
        C._stream_mcp_status_events = _orig_mcp


# ── 4. 三条早退路径都要留 SESSION_END ──────────────────────────────────
async def test_session_end_on_early_returns():
    from query_engine import QueryEngine, Budget
    from query_engine.events import BudgetExceededEvent, MessageDoneEvent
    from hooks.types import HookEvent

    class _RecordingHooks:
        def __init__(self): self.reasons = []
        async def emit(self, ctx):
            if ctx.event == HookEvent.SESSION_END:
                self.reasons.append((ctx.input or {}).get("reason"))

    class _NoopExec:
        async def execute(self, *a, **k): return {"result": "ok"}

    # (a) 预算超限
    hooks = _RecordingHooks()
    budget = Budget(max_tokens=1, max_turns=1, max_seconds=1)
    budget.consume(tokens=10_000)    # 直接顶穿
    engine = QueryEngine(llm_client=_FakeCliLLM(), tool_executor=_NoopExec(),
                         budget=budget, hooks=hooks, max_rounds=3)
    evs = [e async for e in engine.run([], "", [], {})]
    check("预算超限也留下 query_engine:done 记录",
          hooks.reasons == ["budget_exceeded"], str(hooks.reasons))
    check("预算超限仍然 yield BudgetExceededEvent",
          any(isinstance(e, BudgetExceededEvent) for e in evs))

    # (b) CLI 单轮（默认模型走的就是这条）
    hooks2 = _RecordingHooks()
    engine2 = QueryEngine(llm_client=_FakeCliLLM(), tool_executor=_NoopExec(),
                          budget=Budget(max_tokens=10**6, max_turns=10, max_seconds=600),
                          hooks=hooks2, max_rounds=3)
    evs2 = [e async for e in engine2.run([{"role": "user", "content": "hi"}], "sys", [], {})]
    check("CLI 单轮分支也留下 query_engine:done 记录",
          hooks2.reasons == ["done"], str(hooks2.reasons))
    check("CLI 分支照常 yield MessageDoneEvent",
          any(isinstance(e, MessageDoneEvent) for e in evs2))


class _FakeCliLLM:
    """最小的 CLI 模式 LLM stub：走 engine 的 cli 分支，吐一段文本就收工。"""
    api_format = "cli"
    cli_type = "codebuddy"
    model = "fake-cli"
    cli_model = "fake-cli"
    is_configured = True

    async def _call_cli_stream(self, *a, **k):
        yield {"type": "text", "text": "CLI 回复"}


def main():
    test_ctx()
    asyncio.run(test_ctx_isolation())
    asyncio.run(test_persist_and_join())
    asyncio.run(test_endpoint_generates())
    asyncio.run(test_session_end_on_early_returns())

    print(f"\n{_pass} passed, {_fail} failed")
    sys.exit(1 if _fail else 0)


if __name__ == "__main__":
    main()
