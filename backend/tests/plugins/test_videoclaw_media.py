"""VideoClaw 单次生图/生视频：sandbox 契约、Windows 路径兜底、准入分流。

全部 mock HTTP 与落盘，不连真实 sidecar、不写真实 works/。
"""
import asyncio
from pathlib import Path

import pytest

from config import settings
from plugins import registry
from plugins.videoclaw import videoclaw_client as vc
from plugins.videoclaw.actions import vc_media
from plugins.videoclaw.actions.vc_media import VCGenImageAction, VCGenVideoAction


def _run(action, ctx):
    return asyncio.run(action.run(ctx))


@pytest.fixture(autouse=True)
def _reset_registry():
    registry.reset_discovery()
    yield
    registry.reset_discovery()


@pytest.fixture
def _enabled(monkeypatch):
    monkeypatch.setattr(settings, "VIDEOCLAW_ENABLED", True)

    async def _ok():
        return True
    async def _cfg():
        return {
            "models": {
                "image_t2i": "seedream-5",
                "image_it2i": "seedream-5",
                "video": "wan2.7-i2v",
            },
            "generation": {"video_ratio": "16:9"},
        }
    async def _trace(context, tool, command, status):
        assert isinstance(command, str)
        return "TCMD-TEST"
    async def _download(rel, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake-media")
        return 10

    monkeypatch.setattr(vc, "health", _ok)
    monkeypatch.setattr(vc, "get_config", _cfg)
    monkeypatch.setattr(vc, "download_product", _download)
    monkeypatch.setattr(vc_media, "_trace", _trace)


# ── 路径归一化（VC Windows bug，sandbox.py:56-73）──────────────────────────

def test_normalize_media_rel_plain():
    assert vc.normalize_media_rel("result/sandbox/videos/a.mp4") == "result/sandbox/videos/a.mp4"


def test_normalize_media_rel_windows_broken_path():
    broken = r"result/G:\Github\AI\VideoClaw\backend\code\result\sandbox\videos\a1b2.mp4"
    assert vc.normalize_media_rel(broken) == "result/sandbox/videos/a1b2.mp4"


def test_normalize_media_rel_absolute_pipeline_path():
    p = r"G:\Github\AI\VideoClaw\backend\code\result\task\T1\final.mp4"
    assert vc.normalize_media_rel(p) == "result/task/T1/final.mp4"


def test_normalize_media_rel_remote_url_untouched():
    u = "https://dashscope.oss/example.mp4"
    assert vc.normalize_media_rel(u) == u


def test_require_success_rejects_http200_failure():
    with pytest.raises(vc.VideoClawError, match="失败"):
        vc._require_success({"success": False, "error": "ARK_API_KEY not set"}, "/api/sandbox/t2i")
    assert vc._require_success({"success": True, "result": []}, "/api/sandbox/t2i")["success"] is True


# ── 注册与命名 ──────────────────────────────────────────────────────────────

def test_actions_registered_and_no_collision():
    names = registry.available_action_names()
    assert {"vc_gen_image", "vc_gen_video", "vc_run_project"} <= set(names)
    # 不能撞 ADS 公共 gen_image 与 director 的 gen_video
    assert "gen_image" in names and "gen_video" in names
    assert len([n for n in names if n == "vc_gen_image"]) == 1


# ── 环境缺失分流（约束 3）──────────────────────────────────────────────────

def test_disabled_returns_blocked(monkeypatch):
    monkeypatch.setattr(settings, "VIDEOCLAW_ENABLED", False)
    for action in (VCGenImageAction(), VCGenVideoAction()):
        r = _run(action, {"prompt": "一只猫"})
        assert r.success is False
        assert r.data["env_missing"] is True
        assert isinstance(r.data["command"], str)
        assert not str(r.to_dict().get("status", "")).endswith("_failed")


def test_health_fail_returns_blocked(_enabled, monkeypatch):
    async def _false():
        return False
    monkeypatch.setattr(vc, "health", _false)
    r = _run(VCGenImageAction(), {"prompt": "一只猫"})
    assert r.success is False and r.data["env_missing"] is True
    assert "不可达" in r.error


def test_empty_prompt_fails_without_calling_vc(_enabled):
    r = _run(VCGenImageAction(), {"prompt": ""})
    assert r.success is False and r.data["env_missing"] is False
    assert "prompt" in r.error


# ── 生图 ────────────────────────────────────────────────────────────────────

def test_gen_image_t2i_success(_enabled, monkeypatch, tmp_path):
    calls = {}

    async def _t2i(*, model, prompt, ratio):
        calls.update(model=model, prompt=prompt, ratio=ratio)
        return {"success": True, "result": ["result/image/default/seedream_1_0.png"], "record_id": "R1"}
    monkeypatch.setattr(vc, "sandbox_t2i", _t2i)

    r = _run(VCGenImageAction(), {
        "prompt": "一只橘猫", "ratio": "1:1", "filename": "cover.png",
        "repo_path": str(tmp_path), "work_slug": "demo",
    })
    assert r.success is True, r.error
    assert calls["model"] == "seedream-5"          # 动态取，不写死
    assert calls["ratio"] == "1:1"
    assert r.data["downloaded"] is True
    assert r.data["filename"] == "cover.png"
    assert r.data["bytes"] == 10
    assert r.data["vc_rel"] == "result/image/default/seedream_1_0.png"
    assert isinstance(r.data["command"], str)
    assert r.data["task_id"] == "TCMD-TEST"
    assert r.to_dict()["status"] == "success"
    assert (tmp_path / "works" / "demo" / "videoclaw" / "image" / "cover.png").exists()


def test_gen_image_i2i_when_reference_given(_enabled, monkeypatch):
    calls = {}

    async def _i2i(*, model, prompt, image, ratio):
        calls.update(model=model, image=image)
        return {"success": True, "result": [r"result/G:\VC\code\result\image\default\x.png"], "record_id": "R2"}
    monkeypatch.setattr(vc, "sandbox_i2i", _i2i)

    r = _run(VCGenImageAction(), {"prompt": "换背景", "reference_image": "https://x/a.png"})
    assert r.success is True, r.error
    assert calls["image"] == "https://x/a.png"
    # Windows 坏路径被归一化，download URL 不会 404
    assert r.data["vc_rel"] == "result/image/default/x.png"
    assert r.data["downloaded"] is False      # 无 repo_path 时只返回 URL


def test_gen_image_vc_failure_is_not_env_missing(_enabled, monkeypatch):
    async def _boom(**kw):
        raise vc.VideoClawError("VC 生图失败: Seedream 429")
    monkeypatch.setattr(vc, "sandbox_t2i", _boom)
    r = _run(VCGenImageAction(), {"prompt": "一只猫"})
    assert r.success is False
    assert r.data["env_missing"] is False
    assert "429" in r.error
    assert isinstance(r.data["command"], str)


def test_gen_image_path_traversal_rejected(_enabled, monkeypatch, tmp_path):
    async def _t2i(**kw):
        return {"success": True, "result": ["result/image/x.png"], "record_id": "R"}
    monkeypatch.setattr(vc, "sandbox_t2i", _t2i)
    r = _run(VCGenImageAction(), {
        "prompt": "x", "filename": "../../evil.png",
        "repo_path": str(tmp_path), "work_slug": "../escape",
    })
    assert r.success is True
    assert r.data["filename"] == "vc_media.png"   # 非法名回退默认
    assert "/.." not in r.data["path"]
    assert not (tmp_path / "works" / "escape").exists()  # slug 被回退成 videoclaw


# ── 生视频 ──────────────────────────────────────────────────────────────────

def test_gen_video_with_explicit_image(_enabled, monkeypatch, tmp_path):
    calls = {}

    async def _video(*, model, prompt, image, ratio, resolution, duration):
        calls.update(model=model, image=image, duration=duration)
        return {
            "success": True,
            "result": "https://dashscope.oss/expire.mp4",   # 远端过期 URL，不能用
            "video_path": "result/sandbox/videos/a1b2.mp4",
            "record_id": "R3",
        }
    monkeypatch.setattr(vc, "sandbox_video", _video)

    r = _run(VCGenVideoAction(), {
        "prompt": "镜头推进", "image": "https://x/frame.png", "duration": 5,
        "filename": "clip01.mp4", "repo_path": str(tmp_path), "work_slug": "demo",
    })
    assert r.success is True, r.error
    assert calls["model"] == "wan2.7-i2v"
    assert calls["image"] == "https://x/frame.png"
    assert calls["duration"] == 5
    assert r.data["auto_first_frame"] == ""       # 显式给了图，不自动 t2i
    assert r.data["vc_rel"] == "result/sandbox/videos/a1b2.mp4"
    assert "expire" not in r.data["url"]           # 用 video_path 而非 result
    assert r.data["downloaded"] is True
    assert (tmp_path / "works" / "demo" / "videoclaw" / "video" / "clip01.mp4").exists()


def test_gen_video_auto_first_frame(_enabled, monkeypatch):
    calls = {}

    async def _t2i(*, model, prompt, ratio):
        calls["t2i"] = True
        return {"success": True, "result": [r"result/G:\VC\code\result\image\default\f.png"], "record_id": "F"}
    async def _video(*, model, prompt, image, ratio, resolution, duration):
        calls["image"] = image
        return {"success": True, "result": "https://x/e.mp4",
                "video_path": "result/sandbox/videos/v.mp4", "record_id": "V"}
    monkeypatch.setattr(vc, "sandbox_t2i", _t2i)
    monkeypatch.setattr(vc, "sandbox_video", _video)

    r = _run(VCGenVideoAction(), {"prompt": "一只猫在跑"})
    assert r.success is True, r.error
    assert calls.get("t2i") is True
    assert calls["image"].endswith("/code/result/image/default/f.png")  # 归一化后拼回 URL
    assert r.data["auto_first_frame"] == "result/image/default/f.png"
    assert r.to_dict()["status"] == "success"


def test_gen_video_uses_long_timeout(_enabled, monkeypatch):
    seen = {}

    async def _call(method, path, body=None, timeout=None):
        seen["timeout"] = timeout
        return {"success": True, "video_path": "result/sandbox/videos/v.mp4", "record_id": "V"}
    monkeypatch.setattr(vc, "_call", _call)

    r = _run(VCGenVideoAction(), {"prompt": "x", "image": "https://x/f.png"})
    assert r.success is True, r.error
    assert seen["timeout"] == float(settings.VIDEOCLAW_VIDEO_TIMEOUT)
    assert seen["timeout"] > float(settings.VIDEOCLAW_TIMEOUT)


def test_gen_video_vc_failure_is_not_env_missing(_enabled, monkeypatch):
    async def _boom(**kw):
        raise vc.VideoClawError("VC 生视频失败: 首帧图缺失")
    monkeypatch.setattr(vc, "sandbox_video", _boom)
    r = _run(VCGenVideoAction(), {"prompt": "x", "image": "https://x/f.png"})
    assert r.success is False
    assert r.data["env_missing"] is False
    assert isinstance(r.data["command"], str)
    assert r.data["task_id"] == "TCMD-TEST"
