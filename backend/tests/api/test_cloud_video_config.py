"""AI 配置面板「生视频」Tab 后端：脱敏、只更新传入字段、.env 保真、测试连接。

用 TestClient 打真实 router，但 .env 用 tmp_path 替换（monkeypatch BASE_DIR），
ping 用 monkeypatch 打桩，绝不联网、不碰真实 backend/.env。
"""
import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import cloud_video_config as cfg
from config import settings


@pytest.fixture
def client(monkeypatch, tmp_path):
    # 把 .env 重定向到临时目录，绝不碰真实 backend/.env
    monkeypatch.setattr(cfg, "BASE_DIR", tmp_path)
    (tmp_path / ".env").write_text(
        "# 注释要保留\n"
        "LLM_API_KEY=keep-me\n"
        "\n"
        "LIGHTAI_API_KEY=keep-too\n"
        "MINIMAX_H3_CARD_KEY=old-card\n"
        "MINIMAX_H3_ENABLED=false\n",
        encoding="utf-8",
    )
    app = FastAPI()
    app.include_router(cfg.router)
    return TestClient(app)


def _restore(monkeypatch):
    """测试后还原被热更新的 settings 字段。"""
    pass


# ── GET /config/status ──────────────────────────────────────────────────────

def test_status_never_returns_secret(client):
    r = client.get("/api/cloud-video/config/status")
    assert r.status_code == 200
    body = r.text
    assert "sk-" not in body                       # 密钥值绝不出现
    # 注意：probe 的 hint 里会出现「字段名」MINIMAX_H3_CARD_KEY（不是值），
    # 因此只断言具体值不回显，而不是断言字段名不出现。
    from config import settings as _s
    if _s.MINIMAX_H3_CARD_KEY:
        assert _s.MINIMAX_H3_CARD_KEY not in body
    data = r.json()
    assert "card_key_configured" in data["minimax_h3"]      # 只给布尔
    assert "value" not in data["minimax_h3"]
    assert set(data["providers"]) == {"lightai", "minimax_h3"}
    assert "warning" in data and "官方 API" in data["warning"]


def test_status_shape(client):
    d = client.get("/api/cloud-video/config/status").json()
    assert set(d) >= {"configured", "minimax_h3", "queue", "videoclaw", "lightai", "providers", "warning"}
    assert "stats" in d["queue"]                             # 队列可观测
    assert "hint" in d["lightai"]                            # 提示不重复输入 key


# ── POST /config：热更新 + .env 保真 ────────────────────────────────────────

def test_save_updates_only_submitted_fields(client, monkeypatch, tmp_path):
    old_key = settings.MINIMAX_H3_CARD_KEY
    old_enabled = settings.MINIMAX_H3_ENABLED
    old_timeout = settings.MINIMAX_H3_TIMEOUT
    try:
        r = client.post("/api/cloud-video/config", json={"minimax_h3_timeout": 222})
        assert r.status_code == 200, r.text
        assert "MINIMAX_H3_TIMEOUT" in r.json()["changed"]
        assert settings.MINIMAX_H3_TIMEOUT == 222

        env = (tmp_path / ".env").read_text(encoding="utf-8")
        # 保真：注释、空行、其它节都还在
        assert "# 注释要保留" in env
        assert "LLM_API_KEY=keep-me" in env
        assert "LIGHTAI_API_KEY=keep-too" in env
        assert "MINIMAX_H3_CARD_KEY=old-card" in env        # 旧卡密钥没被清掉
        assert "MINIMAX_H3_TIMEOUT=222" in env
    finally:
        settings.MINIMAX_H3_TIMEOUT = old_timeout
        settings.MINIMAX_H3_CARD_KEY = old_key
        settings.MINIMAX_H3_ENABLED = old_enabled


def test_save_empty_key_does_not_overwrite(client, monkeypatch, tmp_path):
    old = settings.MINIMAX_H3_CARD_KEY
    try:
        r = client.post("/api/cloud-video/config", json={"minimax_h3_card_key": ""})
        assert r.status_code == 200
        assert "MINIMAX_H3_CARD_KEY" not in r.json()["changed"]
        assert "MINIMAX_H3_CARD_KEY=old-card" in (tmp_path / ".env").read_text(encoding="utf-8")
    finally:
        settings.MINIMAX_H3_CARD_KEY = old


def test_save_bool_false_is_not_dropped(client, monkeypatch, tmp_path):
    """bool false 不能被 || 兜底吃掉（config.py 用 .lower() 解析，回写必须 true/false）。"""
    old = settings.MINIMAX_H3_ENABLED
    try:
        r = client.post("/api/cloud-video/config", json={
            "minimax_h3_enabled": False, "minimax_h3_queue_enabled": False,
        })
        assert r.status_code == 200, r.text
        assert settings.MINIMAX_H3_ENABLED is False
        assert settings.MINIMAX_H3_QUEUE_ENABLED is False
        env = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "MINIMAX_H3_ENABLED=false" in env
        assert "MINIMAX_H3_QUEUE_ENABLED=false" in env
        assert "True" not in env and "False" not in env     # 不能写 Python 字面量
    finally:
        settings.MINIMAX_H3_ENABLED = old


