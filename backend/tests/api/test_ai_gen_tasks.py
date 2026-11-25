"""AI 生成任务统一记录层 + 统计 API 单测。

用 tmp DB（monkeypatch database.db 与 main.db 指向临时实例）避免碰真实 ads.db。

测试风格与项目其它测试一致：同步 test 函数 + 单个 asyncio.run 包住整个场景。
关键：Database._write_lock 是 asyncio.Lock，绑定到创建/首次使用它的 event loop，
因此 connect + init + 所有业务查询必须在**同一个 loop** 内完成，
不能 fixture 里起一个 loop init、测试里再起一个（会跨 loop 死锁）。
"""
import asyncio

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import ai_gen_tasks as agt
import database as database_mod
import main as main_mod
from database import Database


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    """把 database.db 与 main.db 都换成临时实例（不预先 connect）。"""
    db = Database(db_path=str(tmp_path / "test.db"))
    monkeypatch.setattr(database_mod, "db", db)
    monkeypatch.setattr(main_mod, "db", db)
    return db


def _scenario(db, body):
    """单 loop 内：connect → init → 跑业务协程 → 返回结果。"""
    async def main():
        await db.connect()
        try:
            await db.init_tables()
            return await body()
        finally:
            await db.disconnect()
    return asyncio.run(main())


# ── 记录层 ──────────────────────────────────────────────────────────────────

def test_record_and_update(tmp_db):
    async def body():
        tid = await agt.record_task(kind="image", provider="lightai", status="waiting",
                                    prompt="一只猫", source="image_requests",
                                    external_task_id="IMG-1")
        assert tid.startswith("AIGEN-")
        row = await tmp_db.fetch_one("SELECT * FROM ai_gen_tasks WHERE id = ?", (tid,))
        assert row["status"] == "waiting" and row["prompt"] == "一只猫"
        assert row["queued_at"] and not row["started_at"] and not row["finished_at"]

        await agt.update_task(tid, status="running")
        row = await tmp_db.fetch_one("SELECT * FROM ai_gen_tasks WHERE id = ?", (tid,))
        assert row["status"] == "running" and row["started_at"]

        await agt.update_task(tid, status="done", result_url="http://x/a.png")
        row = await tmp_db.fetch_one("SELECT * FROM ai_gen_tasks WHERE id = ?", (tid,))
        assert row["status"] == "done" and row["finished_at"] and row["result_url"] == "http://x/a.png"
    _scenario(tmp_db, body)


def test_update_by_external(tmp_db):
    async def body():
        tid = await agt.record_task(kind="image", provider="lightai", status="waiting",
                                    external_task_id="IMG-2")
        n = await agt.update_by_external("IMG-2", status="done", result_path="/tmp/a.png")
        assert n == 1
        row = await tmp_db.fetch_one("SELECT * FROM ai_gen_tasks WHERE id = ?", (tid,))
        assert row["status"] == "done" and row["result_path"] == "/tmp/a.png"
        assert await agt.update_by_external("NOPE", status="done") == 0
    _scenario(tmp_db, body)


def test_counts_and_total(tmp_db):
    async def body():
        for st, n in [("waiting", 2), ("running", 3), ("done", 4), ("failed", 1)]:
            for _ in range(n):
                await agt.record_task(kind="video", provider="minimax_h3", status=st)
        c = await agt.counts()
        assert c == {"waiting": 2, "running": 3, "done": 4, "failed": 1}
        assert await agt.total() == 10
    _scenario(tmp_db, body)


def test_recent_limit_and_order(tmp_db):
    async def body():
        for i in range(6):
            await agt.record_task(kind="image", provider="lightai", status="done",
                                  prompt=f"p{i}")
        rows = await agt.recent(3)
        assert len(rows) == 3
        assert all(r["kind"] == "image" for r in rows)
    _scenario(tmp_db, body)


def test_invalid_status_rejected(tmp_db):
    async def body():
        tid = await agt.record_task(kind="image", provider="lightai", status="bogus")
        row = await tmp_db.fetch_one("SELECT status FROM ai_gen_tasks WHERE id = ?", (tid,))
        assert row["status"] == "waiting"
        assert await agt.update_task(tid, status="bogus") is False
    _scenario(tmp_db, body)


def test_record_failure_is_silent(tmp_db, monkeypatch):
    """记录失败返回空串、不抛异常（埋点绝不影响生成）。"""
    async def _boom(*a, **kw):
        raise RuntimeError("db down")

    async def body():
        monkeypatch.setattr(tmp_db, "insert", _boom)
        monkeypatch.setattr(tmp_db, "update", _boom)
        monkeypatch.setattr(tmp_db, "fetch_all", _boom)
        tid = await agt.record_task(kind="image", provider="lightai")
        assert tid == ""
        assert await agt.update_task("whatever", status="done") is False
        assert await agt.counts() == {"waiting": 0, "running": 0, "done": 0, "failed": 0}
    _scenario(tmp_db, body)


# ── API 端点 ────────────────────────────────────────────────────────────────

def test_api_list_and_summary(tmp_db):
    from api.ai_gen_tasks import router
    app = FastAPI()
    app.include_router(router)

    async def body():
        for st in ("waiting", "running", "done"):
            await agt.record_task(kind="video", provider="minimax_h3", status=st,
                                  prompt="cat video")
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            d = (await client.get("/api/ai-gen-tasks")).json()
            assert d["total"] == 3 and d["active"] == 2
            assert d["counts"] == {"waiting": 1, "running": 1, "done": 1, "failed": 0}
            assert len(d["tasks"]) == 3
            assert d["tasks"][0]["prompt"] == "cat video"
            s = (await client.get("/api/ai-gen-tasks/summary")).json()
            assert s["total"] == 3 and s["done"] == 1
            assert "tasks" not in s
            d2 = (await client.get("/api/ai-gen-tasks?limit=1")).json()
            assert len(d2["tasks"]) == 1 and d2["total"] == 3
    _scenario(tmp_db, body)


def test_metrics_includes_ai_gen_tasks(tmp_db):
    """GET /api/metrics 返回 ai_gen_tasks 总数。"""
    async def body():
        for _ in range(2):
            await agt.record_task(kind="image", provider="lightai", status="done")
        async with AsyncClient(transport=ASGITransport(main_mod.app), base_url="http://test") as client:
            response = await client.get("/api/metrics")
            response.raise_for_status()
            d = response.json()
            assert set(d) == {"processing", "asyncio_tasks", "mem_mb", "wal_kb", "llm_pending",
                              "db_ms", "cost_today_usd", "ai_gen_tasks"}
            assert d["ai_gen_tasks"] == 2
            detail = await client.get("/api/metrics/asyncio-tasks")
            detail.raise_for_status()
            listing = detail.json()
            assert listing["count"] == len(listing["tasks"]) > 0
    _scenario(tmp_db, body)
