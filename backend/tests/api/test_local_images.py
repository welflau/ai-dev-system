"""用临时图片经过完整 HTTP 路由验证预览，不启动业务生命周期。"""
import mimetypes

import httpx
from PIL import Image
import pytest
import pytest_asyncio

import main

URL = "/api/local-file"
pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=main.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.parametrize("ext,kind", [
    ("PNG", "png"), ("jpg", "jpeg"), ("JPEG", "jpeg"), ("WebP", "webp"),
    ("gif", "gif"), ("bmp", "bmp"),
])
async def test_original_bytes_and_mime(client, tmp_path, ext, kind):
    path = tmp_path / f"色卡 & 样片.{ext}"
    Image.new("RGB", (3, 2), (36, 96, 140)).save(path, format=kind.upper())
    r = await client.get(URL, params={"path": str(path)})
    assert r.status_code == 200 and r.content == path.read_bytes()
    assert r.headers["content-type"] == "image/" + kind
    assert int(r.headers["content-length"]) == path.stat().st_size


async def test_jpeg_mime_with_incomplete_system_table(client, tmp_path, monkeypatch):
    path = tmp_path / "sample.jpg"
    Image.new("RGB", (1, 1)).save(path)
    monkeypatch.delitem(mimetypes.types_map, ".jpg", raising=False)
    r = await client.get(URL, params={"path": str(path)})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"


async def test_single_byte_range_and_unsatisfiable_range(client, tmp_path):
    path = tmp_path / "sample.png"
    Image.new("RGB", (2, 1)).save(path)
    body = path.read_bytes()
    r = await client.get(URL, params={"path": str(path)}, headers={"Range": "bytes=0-7"})
    assert r.status_code == 206 and r.content == body[:8]
    assert r.headers["content-range"] == f"bytes 0-7/{len(body)}"
    r = await client.get(URL, params={"path": str(path)}, headers={"Range": f"bytes={len(body)+1}-"})
    assert r.status_code == 416


@pytest.mark.parametrize("case,status,detail", [
    ("directory.png", 404, "文件不存在"), ("missing.png", 404, "文件不存在"),
    ("missing.txt", 404, "文件不存在"), ("exists.txt", 400, "不支持的文件类型"),
])
async def test_file_errors(client, tmp_path, case, status, detail):
    path = tmp_path / case
    if case == "directory.png":
        path.mkdir()
    elif case == "exists.txt":
        path.write_text("devnote", encoding="utf8")
    r = await client.get(URL, params={"path": str(path)})
    assert r.status_code == status and r.json() == {"detail": detail}


async def test_missing_query_parameter(client):
    r = await client.get(URL)
    assert r.status_code == 422 and r.json()["detail"][0]["loc"] == ["query", "path"]


async def test_openapi_describes_binary_success():
    operation = main.app.openapi()["paths"][URL]["get"]
    content = operation["responses"]["200"]["content"]
    assert set(content) == {"image/png", "image/jpeg", "image/webp", "image/gif", "image/bmp"}
    assert all(entry["schema"] == {"type": "string", "format": "binary"} for entry in content.values())
    for status in ("400", "404"):
        assert "application/json" in operation["responses"][status]["content"]
