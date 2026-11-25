"""通过真实路由读写临时 YAML；不启动服务生命周期，不改项目的 SOP。"""
from unittest.mock import Mock

from httpx import ASGITransport, AsyncClient
import pytest
import yaml

import main
from orchestrator import orchestrator
from sop import loader


@pytest.fixture
def editor(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "SOP_DIR", tmp_path)
    monkeypatch.setattr(orchestrator, "_sop_config", {})
    monkeypatch.setattr(orchestrator, "transition_rules", {"pending": {"action": "draft"}})

    def load():
        orchestrator._sop_config = loader.load_sop()
        return orchestrator._sop_config

    monkeypatch.setattr(orchestrator, "reload_sop", Mock(side_effect=load))
    return AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test")


def config():
    return {"name": "编辑器测试", "version": "2", "global": {"lang": "zh"},
            "stages": [{"id": "draft", "agent": "PlannerAgent", "action": "draft",
                        "trigger_on": "pending", "success_status": "drafted",
                        "config": {"nested": [1, 2]}}]}


@pytest.mark.asyncio
async def test_empty_sop_views_and_explicit_reload(editor):
    async with editor as client:
        assert (await client.get("/api/sop/config")).json() == {}
        assert (await client.get("/api/sop")).json() == {
            "metadata": {"name": "内置默认", "version": "1.0"}, "stages": [],
            "rules": orchestrator.transition_rules,
        }
        orchestrator.reload_sop.side_effect = [None, config()]
        for name in ("内置默认", "编辑器测试"):
            result = await client.post("/api/sop/reload")
            assert result.status_code == 200
            assert result.json() == {"status": "ok", "message": "SOP 已重载", "name": name}
        assert orchestrator.reload_sop.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [True, False], ids=["replace", "first-save"])
async def test_save_and_read_back(editor, tmp_path, existing):
    path = tmp_path / "default_sop.yaml"
    original = "# 保留原注释\nname: 原流程\n"
    if existing:
        path.write_text(original, encoding="utf-8")
    body = config()
    async with editor as client:
        res = await client.put("/api/sop/config", json=body)
        assert res.status_code == 200
        result = res.json()
        backup = tmp_path / "backups" / result["backup"]
        assert result == {"status": "ok", "name": body["name"], "stages_count": 1, "backup": backup.name}
        assert list(backup.parent.iterdir()) == ([backup] if existing else [])
        if existing:
            assert backup.read_text(encoding="utf-8") == original
        assert yaml.safe_load(path.read_text(encoding="utf-8")) == body
        assert (await client.get("/api/sop/config")).json() == body
        view = (await client.get("/api/sop")).json()
        assert view["metadata"] == {"name": body["name"], "version": "2", "description": "", "stage_count": 1}
        assert view["stages"][0]["config"] == {"nested": [1, 2]}
        assert view["rules"] == orchestrator.transition_rules
        orchestrator.reload_sop.assert_called_once_with()


@pytest.mark.asyncio
async def test_invalid_config_never_touches_disk(editor, tmp_path):
    path = tmp_path / "default_sop.yaml"
    path.write_bytes(b"name: existing\n")
    async with editor as client:
        invalid = await client.put("/api/sop/config", json={"stages": []})
        assert invalid.status_code == 400
        assert invalid.json()["detail"] == {"detail": "SOP 配置校验失败", "errors": ["stages 必须是非空数组"]}
        assert (await client.put("/api/sop/config", json="wrong type")).status_code == 422
    assert list(tmp_path.iterdir()) == [path]
    assert path.read_bytes() == b"name: existing\n"
    orchestrator.reload_sop.assert_not_called()


@pytest.mark.asyncio
async def test_reload_failure_restores_backup_before_retry(editor, tmp_path):
    path = tmp_path / "default_sop.yaml"
    original = "# 旧文件\nname: 旧版\n"
    path.write_text(original, encoding="utf-8")
    observed = []

    def reload():
        backup, = (tmp_path / "backups").glob("*.yaml")
        assert backup.read_text(encoding="utf-8") == original
        observed.append(loader.load_sop()["name"])
        if len(observed) == 1:
            raise RuntimeError("reload probe")

    orchestrator.reload_sop.side_effect = reload
    async with editor as client:
        result = await client.put("/api/sop/config", json=config())
        assert result.status_code == 500
        assert result.json()["detail"] == "热重载失败（已自动回滚）：reload probe"
    assert observed == ["编辑器测试", "旧版"]
    assert path.read_text(encoding="utf-8") == original


@pytest.mark.asyncio
async def test_yaml_serialization_failure_skips_reload(editor, tmp_path, monkeypatch):
    path = tmp_path / "default_sop.yaml"
    path.write_bytes(b"name: existing\n")
    monkeypatch.setattr(yaml, "safe_dump", Mock(side_effect=ValueError("dump probe")))
    async with editor as client:
        res = await client.put("/api/sop/config", json=config())
        assert res.status_code == 500
        assert res.json()["detail"] == "写入 yaml 失败: dump probe"
    assert path.read_bytes() == b"name: existing\n"
    orchestrator.reload_sop.assert_not_called()
