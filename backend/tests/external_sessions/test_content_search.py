"""外部会话搜索要能命中消息正文，不能只看标题。"""
import json
import sqlite3
from pathlib import Path

from external_sessions.base import contains_query, match_snippet
from external_sessions.claude import ClaudeProvider
from external_sessions.codebuddy import CodeBuddyProvider
from external_sessions.cursor import CursorProvider


def test_match_snippet_is_case_insensitive_and_windowed():
    assert contains_query("RefactorInputVector 已落地", "refactorinput")
    text = "前" * 80 + "关键字在这" + "后" * 80
    snip = match_snippet(text, "关键字", radius=4)
    assert "关键字" in snip
    assert snip.startswith("…")
    assert snip.endswith("…")
    assert match_snippet("没有", "关键字") == ""


def _cursor_db(root: Path, title: str, body: str) -> None:
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
        (
            "cid-1",
            "ws1",
            1,
            2,
            json.dumps({"name": title, "isDraft": False, "isArchived": False}),
        ),
    )
    conn.execute(
        "INSERT INTO cursorDiskKV VALUES (?,?)",
        (
            "bubbleId:cid-1:b1",
            json.dumps({"type": 2, "text": body}, ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()


def test_cursor_search_hits_message_body_not_only_title(tmp_path: Path):
    _cursor_db(tmp_path, "别的话题", "GroundModifyData 里的 RefactorInputVector 已经接上")
    provider = CursorProvider(tmp_path)
    roots = ["F:/demo"]

    all_sessions = provider.list_sessions(roots)
    assert [s.id for s in all_sessions] == ["cid-1"]

    hit = provider.list_sessions(roots, query="RefactorInputVector")
    assert [s.id for s in hit] == ["cid-1"]
    assert "RefactorInputVector" in (hit[0].extra or {})["match_snippet"]

    assert provider.list_sessions(roots, query="例会") == []
    titled = provider.list_sessions(roots, query="话题")
    assert [s.id for s in titled] == ["cid-1"]
    assert "match_snippet" not in (titled[0].extra or {})


def test_codebuddy_and_claude_search_message_body(tmp_path: Path):
    cb_dir = tmp_path / "cb" / "projects" / "slug"
    cb_dir.mkdir(parents=True)
    (cb_dir / "s1.jsonl").write_text(
        "\n".join([
            json.dumps({
                "type": "message", "role": "user", "cwd": "F:/demo", "timestamp": 1,
                "content": [{"type": "input_text", "text": "你好"}],
            }, ensure_ascii=False),
            json.dumps({
                "type": "message", "role": "assistant", "cwd": "F:/demo", "timestamp": 2,
                "content": [{"type": "output_text", "text": "这里提到 RefactorInputVector"}],
            }, ensure_ascii=False),
        ]),
        encoding="utf-8",
    )
    cb = CodeBuddyProvider(tmp_path / "cb")
    hit = cb.list_sessions(["F:/demo"], query="RefactorInputVector")
    assert [s.id for s in hit] == ["s1"]
    assert "RefactorInputVector" in hit[0].extra["match_snippet"]
    assert cb.list_sessions(["F:/demo"], query="不存在的句子") == []

    cl_dir = tmp_path / "cl" / "projects" / "slug"
    cl_dir.mkdir(parents=True)
    (cl_dir / "s2.jsonl").write_text(
        "\n".join([
            json.dumps({
                "type": "user", "cwd": "F:/demo", "timestamp": "2026-01-01T00:00:00Z",
                "message": {"content": "你好"},
            }, ensure_ascii=False),
            json.dumps({
                "type": "assistant", "cwd": "F:/demo", "timestamp": "2026-01-01T00:00:01Z",
                "message": {"content": [{"type": "text", "text": "正文里有 RefactorInputVector"}]},
            }, ensure_ascii=False),
        ]),
        encoding="utf-8",
    )
    cl = ClaudeProvider(tmp_path / "cl")
    hit = cl.list_sessions(["F:/demo"], query="RefactorInputVector")
    assert [s.id for s in hit] == ["s2"]
    assert "RefactorInputVector" in hit[0].extra["match_snippet"]
