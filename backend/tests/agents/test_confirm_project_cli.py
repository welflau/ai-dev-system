"""CLI 全局聊天：confirm_project 要从 ads-data MCP 合成确认卡。"""
import asyncio

from actions.chat.confirm_project import ConfirmProjectAction
from query_engine.engine import _synthesize_confirm_action


def test_synthesize_confirm_project_from_tool_input():
    action = _synthesize_confirm_action(
        "mcp__ads-data__confirm_project",
        {
            "name": "PhaserGame",
            "traits": "platform:web, category:game, engine:none, framework:phaser",
            "description": "H5 网页游戏",
            "mode": "auto",
        },
        '{"status":"ok"}',
    )
    assert action is not None
    assert action["type"] == "confirm_project"
    assert action["name"] == "PhaserGame"
    assert "framework:phaser" in action["traits"]
    assert "platform:web" in action["traits"]


def test_synthesize_confirm_project_prefers_result_action():
    action = _synthesize_confirm_action(
        "mcp__ads-data__confirm_project",
        {"name": "Ignored"},
        '{"status":"ok","action":{"type":"confirm_project","name":"FromResult","traits":["platform:web","category:game"]}}',
    )
    assert action["name"] == "FromResult"
    assert action["traits"] == ["platform:web", "category:game"]


def test_synthesize_confirm_project_error_is_none():
    assert _synthesize_confirm_action(
        "mcp__ads-data__confirm_project",
        {"name": "X", "traits": "platform:web, category:game"},
        '{"status":"error","message":"项目名称不能为空"}',
    ) is None


def test_detect_new_h5_project_from_plain_request():
    from api.chat import _detect_new_h5_project
    action = asyncio.run(_detect_new_h5_project("新建项目，H5游戏"))
    assert action is not None
    assert action["type"] == "confirm_project"
    assert "framework:phaser" in action["traits"]


def test_detect_new_h5_project_ignores_unrelated():
    from api.chat import _detect_new_h5_project
    assert asyncio.run(_detect_new_h5_project("这个工单卡在哪")) is None


def test_stash_and_pop_global_mcp_action():
    from api.chat import _pop_global_mcp_action, _stash_global_mcp_action
    _pop_global_mcp_action("sess-test")
    _stash_global_mcp_action("sess-test", {"type": "confirm_project", "name": "X"})
    assert _pop_global_mcp_action("sess-test")["name"] == "X"
    assert _pop_global_mcp_action("sess-test") is None


def test_confirm_project_action_phaser_traits():
    result = asyncio.run(ConfirmProjectAction().run({
        "name": "PhaserGame",
        "traits": [
            "platform:web", "category:game", "engine:none",
            "framework:phaser", "lang:typescript",
        ],
        "description": "H5 网页游戏（Phaser 3 + TypeScript）",
        "mode": "auto",
    }))
    assert result.success
    assert result.data["type"] == "confirm_project"
    assert "framework:phaser" in result.data["traits"]


def test_confirm_project_video_does_not_need_platform():
    from actions.chat.confirm_project import missing_create_traits
    assert missing_create_traits(["category:video", "pipeline:video"]) == []
    result = asyncio.run(ConfirmProjectAction().run({
        "name": "TombRaiderComic",
        "traits": ["category:video", "pipeline:video"],
        "description": "AI 漫剧",
        "preset_id": "ai-video",
        "mode": "auto",
    }))
    assert result.success
    assert "platform:web" not in result.data["traits"]


def test_confirm_project_web_app_still_needs_platform():
    from actions.chat.confirm_project import missing_create_traits
    assert "platform:*" in missing_create_traits(["category:app"])
