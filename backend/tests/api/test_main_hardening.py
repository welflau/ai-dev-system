"""main.py 的几处加固：CORS 来源、兜底 500 的回显、版本号单一来源、默认监听地址。

只检查 app 对象和处理函数本身，不触发 lifespan（不连库、不起后台任务）。
"""
import asyncio
import json
import logging
import re
import types
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

import config
import main as main_mod

REPO_ROOT = Path(__file__).resolve().parents[3]


# ── CORS ────────────────────────────────────────────────────────────────────

def _cors_kwargs():
    for m in main_mod.app.user_middleware:
        if m.cls is CORSMiddleware:
            return getattr(m, "kwargs", None) or getattr(m, "options")
    raise AssertionError("main.app 没有注册 CORSMiddleware")


def test_cors_is_not_wildcard():
    kw = _cors_kwargs()
    assert "*" not in kw["allow_origins"]
    assert kw["allow_origin_regex"] == main_mod.CORS_LOCAL_ORIGIN_REGEX


@pytest.mark.parametrize("origin", [
    "http://localhost:8000",
    "http://127.0.0.1:18000",
    "http://localhost",
    "https://localhost:5173",
    "http://[::1]:8000",
])
def test_local_origin_matches(origin):
    assert re.fullmatch(main_mod.CORS_LOCAL_ORIGIN_REGEX, origin)


@pytest.mark.parametrize("origin", [
    "https://evil.example",
    "http://localhost.evil.example",
    "http://evil.example/?x=http://localhost:8000",
    "http://127.0.0.1.evil.example:8000",
    "http://1270001:8000",
    "null",
    "file://",
])
def test_foreign_origin_does_not_match(origin):
    assert re.fullmatch(main_mod.CORS_LOCAL_ORIGIN_REGEX, origin) is None


def test_cors_behaviour_with_the_same_settings():
    """用与 main.app 相同的 CORS 参数起一个最小应用，验证实际响应头。"""
    app = FastAPI()
    app.add_middleware(CORSMiddleware, **_cors_kwargs())

    @app.get("/ping")
    def ping():
        return {"ok": True}

    client = TestClient(app)

    ok = client.get("/ping", headers={"Origin": "http://localhost:8000"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:8000"

    evil = client.get("/ping", headers={"Origin": "https://evil.example"})
    assert evil.status_code == 200                      # CORS 不拦请求本身
    assert "access-control-allow-origin" not in evil.headers   # 但浏览器读不到响应

    preflight = client.options("/ping", headers={
        "Origin": "https://evil.example",
        "Access-Control-Request-Method": "POST",
    })
    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in preflight.headers


# ── 兜底 500 ────────────────────────────────────────────────────────────────

class _ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


@pytest.fixture
def main_log(monkeypatch):
    """接住 main logger 的输出，并阻止它写进真实的 server.log。"""
    log = logging.getLogger("main")
    handler = _ListHandler()
    monkeypatch.setattr(log, "propagate", False)
    log.addHandler(handler)
    try:
        yield handler
    finally:
        log.removeHandler(handler)


def _fake_request(host):
    return types.SimpleNamespace(
        method="GET",
        url=types.SimpleNamespace(path="/api/boom"),
        client=types.SimpleNamespace(host=host) if host else None,
    )


def _handle(host):
    exc = RuntimeError(r"sqlite error at C:\secret\ads.db")
    resp = asyncio.run(main_mod.global_exception_handler(_fake_request(host), exc))
    return resp.status_code, json.loads(resp.body)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_500_keeps_detail_for_loopback_client(main_log, host):
    status, body = _handle(host)
    assert status == 500
    assert "secret" in body["detail"]
    assert body["error_id"]


@pytest.mark.parametrize("host", ["192.168.1.23", "testclient", None])
def test_500_hides_detail_from_other_clients(main_log, host):
    status, body = _handle(host)
    assert status == 500
    assert "secret" not in json.dumps(body, ensure_ascii=False)
    assert body["error_id"] in body["detail"]
    # 详情必须能凭 error_id 在日志里找到
    assert any(body["error_id"] in m and "secret" in m for m in main_log.messages)


# ── 版本号 ──────────────────────────────────────────────────────────────────

def test_version_has_a_single_source():
    assert re.fullmatch(r"\d+\.\d+\.\d+", config.APP_VERSION)
    assert main_mod.app.version == config.APP_VERSION
    assert asyncio.run(main_mod.health_check())["version"] == config.APP_VERSION


def test_readme_badge_matches_app_version():
    major, minor, _patch = config.APP_VERSION.split(".")
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert f"badge/version-v{major}.{minor}-" in readme


def test_main_source_has_no_hardcoded_version():
    src = Path(main_mod.__file__).read_text(encoding="utf-8")
    assert re.search(r'version\s*[=:]\s*"\d+\.\d+\.\d+"', src) is None
    assert re.search(r'"version"\s*:\s*"\d+\.\d+\.\d+"', src) is None


# ── 默认监听地址 ────────────────────────────────────────────────────────────

def _env_value(path, key):
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return None


def test_default_host_is_loopback():
    """不依赖本机 .env：直接看代码里的缺省值和两份模板。"""
    src = Path(config.__file__).read_text(encoding="utf-8")
    assert 'os.getenv("HOST", "127.0.0.1")' in src
    assert _env_value(REPO_ROOT / "backend" / ".env.example", "HOST") == "127.0.0.1"
    assert _env_value(REPO_ROOT / ".env.example", "HOST") == "127.0.0.1"


def test_root_env_template_declares_matching_api_format():
    """根目录模板给的是 OpenAI 兼容地址，必须显式声明 openai（代码缺省是 anthropic）。"""
    root = REPO_ROOT / ".env.example"
    assert "api.openai.com" in (_env_value(root, "LLM_BASE_URL") or "")
    assert _env_value(root, "LLM_API_FORMAT") == "openai"
