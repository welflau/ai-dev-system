"""端到端验证：直接驱动 _group_board_generator（真实 DB + 真实 LLM CLI），
观察 SSE 事件 + 黑板落库。不用起 HTTP server。"""
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import db
from utils import generate_id
from api.chat import GroupBoardRequest, _group_board_generator


async def main():
    await db.connect()
    await db.init_tables()  # 确保 speaker/kind 列 + chat_blackboards 表已迁移

    pid = "PRJ-20260817-416710"  # MyFlappy
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (pid,))
    if not project:
        print("project not found:", pid)
        await db.disconnect()
        return

    sid = generate_id("E2E")
    req = GroupBoardRequest(
        message="用一句话设计这个项目最核心的玩法亮点，并给出一个技术实现要点",
        chat_session_id=sid,
        rounds=2,
    )
    print(f"=== 开始黑板群聊 E2E === project={pid} session={sid}\n")

    try:
        gen = _group_board_generator(pid, dict(project), req)
        evt = ""
        async for chunk in gen:
            text = chunk.decode("utf-8", "replace")
            for line in text.split("\n"):
                if line.startswith("event:"):
                    evt = line.split(":", 1)[1].strip()
                    print(f"\n--- [{evt}] ---")
                elif line.startswith("data:") and evt:
                    try:
                        data = json.loads(line.split(":", 1)[1].strip())
                    except Exception:
                        continue
                    if evt == "agent_thought":
                        print(f"  [思考 {data.get('agent')} r{data.get('round')}] {data.get('thought','')[:150]}")
                    elif evt == "agent_message":
                        print(f"  [发言 {data.get('agent')} r{data.get('round')}] {data.get('content','')[:200]}")
                    elif evt == "board_update":
                        print(f"  黑板 v{data['board'].get('version')} 改动分区: {data.get('changed_sections')}")
                    elif evt == "converge":
                        print(f"  [收敛] {data.get('content','')[:400]}")
                    elif evt == "board_init":
                        print(f"  主题: {data['board'].get('topic')}")
                    elif evt == "message_done":
                        print(f"  done turn={data.get('turn_id')}")
                    elif evt == "error":
                        print(f"  !! ERROR: {data}")
                    else:
                        print(f"  {data}")
    finally:
        # 验证落库
        print("\n=== DB 验证 ===")
        bb = await db.fetch_one(
            "SELECT version, state_json FROM chat_blackboards WHERE session_id=?", (sid,)
        )
        if bb:
            state = json.loads(bb["state_json"])
            print(f"chat_blackboards version={bb['version']}")
            for sec in ("proposals", "open_questions", "decisions"):
                items = state.get(sec, [])
                if items:
                    print(f"  {sec}: {len(items)} 条")
                    for it in items:
                        print(f"    - [{it.get('agent')}] {it.get('content','')[:80]}")
        else:
            print("!! chat_blackboards 无记录")

        msgs = await db.fetch_all(
            "SELECT speaker, kind, substr(content,1,50) c, thinking_json IS NOT NULL AS has_think "
            "FROM chat_messages WHERE session_id=? ORDER BY created_at ASC, id ASC", (sid,)
        )
        print(f"chat_messages: {len(msgs)} 条")
        for m in msgs:
            print(f"  speaker={m['speaker']} kind={m['kind']} think={bool(m['has_think'])} | {m['c']}")

        await db.disconnect()


asyncio.run(main())
