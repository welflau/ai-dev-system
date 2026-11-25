"""固定 SPA 入口的 HTTP 行为；只切换临时首页，不启动应用生命周期。"""
from xml.etree import ElementTree

import httpx
import pytest
import pytest_asyncio

import main
from api import frontend_pages


CACHE = "no-cache, no-store, must-revalidate"
HTML = "<!doctype html><title>测试首页</title>".encode()
pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def pages(tmp_path, monkeypatch):
    monkeypatch.setattr(frontend_pages, "frontend_dir", tmp_path)
    transport = httpx.ASGITransport(app=main.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, tmp_path


@pytest.mark.parametrize("url", ["/app", "/app/", "/app/reports/detail.html?tab=overview"])
async def test_entry_and_nested_routes_serve_the_same_index(pages, url):
    client, root = pages
    (root / "index.html").write_bytes(HTML)
    (root / "reports").mkdir()
    (root / "reports" / "detail.html").write_text("other page", encoding="utf8")
    response = await client.get(url, follow_redirects=False)
    assert response.status_code == 200 and response.content == HTML
    assert response.headers["content-type"].split(";")[0] == "text/html"
    assert response.headers["cache-control"] == CACHE


async def test_deep_link_preserves_file_response_range(pages):
    client, root = pages
    (root / "index.html").write_bytes(HTML)
    response = await client.get("/app/projects/demo", headers={"Range": "bytes=0-8"})
    assert response.status_code == 206 and response.content == HTML[:9]
    assert response.headers["content-range"] == f"bytes 0-8/{len(HTML)}"


@pytest.mark.parametrize("url, directory_named_index", [
    ("/app", False), ("/app/projects/demo", False), ("/app", True),
])
async def test_no_regular_index_returns_json_404(pages, url, directory_named_index):
    client, root = pages
    if directory_named_index:
        (root / "index.html").mkdir()
    response = await client.get(url)
    assert response.status_code == 404
    assert response.headers["content-type"].split(";")[0] == "application/json"
    assert response.json() == {"message": "前端文件未找到，请确保 frontend/ 目录存在"}


async def test_favicon_does_not_depend_on_the_index(pages):
    client, _ = pages
    response = await client.get("/favicon.ico")
    assert response.status_code == 200 and response.headers["content-type"] == "image/svg+xml"
    assert ElementTree.fromstring(response.content).tag == "{http://www.w3.org/2000/svg}svg"
    assert "cache-control" not in response.headers
    assert "/favicon.ico" not in main.app.openapi()["paths"]


@pytest.mark.parametrize("path", ["/app", "/app/{path}"])
async def test_openapi_describes_html_success_and_json_error(path):
    responses = main.app.openapi()["paths"][path]["get"]["responses"]
    assert set(responses["200"]["content"]) == {"text/html"}
    assert set(responses["404"]["content"]) == {"application/json"}
