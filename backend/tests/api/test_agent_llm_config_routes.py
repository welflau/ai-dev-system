"""使用临时 SQLite、真实缓存与 ASGI 路由验证 Agent 配置写入。"""
import asyncio
from types import SimpleNamespace

from httpx import ASGITransport, AsyncClient
import pytest
import pytest_asyncio

import database
import llm_client as llm
import main


@pytest_asyncio.fixture
async def editor(tmp_path, monkeypatch):
    db = database.Database(str(tmp_path / "settings.db"))
    await db.connect()
    try:
        await db.init_tables()
        monkeypatch.setattr(database, "db", db)
        monkeypatch.setattr(llm, "settings", SimpleNamespace(
            LLM_API_FORMAT="openai", LLM_MODEL="global", LLM_BASE_URL="https://example.invalid",
            LLM_API_KEY="", LLM_TIMEOUT=10, LLM_MAX_RETRIES=1, LLM_CLI_TYPE="demo",
            LLM_CLI_CMD="demo-cli", LLM_CLI_MODEL="demo-model", LLM_CLI_TIMEOUT=20,
        ))
        monkeypatch.setattr(llm, "llm_client", llm.LLMClient())
        monkeypatch.setattr(llm, "_llm_ctx", SimpleNamespace(agent_type="Demo"))
        monkeypatch.setattr(llm, "_agent_clients", {"Other": object()})
        transport = ASGITransport(app=main.app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, db
    finally:
        await db.disconnect()


URL = "/api/llm/agents/Demo/config"


@pytest.mark.asyncio
async def test_save_update_and_restore_inheritance(editor):
    client, db = editor
    other = llm._agent_clients["Other"]
    assert await llm.get_effective_llm_client() is llm.llm_client
    saved = await client.post(URL.replace("Demo", "%20Demo%20"), json={
        "api_format": " cli ", "base_url": " https://example.invalid/agent ", "model": " first ",
        "cli_type": " demo ", "cli_cmd": " demo-cli ", "cli_model": " local ", "cli_timeout": "37",
        "api_key": "fixture-marker",
    })
    assert saved.status_code == 200 and saved.json() == {"status": "ok", "agent_type": "Demo"}
    row = await db.fetch_one("SELECT id, api_format, base_url, model, cli_type, cli_cmd, cli_model, cli_timeout "
                             "FROM agent_llm_config WHERE agent_type='Demo'")
    row_id = row.pop("id")
    assert row == {"api_format": "cli", "base_url": "https://example.invalid/agent", "model": "first",
                   "cli_type": "demo", "cli_cmd": "demo-cli", "cli_model": "local", "cli_timeout": 37}
    first = await llm.get_effective_llm_client()
    assert first.model == "first" and first is await llm.get_effective_llm_client()

    changed = await client.post(URL, json={"model": "second", "api_key": " "})
    assert changed.status_code == 200 and changed.json() == saved.json()
    assert await db.fetch_one("SELECT id, api_key='fixture-marker' AS retained, cli_timeout, cli_model "
                              "FROM agent_llm_config WHERE agent_type='Demo'") == {
        "id": row_id, "retained": 1, "cli_timeout": None, "cli_model": ""}
    second = await llm.get_effective_llm_client()
    assert second is not first and second.model == "second"
    for _ in range(2):
        deleted = await client.delete(URL)
        assert deleted.status_code == 200 and deleted.json() == saved.json()
    assert "Demo" not in llm._agent_clients and llm._agent_clients["Other"] is other
    assert await llm.get_effective_llm_client() is llm.llm_client
    assert await db.fetch_one("SELECT id FROM agent_llm_config WHERE agent_type='Demo'") is None


@pytest.mark.asyncio
async def test_empty_override_is_a_row_and_empty_agent_is_invalid(editor):
    client, db = editor
    for method in ("POST", "DELETE"):
        response = await client.request(method, URL.replace("Demo", "%20"), **({"json": {}} if method == "POST" else {}))
        assert response.status_code == 400 and response.json()["detail"] == "agent_type 不能为空"
    assert (await client.post(URL, json="wrong type")).status_code == 422
    assert await db.fetch_one("SELECT COUNT(*) AS n FROM agent_llm_config") == {"n": 0}
    assert (await client.post(URL, json={})).status_code == 200
    assert await db.fetch_one("SELECT api_key='' AS blank, model, cli_timeout FROM agent_llm_config") == {
        "blank": 1, "model": "", "cli_timeout": None}
    effective = await llm.get_effective_llm_client()
    assert effective.model == "global" and effective is not llm.llm_client


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
async def test_failed_db_write_keeps_previous_row_and_cache(editor, operation):
    client, db = editor
    assert (await client.post(URL, json={"model": "previous"})).status_code == 200
    previous = await llm.get_effective_llm_client()
    await db.execute(f"CREATE TRIGGER refuse_change BEFORE {operation} ON agent_llm_config "
                     "BEGIN SELECT RAISE(ABORT, 'fixture refused'); END")
    response = await client.post(URL, json={"model": "changed"}) if operation == "UPDATE" else await client.delete(URL)
    assert response.status_code == 500
    assert await db.fetch_one("SELECT model FROM agent_llm_config") == {"model": "previous"}
    assert await llm.get_effective_llm_client() is previous


@pytest.mark.asyncio
async def test_concurrent_first_saves_preserve_nonblank_field(editor):
    client, db = editor
    a, b = await asyncio.gather(client.post(URL, json={"model": "a", "api_key": "fixture-marker"}),
                                client.post(URL, json={"model": "b"}))
    assert (a.status_code, b.status_code) == (200, 200)
    assert await db.fetch_all("SELECT api_key='fixture-marker' AS retained FROM agent_llm_config") == [{"retained": 1}]
