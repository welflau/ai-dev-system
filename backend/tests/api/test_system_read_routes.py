"""系统只读接口的 HTTP 约定；候选路径的文件状态来自临时目录。"""
from pathlib import Path

from httpx import ASGITransport, AsyncClient
import pytest

import main
from config import APP_VERSION


@pytest.mark.asyncio
async def test_health_reports_application_version():
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": APP_VERSION}


@pytest.mark.asyncio
async def test_available_paths_keep_missing_suggestions_and_refresh(tmp_path, monkeypatch):
    candidates = list(map(Path, (
        "D:/Projects", "D:/AIProjects", "D:/MyProjects", "D:/A_Works", "D:/Works",
        "C:/Projects", "C:/Users/admin/Documents/Projects", "C:/Users/admin/Documents",
    )))
    locations = {path: tmp_path / str(i) for i, path in enumerate(candidates)}
    locations[candidates[0]].mkdir()
    locations[candidates[1]].touch()  # 普通文件不是可用目录
    exists, is_dir = Path.exists, Path.is_dir
    monkeypatch.setattr(Path, "exists", lambda path: exists(locations.get(path, path)))
    monkeypatch.setattr(Path, "is_dir", lambda path: is_dir(locations.get(path, path)))
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        async def check(available):
            response = await client.get("/api/filesystem/available-paths")
            assert response.status_code == 200
            assert response.json() == {"paths": [
                {"path": str(p), "label": p.name, "exists": p in available} for p in candidates
            ]}

        await check({candidates[0]})
        locations[candidates[2]].mkdir()
        await check({candidates[0], candidates[2]})
