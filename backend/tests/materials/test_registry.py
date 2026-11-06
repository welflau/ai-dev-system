"""会话临时素材登记 / pin / promote / GC。"""
import asyncio
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

import database as database_module
from database import SCHEMA_SQL, Database
from materials.gc import gc_expired
from materials.registry import MaterialRegistry

PROJECT_ID = "P-SM"
SESSION_ID = "sess-test-1"


@asynccontextmanager
async def _env(tmp_path, monkeypatch):
    db_file = tmp_path / "t.db"
    conn = sqlite3.connect(db_file)
    conn.executescript(SCHEMA_SQL)
    try:
        conn.execute("ALTER TABLE chat_sessions ADD COLUMN last_active_at TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE chat_messages ADD COLUMN session_id TEXT DEFAULT 'default'")
    except sqlite3.OperationalError:
        pass
    conn.executescript(f"""
        INSERT INTO projects (id, name, created_at, updated_at)
        VALUES ('{PROJECT_ID}', 'demo', '2026-11-01T00:00:00', '2026-11-01T00:00:00');
        INSERT INTO chat_sessions (id, project_id, title, created_at, updated_at, last_active_at)
        VALUES ('{SESSION_ID}', '{PROJECT_ID}', '谈素材',
                '2026-11-01T00:00:00', '2026-11-01T00:00:00', '2026-11-01T00:00:00');
    """)
    conn.commit()
    conn.close()

    original_db = database_module.db
    test_db = Database(db_path=str(db_file))
    await test_db.connect()
    database_module.db = test_db
    monkeypatch.setattr("materials.registry.db", test_db)
    monkeypatch.setattr("materials.gc.db", test_db)
    monkeypatch.setattr("materials.registry.MATERIALS_ROOT", tmp_path / "session_materials")
    monkeypatch.setattr("materials.registry.DATA_DIR", tmp_path)
    try:
        yield test_db, MaterialRegistry()
    finally:
        database_module.db = original_db
        await test_db.disconnect()


def _run(coro):
    return asyncio.run(coro)


def test_attach_content_and_list(tmp_path, monkeypatch):
    async def body():
        async with _env(tmp_path, monkeypatch) as (_db, reg):
            rec = await reg.attach(
                session_id=SESSION_ID,
                project_id=PROJECT_ID,
                name="shot.png",
                origin="upload",
                content=b"\x89PNG\r\n" + b"x" * 20,
                mime="image/png",
            )
            assert rec["id"].startswith("SM-")
            assert rec["status"] == "scratch"
            assert rec["origin"] == "upload"
            path = Path(tmp_path / "session_materials" / SESSION_ID / f"{rec['id']}_{rec['name']}")
            # rel_path is relative to BASE_DIR; file may live under monkeypatched MATERIALS_ROOT
            listed = await reg.list(SESSION_ID)
            assert len(listed) == 1
            assert listed[0]["name"] == "shot.png"
            pinned = await reg.pin(rec["id"], True)
            assert pinned["status"] == "pinned"
            unpinned = await reg.pin(rec["id"], False)
            assert unpinned["status"] == "scratch"
    _run(body())


def test_attach_existing_path_no_move(tmp_path, monkeypatch):
    async def body():
        async with _env(tmp_path, monkeypatch) as (_db, reg):
            src = tmp_path / "legacy.png"
            src.write_bytes(b"abc")
            rec = await reg.attach(
                session_id=SESSION_ID,
                project_id=PROJECT_ID,
                name="legacy.png",
                origin="import",
                src_path=str(src),
                public_url="/chat-images/p/legacy.png",
            )
            assert src.is_file()
            assert rec["public_url"] == "/chat-images/p/legacy.png"
            assert rec["size_bytes"] == 3
    _run(body())


