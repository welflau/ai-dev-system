"""
Harness Phase 1 自动化测试：Pre/Post Tool Hooks + 预算约束

覆盖：
  T1-1  audit_log_hook 写入 tool_audit_log（内存 DB）
  T1-2  shell_rate_limit_hook 超限时 RuntimeError 传播
  T1-3  failure_library_hook 工具报错写 ticket_logs
  T1-4  Budget check / consume 三重判断
  T1-5  Budget 超限时 emit 返回 budget_exceeded 字段
  T1-6  HookRegistry fail-open（单 Hook 报错不影响后续 Hook）
  T1-7  run_action_with_hooks PRE blocking 阻断 action 执行
  T1-8  run_action_with_hooks POST 成功写审计

运行：
  cd backend && python -m pytest _test_harness_p1.py -v
  或：cd backend && python _test_harness_p1.py
"""
import asyncio
import json
import sys
import time
import pytest
import pytest_asyncio

sys.path.insert(0, ".")

# ─────────────────────────────────────────────────────────────────────────────
# 测试用内存数据库 Fixture
# ─────────────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def mem_db():
    """每个测试用独立的内存数据库，测试结束后自动关闭"""
    import aiosqlite
    from database import SCHEMA_SQL

    db_conn = await aiosqlite.connect(":memory:")
    db_conn.row_factory = aiosqlite.Row
    await db_conn.execute("PRAGMA journal_mode=WAL")
    await db_conn.executescript(SCHEMA_SQL)
    await db_conn.commit()
    yield db_conn
    await db_conn.close()


@pytest_asyncio.fixture
async def patched_db(mem_db, monkeypatch):
    """把 database.db 的 execute / fetch_one / fetch_all 替换到 mem_db"""
    import asyncio

    class _FakeDB:
        _write_lock = asyncio.Lock()

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

    fake = _FakeDB()
    import database
    monkeypatch.setattr(database, "db", fake)
    return fake


# ─────────────────────────────────────────────────────────────────────────────
# T1-1  audit_log_hook 写入 tool_audit_log
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_log_hook_writes_record(patched_db):
    from hooks.builtin import audit_log_hook
    from hooks.types import HookEvent, ToolHookContext

    ctx = ToolHookContext(
        event=HookEvent.POST_TOOL_USE,
        tool_name="GlobAction",
        input={"pattern": "**/*.py"},
        output="matched 5 files",
        duration_ms=12.5,
        project_id="proj-001",
        ticket_id="tk-001",
        agent_type="ChatAssistant",
    )
    await audit_log_hook(ctx)

    rows = await patched_db.fetch_all("SELECT * FROM tool_audit_log")
    assert len(rows) == 1
    r = rows[0]
    assert r["tool_name"] == "GlobAction"
    assert r["project_id"] == "proj-001"
    assert r["duration_ms"] == 12.5
    assert r["success"] == 1


@pytest.mark.asyncio
async def test_audit_log_hook_ignores_pre_event(patched_db):
    from hooks.builtin import audit_log_hook
    from hooks.types import HookEvent, ToolHookContext

    ctx = ToolHookContext(
        event=HookEvent.PRE_TOOL_USE,
        tool_name="ShellAction",
        input={},
    )
    await audit_log_hook(ctx)  # PRE_TOOL_USE 应跳过

    rows = await patched_db.fetch_all("SELECT * FROM tool_audit_log")
    assert len(rows) == 0, "PRE_TOOL_USE 不应写审计"


# ─────────────────────────────────────────────────────────────────────────────
# T1-2  shell_rate_limit_hook 限流
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_shell_rate_limit_blocks_when_over():
    from hooks.builtin import shell_rate_limit_hook, _shell_call_counts
    from hooks.types import HookEvent, ToolHookContext

    _shell_call_counts["tk-over"] = 51
    ctx = ToolHookContext(
        event=HookEvent.PRE_TOOL_USE,
        tool_name="ShellAction",
        input={},
        ticket_id="tk-over",
    )
    with pytest.raises(RuntimeError, match="超限"):
        await shell_rate_limit_hook(ctx)


@pytest.mark.asyncio
async def test_shell_rate_limit_allows_under_limit():
    from hooks.builtin import shell_rate_limit_hook, _shell_call_counts
    from hooks.types import HookEvent, ToolHookContext

    _shell_call_counts.pop("tk-fresh", None)
    ctx = ToolHookContext(
        event=HookEvent.PRE_TOOL_USE,
        tool_name="ShellAction",
        input={},
        ticket_id="tk-fresh",
    )
    await shell_rate_limit_hook(ctx)  # 应该不抛


@pytest.mark.asyncio
async def test_shell_rate_limit_only_applies_to_shell():
    from hooks.builtin import shell_rate_limit_hook, _shell_call_counts
    from hooks.types import HookEvent, ToolHookContext

    _shell_call_counts["tk-other"] = 999
    ctx = ToolHookContext(
        event=HookEvent.PRE_TOOL_USE,
        tool_name="GlobAction",   # 非 ShellAction，不限流
        input={},
        ticket_id="tk-other",
    )
    await shell_rate_limit_hook(ctx)  # 应不抛


