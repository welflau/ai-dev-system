"""走实际 HTTP 路由，只替换刷新模型和测试连接的外部调用。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from httpx import ASGITransport, AsyncClient
import pytest

import llm_client as llm
import main


@pytest.fixture
def probes(monkeypatch):
    fetch = AsyncMock(return_value={"ok": True, "models": ["model-a"], "source": "live", "message": "ready"})
    client = SimpleNamespace(cli_type="configured", cli_cmd="configured-cli", test_connection=AsyncMock())
    monkeypatch.setattr(llm, "fetch_cli_models", fetch)
    monkeypatch.setattr(llm, "llm_client", client)
    return fetch, client


def http():
    transport = ASGITransport(app=main.app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
@pytest.mark.parametrize("body,expected", [
    (None, ("configured", "configured-cli")),
    ({"cli_type": "selected", "cli_cmd": "selected-cli"}, ("selected", "selected-cli")),
    ({"cli_type": "selected", "cli_cmd": ""}, ("selected", "configured-cli")),
    ({"cli_cmd": "selected-cli"}, ("configured", "selected-cli")),
])
async def test_refresh_resolves_each_field_independently(probes, body, expected):
    fetch, _ = probes
    async with http() as client:
        response = await client.post("/api/llm/cli-models/refresh", **({} if body is None else {"json": body}))
    fetch.assert_awaited_once_with(*expected)
    assert response.status_code == 200
    assert response.json() == {"cli_type": expected[0], "cli_cmd": expected[1], **fetch.return_value}


@pytest.mark.asyncio
async def test_refresh_without_config_returns_builtin_result(probes):
    fetch, config = probes
    config.cli_type = config.cli_cmd = ""
    fetch.return_value = {"ok": False, "models": ["fallback"], "source": "builtin", "message": "unavailable"}
    async with http() as client:
        response = await client.post("/api/llm/cli-models/refresh", json={})
    fetch.assert_awaited_once_with("claude", "")
    assert response.status_code == 200
    assert response.json() == {"cli_type": "claude", "cli_cmd": "", **fetch.return_value}


@pytest.mark.asyncio
async def test_refresh_rejects_non_object_before_call(probes):
    fetch, _ = probes
    async with http() as client:
        response = await client.post("/api/llm/cli-models/refresh", json="wrong type")
    assert response.status_code == 422
    fetch.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"status": "ok", "message": "ready", "response": "sample"},
    {"status": "not_configured", "message": "no configuration"},
    {"status": "error", "message": "provider unavailable"},
])
async def test_connection_returns_clients_result(probes, payload):
    _, config = probes
    config.test_connection.return_value = payload
    async with http() as client:
        response = await client.post("/api/llm/test")
    config.test_connection.assert_awaited_once_with()
    assert response.status_code == 200
    assert response.json() == payload


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/llm/cli-models/refresh", "/api/llm/test"])
async def test_unhandled_probe_exception_uses_application_handler(probes, path):
    fetch, config = probes
    probe = fetch if path.endswith("/refresh") else config.test_connection
    probe.side_effect = RuntimeError("fixture unavailable")
    async with http() as client:
        response = await client.post(path)
    probe.assert_awaited_once()
    assert response.status_code == 500
    assert response.json()["detail"] == "fixture unavailable"  # ASGITransport 的默认来源是回环地址
    assert response.json()["error_id"]
