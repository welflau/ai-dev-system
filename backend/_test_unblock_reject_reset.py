"""验证：解除 blocked 后 reject 计数清零，工单能真的重跑

修的问题：MAX_RETRIES 检查数的是 ticket_logs 里 action='reject' 的**全部历史**，
从不清零。撞上限 blocked → 人工解除 → 下一轮派单又数出同样次数 → 秒回 blocked，
「解除 blocked」按钮等于无效。

验：
1. _reject_count_since_reset 只数最近一次 unblock 之后的 reject
2. 按 to_status 过滤（阶段级 max_retries 用）
3. unblock 端点写的 unblock 日志能让计数归零
4. 5 次 reject 撞上限 → unblock → 计数回 0，不再判超限
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

_TMP_DB = str(Path(tempfile.gettempdir()) / "_ads_test_unblock.db")
for _suffix in ("", "-wal", "-shm"):
    try:
        os.remove(_TMP_DB + _suffix)
    except OSError:
        pass
os.environ["DB_PATH"] = _TMP_DB


async def main():
    from database import db
    from orchestrator import orchestrator
    from utils import generate_id, now_iso

    await db.connect()
    await db.init_tables()

    pid = generate_id("PRJ")
    rid = generate_id("REQ")
    tid = generate_id("TK")

    await db.insert("projects", {
        "id": pid, "name": "_t_unblock", "description": "t",
        "status": "active", "traits": "[]",
        "created_at": now_iso(), "updated_at": now_iso(),
    })
    await db.insert("requirements", {
        "id": rid, "project_id": pid, "title": "t", "description": "t",
        "status": "in_progress", "created_at": now_iso(), "updated_at": now_iso(),
    })
    await db.insert("tickets", {
        "id": tid, "requirement_id": rid, "project_id": pid,
        "title": "t", "description": "t", "type": "feature",
        "module": "other", "priority": 3, "sort_order": 0,
        "status": "acceptance_rejected", "assigned_agent": "",
        "created_at": now_iso(), "updated_at": now_iso(),
    })

    seq = [0]

    async def log(action, to_status=None):
        # created_at 必须单调递增，否则「最近一次 unblock」取不准
        seq[0] += 1
        await db.insert("ticket_logs", {
            "id": generate_id("LOG"), "ticket_id": tid, "requirement_id": rid,
            "project_id": pid, "agent_type": "T", "action": action,
            "from_status": None, "to_status": to_status, "detail": "{}",
            "level": "info",
            "created_at": f"2026-09-17T10:{seq[0]:02d}:00.000000",
        })

    try:
        cnt = orchestrator._reject_count_since_reset

        # --- 1. 无 unblock 时数全部历史 ---
        for _ in range(5):
            await log("reject", "acceptance_rejected")
        n = await cnt(tid)
        assert n == 5, f"应数出 5 次，实际 {n}"
        print(f"[OK] 无 unblock: 数出全部历史 {n} 次（撞上限 MAX_RETRIES=5）")

        # --- 2. unblock 后清零 ---
        await log("unblock")
        n = await cnt(tid)
        assert n == 0, f"unblock 后应清零，实际 {n}"
        print(f"[OK] unblock 后: 计数归零 -> {n}，工单重新获得 5 次机会")

        # --- 3. 清零后新的 reject 重新累计 ---
        await log("reject", "acceptance_rejected")
        await log("reject", "testing_failed")
        n = await cnt(tid)
        assert n == 2, f"应数出 2 次新 reject，实际 {n}"
        print(f"[OK] 清零后累计: {n} 次（只数 unblock 之后的）")

        # --- 4. 按 to_status 过滤（阶段级 max_retries）---
        n_acc = await cnt(tid, to_status="acceptance_rejected")
        n_test = await cnt(tid, to_status="testing_failed")
        n_none = await cnt(tid, to_status="engine_compile_failed")
        assert (n_acc, n_test, n_none) == (1, 1, 0), \
            f"按状态过滤错误: {n_acc}/{n_test}/{n_none}"
        print(f"[OK] 按 to_status 过滤: acceptance={n_acc} testing={n_test} compile={n_none}")

        # --- 5. 第二次 unblock 再次清零 ---
        await log("unblock")
        n = await cnt(tid)
        assert n == 0, f"二次 unblock 后应清零，实际 {n}"
        print(f"[OK] 二次 unblock: 再次归零 -> {n}")

        # --- 6. unblock 端点本身会写 unblock 日志 + 清零 ---
        from api.tickets import unblock_ticket
        await db.execute("UPDATE tickets SET status='blocked' WHERE id=?", (tid,))
        for _ in range(5):
            await log("reject", "acceptance_rejected")
        before = await cnt(tid)
        assert before == 5, f"端点调用前应有 5 次，实际 {before}"

        res = await unblock_ticket(pid, tid, target_status="architecture_done")
        after = await cnt(tid)
        row = await db.fetch_one("SELECT status FROM tickets WHERE id=?", (tid,))
        assert res["new_status"] == "architecture_done", res
        assert res["reject_count_cleared"] == 5, \
            f"应只报清零 5 次（本轮生效的），不是全部历史，实际 {res}"
        assert after == 0, f"端点调用后计数应为 0，实际 {after}"
        assert row["status"] == "architecture_done", row
        print(f"[OK] unblock 端点: 5 -> {after}，状态 blocked -> {row['status']}"
              f"，报告清零 {res['reject_count_cleared']} 次（只算本轮生效的）")

        # --- 7. 拒绝解除到 blocked 自身 ---
        from fastapi import HTTPException
        await db.execute("UPDATE tickets SET status='blocked' WHERE id=?", (tid,))
        try:
            await unblock_ticket(pid, tid, target_status="blocked")
            raise AssertionError("解除到 blocked 应被拒绝")
        except HTTPException as e:
            assert e.status_code == 400, e
            print(f"[OK] 拒绝解除到 blocked 自身: HTTP {e.status_code}")

        print("\n=== 全部通过 ===")

    finally:
        for tbl in ("ticket_phase_status", "ticket_logs", "ticket_comments"):
            await db.execute(f"DELETE FROM {tbl} WHERE ticket_id=?", (tid,))
        await db.execute("DELETE FROM tickets WHERE id=?", (tid,))
        await db.execute("DELETE FROM requirements WHERE id=?", (rid,))
        await db.execute("DELETE FROM projects WHERE id=?", (pid,))
        await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
