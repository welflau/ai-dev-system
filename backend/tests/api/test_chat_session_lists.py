"""经完整应用路由请求会话列表；只读合成 SQLite，不启动应用生命周期。"""
from pathlib import Path
import sqlite3

import httpx
import pytest
import pytest_asyncio

import main
from database import db

PROJECT = "/api/projects/alpha/chat/sessions"
GLOBAL = "/api/chat/sessions"
SEED = Path(__file__).with_name("fixtures") / "chat_session_lists.sql"
pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client(monkeypatch):
    conn = sqlite3.connect(":memory:")
    try:
        conn.row_factory = sqlite3.Row
        conn.executescript(SEED.read_text(encoding="utf8"))

        async def fetch_all(sql, params=()):
            return [dict(row) for row in conn.execute(sql, params)]

        monkeypatch.setattr(db, "fetch_all", fetch_all)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as c:
            yield c
    finally:
        conn.close()


async def test_project_list_matches_its_scope_and_counts(client):
    r = await client.get(PROJECT)
    assert r.status_code == 200
    assert r.json() == {"sessions": [
        {"id": "a-new", "title": "分镜讨论", "source": "chat", "created_at": "2026-01-01",
         "updated_at": "2026-01-04", "message_count": 2},
        {"id": "a-empty", "title": "空白草案", "source": "group", "created_at": "2026-01-01",
         "updated_at": "2026-01-02", "message_count": 0},
    ]}


async def test_global_list_keeps_global_message_scope(client):
    r = await client.get(GLOBAL)
    assert r.status_code == 200
    assert r.json() == {"sessions": [
        {"id": "g-one", "title": "全局备忘", "source": "chat", "created_at": "2026-01-01",
         "updated_at": "2026-01-05", "message_count": 1}]}


@pytest.mark.parametrize("url,ids", [
    (PROJECT + "?limit=1", ["a-new"]), (GLOBAL + "?limit=0", []),
    ("/api/projects/unknown/chat/sessions", []), ("/api/projects/beta/chat/sessions", ["b-one"]),
])
async def test_filter_and_limit(client, url, ids):
    r = await client.get(url)
    assert r.status_code == 200
    assert [s["id"] for s in r.json()["sessions"]] == ids


async def test_default_window_is_stable_for_same_updated_time(client):
    r = await client.get("/api/projects/bulk/chat/sessions")
    assert r.status_code == 200
    assert [s["id"] for s in r.json()["sessions"]] == [f"bulk-{i:02}" for i in range(1, 51)]


@pytest.mark.parametrize("url", [PROJECT, GLOBAL])
async def test_non_integer_limit_is_rejected(client, url):
    r = await client.get(url, params={"limit": "many"})
    assert r.status_code == 422 and r.json()["detail"][0]["loc"] == ["query", "limit"]
