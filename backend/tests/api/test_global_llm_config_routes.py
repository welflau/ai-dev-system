"""通过 ASGI 验证全局保存；客户端、配置、项目和用户目录均为测试专用。"""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import config
import database
import llm_client as llm
import main


URL = "/api/llm/config"


@pytest.fixture
def editor(tmp_path, monkeypatch):
    runtime = SimpleNamespace(api_format="openai", base_url="", api_key="", model="in-memory",
                              timeout=30, max_retries=2, cli_type="demo", cli_cmd="demo-cli",
                              cli_model="cli-old", cli_timeout=60, is_configured=True)
    settings = SimpleNamespace(LIGHTAI_API_KEY="", LLM_MODEL="in-memory", LIGHTAI_IMAGE_ENGINE="before")
    repo = tmp_path / "project"
    home = tmp_path / "user"
    query = AsyncMock(return_value=[{"git_repo_path": str(repo)}])
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "settings", settings)
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(llm, "llm_client", runtime)
    monkeypatch.setattr(database, "db", SimpleNamespace(fetch_all=query))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    file = tmp_path / ".env"
    file.write_text("UNRELATED=keep=both\nLLM_MODEL=on-disk\n", encoding="utf-8")
    with_http = TestClient(main.app, raise_server_exceptions=False)
    try:
        yield SimpleNamespace(http=with_http, client=runtime, settings=settings,
                              file=file, query=query, repo=repo, home=home)
    finally:
        with_http.close()


def stored(editor):
    return dict(line.split("=", 1) for line in editor.file.read_text(encoding="utf-8").splitlines())


def test_api_to_cli_and_back(editor):
    e = editor
    saved = e.http.post(URL, json={"api_format": "cli", "model": "from-request",
                                   "cli_model": "local-model", "cli_timeout": "55"})
    assert saved.status_code == 200 and saved.json() == {
        "status": "ok", "configured": True, "api_format": "cli",
        "model": "in-memory", "lightai_configured": False}
    assert e.client.model == e.settings.LLM_MODEL == "in-memory"
    assert e.client.cli_model == e.settings.LLM_CLI_MODEL == "local-model"
    assert e.settings.LLM_CLI_TIMEOUT == 55
    assert stored(e)["LLM_MODEL"] == "on-disk" and stored(e)["UNRELATED"] == "keep=both"
    e.file.write_text("UNRELATED=keep\n", encoding="utf-8")
    assert e.http.post(URL, json={}).status_code == 200
    assert "LLM_MODEL" not in stored(e)
    saved = e.http.post(URL, json={"api_format": "openai", "model": "updated", "base_url": "https://example.invalid///",
                                   "max_retries": "4", "lightai_timeout": "", "lightai_engine": ""})
    assert saved.status_code == 200 and saved.json()["model"] == "updated"
    values = stored(e)
    assert values["LLM_MODEL"] == e.client.model == e.settings.LLM_MODEL == "updated"
    assert values["LLM_BASE_URL"] == "https://example.invalid" and values["LLM_MAX_RETRIES"] == "4"
    assert values["LIGHTAI_IMAGE_TIMEOUT"] == "300" and e.settings.LIGHTAI_IMAGE_ENGINE == "gemini"
    e.query.assert_not_awaited()


@pytest.mark.parametrize("reason", ["invalid-number", "write-denied"])
def test_unsaved_changes_do_not_reach_runtime(editor, monkeypatch, reason):
    e = editor
    before_file = e.file.read_bytes()
    before_client, before_settings = vars(e.client).copy(), vars(e.settings).copy()
    if reason == "write-denied":
        original = Path.write_text

        def deny(path, *args, **kwargs):
            if path == e.file:
                raise PermissionError("fixture denies config write")
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", deny)
    data = {"model": "unsaved", "lightai_engine": "draft"}
    if reason == "invalid-number":
        data["lightai_timeout"] = "not-a-number"
    assert e.http.post(URL, json=data).status_code == 500
    assert e.file.read_bytes() == before_file
    assert vars(e.client) == before_client and vars(e.settings) == before_settings
    e.query.assert_not_awaited()


def test_sync_updates_existing_targets_and_skips_one_invalid_file(editor):
    e = editor
    broken = e.repo / ".codebuddy/packs/ue5-dev/scripts/env.json"
    intact = (e.repo / ".workbuddy/scripts/env.json", e.home / ".claude/skills/lightai-skill/scripts/env.json")
    for file in (broken, *intact):
        file.parent.mkdir(parents=True)
        file.write_text("invalid" if file == broken else '{"other":1}', encoding="utf-8")
    saved = e.http.post(URL, json={"lightai_api_key": "test-placeholder", "model": "saved"})
    assert saved.status_code == 200 and saved.json()["lightai_configured"] is True
    assert set(saved.json()) == {"status", "configured", "api_format", "model", "lightai_configured"}
    assert stored(e)["LLM_MODEL"] == "saved"
    e.query.assert_awaited_once()
    assert broken.read_text(encoding="utf-8") == "invalid"
    for file in intact:
        assert json.loads(file.read_text(encoding="utf-8")) == {"other": 1, "LIGHTAI_API_KEY": "test-placeholder"}
    assert len(list(e.repo.rglob("env.json"))) == 2 and len(list(e.home.rglob("env.json"))) == 1


def test_sync_query_failure_does_not_undo_save(editor):
    e = editor
    e.query.side_effect = RuntimeError("fixture offline")
    e.settings.LIGHTAI_API_KEY = "test-placeholder"
    saved = e.http.post(URL, json={"model": "saved", "lightai_api_key": ""})
    assert saved.status_code == 200 and saved.json()["lightai_configured"] is True
    assert e.client.model == e.settings.LLM_MODEL == stored(e)["LLM_MODEL"] == "saved"
    assert "LIGHTAI_API_KEY" not in stored(e)
    e.query.assert_awaited_once()