def test_save_rebuilds_queue_when_queue_fields_change(client, monkeypatch):
    import cloud_video.client as cvc
    old_queue = cvc._queue
    old_enabled = settings.MINIMAX_H3_QUEUE_ENABLED
    try:
        r = client.post("/api/cloud-video/config", json={"minimax_h3_queue_idle_limit": 3})
        assert r.status_code == 200
        q = cvc.get_queue()
        assert q.idle_limit == 3
    finally:
        cvc.set_queue(old_queue)
        settings.MINIMAX_H3_QUEUE_ENABLED = old_enabled


def test_save_invalid_number_skipped(client, monkeypatch):
    old = settings.MINIMAX_H3_TIMEOUT
    try:
        r = client.post("/api/cloud-video/config", json={"minimax_h3_timeout": "not-a-number"})
        # pydantic 会在入参处 422，或字符串被 int() 拒绝后跳过
        assert r.status_code in (200, 422)
        if r.status_code == 200:
            assert settings.MINIMAX_H3_TIMEOUT == old
    finally:
        settings.MINIMAX_H3_TIMEOUT = old


def test_save_all_three_groups(client, monkeypatch, tmp_path):
    """三项全放：H3 + 排队 + VideoClaw 一起提交。"""
    saved = {k: getattr(settings, k) for k in (
        "MINIMAX_H3_BASE_URL", "MINIMAX_H3_QUEUE_TZ", "VIDEOCLAW_BASE_URL", "VIDEOCLAW_ENABLED",
    )}
    try:
        r = client.post("/api/cloud-video/config", json={
            "minimax_h3_base_url": "https://example.test/mnmx",
            "minimax_h3_queue_tz": "UTC",
            "videoclaw_base_url": "http://127.0.0.1:9999",
            "videoclaw_enabled": True,
        })
        assert r.status_code == 200, r.text
        assert settings.MINIMAX_H3_BASE_URL == "https://example.test/mnmx"
        assert settings.MINIMAX_H3_QUEUE_TZ == "UTC"
        assert settings.VIDEOCLAW_BASE_URL == "http://127.0.0.1:9999"
        env = (tmp_path / ".env").read_text(encoding="utf-8")
        for k in ("MINIMAX_H3_BASE_URL", "MINIMAX_H3_QUEUE_TZ", "VIDEOCLAW_BASE_URL", "VIDEOCLAW_ENABLED"):
            assert f"{k}=" in env
    finally:
        for k, v in saved.items():
            setattr(settings, k, v)


# ── POST /config/test：probe + ping，未保存 key 临时注入 ─────────────────────

def test_test_not_configured_when_no_key(client, monkeypatch):
    monkeypatch.setattr(settings, "MINIMAX_H3_CARD_KEY", "", raising=False)
    r = client.post("/api/cloud-video/config/test", json={})
    assert r.status_code == 200
    assert r.json()["status"] == "not_configured"


def test_test_uses_unsaved_form_key(client, monkeypatch):
    import cloud_video.client as cvc
    seen = {}

    async def _fake_ping():
        seen["card"] = settings.MINIMAX_H3_CARD_KEY
        seen["enabled"] = settings.MINIMAX_H3_ENABLED
        return True
    monkeypatch.setattr(cvc, "ping", _fake_ping)
    old_key, old_enabled = settings.MINIMAX_H3_CARD_KEY, settings.MINIMAX_H3_ENABLED
    try:
        r = client.post("/api/cloud-video/config/test", json={
            "minimax_h3_card_key": "sk-form-not-saved",
            "minimax_h3_enabled": False,     # 测试时应被强制启用
        })
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "ok"
        assert seen["card"] == "sk-form-not-saved"
        assert seen["enabled"] is True
        assert settings.MINIMAX_H3_CARD_KEY == old_key       # finally 已还原
        assert settings.MINIMAX_H3_ENABLED == old_enabled
    finally:
        settings.MINIMAX_H3_CARD_KEY = old_key
        settings.MINIMAX_H3_ENABLED = old_enabled


def test_test_restores_settings_on_exception(client, monkeypatch):
    import cloud_video.client as cvc

    async def _boom():
        raise RuntimeError("network down")
    monkeypatch.setattr(cvc, "ping", _boom)
    old_key, old_enabled = settings.MINIMAX_H3_CARD_KEY, settings.MINIMAX_H3_ENABLED
    try:
        r = client.post("/api/cloud-video/config/test", json={"minimax_h3_card_key": "sk-temp"})
        assert r.status_code == 200
        assert r.json()["status"] == "error"
        assert settings.MINIMAX_H3_CARD_KEY == old_key
        assert settings.MINIMAX_H3_ENABLED == old_enabled
    finally:
        settings.MINIMAX_H3_CARD_KEY = old_key
        settings.MINIMAX_H3_ENABLED = old_enabled


def test_test_ping_false_returns_error(client, monkeypatch):
    import cloud_video.client as cvc

    async def _false():
        return False
    monkeypatch.setattr(cvc, "ping", _false)
    old = settings.MINIMAX_H3_CARD_KEY
    try:
        r = client.post("/api/cloud-video/config/test", json={"minimax_h3_card_key": "sk-bad"})
        assert r.json()["status"] == "error"
        assert "白名单" in r.json()["message"] or "无效" in r.json()["message"]
    finally:
        settings.MINIMAX_H3_CARD_KEY = old
