"""
Harness Phase 3 自动化测试：异步权限审批

覆盖：
  T3-1  detect_risk 正确识别高风险操作
  T3-2  detect_risk 对低风险操作返回 None
  T3-3  gate.check 低风险直接放行（无挂起）
  T3-4  gate.check 高风险写库 + future 挂起 → resolve(True) 批准后恢复
  T3-5  gate.check 高风险 → resolve(False) 拒绝后抛 PermissionDeniedError
  T3-6  gate.check 超时自动拒绝（PermissionDeniedError）
  T3-7  已处理的请求再次 resolve 返回 False（幂等）
  T3-8  API 端点 /pending 和 /resolve 正确响应

运行：cd backend && python -m pytest _test_harness_p3.py -v
"""
import asyncio
import sys
import pytest
import pytest_asyncio

sys.path.insert(0, ".")


# ─────────────────────────────────────────────────────────────────────────────
# Fixture：每个测试用独立的 PermissionGate（不共享 _pending 状态）
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def fresh_gate():
    from permissions.gate import PermissionGate
    return PermissionGate()


@pytest_asyncio.fixture
async def mem_db():
    import aiosqlite
    from database import SCHEMA_SQL
    db_conn = await aiosqlite.connect(":memory:")
    db_conn.row_factory = aiosqlite.Row
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

    fake = _FakeDB()
    import database
    monkeypatch.setattr(database, "db", fake)
    # api/permissions.py 也有模块级 from database import db
    import api.permissions as _ap
    monkeypatch.setattr(_ap, "db", fake)
    return fake


# ─────────────────────────────────────────────────────────────────────────────
# T3-1/T3-2  detect_risk 规则验证
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tool,inp,expect_label_fragment", [
    ("shell",     {"command": "rm -rf /tmp"},            "删除文件"),
    ("shell",     {"command": "git push origin --force"},"强制推送"),
    ("shell",     {"command": "DROP TABLE users"},        "数据库"),
    ("shell",     {"command": "shutdown -h now"},         "关机"),
    ("shell",     {"command": "format C:"},               "格式化"),
    ("git_merge", {"target_branch": "main"},              "主干"),
    ("git_merge", {"target_branch": "master"},            "主干"),
])
def test_detect_risk_high_risk(tool, inp, expect_label_fragment):
    from permissions.gate import detect_risk
    label = detect_risk(tool, inp)
    assert label is not None, f"应检测为高风险: {tool} {inp}"
    assert expect_label_fragment in label, f"期望 label 包含 '{expect_label_fragment}', 实际: {label}"


@pytest.mark.parametrize("tool,inp", [
    ("shell",     {"command": "ls -la"}),
    ("shell",     {"command": "git log --oneline -10"}),
    ("shell",     {"command": "python -m pytest tests/"}),
    ("git_merge", {"target_branch": "feature/new-login"}),
    ("git_merge", {"target_branch": "develop"}),
    ("GlobAction",{}),
    ("GrepAction",{"pattern": "hello"}),
])
def test_detect_risk_low_risk(tool, inp):
    from permissions.gate import detect_risk
    assert detect_risk(tool, inp) is None, f"应为低风险: {tool} {inp}"


# ─────────────────────────────────────────────────────────────────────────────
# T3-3  低风险工具 gate.check 直接返回
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gate_check_low_risk_passes(fresh_gate, monkeypatch, patched_db):
    # 低风险应立即返回，不挂起
    await asyncio.wait_for(
        fresh_gate.check("GlobAction", {"pattern": "*.py"}, {}),
        timeout=1.0,
    )
    # 没有抛异常，没有超时 → 通过


# ─────────────────────────────────────────────────────────────────────────────
# T3-4  高风险 → 审批通过后 gate.check 正常返回
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gate_check_approve(fresh_gate, monkeypatch, patched_db):
    # 短超时（测试用）
    monkeypatch.setattr("permissions.gate.APPROVAL_TIMEOUT_SECONDS", 5)

    # 后台任务：1s 后批准
    async def _approve_later():
        await asyncio.sleep(0.3)
        # 找到 pending future 的 key
        req_id = next(iter(fresh_gate._pending))
        fresh_gate.resolve(req_id, True)
        await fresh_gate.mark_resolved(req_id, True)

    task = asyncio.create_task(_approve_later())
    # gate.check 应在约 0.3s 后返回（不抛）
    await asyncio.wait_for(
        fresh_gate.check("shell", {"command": "rm -rf /tmp/x"}, {"project_id": "__global__"}),
        timeout=3.0,
    )
    await task


# ─────────────────────────────────────────────────────────────────────────────
# T3-5  高风险 → 拒绝后抛 PermissionDeniedError
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gate_check_deny(fresh_gate, monkeypatch, patched_db):
    monkeypatch.setattr("permissions.gate.APPROVAL_TIMEOUT_SECONDS", 5)

    async def _deny_later():
        await asyncio.sleep(0.2)
        req_id = next(iter(fresh_gate._pending))
        fresh_gate.resolve(req_id, False)

    task = asyncio.create_task(_deny_later())
    from permissions.gate import PermissionDeniedError
    with pytest.raises(PermissionDeniedError, match="被拒绝"):
        await asyncio.wait_for(
            fresh_gate.check("shell", {"command": "rm -rf /tmp/x"}, {"project_id": "__global__"}),
            timeout=3.0,
        )
    await task


# ─────────────────────────────────────────────────────────────────────────────
# T3-6  超时自动拒绝
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gate_check_timeout(fresh_gate, monkeypatch, patched_db):
    monkeypatch.setattr("permissions.gate.APPROVAL_TIMEOUT_SECONDS", 0.2)

    from permissions.gate import PermissionDeniedError
    with pytest.raises(PermissionDeniedError):
        await fresh_gate.check(
            "shell", {"command": "rm -rf /tmp/x"}, {"project_id": "__global__"}
        )
    # timeout → _pending 已清空
    assert len(fresh_gate._pending) == 0


# ─────────────────────────────────────────────────────────────────────────────
# T3-7  幂等：已超时后 resolve 返回 False
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gate_resolve_after_timeout_is_noop(fresh_gate, monkeypatch, patched_db):
    monkeypatch.setattr("permissions.gate.APPROVAL_TIMEOUT_SECONDS", 0.1)

    req_id = None

    async def _capture_id():
        nonlocal req_id
        await asyncio.sleep(0.05)
        req_id = next(iter(fresh_gate._pending), None)

    task = asyncio.create_task(_capture_id())
    try:
        await fresh_gate.check(
            "shell", {"command": "rm -rf /x"}, {"project_id": "__global__"}
        )
    except Exception:
        pass

    await task
    if req_id:
        found = fresh_gate.resolve(req_id, True)
        assert not found, "超时后 future 已清理，resolve 应返回 False"


# ─────────────────────────────────────────────────────────────────────────────
# T3-8  API 端点测试（用 httpx.AsyncClient + FastAPI TestClient）
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_permissions_api_pending_empty(patched_db):
    from fastapi import FastAPI
    from api.permissions import router
    from httpx import AsyncClient, ASGITransport

    app = FastAPI()
    app.include_router(router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/permissions/pending")
        assert resp.status_code == 200
        assert resp.json()["items"] == []


@pytest.mark.asyncio
async def test_permissions_api_resolve_not_found(patched_db):
    from fastapi import FastAPI
    from api.permissions import router
    from httpx import AsyncClient, ASGITransport

    app = FastAPI()
    app.include_router(router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/permissions/nonexistent-id/resolve",
            json={"approved": True},
        )
        assert resp.status_code == 404


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
