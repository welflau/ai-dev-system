"""
/api/chat/sessions/{id}/trace 行为测试
    python backend/_test_chat_trace.py

钉住的关键行为：
  1. 消息、LLM 调用、工具调用按 turn_id JOIN 出完整一轮，不串到别的 turn。
  2. 嵌套的 Compaction LLM 调用挂同一个 turn_id，但靠 action 区分——
     `total_input_tokens` 要把它一起算进去，别只算主调用。
  3. SESSION_END（query_engine:done）单独拎出来当 turn 结束标记，
     不混进 tool_calls 里。
  4. 未挂 turn_id 的旧消息不丢，落进 orphan_messages。
  5. turn 按 started_at 排序：第二轮的消息虽然 chat_messages 的 id 大，
     但如果时间早，排在前面（模拟异步落库时序偏差）。
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


async def test_trace():
    from database import db
    from utils import generate_id, now_iso, iso_before
    from llm_client import set_llm_context, clear_llm_context, llm_client
    from hooks.builtin import audit_log_hook, _handle_session_end
    from hooks.types import HookEvent, ToolHookContext
    from api.chat import get_session_trace, _save_chat_message

    await db.connect()
    try:
        await db.init_tables()

        pid = "__global__"
        sid = generate_id("sess-")
        turn1 = generate_id("TURN")
        turn2 = generate_id("TURN")
        orphan_sid = sid  # 同一个 session 也带一条 orphan（模拟历史遗留）

        # 造 session
        now = now_iso()
        await db.execute(
            "INSERT OR IGNORE INTO chat_sessions (id, project_id, title, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (sid, None, "trace 测试会话", now, now),
        )

        # ── turn 1：主 LLM + 嵌套 Compaction + 一次工具调用 + query_engine:done ──
        await _save_chat_message(pid, "user", "看一下 app.py", session_id=sid, turn_id=turn1)

        set_llm_context(project_id=pid, agent_type="ChatAssistant",
                        action="chat_stream", turn_id=turn1)
        await llm_client._save_conversation(
            [{"role": "user", "content": "看一下 app.py"}], "看完了",
            {"input_tokens": 120, "output_tokens": 30}, 900,
        )
        set_llm_context(project_id=pid, agent_type="ChatAssistant",
                        action="compact_history", turn_id=turn1)
        await llm_client._save_conversation(
            [{"role": "user", "content": "压缩历史"}], "摘要…",
            {"input_tokens": 4000, "output_tokens": 200}, 2100,
        )
        set_llm_context(project_id=pid, agent_type="ChatAssistant",
                        action="chat_stream", turn_id=turn1)
        await audit_log_hook(ToolHookContext(
            event=HookEvent.POST_TOOL_USE, tool_name="read_files",
            input={"paths": ["app.py"]}, output="ok", duration_ms=12.0,
            project_id=pid, agent_type="ChatAssistant",
        ))
        await _handle_session_end(ToolHookContext(
            event=HookEvent.SESSION_END, tool_name="query_engine",
            input={"rounds": 1, "total_tokens": 4350, "elapsed_s": 3.0,
                   "reason": "done", "max_tokens": 100000, "max_turns": 10},
            duration_ms=3000, project_id=pid, agent_type="ChatAssistant",
        ))

        await _save_chat_message(pid, "assistant", "看完了", session_id=sid, turn_id=turn1)

        # ── turn 2：只有一次简单调用，assistant 消息带思考 ──
        await _save_chat_message(pid, "user", "再看看 test.py", session_id=sid, turn_id=turn2)
        set_llm_context(project_id=pid, agent_type="ChatAssistant",
                        action="chat_stream", turn_id=turn2)
        await llm_client._save_conversation(
            [{"role": "user", "content": "再看看 test.py"}], "看完了",
            {"input_tokens": 80, "output_tokens": 20}, 500,
        )
        thinking_payload = [
            {"round": 1, "reasoning": "这是一个测试文件请求，应该先读文件再回答。",
             "steps": [], "events": []},
        ]
        await _save_chat_message(pid, "assistant", "看完了", session_id=sid,
                                 turn_id=turn2, thinking=thinking_payload)

        # ── orphan：无 turn_id 的旧消息 ──
        await _save_chat_message(pid, "user", "老消息（无 turn_id）", session_id=sid)

        clear_llm_context()

        # ── 调接口 ─────────────────────────────────────────────────
        resp = await get_session_trace(sid)
        turns = resp["turns"]

        check("返回本 session 的两个 turn", len(turns) == 2, f"实得 {len(turns)}")

        # 找出 turn1 / turn2 对应的返回条目
        t1 = next((t for t in turns if t["turn_id"] == turn1), None)
        t2 = next((t for t in turns if t["turn_id"] == turn2), None)
        check("turn1 存在", t1 is not None)
        check("turn2 存在", t2 is not None)

        if t1 and t2:
            # 关键行为 1：JOIN 只捞属于本轮的记录
            check("turn1 拿到两条 LLM（主 + Compaction）",
                  len(t1["llm_calls"]) == 2, f"{len(t1['llm_calls'])}")
            check("turn2 只拿到一条 LLM，不串到 turn1",
                  len(t2["llm_calls"]) == 1, f"{len(t2['llm_calls'])}")
            check("turn1 只拿到 read_files 一个工具",
                  [t["tool_name"] for t in t1["tool_calls"]] == ["read_files"],
                  str([t["tool_name"] for t in t1["tool_calls"]]))
            check("turn2 没有工具调用（读文件不属于它）",
                  t2["tool_calls"] == [], str(t2["tool_calls"]))

            # 关键行为 2：token 统计把 Compaction 也算进去
            check("turn1 的 total_input_tokens 覆盖主+嵌套（120+4000）",
                  t1["total_input_tokens"] == 4120, str(t1["total_input_tokens"]))
            check("turn1 的 total_output_tokens 覆盖主+嵌套（30+200）",
                  t1["total_output_tokens"] == 230, str(t1["total_output_tokens"]))

            # 关键行为 3：SESSION_END 单独拎出来
            check("turn1 有 session_end（query_engine:done）",
                  t1["session_end"] is not None and
                  t1["session_end"]["tool_name"] == "query_engine:done",
                  str(t1.get("session_end", {}).get("tool_name")))
            check("session_end 不重复出现在 tool_calls 里",
                  not any(t["tool_name"] == "query_engine:done" for t in t1["tool_calls"]))

            # 关键行为：消息也按 turn 分组
            check("turn1 的 messages 含 user + assistant 各 1 条",
                  len(t1["messages"]) == 2 and
                  [m["role"] for m in t1["messages"]] == ["user", "assistant"],
                  str([m["role"] for m in t1["messages"]]))

        # 关键行为 4：orphan 不丢
        orphans = resp["orphan_messages"]
        check("orphan_messages 收到无 turn_id 的旧消息",
              len(orphans) == 1 and orphans[0]["content"].startswith("老消息"),
              f"{len(orphans)} 条")

        # 关键行为 5：turn 按时间排序（turn1 先，turn2 后）
        check("turns 按 started_at 升序排列",
              turns[0]["turn_id"] == turn1 and turns[1]["turn_id"] == turn2,
              str([t["turn_id"] for t in turns]))

        # 关键行为 6：thinking 字段透传到助手消息，前端才能画「思考过程」折叠区
        if t2:
            asst2 = next((m for m in t2["messages"] if m["role"] == "assistant"), None)
            check("turn2 助手消息带出 thinking 数组",
                  asst2 is not None and isinstance(asst2.get("thinking"), list)
                  and len(asst2["thinking"]) == 1
                  and asst2["thinking"][0].get("reasoning", "").startswith("这是一个"),
                  str((asst2 or {}).get("thinking"))[:80])

        # 附加：接口拒绝不存在的 session
        from fastapi import HTTPException
        try:
            await get_session_trace("SESS-does-not-exist")
            check("不存在的 session 抛 404", False, "应抛 HTTPException")
        except HTTPException as e:
            check("不存在的 session 抛 404", e.status_code == 404, str(e.status_code))

        # 清理
        await db.execute("DELETE FROM chat_messages WHERE session_id = ?", (sid,))
        await db.execute("DELETE FROM chat_sessions  WHERE id = ?", (sid,))
        await db.execute("DELETE FROM llm_conversations WHERE turn_id IN (?, ?)", (turn1, turn2))
        await db.execute("DELETE FROM tool_audit_log   WHERE turn_id IN (?, ?)", (turn1, turn2))
    finally:
        await db.disconnect()


def main():
    asyncio.run(test_trace())
    asyncio.run(test_global_scope())
    print(f"\n{_pass} passed, {_fail} failed")
    sys.exit(1 if _fail else 0)


async def test_global_scope():
    """全局会话（chat_sessions.project_id IS NULL）走独立的 global_chat_router：
    /api/chat/sessions (list_global_sessions) + /api/chat/sessions/{id}/trace
    (get_global_session_trace)。项目 scope 的接口拉不到它，反之亦然。"""
    from database import db
    from utils import generate_id, now_iso
    from llm_client import set_llm_context, clear_llm_context, llm_client
    from api.chat import (
        get_session_trace, list_sessions, list_global_sessions,
        get_global_session_trace, _save_chat_message,
    )

    await db.connect()
    try:
        await db.init_tables()
        gsid = generate_id("sess-")
        gturn = generate_id("TURN")
        now = now_iso()
        # 全局会话：chat_sessions.project_id 明确为 NULL
        await db.execute(
            "INSERT OR IGNORE INTO chat_sessions (id, project_id, title, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (gsid, None, "全局对话", now, now),
        )
        await _save_chat_message("__global__", "user", "全局 hello",
                                 session_id=gsid, turn_id=gturn)
        set_llm_context(project_id="__global__", agent_type="ChatAssistant",
                        action="chat_stream", turn_id=gturn)
        await llm_client._save_conversation(
            [{"role": "user", "content": "全局 hello"}], "回复",
            {"input_tokens": 5, "output_tokens": 3}, 100,
        )
        await _save_chat_message("__global__", "assistant", "回复",
                                 session_id=gsid, turn_id=gturn)
        clear_llm_context()

        # 全局 list：/api/chat/sessions → list_global_sessions
        gd = await list_global_sessions(limit=100)
        gids = {s["id"] for s in gd["sessions"]}
        check("list_global_sessions 拉到全局会话", gsid in gids, f"命中 {len(gids)} 个")

        # 项目 list 反向：/api/projects/{pid}/chat/sessions 拉不到全局会话
        pd = await list_sessions("tiktok-clone-fake-id", limit=100)
        check("项目 list_sessions 不会捞到全局会话",
              gsid not in {s["id"] for s in pd["sessions"]})

        # 全局 /trace：/api/chat/sessions/{id}/trace → get_global_session_trace
        gt = await get_global_session_trace(gsid)
        check("global /trace 返回全局会话的 turn",
              len(gt["turns"]) == 1 and gt["turns"][0]["turn_id"] == gturn)

        # 清理
        await db.execute("DELETE FROM chat_messages WHERE session_id = ?", (gsid,))
        await db.execute("DELETE FROM chat_sessions WHERE id = ?", (gsid,))
        await db.execute("DELETE FROM llm_conversations WHERE turn_id = ?", (gturn,))
    finally:
        await db.disconnect()


if __name__ == "__main__":
    main()
