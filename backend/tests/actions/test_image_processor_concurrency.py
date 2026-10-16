"""LightAI 生图并发控制：429 重试等待 + 信号量串行化。

背景：LightAI 服务端同一 key 只允许 1 个任务同时在生成，超出返回 429。
本地用信号量串行化（create+poll 整段），429 则等待重试而不是立即失败。

这里测 429 重试逻辑（信号量串行化要真并发计时，成本高，靠代码审阅保障）。
"""
import asyncio
import urllib.error

import pytest

import image_processor as ip


def _http_error(code, body="err"):
    e = urllib.error.HTTPError(
        "https://x", code, body, {}, None,
    )
    return e


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "LIGHTAI_API_KEY", "test-key", raising=False)


@pytest.fixture
def _fast_retry(monkeypatch):
    """缩短 429 重试间隔，避免测试真等 15s。"""
    monkeypatch.setattr(ip, "_LIGHTAI_429_INTERVAL", 0.01)
    monkeypatch.setattr(ip, "_LIGHTAI_429_MAX_WAIT", 2.0)


def _run(coro):
    return asyncio.run(coro)


def test_create_retries_on_429_then_succeeds(monkeypatch, _fast_retry):
    """429 → 等待 → 重试 → 成功。"""
    calls = {"n": 0}

    def post(path, body, timeout=60):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _http_error(429, "检测到您当前有AI任务在生成")
        return {"task_id": "task-ok"}

    monkeypatch.setattr(ip, "_lightai_post", post)

    task_id = _run(ip._create_lightai_task(
        {"prompt": "a cat", "engine": "gemini", "aspect_ratio": "16:9", "image_size": "2K"}
    ))
    assert task_id == "task-ok"
    assert calls["n"] == 3, f"应重试 2 次后第 3 次成功，实际 {calls['n']} 次"


def test_create_gives_up_after_429_deadline(monkeypatch, _fast_retry):
    """一直 429 → 重试到 deadline → 返回 None（不是无限等待）。"""
    def post(path, body, timeout=60):
        raise _http_error(429, "仍占用")

    monkeypatch.setattr(ip, "_lightai_post", post)

    task_id = _run(ip._create_lightai_task(
        {"prompt": "a cat", "engine": "gemini"}
    ))
    assert task_id is None


def test_create_returns_none_on_401(monkeypatch):
    """401（key 过期）不重试，直接失败。"""
    def post(path, body, timeout=60):
        raise _http_error(401, "API key has expired")

    monkeypatch.setattr(ip, "_lightai_post", post)

    task_id = _run(ip._create_lightai_task(
        {"prompt": "a cat", "engine": "gemini"}
    ))
    assert task_id is None


def test_create_and_poll_returns_both(monkeypatch):
    """helper 返回 (task_id, url)，且 create 失败时两者都是 None。"""
    async def create(req):
        return "t1"

    async def poll(task_id, engine):
        return "https://img/x.png"

    monkeypatch.setattr(ip, "_create_lightai_task", create)
    monkeypatch.setattr(ip, "_poll_lightai_task", poll)

    tid, url = _run(ip._create_and_poll({"prompt": "x", "engine": "gemini"}))
    assert tid == "t1"
    assert url == "https://img/x.png"


def test_create_and_poll_none_on_create_failure(monkeypatch):
    """create 返回 None → helper 直接 (None, None)，不再 poll。"""
    async def create(req):
        return None

    async def poll(task_id, engine):
        raise AssertionError("create 失败后不该再 poll")

    monkeypatch.setattr(ip, "_create_lightai_task", create)
    monkeypatch.setattr(ip, "_poll_lightai_task", poll)

    tid, url = _run(ip._create_and_poll({"prompt": "x", "engine": "gemini"}))
    assert tid is None and url is None
