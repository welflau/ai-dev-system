"""
Harness Phase 4 自动化测试：子任务派发

覆盖：
  T4-1  DispatchSubtaskAction 创建子 Ticket + 父 Ticket 置为 waiting_subtasks
  T4-2  循环检测：嵌套深度超限时返回错误
  T4-3  循环检测：正常深度（< MAX_SUBTASK_DEPTH）允许派发
  T4-4  _check_subtasks_complete：子任务未完成时不恢复父 Ticket
  T4-5  _check_subtasks_complete：子任务全完成后恢复父 Ticket 为 PENDING
  T4-6  _get_ancestor_ids 正确追踪祖先链

运行：cd backend && python -m pytest _test_harness_p4.py -v
"""
import asyncio
import sys
import json
import pytest
import pytest_asyncio

sys.path.insert(0, ".")


# ─────────────────────────────────────────────────────────────────────────────
# Fixture：内存数据库 + 最小必要数据（project + requirement + parent ticket）
# ─────────────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def mem_db():
    import aiosqlite
    from database import SCHEMA_SQL

    db_conn = await aiosqlite.connect(":memory:")
    db_conn.row_factory = aiosqlite.Row
    await db_conn.execute("PRAGMA foreign_keys=ON")
    await db_conn.executescript(SCHEMA_SQL)
    await db_conn.commit()
    yield db_conn
    await db_conn.close()


@pytest_asyncio.fixture
async def patched_db(mem_db, monkeypatch):
    import asyncio as _asyncio

    class _FakeDB:
        _write_lock = _asyncio.Lock()

        async def execute(self, sql, params=()):
            async with self._write_lock:
                cur = await mem_db.execute(sql, params)
                await mem_db.commit()
                return cur

        async def fetch_one(self, sql, params=()):
            cur = await mem_db.execute(sql, params)
            row = await cur.fetchone()
            return dict(row) if row else None

        async def fetch_all(self, sql, params=()):
            cur = await mem_db.execute(sql, params)
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

        async def insert(self, table, data: dict):
            cols = ", ".join(data.keys())
            placeholders = ", ".join(["?"] * len(data))
            sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
            async with self._write_lock:
                await mem_db.execute(sql, tuple(data.values()))
                await mem_db.commit()

        async def update(self, table, data: dict, where: str, params=()):
            sets = ", ".join(f"{k}=?" for k in data.keys())
            sql = f"UPDATE {table} SET {sets} WHERE {where}"
            async with self._write_lock:
                await mem_db.execute(sql, tuple(data.values()) + params)
                await mem_db.commit()

    fake = _FakeDB()
    import database
    monkeypatch.setattr(database, "db", fake)
    # 同步 patch 各模块级 db 引用（from database import db 只绑定一次）
    import actions.chat.dispatch_subtask as _dst
    monkeypatch.setattr(_dst, "db", fake)
    import orchestrator as _orch
    monkeypatch.setattr(_orch, "db", fake)
    return fake


@pytest_asyncio.fixture
async def seed_data(patched_db):
    """插入最小必要数据：project + requirement + parent ticket"""
    from utils import now_iso

    now = now_iso()

    await patched_db.execute(
        "INSERT INTO projects (id,name,description,status,tech_stack,config,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        ("proj-001", "TestProj", "", "active", "", "{}", now, now),
    )
    await patched_db.execute(
        "INSERT INTO requirements (id,project_id,title,description,priority,status,"
        "submitter,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        ("req-001", "proj-001", "Test Req", "", "medium", "in_progress", "tester", now, now),
    )
    await patched_db.execute(
        "INSERT INTO tickets (id,requirement_id,project_id,title,description,type,"
        "module,priority,sort_order,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("tk-parent", "req-001", "proj-001", "父任务", "描述", "feature",
         "core", 2, 0, "development_in_progress", now, now),
    )
    return {"project_id": "proj-001", "requirement_id": "req-001", "parent_ticket_id": "tk-parent"}


