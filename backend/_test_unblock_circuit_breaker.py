"""验证：人工解除 blocked 能成为两个止损计数的共同清零起点（治本修复）

复现的 bug（TK-20261110-48b6af）：工单累计 25 reject / 8 unblock，
点「解除 blocked」后状态回到 architecture_done 并立即派单，但 process_ticket
一进来就查两个止损计数：
  1. _reject_count_since_reset 有 MAX_UNBLOCK_RESETS=2 钉死 → 8>2 后计数起点
     被钉在第 2 次 unblock，之后全部 reject 计入 → 恒 >= 5 → hit_global
  2. _consecutive_same_failure 完全无视 unblock → 最近 20 条 reject 里
     15 条同因 development_failed → 恒 >= 3 → hit_repeated
任一命中即秒回 blocked，解除按钮形同无效。

修复：新增 _last_reset_at，三个计数函数统一以「最近一次 unblock」为界；
去掉 MAX_UNBLOCK_RESETS 钉死。防无限续命改由「解除后重新累计的闸门」承担。

验：
1. 多次 unblock（>2）后 _reject_count_since_reset 仍归零（不再钉死）
2. _consecutive_same_failure 在 unblock 后归零
3. unblock 后重新连续 3 次同因失败 → 又能触发熔断（防烧 token 仍在）
4. 端到端：模拟 25 reject + 8 unblock 的历史，解除后两计数都不再命中
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

_TMP_DB = str(Path(tempfile.gettempdir()) / "_ads_test_circuit_breaker.db")
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
        "id": pid, "name": "_t_cb", "description": "t",
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
        "status": "blocked", "assigned_agent": "",
        "created_at": now_iso(), "updated_at": now_iso(),
    })

    seq = [0]

    async def log(action, to_status=None, reason=None):
        # created_at 必须单调递增，否则「最近一次 unblock」取不准
        seq[0] += 1
        import json
        detail = json.dumps({"reason": reason} if reason else {}, ensure_ascii=False)
        await db.insert("ticket_logs", {
            "id": generate_id("LOG"), "ticket_id": tid, "requirement_id": rid,
            "project_id": pid, "agent_type": "T", "action": action,
            "from_status": None, "to_status": to_status, "detail": detail,
            "level": "info",
            "created_at": f"2026-11-17T10:{seq[0]:02d}:00.000000",
        })

    SAME_REASON = "LLM 输出无效。项目已有代码，增量修改不能用降级模板"

    try:
        rc = orchestrator._reject_count_since_reset
        cs = orchestrator._consecutive_same_failure

        # --- 1. 模拟历史：25 条 development_failed 同因 reject ---
        for _ in range(25):
            await log("reject", "development_failed", SAME_REASON)
        n = await rc(tid)
        same, _ = await cs(tid)
        assert n == 25, f"应为 25，实际 {n}"
        assert same >= 3, f"同因连续应 >=3，实际 {same}"
        print(f"[OK] 历史累计: reject={n}, 同因连续={same}（两个止损都会命中）")

        # --- 2. 连点 8 次 unblock（>旧 MAX_UNBLOCK_RESETS=2）每次都清零 ---
        for i in range(8):
            await log("unblock")
            n = await rc(tid)
            assert n == 0, f"第 {i+1} 次 unblock 后 reject 计数应清零，实际 {n}"
        print("[OK] 8 次 unblock: 每次 _reject_count_since_reset 都归零（不再钉死）")

        # --- 3. _consecutive_same_failure 也归零 ---
        same, fp = await cs(tid)
        assert same == 0, f"unblock 后同因连续应清零，实际 {same}"
        print("[OK] unblock 后 _consecutive_same_failure 归零（不再秒回 blocked）")

        # --- 4. 解除后重新连续 3 次同因失败 → 再次达到熔断线 ---
        for _ in range(3):
            await log("reject", "development_failed", SAME_REASON)
        n = await rc(tid)
        same, _ = await cs(tid)
        assert n == 3 and same == 3, f"解除后重新累计错误: reject={n}, same={same}"
        print(f"[OK] 解除后重跑再连续 3 次同因: reject={n}, same={same}（再次熔断，防烧 token 仍在）")

        # --- 5. 端到端判定：刚解除（无新失败）时两个闸门都不命中 ---
        await log("unblock")  # 用户第 9 次解除
        n = await rc(tid)
        same, _ = await cs(tid)
        MAX_RETRIES, CONSEC_LIMIT = 5, 3
        hit_global = n >= MAX_RETRIES
        hit_repeated = same >= CONSEC_LIMIT
        assert not hit_global and not hit_repeated, \
            f"解除后不应被秒回 blocked: global={hit_global} repeated={hit_repeated}"
        print(f"[OK] 端到端: 刚解除时 reject={n}(<{MAX_RETRIES}), same={same}(<{CONSEC_LIMIT})"
              f" → 两闸门都不命中，工单能真正重跑")

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
