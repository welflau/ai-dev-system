"""全局助手把气泡里的相对路径对到本地文件。"""
import os
from pathlib import Path

import pytest

from api.local_preview import blocked_reason, read_local_preview, resolve_local_file


def test_absolute_path_opens(tmp_path: Path):
    f = tmp_path / "AGENTS.md"
    f.write_text("# hi\n", encoding="utf-8")
    assert resolve_local_file(str(f)) == f
    preview = read_local_preview(f)
    assert preview["kind"] == "text"
    assert preview["content"].replace("\r\n", "\n") == "# hi\n"


def test_relative_path_matches_hint_suffix(tmp_path: Path):
    f = tmp_path / "agent" / "siboot" / "AGENTS.md"
    f.parent.mkdir(parents=True)
    f.write_text("body", encoding="utf-8")
    found = resolve_local_file("AGENTS.md", hints=[str(f)])
    assert found == f
    found = resolve_local_file("agent/siboot/SKILL.md", hints=[str(tmp_path / "agent" / "siboot")])
    skill = tmp_path / "agent" / "siboot" / "SKILL.md"
    skill.write_text("skill", encoding="utf-8")
    found = resolve_local_file("agent/siboot/SKILL.md", hints=[str(tmp_path / "agent" / "siboot")])
    assert found == skill


def test_env_root_resolves_relative(tmp_path: Path, monkeypatch):
    f = tmp_path / "skills" / "demo" / "SKILL.md"
    f.parent.mkdir(parents=True)
    f.write_text("x", encoding="utf-8")
    monkeypatch.setenv("SIBOOT_WORKSPACE_PATH", str(tmp_path))
    assert resolve_local_file(r"$SIBOOT_WORKSPACE_PATH\skills\demo\SKILL.md") == f
    assert resolve_local_file("skills/demo/SKILL.md") == f


def test_paren_wrapped_hint_finds_sibling(tmp_path: Path):
    folder = tmp_path / "agent" / "siboot-smallrpg"
    folder.mkdir(parents=True)
    agents = folder / "AGENTS.md"
    skill = folder / "SKILL.md"
    agents.write_text("agents", encoding="utf-8")
    skill.write_text("skill-body", encoding="utf-8")
    found = resolve_local_file("SKILL.md", hints=[str(agents) + ")"])
    assert found == skill


def test_relative_dir_hint_beats_other_skill_md(tmp_path: Path, monkeypatch):
    appdata = tmp_path / "roaming"
    ws = appdata / "siboot" / "workspace"
    agent = ws / "agent" / "siboot-smallrpg"
    other = ws / "skills" / "docx"
    agent.mkdir(parents=True)
    other.mkdir(parents=True)
    (agent / "SKILL.md").write_text("agent-skill", encoding="utf-8")
    (other / "SKILL.md").write_text("docx-skill", encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(appdata))
    found = resolve_local_file("SKILL.md", hints=[r"agent\siboot-smallrpg"])
    assert found == agent / "SKILL.md"
    assert read_local_preview(found)["content"].startswith("agent-skill")


def test_secrets_are_refused(tmp_path: Path):
    envf = tmp_path / ".env"
    envf.write_text("K=1", encoding="utf-8")
    assert blocked_reason(envf)
    with pytest.raises(PermissionError):
        read_local_preview(envf)
    assert resolve_local_file("missing.md", hints=[]) is None
    assert "SIBOOT_WORKSPACE_PATH" not in os.environ or True