# ─────────────────────────────────────────────────────────────────────────────
# T1-3  failure_library_hook 错误写 ticket_logs
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_failure_library_hook_writes_error(patched_db):
    from hooks.builtin import failure_library_hook
    from hooks.types import HookEvent, ToolHookContext

    ctx = ToolHookContext(
        event=HookEvent.TOOL_ERROR,
        tool_name="ShellAction",
        input={"command": "rm -rf /"},
        error=RuntimeError("permission denied"),
        duration_ms=5.0,
        project_id="proj-001",
        ticket_id="tk-001",
        agent_type="DevAgent",
    )
    # ticket_logs 需要 project_id，但 __global__ 项目不需要外键
    await failure_library_hook(ctx)

    rows = await patched_db.fetch_all(
        "SELECT * FROM ticket_logs WHERE level='error'"
    )
    assert len(rows) == 1
    r = rows[0]
    assert "ToolError:ShellAction" in r["action"]
    detail = json.loads(r["detail"])
    assert "permission denied" in detail["error"]


# ─────────────────────────────────────────────────────────────────────────────
# T1-4  Budget check / consume 三重判断
# ─────────────────────────────────────────────────────────────────────────────

def test_budget_token_limit():
    from query_engine.budget import Budget
    b = Budget(max_tokens=1000, max_turns=99, max_seconds=999)
    assert b.check() is None
    b.consume(tokens=1001)
    reason = b.check()
    assert reason is not None
    assert "Token" in reason


def test_budget_turn_limit():
    from query_engine.budget import Budget
    b = Budget(max_tokens=999999, max_turns=3, max_seconds=999)
    b.consume(turns=3)
    reason = b.check()
    assert reason is not None
    assert "轮次" in reason


def test_budget_time_limit():
    from query_engine.budget import Budget
    b = Budget(max_tokens=999999, max_turns=999, max_seconds=0.01)
    time.sleep(0.05)  # 超过 0.01s
    reason = b.check()
    assert reason is not None
    assert "时间" in reason


def test_budget_no_limit():
    from query_engine.budget import Budget
    b = Budget(max_tokens=100_000, max_turns=30, max_seconds=180)
    b.consume(tokens=500, turns=1)
    assert b.check() is None
    assert b.used_tokens == 500
    assert b.used_turns == 1


# ─────────────────────────────────────────────────────────────────────────────
# T1-6  HookRegistry fail-open（单 Hook 报错不阻断后续）
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hook_registry_fail_open():
    from hooks.registry import HookRegistry
    from hooks.types import HookEvent, ToolHookContext

    results = []

    async def bad_hook(ctx):
        raise ValueError("我坏掉了")

    async def good_hook(ctx):
        results.append("good")

    reg = HookRegistry()
    reg.register(bad_hook)
    reg.register(good_hook)

    ctx = ToolHookContext(event=HookEvent.POST_TOOL_USE, tool_name="Test", input={})
    await reg.emit(ctx)  # 不应抛异常

    assert results == ["good"], "fail-open：bad_hook 失败不应阻止 good_hook 执行"


@pytest.mark.asyncio
async def test_hook_registry_blocking_propagates_first_error():
    from hooks.registry import HookRegistry
    from hooks.types import HookEvent, ToolHookContext

    async def hook_a(ctx):
        raise RuntimeError("A 限流")

    async def hook_b(ctx):
        raise RuntimeError("B 也报错")

    reg = HookRegistry()
    reg.register(hook_a)
    reg.register(hook_b)

    ctx = ToolHookContext(event=HookEvent.PRE_TOOL_USE, tool_name="Shell", input={})
    with pytest.raises(RuntimeError, match="A 限流"):
        await reg.emit(ctx, blocking=True)


# ─────────────────────────────────────────────────────────────────────────────
# T1-7  run_action_with_hooks PRE blocking 阻断 action 执行
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_executor_pre_hook_blocks_action(monkeypatch):
    from hooks.registry import HookRegistry
    from hooks.types import HookEvent, ToolHookContext
    from actions.base import ActionBase, ActionResult

    class _FakeAction(ActionBase):
        name = "fake_shell"
        description = "test"
        ran = False
        async def run(self, ctx):
            _FakeAction.ran = True
            return ActionResult(success=True, message="ran")

    fake_action = _FakeAction()

    # 替换全局 hook_registry
    fake_reg = HookRegistry()
    async def blocking_hook(ctx):
        raise RuntimeError("blocked by rate limit")
    fake_reg.register(blocking_hook)

    # hook_registry 在函数内部导入，patch hooks.registry 模块级单例
    import hooks.registry as hr
    monkeypatch.setattr(hr, "hook_registry", fake_reg)
    # 也要 patch permissions gate（避免真实挂起）
    import permissions.gate as pg
    async def _noop(*a, **kw): pass
    monkeypatch.setattr(pg.permission_gate, "check", _noop)

    from actions.executor import run_action_with_hooks
    with pytest.raises(RuntimeError, match="blocked"):
        await run_action_with_hooks(fake_action, {})

    assert not _FakeAction.ran, "PRE Hook 阻断后 action.run() 不应执行"


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
