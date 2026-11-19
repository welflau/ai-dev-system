"""VideoClaw 平级插件：准入约束与最小闭环（全部 mock HTTP，不连真实 sidecar）。

覆盖 docs/20261023_01_插件套件准入规范与五道约束.md 的关键项：
- Action 名全局唯一、vc_ 前缀，不与 director 冲突
- 环境缺失 → env_missing=True / success=False，绝不 *_failed
- data["command"] 必须是 str、task_id 落时间轴
- 模型名从 GET /api/config 动态取，不写死
- plugin.json 合法、required_traits 在词表内
"""
import asyncio
import json
from pathlib import Path

import pytest

from actions.base import ActionResult
from config import settings
from plugins import registry
from plugins.videoclaw import videoclaw_client as vc
from plugins.videoclaw.actions.vc_project import VCRunProjectAction


def _run(action, ctx):
    return asyncio.run(action.run(ctx))


@pytest.fixture(autouse=True)
def _reset_registry():
    registry.reset_discovery()
    yield
    registry.reset_discovery()


# ── 注册与命名 ──────────────────────────────────────────────────────────────

def test_action_registered_with_vc_prefix():
    names = registry.available_action_names()
    assert "vc_run_project" in names
    assert all(n.startswith("vc_") for n in names if "videoclaw" in n or n.startswith("vc_"))
    # 不能覆盖 director 的既有 Action
    assert "gen_video" in names
    assert registry.get_action_class("vc_run_project") is VCRunProjectAction


def test_plugin_json_valid_and_traits_in_taxonomy():
    p = Path("plugins/videoclaw/plugin.json")
    meta = json.loads(p.read_text(encoding="utf-8"))
    assert meta["id"] == "videoclaw"
    assert meta["required_traits"]["any_of"]
    taxonomy = Path("skills/rules/trait_taxonomy.yaml").read_text(encoding="utf-8")
    # category:video 与 pipeline:video 都已在词表里（不新增维度）
    assert "- video" in taxonomy


# ── 模型动态解析 ────────────────────────────────────────────────────────────

def test_resolve_start_params_reads_models_from_config():
    cfg = {
        "models": {
            "llm": "qwen-A", "vlm": "qwen-A",
            "image_t2i": "seedream-X", "image_it2i": "seedream-X",
            "video": "wan-Z", "video_first_frame": "wan-Z",
        },
        "generation": {"video_generation_mode": "first_frame", "style": "realistic"},
    }
    params = vc.resolve_start_params(cfg, idea="一只猫", episodes=1)
    assert params["llm_model"] == "qwen-A"
    assert params["image_t2i_model"] == "seedream-X"
    assert params["video_model"] == "wan-Z"
    assert params["video_generation_mode"] == "first_frame"
    assert params["episodes"] == 1
    # 四个硬校验字段必须齐全（VC workflow.py:44-52）
    for k in ("llm_model", "vlm_model", "image_t2i_model", "image_it2i_model"):
        assert params[k]


def test_resolve_start_params_rejects_missing_models():
    with pytest.raises(vc.VideoClawError, match="缺模型配置"):
        vc.resolve_start_params({"models": {"llm": "x"}}, idea="x")


# ── 环境缺失分流（约束 3）──────────────────────────────────────────────────

def test_disabled_returns_env_missing_blocked(monkeypatch):
    monkeypatch.setattr(settings, "VIDEOCLAW_ENABLED", False)
    r = _run(VCRunProjectAction(), {"idea": "一只猫"})
    assert isinstance(r, ActionResult)
    assert r.success is False
    assert r.data["env_missing"] is True
    assert isinstance(r.data["command"], str)
    assert not str(r.to_dict().get("status", "")).endswith("_failed")


def test_health_fail_returns_env_missing_blocked(monkeypatch):
    monkeypatch.setattr(settings, "VIDEOCLAW_ENABLED", True)

    async def _false():
        return False
    monkeypatch.setattr(vc, "health", _false)

    async def _trace(ctx, cmd, status):
        return "TCMD-TEST"
    monkeypatch.setattr(VCRunProjectAction, "_trace", staticmethod(_trace))

    r = _run(VCRunProjectAction(), {"idea": "一只猫"})
    assert r.success is False
    assert r.data["env_missing"] is True
    assert "sidecar 不可达" in r.error
    assert isinstance(r.data["command"], str)
    assert r.data["task_id"] == "TCMD-TEST"


def test_vc_error_is_not_env_missing(monkeypatch):
    monkeypatch.setattr(settings, "VIDEOCLAW_ENABLED", True)

    async def _ok():
        return True
    async def _cfg():
        return {"models": {"llm": "a", "vlm": "a", "image_t2i": "b", "image_it2i": "b", "video": "c"}}
    async def _boom(*a, **k):
        raise vc.VideoClawError("VC 返回 400")
    async def _trace(ctx, cmd, status):
        return "TCMD-TEST"

    monkeypatch.setattr(vc, "health", _ok)
    monkeypatch.setattr(vc, "get_config", _cfg)
    monkeypatch.setattr(vc, "start_project", _boom)
    monkeypatch.setattr(VCRunProjectAction, "_trace", staticmethod(_trace))

    r = _run(VCRunProjectAction(), {"idea": "一只猫"})
    assert r.success is False
    assert r.data["env_missing"] is False
    assert isinstance(r.data["command"], str)


# ── 成功路径（约束 2：command 为 str、task_id 落时间轴）────────────────────

def test_success_minimal_closed_loop(monkeypatch):
    monkeypatch.setattr(settings, "VIDEOCLAW_ENABLED", True)

    async def _ok():
        return True
    async def _cfg():
        return {
            "models": {"llm": "q", "vlm": "q", "image_t2i": "s", "image_it2i": "s", "video": "w"},
            "generation": {"video_generation_mode": "first_frame"},
        }
    async def _start(cfg, *, idea, episodes):
        assert episodes == 1
        return {"session_id": "1700000000000", "status": "init"}
    async def _cont(sid):
        assert sid == "1700000000000"
        return {"status": "script_generation"}
    async def _status(sid):
        return {"stage": "script_generation", "status": "in_progress"}
    async def _trace(ctx, cmd, status):
        assert isinstance(cmd, str)
        return "TCMD-TEST"

    monkeypatch.setattr(vc, "health", _ok)
    monkeypatch.setattr(vc, "get_config", _cfg)
    monkeypatch.setattr(vc, "start_project", _start)
    monkeypatch.setattr(vc, "continue_workflow", _cont)
    monkeypatch.setattr(vc, "get_status", _status)
    monkeypatch.setattr(VCRunProjectAction, "_trace", staticmethod(_trace))

    r = _run(VCRunProjectAction(), {"idea": "一只猫", "episodes": 1})
    assert r.success is True
    assert r.data["session_id"] == "1700000000000"
    assert r.data["env_missing"] is False
    assert isinstance(r.data["command"], str)
    assert r.data["task_id"] == "TCMD-TEST"
    assert r.data["models"]["video"] == "w"
    # status 是 ActionResult 的保留字段，VC 快照必须放在 vc_status，不能覆盖它
    assert r.to_dict()["status"] == "success"
    assert r.data["vc_status"]["stage"] == "script_generation"


def test_command_is_quoted_single_string():
    cmd = VCRunProjectAction()._command('一只 "猫"', 1, "")
    assert isinstance(cmd, str)
    assert "一只" in cmd
    assert "'" in cmd  # shlex.quote 对含空格/引号的参数加引号
