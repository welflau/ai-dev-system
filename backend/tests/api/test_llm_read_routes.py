"""通过真实 HTTP 路由验证展示配置；模型、目录、数据库行均来自测试。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from httpx import ASGITransport, AsyncClient
import pytest

import agent_registry
import database
import llm_client as llm
import main


@pytest.fixture
def client(monkeypatch):
    settings = SimpleNamespace(
        LLM_API_FORMAT="openai", LLM_MODEL="global-model", LLM_BASE_URL="https://example.invalid/v1",
        LLM_API_KEY="", LLM_TIMEOUT=15, LLM_MAX_RETRIES=2, LLM_CLI_TYPE="demo",
        LLM_CLI_CMD="demo-cmd", LLM_CLI_MODEL="cli-model", LLM_CLI_TIMEOUT=30,
    )
    monkeypatch.setattr(llm, "settings", settings)
    monkeypatch.setattr(llm, "llm_client", llm.LLMClient())
    monkeypatch.setattr(llm, "_CLI_ADAPTERS", {"demo": {"default_cmd": "demo-cmd"}})
    monkeypatch.setattr(llm, "get_cli_model_options", lambda: {"demo": ["cli-model"]})
    return AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,cli_model,display", [
    ("openai", "unused-cli", "global-model"),
    ("cli", "selected-cli", "selected-cli"),
    ("cli", "", "global-model"),
])
async def test_status_contract(client, mode, cli_model, display):
    llm.llm_client.api_format = mode
    llm.llm_client.cli_model = cli_model
    cli = mode == "cli"
    async with client:
        response = await client.get("/api/llm/status")
    assert response.status_code == 200
    assert response.json() == {
        "configured": cli, "api_format": mode, "base_url": None if cli else "https://example.invalid/v1",
        "model": "global-model", "display_model": display, "timeout": 15, "max_retries": 2,
        "cli_type": "demo" if cli else None, "cli_cmd": "demo-cmd" if cli else None,
        "cli_model": cli_model if cli else None, "cli_timeout": 30 if cli else None,
        "cli_model_options": {"demo": ["cli-model"]}, "cli_default_cmds": {"demo": "demo-cmd"},
    }


@pytest.mark.asyncio
async def test_agent_overrides_inheritance_and_public_fields(client, monkeypatch):
    # discover_agents 在请求内填充注册表。给数据库访问提供行，其余回退和客户端构造走实际代码。
    registry = {}
    monkeypatch.setattr(agent_registry, "get_registry", lambda: dict(registry))
    monkeypatch.setattr(agent_registry, "discover_agents",
                        lambda: registry.update({"ZInherited": object, "ACustom": object, "BDefaults": object}))
    rows = {"ACustom": {"api_format": "cli", "cli_model": "agent-cli", "api_key": True},
            "BDefaults": {"model": ""}, "ZInherited": None}
    monkeypatch.setattr(database.db, "fetch_one", AsyncMock(side_effect=lambda sql, args: rows[args[0]]))
    global_fields = {"api_format": "openai", "model": "global-model", "display_model": "global-model",
                     "base_url": "https://example.invalid/v1", "cli_type": "demo", "cli_cmd": "demo-cmd",
                     "cli_model": "cli-model", "cli_timeout": 30, "has_api_key": False}
    custom_fields = {**global_fields, "api_format": "cli", "display_model": "agent-cli",
                     "cli_model": "agent-cli", "has_api_key": True}
    async with client:
        response = await client.get("/api/llm/agents")
    assert response.status_code == 200
    assert response.json() == {
        "agents": [
            {"agent_type": "ACustom", "has_override": True, "effective": custom_fields},
            {"agent_type": "BDefaults", "has_override": True, "effective": global_fields},
            {"agent_type": "ZInherited", "has_override": False, "effective": global_fields},
        ],
        "global": global_fields, "cli_model_options": {"demo": ["cli-model"]},
        "cli_default_cmds": {"demo": "demo-cmd"},
    }