# ─────────────────────────────────────────────────────────────────────────────
# T4-1  DispatchSubtaskAction 创建子 Ticket + 父 Ticket 置为 waiting_subtasks
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dispatch_subtask_creates_child_and_waits(patched_db, seed_data):
    from actions.chat.dispatch_subtask import DispatchSubtaskAction, WAITING_SUBTASKS_STATUS

    action = DispatchSubtaskAction()
    ctx = {
        **seed_data,
        "title": "专项测试",
        "description": "覆盖登录/注销/超时场景",
        "start_status": "development_done",
        "priority": 2,
        "ticket_id": seed_data["parent_ticket_id"],
    }
    result = await action.run(ctx)

    assert result.success, f"派发失败: {result.error}"
    assert "sub_ticket_id" in result.data
    sub_id = result.data["sub_ticket_id"]

    # 子 Ticket 存在
    sub = await patched_db.fetch_one("SELECT * FROM tickets WHERE id=?", (sub_id,))
    assert sub is not None
    assert sub["parent_ticket_id"] == "tk-parent"
    assert sub["status"] == "development_done"
    assert sub["title"] == "[子任务] 专项测试"

    # 父 Ticket 置为 waiting_subtasks
    parent = await patched_db.fetch_one("SELECT status FROM tickets WHERE id=?", ("tk-parent",))
    assert parent["status"] == WAITING_SUBTASKS_STATUS


# ─────────────────────────────────────────────────────────────────────────────
# T4-2  循环检测：模拟深度已满
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dispatch_subtask_depth_limit(patched_db, seed_data, monkeypatch):
    from actions.chat.dispatch_subtask import DispatchSubtaskAction

    # 强制让 _get_subtask_depth 返回 MAX_SUBTASK_DEPTH
    import actions.chat.dispatch_subtask as dst
    async def _fake_get_ancestors(ticket_id):
        return ["a", "b", "c"]  # 深度 3 = MAX_SUBTASK_DEPTH

    monkeypatch.setattr(dst, "_get_ancestor_ids", _fake_get_ancestors)

    action = DispatchSubtaskAction()
    ctx = {
        **seed_data,
        "ticket_id": seed_data["parent_ticket_id"],
        "title": "无法派发的子任务",
        "description": "太深了",
    }
    result = await action.run(ctx)

    assert not result.success
    assert "深度" in result.error or "上限" in result.error


# ─────────────────────────────────────────────────────────────────────────────
# T4-3  正常深度（深度 1）可以派发
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dispatch_subtask_depth_ok(patched_db, seed_data, monkeypatch):
    from actions.chat.dispatch_subtask import DispatchSubtaskAction

    import actions.chat.dispatch_subtask as dst
    async def _fake_ancestors(ticket_id):
        return ["a"]  # 深度 1，< MAX_SUBTASK_DEPTH

    monkeypatch.setattr(dst, "_get_ancestor_ids", _fake_ancestors)

    action = DispatchSubtaskAction()
    ctx = {
        **seed_data,
        "ticket_id": seed_data["parent_ticket_id"],
        "title": "可以派发",
        "description": "深度 1",
    }
    result = await action.run(ctx)
    assert result.success


