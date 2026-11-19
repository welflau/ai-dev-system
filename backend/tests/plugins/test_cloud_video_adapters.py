"""director / videoclaw 适配系统公共云端层（新增可选后端）+ 公共层 dispatch。

覆盖：
- 后端真源单一化（ALLOWED_BACKENDS 派生自 cloud_video.ALLOWED_PROVIDERS）
- director gen_video backend=minimax_h3 走 cloud_video；原有 lightai/CLI 分支不变
- videoclaw vc_gen_video provider=minimax_h3 走 cloud_video；VC sandbox 路径不变
- 公共层 dispatch / probe / normalize / lightai shim
- 环境缺失 → env_missing/blocked，绝不 *_failed

全部 mock，不联网、不写真实 works/。
"""
import asyncio
from pathlib import Path

import pytest

from config import settings
from plugins import registry
from plugins.director.backends import ALLOWED_BACKENDS, normalize_backend, probe_backend
from cloud_video import (
    ALLOWED_PROVIDERS,
    CloudVideoError,
    CloudVideoUnavailable,
    normalize_provider,
    probe_provider,
)
from cloud_video import client as cv_client


def _run(action, ctx):
    return asyncio.run(action.run(ctx))


@pytest.fixture(autouse=True)
def _reset_registry():
    registry.reset_discovery()
    yield
    registry.reset_discovery()


@pytest.fixture
def _h3_enabled(monkeypatch):
    monkeypatch.setattr(settings, "MINIMAX_H3_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MINIMAX_H3_CARD_KEY", "sk-test", raising=False)


# ── 单一真源 ────────────────────────────────────────────────────────────────

def test_backend_truth_single_source():
    # 所有云端 provider 都在 director 的 ALLOWED_BACKENDS 里
    assert set(ALLOWED_PROVIDERS) <= set(ALLOWED_BACKENDS)
    # CLI 后端仍保留
    assert {"libtv", "dreamina"} <= set(ALLOWED_BACKENDS)
    # gen_video.py 不再自己维护一份 _BACKENDS 字面量
    src = Path("plugins/director/actions/gen_video.py").read_text(encoding="utf-8")
    assert '_BACKENDS = ("lightai"' not in src
    assert "ALLOWED_BACKENDS as _BACKENDS" in src


def test_normalize_provider_aliases():
    for raw in ("minimax", "h3", "mnmx", "鼠鼠", "minimax_h3"):
        assert normalize_provider(raw) == "minimax_h3"
    for raw in ("kling", "lightai", "可灵"):
        assert normalize_provider(raw) == "lightai"
    assert normalize_backend("minimax") == "minimax_h3"


def test_probe_provider_lightai(monkeypatch):
    monkeypatch.setattr(settings, "LIGHTAI_API_KEY", "k", raising=False)
    assert probe_provider("lightai")["available"] is True
    monkeypatch.setattr(settings, "LIGHTAI_API_KEY", "", raising=False)
    assert probe_provider("lightai")["available"] is False


def test_probe_provider_h3(monkeypatch):
    monkeypatch.setattr(settings, "MINIMAX_H3_CARD_KEY", "sk", raising=False)
    monkeypatch.setattr(settings, "MINIMAX_H3_ENABLED", False, raising=False)
    assert probe_provider("minimax_h3")["available"] is False
    monkeypatch.setattr(settings, "MINIMAX_H3_ENABLED", True, raising=False)
    assert probe_provider("minimax_h3")["available"] is True


def test_probe_backend_delegates_to_public_layer(_h3_enabled):
    pr = probe_backend("minimax_h3")
    assert pr.available is True and pr.backend == "minimax_h3"


def test_lightai_shim_reexports_public_impl():
    import plugins.director.lightai_video as shim
    from cloud_video import lightai as pub
    assert shim.create_and_poll_video is pub.create_and_poll_video
    assert shim.download_url is pub.download_url
    assert shim.resolve_media_url is pub.resolve_media_url
    assert shim._as_list is pub._as_list


# ── 公共层统一 dispatch ─────────────────────────────────────────────────────

def test_dispatch_minimax_h3(_h3_enabled, monkeypatch, tmp_path):
    seen = {}

    async def _fake(**kw):
        seen.update(kw)
        return {"task_id": "T1", "url": "https://cdn/x.mp4", "downloaded": False}
    monkeypatch.setattr(cv_client, "generate_video", _fake)

    r = asyncio.run(cv_client.generate_video_with_provider(
        "minimax", prompt="一只猫", dest=tmp_path / "a.mp4",
        duration=6, aspect_ratio="9:16 (Portrait Widescreen)", resolution="2",
    ))
    assert r["provider"] == "minimax_h3" and r["task_id"] == "T1"
    assert seen["prompt"] == "一只猫" and seen["duration"] == 6
    assert seen["resolution"] == "2"


