"""从 HTTP 路由验证桌面浏览器调用。所有请求使用替身，不启动浏览器或访问目标站点。"""
import asyncio
from threading import Event
from unittest.mock import Mock
import webbrowser

import httpx
import pytest
import pytest_asyncio

import main


URL = "/api/open-in-browser"
pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def desktop(monkeypatch):
    launch = Mock(return_value=True)
    monkeypatch.setattr(webbrowser, "open", launch)
    transport = httpx.ASGITransport(app=main.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, launch


@pytest.mark.parametrize("url, expected", [
    ("http://localhost:8001/app", "http://localhost:8001/app"),
    ("https://example.org", "https://example.org"),
    ("HTTPS://Example.org/Docs%2FOne?q=A%26B&q=Two#Top", "https://Example.org/Docs%2FOne?q=A%26B&q=Two#Top"),
    ("hTtP://[::1]:8001/目录", "http://[::1]:8001/目录"),
])
async def test_valid_web_url_preserves_everything_after_scheme(desktop, url, expected):
    client, launch = desktop
    r = await client.get(URL, params={"url": url})
    assert r.status_code == 200 and r.json() == {"ok": True}
    launch.assert_called_once_with(expected)


@pytest.mark.parametrize("url", [
    "", "docs/notes", "ftp://example.org/docs", "https://", "http://example.org:65536/docs",
    "https://not a host/docs",
])
async def test_invalid_address_never_reaches_desktop(desktop, url):
    client, launch = desktop
    r = await client.get(URL, params={"url": url})
    assert r.status_code == 400
    launch.assert_not_called()


async def test_missing_query_is_still_required(desktop):
    client, launch = desktop
    assert (await client.get(URL)).status_code == 422
    launch.assert_not_called()


@pytest.mark.parametrize("failure", [False, webbrowser.Error("no browser"), OSError("launch failed")])
async def test_launch_failure_has_consistent_response(desktop, failure):
    client, launch = desktop
    if isinstance(failure, Exception):
        launch.side_effect = failure
    else:
        launch.return_value = failure
    r = await client.get(URL, params={"url": "https://example.org/docs"})
    assert r.status_code == 500 and r.json() == {"detail": "无法调起系统浏览器"}
    launch.assert_called_once()


async def test_pending_desktop_call_does_not_hold_up_health_check(desktop):
    client, launch = desktop
    loop, entered, release, finished = asyncio.get_running_loop(), asyncio.Event(), Event(), Event()

    def wait_for_health(_):
        loop.call_soon_threadsafe(entered.set)
        try:
            return release.wait(5)  # 超时仅用于保证错误实现也能退出测试
        finally:
            finished.set()

    launch.side_effect = wait_for_health
    pending = asyncio.create_task(client.get(URL, params={"url": "https://example.org/docs"}))
    try:
        await asyncio.wait_for(entered.wait(), 8)
        r = await asyncio.wait_for(client.get("/api/health"), 5)
        assert r.status_code == 200 and not finished.is_set()
    finally:
        release.set()
        result = await pending
    assert result.status_code == 200