# ─────────────────────────────────────────────────────────────────────────────
# T4-4  _check_subtasks_complete：子任务未完成，不恢复父 Ticket
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_subtasks_not_complete(patched_db, seed_data):
    from utils import now_iso
    from actions.chat.dispatch_subtask import WAITING_SUBTASKS_STATUS

    # 创建一个未完成的子 Ticket
    await patched_db.execute(
        "INSERT INTO tickets (id,requirement_id,project_id,title,description,type,"
        "parent_ticket_id,module,priority,sort_order,status,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("tk-child", "req-001", "proj-001", "子任务", "", "subtask",
         "tk-parent", "core", 2, 0, "development_in_progress",
         now_iso(), now_iso()),
    )
    # 父 Ticket 置为 waiting
    await patched_db.execute(
        "UPDATE tickets SET status=? WHERE id=?",
        (WAITING_SUBTASKS_STATUS, "tk-parent"),
    )

    # 模拟 orchestrator._check_subtasks_complete
    from models import TicketStatus
    from orchestrator import TicketOrchestrator
    orch = TicketOrchestrator.__new__(TicketOrchestrator)
    orch._processing = set()
    orch._project_active = {}

    parent_row = await patched_db.fetch_one("SELECT * FROM tickets WHERE id=?", ("tk-parent",))
    await orch._check_subtasks_complete("tk-parent", "proj-001", parent_row)

    # 父 Ticket 应仍为 waiting_subtasks
    parent = await patched_db.fetch_one("SELECT status FROM tickets WHERE id=?", ("tk-parent",))
    assert parent["status"] == WAITING_SUBTASKS_STATUS


# ─────────────────────────────────────────────────────────────────────────────
# T4-5  _check_subtasks_complete：子任务全完成，恢复父 Ticket
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_subtasks_all_complete(patched_db, seed_data):
    from utils import now_iso
    from actions.chat.dispatch_subtask import WAITING_SUBTASKS_STATUS
    from models import TicketStatus

    # 子 Ticket 已完成
    await patched_db.execute(
        "INSERT INTO tickets (id,requirement_id,project_id,title,description,type,"
        "parent_ticket_id,module,priority,sort_order,status,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("tk-child-done", "req-001", "proj-001", "子任务完成", "", "subtask",
         "tk-parent", "core", 2, 0, TicketStatus.TESTING_DONE.value,
         now_iso(), now_iso()),
    )
    await patched_db.execute(
        "UPDATE tickets SET status=? WHERE id=?",
        (WAITING_SUBTASKS_STATUS, "tk-parent"),
    )

    from orchestrator import TicketOrchestrator
    orch = TicketOrchestrator.__new__(TicketOrchestrator)
    orch._processing = set()
    orch._project_active = {}

    parent_row = await patched_db.fetch_one("SELECT * FROM tickets WHERE id=?", ("tk-parent",))
    await orch._check_subtasks_complete("tk-parent", "proj-001", parent_row)

    # 父 Ticket 应恢复为 PENDING
    parent = await patched_db.fetch_one("SELECT status FROM tickets WHERE id=?", ("tk-parent",))
    assert parent["status"] == TicketStatus.PENDING.value

    # ticket_logs 应有 subtasks_complete 记录
    log = await patched_db.fetch_one(
        "SELECT * FROM ticket_logs WHERE action='subtasks_complete' AND ticket_id=?",
        ("tk-parent",),
    )
    assert log is not None


# ─────────────────────────────────────────────────────────────────────────────
# T4-6  _get_ancestor_ids 追踪祖先链
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_ancestor_ids(patched_db, seed_data):
    from utils import now_iso
    from actions.chat.dispatch_subtask import _get_ancestor_ids

    # 建链：tk-parent → tk-child1 → tk-grandchild
    await patched_db.execute(
        "INSERT INTO tickets (id,requirement_id,project_id,title,description,type,"
        "parent_ticket_id,module,priority,sort_order,status,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("tk-child1", "req-001", "proj-001", "子", "", "subtask",
         "tk-parent", "core", 2, 0, "pending", now_iso(), now_iso()),
    )
    await patched_db.execute(
        "INSERT INTO tickets (id,requirement_id,project_id,title,description,type,"
        "parent_ticket_id,module,priority,sort_order,status,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("tk-grandchild", "req-001", "proj-001", "孙", "", "subtask",
         "tk-child1", "core", 2, 0, "pending", now_iso(), now_iso()),
    )

    ancestors = await _get_ancestor_ids("tk-grandchild")
    assert "tk-child1" in ancestors
    assert "tk-parent" in ancestors
    assert len(ancestors) == 2


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
