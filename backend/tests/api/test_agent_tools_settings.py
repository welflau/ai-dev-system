"""只操作当前测试进程的开关和临时配置；不启动 Agent 或应用生命周期。"""
import os
from types import SimpleNamespace

from dotenv import dotenv_values
from fastapi.testclient import TestClient
import pytest

import config
import main


KEY = "ENABLE_AGENT_TOOLS"
URL = "/api/settings/agent-tools"


@pytest.fixture
def editor(monkeypatch, tmp_path):
    file = tmp_path / ".env"
    settings = SimpleNamespace(ENABLE_AGENT_TOOLS=False)
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "ENV_PATH", file, raising=False)
    monkeypatch.setattr(config, "settings", settings)
    monkeypatch.setenv(KEY, "false")
    client = TestClient(main.app, raise_server_exceptions=False)
    try:
        yield client, file, settings
    finally:
        client.close()


def test_get_reads_live_environment_without_creating_file(editor, monkeypatch):
    client, file, _ = editor
    monkeypatch.delenv(KEY)
    for raw, expected in [(None, False), ("YES", True), ("1", True), ("true", True), ("off", False)]:
        if raw is not None:
            monkeypatch.setenv(KEY, raw)
        assert client.get(URL).json() == {"enabled": expected}
    assert not file.exists()


@pytest.mark.parametrize("body, expected", [
    ({"enabled": True}, True), ({"enabled": False}, False), ({}, False),
    ({"enabled": "false"}, False), ({"enabled": "OFF"}, False), ({"enabled": "0"}, False),
    ({"enabled": "YES"}, True), ({"enabled": 1}, True), ({"enabled": 0}, False),
])
def test_save_normalizes_and_agrees_with_get_and_disk(editor, monkeypatch, body, expected):
    client, file, settings = editor
    settings.ENABLE_AGENT_TOOLS = not expected
    monkeypatch.setenv(KEY, "false" if expected else "true")
    response = client.post(URL, json=body)
    assert response.status_code == 200 and response.json() == {
        "enabled": expected, "message": f"Agent Tool Use {'已开启' if expected else '已关闭'}"}
    assert client.get(URL).json() == {"enabled": expected}
    assert dotenv_values(file)[KEY] == os.environ[KEY] == str(expected).lower()
    assert settings.ENABLE_AGENT_TOOLS is expected


@pytest.mark.parametrize("bad", ["unknown", None, [], 2])
def test_invalid_value_leaves_file_and_runtime_alone(editor, monkeypatch, bad):
    client, file, settings = editor
    file.write_text("# fixture\nENABLE_AGENT_TOOLS=false\n", encoding="utf-8")
    before = file.read_bytes()
    monkeypatch.setenv(KEY, "false")
    assert client.post(URL, json={"enabled": bad}).status_code == 422
    assert file.read_bytes() == before and os.environ[KEY] == "false"
    assert settings.ENABLE_AGENT_TOOLS is False


def test_preserves_other_dotenv_values_and_updates_duplicates(editor):
    client, file, _ = editor
    file.write_text('# keep\nTEXT="first\nENABLE_AGENT_TOOLS=literal\nlast"\n'
                    'ENABLE_AGENT_TOOLS = False\nexport ENABLE_AGENT_TOOLS=false\nOTHER=a=b', encoding="utf-8")
    assert client.post(URL, json={"enabled": True}).status_code == 200
    assert dotenv_values(file) == {"TEXT": "first\nENABLE_AGENT_TOOLS=literal\nlast", KEY: "true", "OTHER": "a=b"}
    assert file.read_text(encoding="utf-8").startswith("# keep\n")


def test_failed_persistence_leaves_switch_off(editor, monkeypatch):
    client, file, settings = editor
    monkeypatch.setenv(KEY, "false")
    file.mkdir()  # 同名目录阻止配置写入，不依赖本机 ACL 或管理员权限。
    assert client.post(URL, json={"enabled": True}).status_code == 500
    assert client.get(URL).json() == {"enabled": False}
    assert settings.ENABLE_AGENT_TOOLS is False and file.is_dir()


def test_writes_to_bootstrap_location_when_runtime_directory_is_separate(editor, monkeypatch):
    client, file, _ = editor
    runtime = file.parent / "runtime"
    runtime.mkdir()
    monkeypatch.setattr(config, "BASE_DIR", runtime)
    file.write_text("OTHER=keep", encoding="utf-8")
    assert client.post(URL, json={"enabled": True}).status_code == 200
    assert dotenv_values(file) == {"OTHER": "keep", KEY: "true"}
    assert not (runtime / ".env").exists()
