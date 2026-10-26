"""引擎目录 Tab：由插件声明根，宿主只按 traits 收集，路径不能逃出根。"""
import asyncio
import json

import pytest
from fastapi import HTTPException

from api.repos import _safe_join
from api.workspace_roots import _search
from plugins.registry import collect_workspace_roots
from plugins.ue5.workspace import workspace_roots as ue_roots
from plugins.unity import workspace as unity_ws


def test_ue_workspace_uses_saved_engine_path(tmp_path):
    engine = tmp_path / "UE_5.7"
    (engine / "Engine").mkdir(parents=True)
    roots = ue_roots({
        "ue_engine_path": str(engine),
        "ue_engine_version": "5.7",
    })
    assert roots[0]["id"] == "engine"
    assert roots[0]["available"] is True
    assert roots[0]["path"] == str(engine)
    assert roots[0]["label"] == "UE 引擎 5.7"


def test_ue_workspace_reports_missing_engine(tmp_path):
    repo = tmp_path / "empty"
    repo.mkdir()
    roots = ue_roots({"git_repo_path": str(repo), "ue_engine_path": ""})
    assert roots[0]["available"] is False
    assert roots[0]["path"] == ""
    assert roots[0]["message"]


def test_unity_workspace_finds_hub_editor(tmp_path, monkeypatch):
    repo = tmp_path / "game"
    (repo / "ProjectSettings").mkdir(parents=True)
    (repo / "ProjectSettings" / "ProjectVersion.txt").write_text(
        "m_EditorVersion: 2022.3.10f1\n", encoding="utf-8"
    )
    editor = tmp_path / "Hub" / "Editor" / "2022.3.10f1" / "Editor"
    editor.mkdir(parents=True)
    (editor / "Unity.exe").write_bytes(b"")
    monkeypatch.setattr(unity_ws, "_hub_editor_dirs", lambda: [tmp_path / "Hub" / "Editor"])
    monkeypatch.setattr(unity_ws, "_hub_exes_for_version", lambda version: [])
    roots = unity_ws.workspace_roots({"git_repo_path": str(repo)})
    assert roots[0]["available"] is True
    assert roots[0]["label"] == "Unity 2022.3.10f1"
    assert roots[0]["path"] == str(tmp_path / "Hub" / "Editor" / "2022.3.10f1")


def test_unity_workspace_missing_version_file(tmp_path):
    repo = tmp_path / "game"
    repo.mkdir()
    roots = unity_ws.workspace_roots({"git_repo_path": str(repo)})
    assert roots[0]["available"] is False
    assert "ProjectVersion.txt" in roots[0]["message"]


def test_collect_workspace_roots_follows_traits(tmp_path):
    engine = tmp_path / "UE"
    (engine / "Engine").mkdir(parents=True)
    project = {
        "traits": json.dumps(["engine:ue5", "category:game"]),
        "ue_engine_path": str(engine),
        "ue_engine_version": "5.7",
        "git_repo_path": "",
    }
    roots = asyncio.run(collect_workspace_roots(project))
    assert [r["id"] for r in roots] == ["ue5.engine"]
    assert roots[0]["plugin_id"] == "ue5"
    assert roots[0]["available"] is True

    other = asyncio.run(collect_workspace_roots({
        "traits": ["engine:phaser"],
        "ue_engine_path": str(engine),
        "git_repo_path": str(tmp_path),
    }))
    assert other == []


def test_safe_join_rejects_parent(tmp_path):
    root = tmp_path / "engine"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("nope", encoding="utf-8")
    with pytest.raises(HTTPException) as exc:
        _safe_join(str(root), "../secret.txt")
    assert exc.value.status_code == 400


def test_search_matches_name_under_root(tmp_path):
    root = tmp_path / "eng"
    binaries = root / "Engine" / "Binaries"
    binaries.mkdir(parents=True)
    (binaries / "UnrealEditor.exe").write_bytes(b"\0\0")
    (root / "readme.txt").write_text("hi", encoding="utf-8")
    data = _search(root, "UnrealEditor", 10)
    names = [e["name"] for e in data["entries"]]
    assert "UnrealEditor.exe" in names
    assert all(".." not in e["path"] for e in data["entries"])