def test_dispatch_lightai(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "LIGHTAI_API_KEY", "k", raising=False)
    import cloud_video.lightai as la
    seen = {}

    async def _fake(req, dest):
        seen.update(req=req, dest=dest)
        return {"provider": "lightai", "task_id": "L1", "url": "https://cdn/y.mp4",
                "downloaded": False}
    monkeypatch.setattr(la, "generate", _fake)

    r = asyncio.run(cv_client.generate_video_with_provider(
        "kling", prompt="一只猫", dest=tmp_path / "b.mp4",
        lightai_req={"prompt": "覆盖用", "duration": 10},
    ))
    assert r["provider"] == "lightai"
    assert seen["req"]["prompt"] == "覆盖用"   # lightai_req 优先
    assert seen["req"]["duration"] == 10


def test_dispatch_missing_key_is_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "MINIMAX_H3_CARD_KEY", "", raising=False)
    monkeypatch.setattr(settings, "MINIMAX_H3_ENABLED", True, raising=False)
    with pytest.raises(CloudVideoUnavailable, match="CARD_KEY"):
        asyncio.run(cv_client.generate_video_with_provider("minimax_h3", prompt="x"))


def test_dispatch_unknown_provider():
    with pytest.raises(CloudVideoUnavailable, match="未知"):
        asyncio.run(cv_client.generate_video_with_provider("bogus", prompt="x"))


# ── director gen_video 新后端 ───────────────────────────────────────────────

def test_director_h3_backend_uses_public_layer(_h3_enabled, monkeypatch, tmp_path):
    from plugins.director.actions.gen_video import GenVideoAction
    import cloud_video.client as cvc
    seen = {}

    async def _fake(provider, **kw):
        seen.update(provider=provider, **kw)
        dest = kw["dest"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"MP4")
        return {"provider": "minimax_h3", "task_id": "T9", "url": "https://cdn/z.mp4",
                "downloaded": True, "path": str(dest), "bytes": 3}

    async def _trace(ctx, cmd, cwd, status):
        return "TCMD-DIR"
    monkeypatch.setattr(cvc, "generate_video_with_provider", _fake)
    monkeypatch.setattr(GenVideoAction, "_trace", staticmethod(_trace))

    # 用 init_work_package 建出 works/<slug>/video/
    init = registry.create_action("init_work_package")
    pack = asyncio.run(init.run({"repo_path": str(tmp_path), "title": "t"}))
    slug = pack.data["slug"]

    r = _run(GenVideoAction(), {
        "repo_path": str(tmp_path), "work_slug": slug,
        "prompt": "一只猫", "filename": "片段01.mp4",
        "backend": "minimax_h3", "duration": 8, "resolution": "720p",
    })
    assert r.success is True, r.error
    assert seen["provider"] == "minimax_h3"
    assert seen["duration"] == 8
    assert r.data["backend"] == "minimax_h3"
    assert isinstance(r.data["command"], str)
    assert r.data["task_id"] == "TCMD-DIR"
    assert (tmp_path / "works" / slug / "video" / "片段01.mp4").is_file()


def test_director_h3_missing_key_blocked(monkeypatch, tmp_path):
    from plugins.director.actions.gen_video import GenVideoAction
    monkeypatch.setattr(settings, "MINIMAX_H3_CARD_KEY", "", raising=False)
    monkeypatch.setattr(settings, "MINIMAX_H3_ENABLED", True, raising=False)
    init = registry.create_action("init_work_package")
    pack = asyncio.run(init.run({"repo_path": str(tmp_path), "title": "t"}))
    slug = pack.data["slug"]
    r = _run(GenVideoAction(), {
        "repo_path": str(tmp_path), "work_slug": slug,
        "prompt": "x", "filename": "片段01.mp4", "backend": "minimax_h3",
    })
    assert r.success is False
    assert r.data["env_missing"] is True
    assert isinstance(r.data["command"], str)


def test_director_unknown_backend_still_rejected(tmp_path):
    from plugins.director.actions.gen_video import GenVideoAction
    init = registry.create_action("init_work_package")
    pack = asyncio.run(init.run({"repo_path": str(tmp_path), "title": "t"}))
    slug = pack.data["slug"]
    r = _run(GenVideoAction(), {
        "repo_path": str(tmp_path), "work_slug": slug,
        "prompt": "x", "filename": "片段01.mp4", "backend": "bogus",
    })
    assert r.success is False and "未知后端" in r.error


