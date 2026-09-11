"""报错后自动检索知识库（Agent 处理流程）。

运行：cd backend && python -m pytest _test_error_playbook.py -v
"""
import sys

import pytest
import pytest_asyncio

sys.path.insert(0, ".")


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
    import actions.chat.search_knowledge as sk
    monkeypatch.setattr(sk, "db", fake)
    return fake


def test_build_error_search_query_extracts_git_terms():
    from actions.chat.search_knowledge import build_error_search_query
    q = build_error_search_query(
        "代码已提交但未推送到远端。blocked_main",
        tool_name="git:push_failed",
        extra="blocked_main",
    )
    low = q.lower()
    assert "git" in low
    assert "push" in low


@pytest.mark.asyncio
async def test_lookup_error_playbook_hits_git_faq(patched_db):
    from actions.chat.search_knowledge import lookup_error_playbook

    await patched_db.execute(
        "INSERT INTO knowledge_index (project_id, filename, content, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (
            None,
            "sys_docs__FAQ-git-push失败.md",
            "Git Push 失败：不要让用户自己找原因。系统禁止 Agent 直接推送到 main。"
            "原因 blocked_main 时应点「推送到远端」。",
            "2026-08-17T00:00:00Z",
        ),
    )
    hits = await lookup_error_playbook(
        "未推送到远端（保护策略）",
        project_id="PRJ-test",
        tool_name="git:push_failed",
        extra="blocked_main",
    )
    assert hits, "报错后应命中 Git Push FAQ"
    assert any("git-push" in (h.get("display_name") or "").lower()
               or "git" in (h.get("display_name") or "").lower()
               for h in hits)


@pytest.mark.asyncio
async def test_skip_search_knowledge_tool(patched_db):
    from actions.chat.search_knowledge import lookup_error_playbook

    hits = await lookup_error_playbook(
        "anything",
        tool_name="search_knowledge",
    )
    assert hits == []