def test_keep_n_trims_scratch(tmp_path, monkeypatch):
    async def body():
        async with _env(tmp_path, monkeypatch) as (_db, reg):
            monkeypatch.setattr("materials.registry.KEEP_SCRATCH", 3)
            ids = []
            for i in range(5):
                rec = await reg.attach(
                    session_id=SESSION_ID,
                    project_id=PROJECT_ID,
                    name=f"n{i}.txt",
                    origin="generated",
                    content=f"x{i}".encode(),
                    mime="text/plain",
                )
                ids.append(rec["id"])
            listed = await reg.list(SESSION_ID)
            assert len(listed) == 3
            remaining = {r["id"] for r in listed}
            assert ids[0] not in remaining
            assert ids[1] not in remaining
    _run(body())


def test_gc_expires_idle_scratch(tmp_path, monkeypatch):
    async def body():
        async with _env(tmp_path, monkeypatch) as (tdb, reg):
            rec = await reg.attach(
                session_id=SESSION_ID,
                project_id=PROJECT_ID,
                name="old.txt",
                origin="upload",
                content=b"old",
                mime="text/plain",
            )
            await tdb.execute(
                "UPDATE chat_sessions SET last_active_at=?, updated_at=? WHERE id=?",
                ("2020-01-01T00:00:00", "2020-01-01T00:00:00", SESSION_ID),
            )
            stats = await gc_expired(ttl_days=14)
            assert stats["expired"] >= 1
            assert await reg.get(rec["id"]) is None
    _run(body())


def test_attach_inline_docs_chinese_md(tmp_path, monkeypatch):
    async def body():
        async with _env(tmp_path, monkeypatch) as (_db, reg):
            content = (
                "现在有个这样的小说，能否生成AI漫剧\n\n"
                "【附件：26021001_古墓丽影：劳拉传奇.md】\n"
                "# 正文\n劳拉走进墓穴\n"
            )
            recs = await reg.attach_inline_docs(
                session_id=SESSION_ID,
                project_id=PROJECT_ID,
                content=content,
                message_id="MSG-1",
            )
            assert len(recs) == 1
            assert recs[0]["name"] == "26021001_古墓丽影：劳拉传奇.md"
            assert recs[0]["origin"] == "upload"
            listed = await reg.list(SESSION_ID)
            assert listed[0]["name"] == "26021001_古墓丽影：劳拉传奇.md"
            again = await reg.attach_inline_docs(
                session_id=SESSION_ID,
                project_id=PROJECT_ID,
                content=content,
            )
            assert again[0]["id"] == recs[0]["id"]
            assert len(await reg.list(SESSION_ID)) == 1
            path_only = await reg.attach_inline_docs(
                session_id=SESSION_ID,
                project_id=PROJECT_ID,
                content="【附件路径：F:/novel.md】",
            )
            assert path_only == []
    _run(body())


def test_sync_inline_docs_from_session(tmp_path, monkeypatch):
    async def body():
        async with _env(tmp_path, monkeypatch) as (tdb, reg):
            await tdb.execute(
                "INSERT INTO chat_messages (id, project_id, role, content, created_at, session_id) "
                "VALUES (?,?,?,?,?,?)",
                (
                    "MSG-doc", PROJECT_ID, "user",
                    "问一句\n\n【附件：26021001_古墓丽影：劳拉传奇.md】\n第一章",
                    "2026-11-01T00:00:00", SESSION_ID,
                ),
            )
            recs = await reg.sync_inline_docs_from_session(SESSION_ID, PROJECT_ID)
            assert len(recs) == 1
            assert recs[0]["name"] == "26021001_古墓丽影：劳拉传奇.md"
            listed = await reg.list(SESSION_ID)
            assert len(listed) == 1
    _run(body())


def test_markdown_links(tmp_path, monkeypatch):
    async def body():
        async with _env(tmp_path, monkeypatch) as (_db, reg):
            rec = await reg.attach(
                session_id=SESSION_ID,
                project_id=PROJECT_ID,
                name="a.png",
                origin="upload",
                content=b"img",
                mime="image/png",
            )
            md = await reg.markdown_links([rec["id"]])
            assert rec["name"] in md
            assert "![" in md
    _run(body())
