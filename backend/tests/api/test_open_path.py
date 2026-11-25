"""通过真实 HTTP 路由验证参数，只用临时路径，不调用系统文件管理器。"""
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
import pytest_asyncio

import main
from services import file_manager


URL = "/api/system/open_path"
pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=main.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def launch(monkeypatch):
    spawn, startfile = Mock(), Mock()
    monkeypatch.setattr(file_manager, "subprocess", SimpleNamespace(Popen=spawn))
    monkeypatch.setattr(file_manager, "os", SimpleNamespace(startfile=startfile))
    return spawn, startfile


@pytest.mark.parametrize("platform, kind, prefix", [
    ("win32", "file", ["explorer", "/select,"]), ("win32", "directory", None),
    ("darwin", "file", ["open", "-R"]), ("darwin", "directory", ["open"]),
    ("linux", "file", ["xdg-open"]), ("linux", "directory", ["xdg-open"]),
])
async def test_native_call_and_reported_directory(client, launch, monkeypatch, tmp_path, platform, kind, prefix):
    folder = tmp_path / "项目 A"
    folder.mkdir()
    path = folder / "O'Brien note.txt" if kind == "file" else folder
    if kind == "file":
        path.touch()
    monkeypatch.setattr(file_manager, "sys", SimpleNamespace(platform=platform))
    response = await client.post(URL, json={"path": f"  {path}  "})
    assert response.status_code == 200 and response.json() == {"ok": True, "opened": str(folder)}
    spawn, startfile = launch
    if prefix is None:
        startfile.assert_called_once_with(str(folder))
        spawn.assert_not_called()
    else:
        spawn.assert_called_once_with([*prefix, str(folder if platform == "linux" else path)])
        startfile.assert_not_called()


async def test_relative_file_keeps_response_but_opens_absolute_location(client, launch, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "note.txt").touch()
    monkeypatch.setattr(file_manager, "sys", SimpleNamespace(platform="linux"))
    response = await client.post(URL, json={"path": "note.txt"})
    assert response.status_code == 200 and response.json()["opened"] == "."
    launch[0].assert_called_once_with(["xdg-open", str(tmp_path)])


@pytest.mark.parametrize("body, status", [
    ({}, 400), ({"path": None}, 400), ({"path": "  "}, 400),
    ({"path": 12}, 422), ({"path": ["notes"]}, 422),
])
async def test_invalid_path_does_not_launch(client, launch, body, status):
    response = await client.post(URL, json=body)
    assert response.status_code == status
    if status == 400:
        assert response.json()["detail"] == "path 不能为空"
    for call in launch:
        call.assert_not_called()


async def test_missing_file_does_not_open_existing_parent(client, launch, tmp_path):
    path = tmp_path / "missing.txt"
    response = await client.post(URL, json={"path": str(path)})
    assert response.status_code == 404 and response.json()["detail"] == f"路径不存在: {path}"
    for call in launch:
        call.assert_not_called()


async def test_missing_desktop_program_is_launch_error(client, launch, monkeypatch, tmp_path):
    monkeypatch.setattr(file_manager, "sys", SimpleNamespace(platform="darwin"))
    launch[0].side_effect = FileNotFoundError("desktop program unavailable")
    response = await client.post(URL, json={"path": str(tmp_path)})
    assert response.status_code == 500
    assert response.json()["detail"].startswith("打开失败")
    launch[0].assert_called_once()
