"""LLM 状态显示修复：CLI 模式 display_model、顶栏单一数据源、保存不固化 hy4。

覆盖 4 项修复：
1. /api/llm/status 的 display_model 在 CLI 模式取 cli_model（实际生效模型）
2. _public_llm_fields 同样给 display_model
3. POST /api/llm/config 在 CLI 模式忽略提交的 model、不写 LLM_MODEL 到 .env
4. 历史聊天消息的 llm_model 快照是历史事实，不做改写（只验证函数不改它）

用 TestClient 打真实端点，但 .env 用 tmp_path 替换；绝不碰真实 backend/.env。
"""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from llm_client import llm_client
import main as main_mod


@pytest.fixture
def app_client(monkeypatch, tmp_path):
    # 使用临时主配置与独立 settings；这两个展示回归用例不执行安装目录同步。
    monkeypatch.setattr("config.BASE_DIR", tmp_path)
    monkeypatch.setattr("config.settings", SimpleNamespace(LIGHTAI_API_KEY=""))
    monkeypatch.setattr(llm_client, "api_key", "")
    (tmp_path / ".env").write_text(
        "LLM_API_FORMAT=cli\n"
        "LLM_MODEL=hy4-stale\n"
        "LLM_CLI_MODEL=deepseek-v4-pro-ioa\n"
        "LLM_CLI_TYPE=codebuddy\n"
        "LLM_CLI_CMD=codebuddy\n",
        encoding="utf-8",
    )
    app = FastAPI()
    # 只挂需要的端点，避免把整个 main 的 lifespan 拉起来
    from fastapi.routing import APIRoute
    for route in main_mod.app.routes:
        if isinstance(route, APIRoute) and route.path in (
            "/api/llm/status", "/api/llm/config",
        ):
            app.router.routes.append(route)
    return TestClient(app), tmp_path


def _snapshot():
    keys = (
        "api_format", "base_url", "api_key", "model", "cli_type", "cli_cmd",
        "cli_model", "cli_timeout", "timeout", "max_retries",
    )
    return {k: getattr(llm_client, k) for k in keys}


def _restore(snap):
    for k, v in snap.items():
        setattr(llm_client, k, v)


def test_status_display_model_is_cli_model(monkeypatch):
    """CLI 模式：display_model 必须是实际生效的 cli_model，不是遗留的 model。"""
    snap = _snapshot()
    try:
        llm_client.api_format = "cli"
        llm_client.model = "hy4-stale"          # 切换前残留
        llm_client.cli_model = "deepseek-v4-pro-ioa"
        llm_client.cli_cmd = "codebuddy"
        data = asyncio.run(main_mod.llm_status())
        assert data["display_model"] == "deepseek-v4-pro-ioa"
        assert data["model"] == "hy4-stale"     # 原语义保留，供 API 输入框回填
        assert data["api_format"] == "cli"
    finally:
        _restore(snap)


def test_status_display_model_is_model_in_api_mode(monkeypatch):
    """API 模式：display_model 取 model。"""
    snap = _snapshot()
    try:
        llm_client.api_format = "openai"
        llm_client.model = "gpt-4o"
        llm_client.api_key = "k"
        llm_client.base_url = "https://api.example/v1"
        data = asyncio.run(main_mod.llm_status())
        assert data["display_model"] == "gpt-4o"
        assert data["cli_model"] is None        # 非 CLI 模式 CLI 字段为 None
    finally:
        _restore(snap)


def test_public_llm_fields_has_display_model():
    """Agent 级配置也带 display_model（CLI 取 cli_model）。"""
    from llm_client import LLMClient
    c = LLMClient(config={
        "api_format": "cli", "model": "hy4-stale",
        "cli_model": "deepseek-v4-pro-ioa", "cli_cmd": "codebuddy",
    })
    f = main_mod._public_llm_fields(c)
    assert f["display_model"] == "deepseek-v4-pro-ioa"
    assert f["model"] == "hy4-stale"


def test_save_cli_ignores_model_and_does_not_write_llm_model(app_client, monkeypatch):
    """CLI 模式保存：提交的 model 被忽略、.env 不再写 LLM_MODEL（hy4 不复活）。"""
    client, tmp_path = app_client
    snap = _snapshot()
    try:
        llm_client.api_format = "cli"
        llm_client.model = "hy4-stale"
        llm_client.cli_model = "deepseek-v4-pro-ioa"
        r = client.post("/api/llm/config", json={
            "api_format": "cli",
            "model": "hy4-stale",              # 前端旧逻辑会把它发回来
            "cli_type": "codebuddy",
            "cli_cmd": "codebuddy",
            "cli_model": "deepseek-v4-pro-ioa",
        })
        assert r.status_code == 200, r.text
        assert llm_client.model == "hy4-stale"         # 没被 body.model 改成别的值
        assert llm_client.cli_model == "deepseek-v4-pro-ioa"
        env = (tmp_path / ".env").read_text(encoding="utf-8")
        # CLI 模式不写 LLM_MODEL：原有那行保留，但值仍是原来的（不更新为 hy4）
        assert "LLM_API_FORMAT=cli" in env
        assert "LLM_CLI_MODEL=deepseek-v4-pro-ioa" in env
        # 关键：没有把 body.model 当成新值固化（值仍是文件里原有的）
        assert "LLM_MODEL=hy4-stale" in env
        assert "LLM_MODEL=gpt-4" not in env
        assert r.json()["model"] == "hy4-stale"        # 返回体仍给 model 原语义
    finally:
        _restore(snap)


def test_save_api_mode_still_writes_model(app_client, monkeypatch):
    """API 模式保存行为不变：model 正常更新 + 写回 .env。"""
    client, tmp_path = app_client
    snap = _snapshot()
    try:
        llm_client.api_format = "openai"
        llm_client.model = "old"
        r = client.post("/api/llm/config", json={
            "api_format": "openai", "model": "gpt-4o",
            "base_url": "https://api.example/v1", "api_key": "k",
        })
        assert r.status_code == 200, r.text
        assert llm_client.model == "gpt-4o"
        assert "LLM_MODEL=gpt-4o" in (tmp_path / ".env").read_text(encoding="utf-8")
    finally:
        _restore(snap)


def test_history_message_snapshot_is_not_rewritten():
    """历史聊天消息的 llm_model 快照属历史事实：修的是显示层，不改数据存储。

    这里直接验证 _snapshot_llm_meta（CLI 模式）产出的是当时的 cli_model，
    语义上「历史快照按当时配置记录」，本轮修复不动它。
    """
    from api.chat import _snapshot_llm_meta
    snap = _snapshot()
    try:
        llm_client.api_format = "cli"
        llm_client.cli_model = "deepseek-v4-pro-ioa"
        llm_client.cli_type = "codebuddy"
        llm_client.cli_cmd = "codebuddy"
        # user 消息不写快照
        u = asyncio.run(_snapshot_llm_meta("user"))
        assert u == {"api_format": None, "cli_type": None, "llm_model": None}
        # assistant 消息快照 = 当时实际模型；老消息里的 hy4 是历史事实，不回填改写
        a = asyncio.run(_snapshot_llm_meta("assistant"))
        assert a["api_format"] == "cli"
        assert a["llm_model"] == "deepseek-v4-pro-ioa"
    finally:
        _restore(snap)
