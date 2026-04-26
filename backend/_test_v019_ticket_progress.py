"""
v0.19.x 工单面板「📍 当前进度」区 —— smoke test

不启 UBT，直接模拟 orchestrator 的心跳 callback：
  1. DB 迁移把 4 列加上
  2. _make_ticket_progress_callback 能过滤关键字 + throttle 写 DB
  3. GET /current-action 算 elapsed_ms / silence_ms / health 正确
  4. health 边界：< 60s → active / 60-300s → silent / > 300s → zombie / null latest_log → starting

用法：
    cd backend && python _test_v019_ticket_progress.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timezone, timedelta
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
    from orchestrator import TicketOrchestrator
    from utils import generate_id, now_iso

    await db.connect()
    await db.init_tables()

    # =========== 1. DB 迁移：tickets 含 4 列 ===========
    _banner("1. tickets 表含 current_action / started_at / latest_log / updated_at")
    c = await db._db.execute("PRAGMA table_info(tickets)")
    cols = [r[1] for r in await c.fetchall()]
    for col in ("current_action", "current_action_started_at",
                "current_action_latest_log", "current_action_updated_at"):
        check(f"列存在: {col}", col in cols)

    # =========== 2. 准备测试工单 ===========
    _banner("2. 建测试项目 + 工单")
    pid = generate_id("PRJ")
    rid = generate_id("REQ")
    tid = generate_id("TKT")
    await db.insert("projects", {
        "id": pid, "name": "TicketProgressTest", "description": "",
        "status": "active", "tech_stack": "", "config": "{}",
        "git_repo_path": "D:/Projects/_tpt",
        "git_remote_url": "", "traits": "[]",
        "traits_confidence": "{}", "preset_id": None,
        "created_at": now_iso(), "updated_at": now_iso(),
    })
    await db.insert("requirements", {
        "id": rid, "project_id": pid, "title": "",
        "description": "", "priority": "medium",
        "status": "pending", "created_at": now_iso(),
        "updated_at": now_iso(),
    })
    await db.insert("tickets", {
        "id": tid, "requirement_id": rid, "project_id": pid,
        "title": "test progress", "description": "",
        "module": "other", "status": "pending", "priority": 2,
        "created_at": now_iso(), "updated_at": now_iso(),
    })

    # =========== 3. orchestrator set / clear ===========
    _banner("3. _set_ticket_current_action + _clear 写清 4 列")
    orc = TicketOrchestrator()

    await orc._set_ticket_current_action(tid, "DevAgent.run_engine_compile")
    row = await db.fetch_one("SELECT * FROM tickets WHERE id = ?", (tid,))
    check("current_action 写入",
          row.get("current_action") == "DevAgent.run_engine_compile")
    check("current_action_started_at 写入",
          bool(row.get("current_action_started_at")))
    check("latest_log 初始为 NULL",
          row.get("current_action_latest_log") is None)

    await orc._clear_ticket_current_action(tid)
    row = await db.fetch_one("SELECT * FROM tickets WHERE id = ?", (tid,))
    check("clear 后 4 列都 NULL",
          all(row.get(k) is None for k in
              ("current_action", "current_action_started_at",
               "current_action_latest_log", "current_action_updated_at")),
          f"row={dict(row)}")

    # =========== 4. progress_cb 过滤关键字 + 写 DB ===========
    _banner("4. progress_cb 关键字过滤 + 写 DB")
    await orc._set_ticket_current_action(tid, "DevAgent.run_engine_compile")
    cb = orc._make_ticket_progress_callback(pid, tid)

    # 不含关键字 → 不写
    await cb("just some random line")
    row = await db.fetch_one(
        "SELECT current_action_latest_log FROM tickets WHERE id = ?", (tid,)
    )
    check("非关键字行不写 DB",
          row.get("current_action_latest_log") is None,
          f"got={row.get('current_action_latest_log')}")

    # 含 error 关键字 → 写
    await cb("TestFoo.cpp(42): error C2065: undeclared identifier")
    row = await db.fetch_one(
        "SELECT current_action_latest_log, current_action_updated_at FROM tickets WHERE id = ?",
        (tid,),
    )
    check("含 error 行写入 DB", "error C2065" in (row.get("current_action_latest_log") or ""))
    check("updated_at 已写", bool(row.get("current_action_updated_at")))

    # 5s 内重复写 → throttle
    old_log = row.get("current_action_latest_log")
    await cb("AnotherFile.cpp(10): error C3668: 另一个错误")   # 5s 内
    row2 = await db.fetch_one(
        "SELECT current_action_latest_log FROM tickets WHERE id = ?", (tid,)
    )
    check("5s throttle 生效（仍是第一条）",
          row2.get("current_action_latest_log") == old_log,
          f"now={row2.get('current_action_latest_log')}")

    # =========== 5. GET /current-action 算 elapsed / silence / health ===========
    _banner("5. GET /current-action 返回 elapsed / silence / health")
    from api.tickets import get_ticket_current_action
    resp = await get_ticket_current_action(pid, tid)
    check("返回 current_action 匹配",
          resp.get("current_action") == "DevAgent.run_engine_compile")
    check("返回 elapsed_ms (int)", isinstance(resp.get("elapsed_ms"), int))
    check("返回 latest_log", bool(resp.get("latest_log")))
    check("返回 health == active（刚写过 log）",
          resp.get("health") == "active",
          f"got={resp.get('health')}")

    # =========== 6. health 边界：无 log + 老 started_at → zombie ===========
    _banner("6. health 边界判定")
    # 手动把 started_at 改到 400s 前 + latest_log 清空 → zombie
    old_ts = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
    await db.update("tickets", {
        "current_action_started_at": old_ts,
        "current_action_latest_log": None,
        "current_action_updated_at": None,
    }, "id = ?", (tid,))
    resp2 = await get_ticket_current_action(pid, tid)
    check("老 started_at 无 log → zombie",
          resp2.get("health") == "zombie",
          f"got={resp2.get('health')}")

    # started_at 30s 前 + 无 log → starting
    new_ts = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    await db.update("tickets", {
        "current_action_started_at": new_ts,
    }, "id = ?", (tid,))
    resp3 = await get_ticket_current_action(pid, tid)
    check("新 started_at 无 log → starting",
          resp3.get("health") == "starting",
          f"got={resp3.get('health')}")

    # started_at 30s + log 在 120s 前 → silent
    old_log_ts = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    await db.update("tickets", {
        "current_action_latest_log": "some log",
        "current_action_updated_at": old_log_ts,
    }, "id = ?", (tid,))
    resp4 = await get_ticket_current_action(pid, tid)
    check("log 120s 前 → silent",
          resp4.get("health") == "silent",
          f"got={resp4.get('health')}")

    # =========== 7. current_action=NULL → health=None ===========
    _banner("7. current_action=NULL → 接口返回 health=None")
    await orc._clear_ticket_current_action(tid)
    resp5 = await get_ticket_current_action(pid, tid)
    check("空 current_action 时 health=None",
          resp5.get("health") is None and resp5.get("current_action") is None)

    # =========== 8. 批量端点 ===========
    _banner("8. 批量 /tickets/current-actions")
    # 再起两个工单
    tid2 = generate_id("TKT")
    tid3 = generate_id("TKT")
    for t in (tid2, tid3):
        await db.insert("tickets", {
            "id": t, "requirement_id": rid, "project_id": pid,
            "title": "t", "description": "", "module": "other",
            "status": "pending", "priority": 2,
            "created_at": now_iso(), "updated_at": now_iso(),
        })
    await orc._set_ticket_current_action(tid2, "TestAgent.run_playtest")
    # tid3 不 set
    from api.tickets import get_tickets_current_actions
    # endpoint 路径改成 _tickets-current-actions（避免和 {ticket_id} 冲突）
    batch = await get_tickets_current_actions(pid, f"{tid},{tid2},{tid3}")
    check("批量返回含 tid2",
          tid2 in batch.get("items", {}),
          f"items keys={list(batch.get('items',{}).keys())}")
    check("批量不含 tid（已清空）",
          tid not in batch.get("items", {}))
    check("批量不含 tid3（从未 set）",
          tid3 not in batch.get("items", {}))

    # =========== 清理 ===========
    _banner("清理")
    for t in (tid, tid2, tid3):
        await db.execute("DELETE FROM tickets WHERE id = ?", (t,))
    await db.execute("DELETE FROM requirements WHERE id = ?", (rid,))
    await db.execute("DELETE FROM projects WHERE id = ?", (pid,))

    _banner("Summary")
    total = passed + failed
    print(f"  PASS {passed}/{total}  FAIL {failed}/{total}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
