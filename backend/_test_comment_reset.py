"""验证：测试阶段评论 → 变更分析命中 → 阶段回退 → 工单重跑

不打真 LLM（monkeypatch change_analyzer.analyze），只验：
1. is_active_phase 覆盖测试/审查/验收阶段真实状态
2. reset_phases 会真的改写 tickets.status 并发 ticket_ready
3. 工单在途时回退排队，收尾后应用
4. 尚未跑到该阶段时不前跳
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# 用独立临时库，别碰正在跑的后端那份（否则会卡在 sqlite 锁上）
_TMP_DB = str(Path(tempfile.gettempdir()) / "_ads_test_comment_reset.db")
for _suffix in ("", "-wal", "-shm"):
    try:
        os.remove(_TMP_DB + _suffix)
    except OSError:
        pass
os.environ["DB_PATH"] = _TMP_DB


def test_active_phase():
    from change_impact import is_active_phase

    should_analyze = [
        "testing_in_progress", "testing_failed",
        "review_in_progress", "review_passed",
        "acceptance_rejected", "acceptance_passed",
        "development_in_progress", "development_done",
        "architecture_done", "engine_compile_failed",
        "play_test_failed", "self_test_failed",
    ]
    should_skip = [
        "pending", "todo", "blocked", "cancelled",
        "testing_done", "deployed", "done", "completed", "",
    ]

    bad = [s for s in should_analyze if not is_active_phase(s)]
    bad += [s for s in should_skip if is_active_phase(s)]
    assert not bad, f"is_active_phase 判断错误: {bad}"
    print(f"[OK] is_active_phase: {len(should_analyze)} 个活跃 / {len(should_skip)} 个跳过，全部正确")


async def test_reset_rewinds_status():
    from database import db
    from orchestrator import orchestrator
    from utils import generate_id, now_iso

    await db.connect()
    await db.init_tables()

    pid = generate_id("PRJ")
    rid = generate_id("REQ")
    tid = generate_id("TK")

    await db.insert("projects", {
        "id": pid, "name": "_t_reset", "description": "test",
        "status": "active", "traits": "[]",
        "created_at": now_iso(), "updated_at": now_iso(),
    })
    await db.insert("requirements", {
        "id": rid, "project_id": pid, "title": "t", "description": "t",
        "status": "in_progress", "created_at": now_iso(), "updated_at": now_iso(),
    })

    async def mk(status):
        # 先清子表（ticket_logs / comments 有 FK 指向 tickets）
        for tbl in ("ticket_phase_status", "ticket_logs", "ticket_comments"):
            await db.execute(f"DELETE FROM {tbl} WHERE ticket_id=?", (tid,))
        await db.execute("DELETE FROM tickets WHERE id=?", (tid,))
        await db.insert("tickets", {
            "id": tid, "requirement_id": rid, "project_id": pid,
            "title": "t", "description": "t", "type": "feature",
            "module": "other", "priority": 3, "sort_order": 0,
            "status": status, "assigned_agent": "",
            "created_at": now_iso(), "updated_at": now_iso(),
        })

    async def cur():
        r = await db.fetch_one("SELECT status FROM tickets WHERE id=?", (tid,))
        return (r or {}).get("status")

    published = []
    orig_pub = orchestrator._publish_ticket_ready

    async def spy(project_id, ticket_id):
        published.append(ticket_id)

    orchestrator._publish_ticket_ready = spy

    try:
        # --- 场景 1：测试阶段（testing_in_progress）评论 → 回退到 development 入口 ---
        await mk("testing_in_progress")
        published.clear()
        ok = await orchestrator.reset_phases(tid, pid, "development", "评论要求改实现")
        s = await cur()
        assert ok, "reset_phases 应返回 True"
        assert s == "architecture_done", f"期望回退到 architecture_done，实际 {s}"
        assert published == [tid], f"应发 ticket_ready，实际 {published}"
        print(f"[OK] 场景1 测试阶段评论: testing_in_progress -> {s}，已发 ticket_ready")

        # --- 场景 2：工单在途 → 回退排队，不立即改状态 ---
        await mk("testing_in_progress")
        published.clear()
        orchestrator._processing.add(tid)
        try:
            await orchestrator.reset_phases(tid, pid, "development", "在途评论")
            s = await cur()
            assert s == "testing_in_progress", f"在途时不该改状态，实际 {s}"
            assert tid in orchestrator._pending_restart, "应登记 _pending_restart"
            assert published == [], "在途时不该发 ticket_ready"
            print(f"[OK] 场景2 在途: 状态保持 {s}，回退已排队")

            # 模拟收尾时应用
            await orchestrator._apply_status_rewind(
                tid, pid, s, orchestrator._pending_restart[tid]["status"], "收尾应用",
            )
            orchestrator._pending_restart.pop(tid, None)
            s2 = await cur()
            assert s2 == "architecture_done", f"收尾后应回退，实际 {s2}"
            print(f"[OK] 场景2 收尾: {s} -> {s2}")
        finally:
            orchestrator._processing.discard(tid)
            orchestrator._pending_restart.pop(tid, None)

        # --- 场景 3：还没跑到开发（pending 之后的 architecture_in_progress）→ 不前跳 ---
        await mk("architecture_in_progress")
        published.clear()
        await orchestrator.reset_phases(tid, pid, "deploy", "要求改部署")
        s = await cur()
        assert s == "architecture_in_progress", f"不该前跳，实际 {s}"
        print(f"[OK] 场景3 防前跳: 状态保持 {s}")

        # --- 场景 3b：_is_forward_jump 决策矩阵（防前跳不能误伤正常回退）---
        entry = {}
        for p in ("architecture", "development", "review", "testing", "deploy"):
            entry[p] = await orchestrator._resolve_phase_entry_status(pid, p, "feature")
        # (当前状态, 目标阶段, 是否应判为前跳)
        cases = [
            ("pending", "development", True),
            ("pending", "deploy", True),
            ("architecture_in_progress", "review", True),
            ("development_in_progress", "testing", True),
            ("review_passed", "deploy", True),
            # 以下都是真回退，不能拦
            ("testing_in_progress", "development", False),
            ("testing_failed", "development", False),
            ("acceptance_rejected", "development", False),
            ("development_done", "development", False),
            ("review_passed", "development", False),
            ("acceptance_passed", "development", False),
            ("deploying", "development", False),
            ("development_in_progress", "architecture", False),
        ]
        bad = []
        for cur_s, phase, want in cases:
            got = await orchestrator._is_forward_jump(
                pid, cur_s, entry[phase], "feature",
            )
            if got != want:
                bad.append(f"{cur_s}->{phase}({entry[phase]}) 期望前跳={want} 实际={got}")
        assert not bad, "防前跳判断错误:\n  " + "\n  ".join(bad)
        print(f"[OK] 场景3b 防前跳矩阵: {len(cases)} 组全部正确")

        # --- 场景 3c：在途收尾时状态已比目标更靠前 → 放弃排队的回退 ---
        # 排队目标 acceptance_passed（testing 入口），但 run 收尾把状态打回
        # development_done，此时应用回退会跳过 review/acceptance。
        assert await orchestrator._is_forward_jump(
            pid, "development_done", entry["testing"], "feature",
        ), "收尾后前跳应被识别"
        print("[OK] 场景3c 收尾后前跳: development_done -> acceptance_passed 已识别为前跳")

        # --- 场景 4：超过重置上限 → blocked ---
        await mk("testing_in_progress")
        for i in range(orchestrator.MAX_RESET_COUNT):
            await orchestrator.reset_phases(tid, pid, "development", f"第{i+1}次")
            await db.execute(
                "UPDATE tickets SET status='testing_in_progress' WHERE id=?", (tid,)
            )
        ok = await orchestrator.reset_phases(tid, pid, "development", "超限那次")
        s = await cur()
        assert ok is False, "超限应返回 False"
        assert s == "blocked", f"超限应 blocked，实际 {s}"
        print(f"[OK] 场景4 超限({orchestrator.MAX_RESET_COUNT}次): -> {s}")

    finally:
        orchestrator._publish_ticket_ready = orig_pub
        await db.execute("DELETE FROM ticket_phase_status WHERE ticket_id=?", (tid,))
        await db.execute("DELETE FROM ticket_logs WHERE ticket_id=?", (tid,))
        await db.execute("DELETE FROM ticket_comments WHERE ticket_id=?", (tid,))
        await db.execute("DELETE FROM tickets WHERE id=?", (tid,))
        await db.execute("DELETE FROM requirements WHERE id=?", (rid,))
        await db.execute("DELETE FROM projects WHERE id=?", (pid,))


async def main():
    from database import db

    test_active_phase()
    try:
        await test_reset_rewinds_status()
        print("\n=== 全部通过 ===")
    finally:
        # 不断开的话 aiosqlite 的连接线程会挂着，进程打印完不退出
        await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
