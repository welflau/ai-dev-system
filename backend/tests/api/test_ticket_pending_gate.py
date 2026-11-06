"""工单抽屉的人审卡 / 产物路径：从对话 pending 卡和 result 回填。"""
import asyncio
import json
from contextlib import asynccontextmanager

import database as database_module
from database import Database
from api.tickets import (
    collect_ticket_output_files,
    load_ticket_pending_gate,
    _synthetic_output_artifacts,
)


def test_collect_prefers_preview_paths():
    files = collect_ticket_output_files(
        artifacts=[{"path": "artifacts/x/video_brief.json"}],
        result={
            "outputs": ["slug/video_brief.json"],
            "waiting_human": {"preview_paths": ["works/slug/video_brief.json"]},
        },
        pending_gate={"preview_paths": ["works/slug/video_brief.json"]},
    )
    assert files[0] == "works/slug/video_brief.json"
    assert "artifacts/x/video_brief.json" in files


def test_collect_prefixes_skill_relative_outputs():
    files = collect_ticket_output_files(
        result={"outputs": ["第一集/video_brief.json"]},
    )
    assert files == ["works/第一集/video_brief.json"]


def test_synthetic_artifacts_use_path():
    rows = _synthetic_output_artifacts(["works/a/video_brief.json"])
    assert rows[0]["path"] == "works/a/video_brief.json"
    assert rows[0]["name"] == "video_brief.json"


@asynccontextmanager
async def _db(tmp_path):
    original = database_module.db
    test_db = Database(db_path=str(tmp_path / "t.db"))
    await test_db.connect()
    await test_db.init_tables()
    database_module.db = test_db
    try:
        yield test_db
    finally:
        database_module.db = original
        await test_db.disconnect()


def test_load_pending_gate_matches_ticket(tmp_path):
    async def body():
        async with _db(tmp_path) as db:
            await db.insert("projects", {
                "id": "P1", "name": "demo", "traits": '["pipeline:video"]',
                "created_at": "2026-11-03T00:00:00Z",
                "updated_at": "2026-11-03T00:00:00Z",
            })
            payload = {
                "type": "confirm_video_gate",
                "ticket_id": "TK-1",
                "title": "确认 Mode 与简报",
                "preview_paths": ["works/slug/video_brief.json"],
            }
            await db.insert("chat_messages", {
                "id": "MSG-1",
                "project_id": "P1",
                "role": "assistant",
                "content": "请确认：确认 Mode 与简报",
                "action_type": "confirm_video_gate",
                "action_data": json.dumps(payload, ensure_ascii=False),
                "action_state": "pending",
                "session_id": "sess-chat",
                "created_at": "2026-11-03T00:00:00Z",
            })
            stored = await db.fetch_all(
                "SELECT id, action_type FROM chat_messages WHERE id = ?",
                ("MSG-1",),
            )
            assert stored, "chat_messages 没写进测试库"
            gate = await load_ticket_pending_gate("P1", "TK-1")
            assert gate is not None, "load_ticket_pending_gate 没读到测试库里的确认卡"
            assert gate["_message_id"] == "MSG-1"
            assert gate["session_id"] == "sess-chat"
            assert gate["_state"] == "pending"
            assert gate["preview_paths"] == ["works/slug/video_brief.json"]
            assert await load_ticket_pending_gate("P1", "TK-other") is None
    asyncio.run(body())


def test_load_pending_gate_synthesizes_from_ready_ticket(tmp_path):
    """对话里没卡时，*_ready 工单仍要能在抽屉确认。"""
    async def body():
        async with _db(tmp_path) as db:
            await db.insert("projects", {
                "id": "P1", "name": "demo", "traits": '["pipeline:video"]',
                "created_at": "2026-11-03T00:00:00Z",
                "updated_at": "2026-11-03T00:00:00Z",
            })
            await db.insert("requirements", {
                "id": "REQ-1", "project_id": "P1", "title": "需求",
                "description": "",
                "created_at": "2026-11-03T00:00:00Z",
                "updated_at": "2026-11-03T00:00:00Z",
            })
            await db.insert("tickets", {
                "id": "TK-ready", "project_id": "P1", "requirement_id": "REQ-1",
                "title": "讲稿", "description": "",
                "type": "feature", "module": "video",
                "status": "director_script_ready",
                "result": json.dumps({
                    "waiting_human": {
                        "type": "confirm_video_gate",
                        "title": "确认讲稿与拆解",
                        "preview_paths": ["works/slug/旁白.md"],
                    }
                }, ensure_ascii=False),
                "created_at": "2026-11-03T00:00:00Z",
                "updated_at": "2026-11-03T00:00:00Z",
            })
            gate = await load_ticket_pending_gate("P1", "TK-ready")
            assert gate is not None
            assert gate["_state"] == "pending"
            assert gate["title"] == "确认讲稿与拆解"
            assert gate["preview_paths"] == ["works/slug/旁白.md"]
            assert gate["ticket_id"] == "TK-ready"
    asyncio.run(body())


def test_load_pending_gate_ignores_other_ticket_waiting_human(tmp_path):
    """clip-trial 失败后会把另一张工单的旧确认卡写进 result，抽屉不能接着给人点。"""
    async def body():
        async with _db(tmp_path) as db:
            await db.insert("projects", {
                "id": "P1", "name": "demo", "traits": '["pipeline:video"]',
                "created_at": "2026-11-03T00:00:00Z",
                "updated_at": "2026-11-03T00:00:00Z",
            })
            await db.insert("requirements", {
                "id": "REQ-1", "project_id": "P1", "title": "需求",
                "description": "",
                "created_at": "2026-11-03T00:00:00Z",
                "updated_at": "2026-11-03T00:00:00Z",
            })
            await db.insert("tickets", {
                "id": "TK-clip", "project_id": "P1", "requirement_id": "REQ-1",
                "title": "分镜", "description": "",
                "type": "feature", "module": "video",
                "status": "director_clip_trial_ready",
                "result": json.dumps({
                    "skill_id": "director-clip-trial",
                    "outputs": [],
                    "waiting_human": {
                        "type": "confirm_video_gate",
                        "waiting_human": True,
                        "title": "确认第一集试片片段表",
                        "preview_paths": ["works/dragon-triangle-ep1/片段表.md"],
                        "ticket_id": "TK-other",
                        "_message_id": "MSG-old",
                    },
                }, ensure_ascii=False),
                "created_at": "2026-11-03T00:00:00Z",
                "updated_at": "2026-11-03T00:00:00Z",
            })
            assert await load_ticket_pending_gate("P1", "TK-clip") is None
    asyncio.run(body())


def test_collect_skips_waiting_human_from_other_ticket():
    files = collect_ticket_output_files(
        artifacts=[{"path": "artifacts/x/lara.png"}],
        result={
            "outputs": [],
            "waiting_human": {
                "ticket_id": "TK-old",
                "preview_paths": ["works/dragon-triangle-ep1/片段表.md"],
            },
        },
        ticket_id="TK-new",
    )
    assert "works/dragon-triangle-ep1/片段表.md" not in files
