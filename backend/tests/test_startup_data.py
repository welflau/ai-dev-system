"""启动数据迁移必须对非空旧数据生效；只用合成行。"""
import json
from unittest.mock import AsyncMock, Mock

import pytest

from app_runtime import startup_data


@pytest.mark.asyncio
async def test_restore_custom_path_and_migrate_only_missing_remotes(tmp_path, monkeypatch):
    import git_manager
    manager = Mock()
    monkeypatch.setattr(git_manager, "git_manager", manager)
    monkeypatch.setattr(git_manager, "PROJECTS_DIR", tmp_path)
    custom = str(tmp_path / "custom")
    db = AsyncMock()
    db.fetch_all.return_value = [
        {"id": "a", "git_repo_path": custom, "git_remote_url": "test-url"},
        {"id": "b", "git_repo_path": str(tmp_path / "b"), "git_push_remote": "upstream",
         "git_remote_url": "kept", "git_remotes": '[{"name":"upstream"}]'},
    ]
    await startup_data.restore_project_repositories(db)
    manager.set_project_path.assert_called_once_with("a", custom)
    assert [c.args for c in manager.set_push_remote.call_args_list] == [("a", "origin"), ("b", "upstream")]
    table, changes, where, args = db.update.await_args.args
    assert db.update.await_count == 1 and (table, where, args) == ("projects", "id = ?", ("a",))
    assert json.loads(changes["git_remotes"]) == [{"name": "origin", "url": "test-url"}]


@pytest.mark.asyncio
async def test_index_ticket_reflection_and_continue_past_invalid_json(monkeypatch):
    from api import knowledge
    upsert = AsyncMock()
    monkeypatch.setattr(knowledge, "_upsert_tickets_fts", upsert)
    db = AsyncMock()
    db.fetch_all.return_value = [
        {"id": "a", "project_id": "p", "title": "A", "description": "demo", "reflection_detail": "bad json"},
        {"id": "b", "project_id": "p", "title": "B", "description": "detail",
         "reflection_detail": '{"reflection":{"root_cause":"原因"}}'},
    ]
    await startup_data.index_finished_tickets(db)
    assert [call.args for call in upsert.await_args_list] == [
        ("a", "p", "A demo"), ("b", "p", "B detail 原因")]
