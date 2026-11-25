"""项目预览兼容查询：优先级、不同项目隔离，以及链接与实际部署入口的一致性。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from httpx import ASGITransport, AsyncClient
import pytest

from agents.deploy import DeployAgent
from api import projects
import config
import database
import git_manager
import main


def http():
    return AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test")


@pytest.mark.asyncio
@pytest.mark.parametrize("registered,expected", [
    ([], None),
    (["prod"], "prod"),
    (["prod", "test"], "test"),
    (["prod", "test", "dev"], "dev"),
])
async def test_lookup_uses_only_requested_project_and_preferred_environment(monkeypatch, registered, expected):
    ports = {"dev": 9011, "test": 9111, "prod": 9211}
    records = {("other", "dev"): {"port": 9000}}
    for env in registered:
        records["example", env] = {"port": ports[env], "process": object()}
    monkeypatch.setattr(DeployAgent, "_preview_servers", records)
    async with http() as client:
        response = await client.get("/api/projects/example/preview")
    assert response.status_code == 200
    if expected is None:
        assert response.json() == {"preview_url": None}
    else:
        port = ports[expected]
        assert response.json() == {"preview_url": f"http://localhost:{port}", "port": port, "env": expected}


@pytest.mark.asyncio
async def test_builtin_fallback_environment_uses_its_own_page(monkeypatch):
    records = {("example", env): {"port": 18003, "builtin": True} for env in ("prod", "test")}
    monkeypatch.setattr(DeployAgent, "_preview_servers", records)
    async with http() as client:
        response = await client.get("/api/projects/example/preview")
    assert response.status_code == 200
    assert response.json() == {
        "preview_url": "http://localhost:18003/api/projects/example/preview/test/index.html",
        "port": 18003, "env": "test",
    }


@pytest.mark.asyncio
async def test_builtin_lookup_returns_the_deployed_page(tmp_path, monkeypatch):
    # dev 不需要克隆仓库；隔离 Git 和数据库，让部署、登记、路由、静态文件读取走真实代码。
    entry = tmp_path / "dist" / "index.html"
    entry.parent.mkdir()
    entry.write_text("<title>fixture preview</title>", encoding="utf-8")
    project_id = "preview-fixture"
    db = SimpleNamespace(fetch_one=AsyncMock(return_value=None), insert=AsyncMock())
    monkeypatch.setattr(database, "db", db)
    monkeypatch.setattr(projects, "db", db)
    monkeypatch.setattr(git_manager.git_manager, "_repo_path", lambda _: tmp_path)
    monkeypatch.setattr(git_manager.git_manager, "_run_git", AsyncMock(return_value=(0, "abc", "")))
    monkeypatch.setattr(config.settings, "PORT", 18541)
    monkeypatch.setattr(DeployAgent, "_preview_servers", {})

    deployed = await DeployAgent.deploy_env(project_id, "dev", branch="fixture")
    assert deployed == f"http://localhost:18541/api/projects/{project_id}/preview/dev/index.html"
    assert db.insert.await_args.args[1]["url"] == deployed
    db.fetch_one.return_value = {"id": project_id}
    async with http() as client:
        lookup = await client.get(f"/api/projects/{project_id}/preview")
        assert lookup.status_code == 200
        assert lookup.json() == {"preview_url": deployed, "port": 18541, "env": "dev"}
        page = await client.get(lookup.json()["preview_url"])
        assert page.status_code == 200 and page.text == "<title>fixture preview</title>"
