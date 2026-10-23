"""新版 Cursor 把消息顺序拆到 composerConvHeaders 分片，详情不能再读成空会话。"""
import json
import sqlite3
from pathlib import Path

from external_sessions.cursor import CursorProvider


def _db(root: Path, composer_value: dict, kv: dict) -> None:
    ws = root / "workspaceStorage" / "ws1"
    ws.mkdir(parents=True)
    (ws / "workspace.json").write_text(
        json.dumps({"folder": "file:///F:/demo"}), encoding="utf-8"
    )
    db_path = root / "globalStorage" / "state.vscdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE composerHeaders (composerId TEXT, workspaceId TEXT, createdAt INTEGER, lastUpdatedAt INTEGER, value TEXT)"
    )
    conn.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "INSERT INTO composerHeaders VALUES (?,?,?,?,?)",
        ("cid-1", "ws1", 1, 2, json.dumps({"name": "NPC stop time"})),
    )
    for key, value in kv.items():
        conn.execute("INSERT INTO cursorDiskKV VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))
    conn.execute(
        "INSERT INTO cursorDiskKV VALUES (?,?)",
        ("composerData:cid-1", json.dumps(composer_value, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()


def test_chunked_headers_restore_message_order(tmp_path: Path):
    _db(
        tmp_path,
        {
            "fullConversationHeadersOnly": [],
            "headerLog": {"chunkSize": 256, "chunkCount": 1, "count": 2},
        },
        {
            "composerConvHeaders:cid-1:000000": [
                {"bubbleId": "later", "type": 1},
                {"bubbleId": "earlier", "type": 2},
            ],
            "bubbleId:cid-1:later": {"bubbleId": "later", "type": 1, "text": "后一句", "createdAt": "2026-10-02T00:00:00Z"},
            "bubbleId:cid-1:earlier": {"bubbleId": "earlier", "type": 2, "text": "先一句", "createdAt": "2026-10-01T00:00:00Z"},
        },
    )
    detail = CursorProvider(tmp_path).get_session("cid-1")
    assert detail is not None
    assert [m.content for m in detail.messages] == ["后一句", "先一句"]
    assert detail.message_count == 2


def test_inline_headers_still_used_when_chunks_absent(tmp_path: Path):
    _db(
        tmp_path,
        {"fullConversationHeadersOnly": [{"bubbleId": "b1", "type": 1}]},
        {"bubbleId:cid-1:b1": {"type": 1, "text": "还在旧字段里"}},
    )
    detail = CursorProvider(tmp_path).get_session("cid-1")
    assert detail is not None
    assert [m.content for m in detail.messages] == ["还在旧字段里"]


def test_bubbles_are_read_when_no_order_is_stored(tmp_path: Path):
    _db(
        tmp_path,
        {},
        {
            "bubbleId:cid-1:b2": {"bubbleId": "b2", "type": 2, "text": "第二条", "createdAt": "2026-10-02T00:00:00Z"},
            "bubbleId:cid-1:b1": {"bubbleId": "b1", "type": 1, "text": "第一条", "createdAt": "2026-10-01T00:00:00Z"},
        },
    )
    detail = CursorProvider(tmp_path).get_session("cid-1")
    assert detail is not None
    assert [m.content for m in detail.messages] == ["第一条", "第二条"]


def test_multi_root_code_workspace_matches_project_roots(tmp_path: Path):
    _db(tmp_path, {"fullConversationHeadersOnly": [{"bubbleId": "b1", "type": 1}]}, {"bubbleId:cid-1:b1": {"type": 1, "text": "多根工作区会话"}})
    cw_file = tmp_path / "glassMultiRootWorkspaces" / "OG_I.code-workspace"
    cw_file.parent.mkdir(parents=True)
    cw_file.write_text(json.dumps({"folders": [{"path": "I:/A_Works/OG2/P4/UE5"}]}), encoding="utf-8")
    ws2 = tmp_path / "workspaceStorage" / "ws-multi"
    ws2.mkdir(parents=True)
    (ws2 / "workspace.json").write_text(
        json.dumps({"workspace": f"file:///{cw_file.as_posix()}"}), encoding="utf-8"
    )
    conn = sqlite3.connect(tmp_path / "globalStorage" / "state.vscdb")
    conn.execute(
        "INSERT INTO composerHeaders VALUES (?,?,?,?,?)",
        ("cid-multi", "ws-multi", 10, 20, json.dumps({"name": "Multi root session"})),
    )
    conn.commit()
    conn.close()

    sessions = CursorProvider(tmp_path).list_sessions(["I:\\A_Works\\OG2\\P4\\UE5\\"])
    assert [s.id for s in sessions] == ["cid-multi"]

