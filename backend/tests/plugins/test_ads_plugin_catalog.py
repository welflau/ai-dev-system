"""ADS 成套插件目录：给「套件与插件」页的列表 / 详情。"""
from plugins.registry import get_ads_plugin, list_ads_plugins


def test_list_includes_ue5_and_content():
    plugins = {p["id"]: p for p in list_ads_plugins()}
    assert {"ue5", "content", "h5"} <= set(plugins)
    assert plugins["ue5"]["counts"]["actions"] >= 15
    assert plugins["ue5"]["counts"]["skills"] >= 1
    assert plugins["content"]["counts"]["actions"] >= 6
    assert plugins["h5"]["counts"]["actions"] >= 3
    assert plugins["h5"]["counts"]["skills"] >= 3
    assert plugins["ue5"]["active"] is None


def test_active_follows_project_traits():
    ue = {p["id"]: p for p in list_ads_plugins(traits=["engine:ue5"])}
    assert ue["ue5"]["active"] is True
    assert ue["content"]["active"] is False

    content = {p["id"]: p for p in list_ads_plugins(traits=["pipeline:content"])}
    assert content["ue5"]["active"] is False
    assert content["content"]["active"] is True
    assert content["h5"]["active"] is False

    h5 = {p["id"]: p for p in list_ads_plugins(traits=["framework:phaser"])}
    assert h5["h5"]["active"] is True
    assert h5["ue5"]["active"] is False


def test_detail_lists_actions_and_compile_skill():
    info = get_ads_plugin("ue5")
    assert info is not None
    names = {a["name"] for a in info["actions"]}
    assert "ue_compile_check" in names
    assert "ue_playtest" in names
    skill_ids = {s["id"] for s in info["skills"]}
    assert "engine-compile" in skill_ids
    compile_skill = next(s for s in info["skills"] if s["id"] == "engine-compile")
    assert compile_skill["stage_id"] == "engine_compile"


def test_unknown_plugin_is_none():
    assert get_ads_plugin("not-a-plugin") is None


def test_ads_http_endpoints():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.plugins import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    listed = client.get("/api/plugins/ads")
    assert listed.status_code == 200
    body = listed.json()
    ids = {p["id"] for p in body["plugins"]}
    assert {"ue5", "content", "h5"} <= ids

    detail = client.get("/api/plugins/ads/detail", params={"id": "ue5"})
    assert detail.status_code == 200
    assert detail.json()["id"] == "ue5"
    assert any(a["name"] == "ue_compile_check" for a in detail.json()["actions"])

    missing = client.get("/api/plugins/ads/detail", params={"id": "nope"})
    assert missing.status_code == 404
