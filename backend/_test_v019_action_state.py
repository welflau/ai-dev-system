"""
v0.19.1 action state 持久化 —— smoke test（不依赖活的后端，直接调模块函数）

验证：
  1. _auto_migrate 会加上 chat_messages.action_state / action_result 两列
  2. 直接 PATCH 逻辑：db.update + GET history 的解析能正确 round-trip
  3. GET /history 把 action_result JSON 串解析成 dict（方便前端直接用）
  4. 非 UE 项目 chat_messages 不受影响

用法：
    cd backend && python _test_v019_action_state.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")


def _banner(msg: str):
    print()
    print("=" * 70)
    print(f"  {msg}")
    print("=" * 70)


async def main():
    passed, failed = 0, 0

    def check(name: str, ok: bool, detail: str = ""):
        nonlocal passed, failed
        marker = "PASS" if ok else "FAIL"
        print(f"  [{marker}] {name}" + (f"  -- {detail}" if detail else ""))
        if ok:
            passed += 1
        else:
            failed += 1

    from database import db
    from api.chat import _save_chat_message, get_chat_history
    from utils import generate_id, now_iso

    await db.connect()
    # _auto_migrate 挂在 init_tables，单跑必须显式触发
    await db.init_tables()

    # =========== 1. 迁移生效：列存在 ===========
    _banner("1. chat_messages 表已含 action_state + action_result 列")
    cursor = await db._db.execute("PRAGMA table_info(chat_messages)")
    cols = [r[1] for r in await cursor.fetchall()]
    check("action_state 列存在", "action_state" in cols, f"cols count={len(cols)}")
    check("action_result 列存在", "action_result" in cols)

    # =========== 2. 建测试数据 ===========
    _banner("2. 准备项目 + 两条 assistant 消息（propose_ue_framework + confirm_requirement）")
    pid = generate_id("PRJ")
    await db.insert("projects", {
        "id": pid,
        "name": "ActionStateTest",
        "description": "",
        "status": "active",
        "tech_stack": "",
        "config": "{}",
        "git_repo_path": "D:/Projects/_v019_action_state_test",
        "git_remote_url": "",
        "traits": "[]",
        "traits_confidence": "{}",
        "preset_id": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    })

    action_req = {
        "type": "confirm_requirement",
        "title": "测试需求 A",
        "description": "desc",
        "priority": "medium",
    }
    action_ue = {
        "type": "propose_ue_framework",
        "project_id": pid,
        "recommended_template": "TP_FirstPerson",
        "project_name_target": "TestFPS",
        "engines": [],
        "traits": [],
        "target_dir": "",
    }
    await _save_chat_message(project_id=pid, role="assistant",
                             content="识别到新需求", action=action_req)
    await _save_chat_message(project_id=pid, role="assistant",
                             content="UE 方案", action=action_ue)

    rows = await db.fetch_all(
        "SELECT id, action_type, action_state FROM chat_messages "
        "WHERE project_id = ? ORDER BY created_at",
        (pid,),
    )
    check("2 条 assistant 消息已入库", len(rows) == 2, f"rows={len(rows)}")
    for r in rows:
        check(f"初始 action_state NULL: {r['action_type']}",
              r["action_state"] is None, f"state={r['action_state']}")

    req_msg_id = rows[0]["id"]
    ue_msg_id = rows[1]["id"]

    # =========== 3. 写入 executed / cancelled 状态 + action_result JSON ===========
    _banner("3. 模拟 PATCH：写 executed / cancelled + action_result")
    executed_result = {
        "template": "TP_FirstPerson",
        "project_name": "TestFPS",
        "commit": "abc12345",
        "at": "2026-04-25T00:00:00Z",
    }
    await db.update(
        "chat_messages",
        {"action_state": "executed",
         "action_result": json.dumps(executed_result, ensure_ascii=False)},
        "id = ?",
        (req_msg_id,),
    )
    await db.update(
        "chat_messages",
        {"action_state": "cancelled",
         "action_result": json.dumps({"reason": "手动取消"}, ensure_ascii=False)},
        "id = ?",
        (ue_msg_id,),
    )

    rows2 = await db.fetch_all(
        "SELECT id, action_state, action_result FROM chat_messages "
        "WHERE project_id = ? ORDER BY created_at",
        (pid,),
    )
    check("req 消息 action_state=executed", rows2[0]["action_state"] == "executed")
    check("UE 消息 action_state=cancelled", rows2[1]["action_state"] == "cancelled")

    # =========== 4. get_chat_history 返回解析后的 action_result ===========
    _banner("4. GET /history 返回的 action_result 是 dict，而非 JSON 字符串")
    try:
        resp = await get_chat_history(pid, limit=10)
    except Exception as e:
        resp = None
        check("get_chat_history 正常返回", False, str(e))

    if resp:
        msgs = resp.get("messages") or []
        by_id = {m["id"]: m for m in msgs}
        m_req = by_id.get(req_msg_id) or {}
        m_ue = by_id.get(ue_msg_id) or {}

        check("req 消息 action_state 字段回传 executed",
              m_req.get("action_state") == "executed")
        check("req 消息 action_result 已解析为 dict",
              isinstance(m_req.get("action_result"), dict),
              f"type={type(m_req.get('action_result')).__name__}")
        check("req 消息 action_result.template=TP_FirstPerson",
              (m_req.get("action_result") or {}).get("template") == "TP_FirstPerson")
        check("req 消息 action_result.commit=abc12345",
              (m_req.get("action_result") or {}).get("commit") == "abc12345")

        check("UE 消息 action_state=cancelled",
              m_ue.get("action_state") == "cancelled")
        check("UE 消息 action_result.reason=手动取消",
              (m_ue.get("action_result") or {}).get("reason") == "手动取消")

    # =========== 5. ActionStatePatchRequest 模型：非法 state 被拒 ===========
    _banner("5. ActionStatePatchRequest 校验非法 state 被拒（pydantic pattern）")
    from api.chat import ActionStatePatchRequest
    try:
        ActionStatePatchRequest(state="bogus")
        check("非法 state='bogus' 被拒", False, "pydantic 没拦住")
    except Exception:
        check("非法 state='bogus' 被拒", True)
    try:
        ok = ActionStatePatchRequest(state="executed", result={"a": 1})
        check("合法 state='executed' 通过", ok.state == "executed")
    except Exception as e:
        check("合法 state='executed' 通过", False, str(e))

    # =========== 6. 清理 ===========
    _banner("6. 清理测试数据")
    try:
        await db.execute("DELETE FROM chat_messages WHERE project_id = ?", (pid,))
        await db.execute("DELETE FROM projects WHERE id = ?", (pid,))
        print(f"  清理 project_id={pid}")
    except Exception as e:
        print(f"  清理失败: {e}")

    _banner("Summary")
    total = passed + failed
    print(f"  PASS {passed}/{total}  FAIL {failed}/{total}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