def test_director_lightai_branch_unchanged(tmp_path, monkeypatch):
    """原有 lightai 分支行为不变（monkeypatch 目标仍是 plugins.director.lightai_video）。"""
    from plugins.director.actions.gen_video import GenVideoAction
    monkeypatch.setattr(settings, "LIGHTAI_API_KEY", "test-key", raising=False)

    async def fake_create(req):
        return "tid-video", "https://cdn.example/clip.mp4", ""

    async def fake_dl(url, dest):
        dest.write_bytes(b"fake-mp4")
        return True, ""
    monkeypatch.setattr("plugins.director.lightai_video.create_and_poll_video", fake_create)
    monkeypatch.setattr("plugins.director.lightai_video.download_url", fake_dl)

    init = registry.create_action("init_work_package")
    pack = asyncio.run(init.run({"repo_path": str(tmp_path), "title": "t"}))
    slug = pack.data["slug"]
    r = _run(GenVideoAction(), {
        "repo_path": str(tmp_path), "work_slug": slug,
        "prompt": "一只猫", "filename": "片段01.mp4",
    })
    assert r.success is True, r.error
    assert (tmp_path / "works" / slug / "video" / "片段01.mp4").is_file()


# ── videoclaw vc_gen_video 可选 provider ────────────────────────────────────

def test_videoclaw_provider_uses_public_layer(_h3_enabled, monkeypatch, tmp_path):
    from plugins.videoclaw.actions import vc_media
    import cloud_video.client as cvc
    seen = {}

    async def _fake(provider, **kw):
        seen.update(provider=provider, **kw)
        dest = kw["dest"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"MP4")
        return {"provider": "minimax_h3", "task_id": "T7", "url": "https://cdn/w.mp4",
                "downloaded": True, "path": str(dest), "bytes": 3}

    async def _trace(ctx, tool, cmd, status):
        return "TCMD-VC"
    monkeypatch.setattr(cvc, "generate_video_with_provider", _fake)
    monkeypatch.setattr(vc_media, "_trace", _trace)

    r = _run(vc_media.VCGenVideoAction(), {
        "repo_path": str(tmp_path), "work_slug": "demo",
        "prompt": "一只猫", "filename": "clip01.mp4",
        "provider": "minimax_h3", "duration": 6,
    })
    assert r.success is True, r.error
    assert seen["provider"] == "minimax_h3" and seen["duration"] == 6
    assert r.data["provider"] == "minimax_h3"
    assert isinstance(r.data["command"], str)
    assert r.data["env_missing"] is False
    assert (tmp_path / "works" / "demo" / "videoclaw" / "video" / "clip01.mp4").is_file()


def test_videoclaw_provider_does_not_need_vc_sidecar(_h3_enabled, monkeypatch, tmp_path):
    """指定 provider 时不应触发 VC health（VC 未启用也能用云端）。"""
    from plugins.videoclaw.actions import vc_media
    import cloud_video.client as cvc
    monkeypatch.setattr(settings, "VIDEOCLAW_ENABLED", False, raising=False)

    async def _fake(provider, **kw):
        return {"provider": "minimax_h3", "task_id": "T", "url": "u", "downloaded": False}
    async def _trace(ctx, tool, cmd, status):
        return "TCMD"
    monkeypatch.setattr(cvc, "generate_video_with_provider", _fake)
    monkeypatch.setattr(vc_media, "_trace", _trace)

    r = _run(vc_media.VCGenVideoAction(), {
        "prompt": "一只猫", "provider": "minimax_h3",
    })
    assert r.success is True, r.error


def test_videoclaw_provider_missing_key_blocked(monkeypatch):
    from plugins.videoclaw.actions import vc_media
    monkeypatch.setattr(settings, "MINIMAX_H3_CARD_KEY", "", raising=False)
    monkeypatch.setattr(settings, "MINIMAX_H3_ENABLED", True, raising=False)
    async def _trace(ctx, tool, cmd, status):
        return "TCMD"
    monkeypatch.setattr(vc_media, "_trace", _trace)
    r = _run(vc_media.VCGenVideoAction(), {"prompt": "x", "provider": "minimax_h3"})
    assert r.success is False and r.data["env_missing"] is True


def test_videoclaw_default_path_still_uses_vc_sandbox(monkeypatch):
    """未给 provider 时仍走原 VC sandbox（_prepare 会被调用）。"""
    from plugins.videoclaw.actions import vc_media
    seen = {}

    async def _prepare(ctx, tool, command):
        seen["called"] = True
        return None, None, "", "BLOCKED_SENTINEL"
    monkeypatch.setattr(vc_media, "_prepare", _prepare)
    r = _run(vc_media.VCGenVideoAction(), {"prompt": "x"})
    assert seen.get("called") is True
    assert r == "BLOCKED_SENTINEL"
