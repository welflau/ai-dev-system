"""系统公共云端生视频层（backend/cloud_video/）单测。

全部 mock `_call` / `download`，不打真实 runlive.top、不花钱、不写真实 works/。
覆盖：配置分流、参数归一化、multipart、上游错误映射、重试、轮询终止、一站式编排。
"""
import asyncio
from pathlib import Path

import pytest

from config import settings
from cloud_video import client as cv


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def _enabled(monkeypatch):
    monkeypatch.setattr(settings, "MINIMAX_H3_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MINIMAX_H3_CARD_KEY", "sk-test", raising=False)
    monkeypatch.setattr(settings, "MINIMAX_H3_BASE_URL", "https://www.runlive.top/mnmx", raising=False)
    monkeypatch.setattr(settings, "MINIMAX_H3_TIMEOUT", 120, raising=False)
    monkeypatch.setattr(settings, "MINIMAX_H3_POLL_INTERVAL", 5, raising=False)
    monkeypatch.setattr(settings, "MINIMAX_H3_MAX_POLLS", 180, raising=False)


@pytest.fixture
def _no_sleep(monkeypatch):
    async def _fast(_s):
        return None
    monkeypatch.setattr(cv.asyncio, "sleep", _fast)


# ── 配置与异常分层 ──────────────────────────────────────────────────────────

def test_disabled_is_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "MINIMAX_H3_ENABLED", False, raising=False)
    with pytest.raises(cv.CloudVideoUnavailable, match="未启用"):
        _run(cv.submit(prompt="x"))


def test_missing_key_is_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "MINIMAX_H3_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MINIMAX_H3_CARD_KEY", "", raising=False)
    with pytest.raises(cv.CloudVideoUnavailable, match="CARD_KEY"):
        _run(cv.submit(prompt="x"))


def test_ping_without_key_returns_false(monkeypatch):
    monkeypatch.setattr(settings, "MINIMAX_H3_ENABLED", False, raising=False)
    assert _run(cv.ping()) is False


def test_provider_registry_marks_third_party():
    p = cv.PROVIDERS["minimax_h3"]
    assert p["auth_header"] == "X-Card-Key"
    assert "非 MiniMax 官方" in p["note"]


# ── 参数归一化（鼠鼠文档 :33-83）────────────────────────────────────────────

def test_normalize_defaults():
    p = cv._normalize_params(task_name=cv.TASK_T2V, resolution=None, duration=None,
                             aspect_ratio=None, has_last_frame=False)
    assert p == {"task_name": "minimax_h3_v2", "resolution": "1", "duration": "5",
                 "aspect_ratio": "16:9 (Widescreen)"}


def test_normalize_clamps_duration_and_resolution():
    p = cv._normalize_params(task_name=cv.TASK_T2V, resolution="2", duration=99,
                             aspect_ratio="9:16 (Portrait Widescreen)", has_last_frame=False)
    assert p["duration"] == "15"
    assert p["resolution"] == "2"
    assert p["aspect_ratio"] == "9:16 (Portrait Widescreen)"


def test_normalize_multi_ref_no_1080p():
    p = cv._normalize_params(task_name=cv.TASK_MULTI_REF, resolution="2", duration=5,
                             aspect_ratio=None, has_last_frame=False)
    assert p["resolution"] == "1"


def test_normalize_first_last_frame_1080p_max_10s():
    p = cv._normalize_params(task_name=cv.TASK_T2V, resolution="2", duration=15,
                             aspect_ratio=None, has_last_frame=True)
    assert p["duration"] == "10"


def test_normalize_bad_ratio_falls_back():
    p = cv._normalize_params(task_name=cv.TASK_T2V, resolution="x", duration=2,
                             aspect_ratio="16:9", has_last_frame=False)
    assert p["resolution"] == "1" and p["duration"] == "4"
    assert p["aspect_ratio"] == "16:9 (Widescreen)"


def test_normalize_rejects_unknown_task():
    with pytest.raises(cv.CloudVideoError, match="task_name"):
        cv._normalize_params(task_name="T2V-01", resolution="1", duration=5,
                             aspect_ratio=None, has_last_frame=False)


# ── multipart ───────────────────────────────────────────────────────────────

def test_multipart_fields_and_files():
    body, boundary = cv._encode_multipart(
        {"task_name": "minimax_h3_v2", "prompt": "猫", "resolution": "1"},
        [cv.CloudVideoFile("first_frame", "f.jpg", "image/jpeg", b"\xff\xd8\xff")],
    )
    assert boundary and body.startswith(b"--")
    assert b'name="task_name"' in body and "猫".encode() in body
    assert b'name="first_frame"' in body and b'filename="f.jpg"' in body
    assert b"image/jpeg" in body and b"\xff\xd8\xff" in body
    assert body.rstrip().endswith(b"--")


def test_file_from_path_missing():
    with pytest.raises(cv.CloudVideoError, match="不存在"):
        cv.CloudVideoFile.from_path("first_frame", "/no/such/file.png")


def test_file_from_path(tmp_path):
    p = tmp_path / "frame.png"
    p.write_bytes(b"PNG")
    f = cv.CloudVideoFile.from_path("first_frame", p)
    assert f.field == "first_frame" and f.data == b"PNG" and "image/png" in f.mime


# ── 提交 / 查询 / 直链 ──────────────────────────────────────────────────────

def test_submit_returns_task_id(_enabled, monkeypatch):
    seen = {}

    async def _call(method, path, *, key, fields=None, files=None, timeout=None):
        seen.update(method=method, path=path, key=key, fields=fields, files=files)
        return {"success": True, "data": {"task_id": "T1", "status": "queued", "credit_cost": 25}}
    monkeypatch.setattr(cv, "_call", _call)

    r = _run(cv.submit(prompt="一只猫", duration=6))
    assert r["task_id"] == "T1" and r["credit_cost"] == 25
    assert seen["key"] == "sk-test" and seen["method"] == "POST"
    assert seen["fields"]["duration"] == "6"
    assert seen["fields"]["task_name"] == "minimax_h3_v2"


def test_submit_empty_prompt(_enabled):
    with pytest.raises(cv.CloudVideoError, match="prompt"):
        _run(cv.submit(prompt=""))


def test_submit_missing_task_id_is_error(_enabled, monkeypatch):
    async def _call(**kw):
        return {"success": True, "data": {}}
    monkeypatch.setattr(cv, "_call", _call)
    with pytest.raises(cv.CloudVideoError, match="task_id"):
        _run(cv.submit(prompt="x"))


def test_submit_retries_429(_enabled, monkeypatch, _no_sleep):
    calls = {"n": 0}

    async def _call(**kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise cv.CloudVideoError("鼠鼠工具 HTTP 429: 限速")
        return {"success": True, "data": {"task_id": "T2", "status": "queued"}}
    monkeypatch.setattr(cv, "_call", _call)
    r = _run(cv.submit(prompt="x", retries=3))
    assert r["task_id"] == "T2" and calls["n"] == 3


def test_submit_402_no_retry(_enabled, monkeypatch, _no_sleep):
    calls = {"n": 0}

    async def _call(**kw):
        calls["n"] += 1
        raise cv.CloudVideoError("鼠鼠工具 HTTP 402: 积分不足")
    monkeypatch.setattr(cv, "_call", _call)
    with pytest.raises(cv.CloudVideoError, match="402"):
        _run(cv.submit(prompt="x", retries=3))
    assert calls["n"] == 1     # 非重试码立即抛


def test_query_returns_data_block(_enabled, monkeypatch):
    async def _call(**kw):
        assert kw["path"] == "/api/v1/tasks/T1"
        return {"success": True, "data": {"status": "processing", "queue_position": 2}}
    monkeypatch.setattr(cv, "_call", _call)
    assert _run(cv.query("T1"))["status"] == "processing"


def test_file_url_requires_url(_enabled, monkeypatch):
    async def _call(**kw):
        return {"success": True, "data": {"filename": "x.mp4"}}
    monkeypatch.setattr(cv, "_call", _call)
    with pytest.raises(cv.CloudVideoError, match="下载地址"):
        _run(cv.file_url("T1"))


# ── 底层 HTTP 错误映射（_request）───────────────────────────────────────────

def test_request_403_is_unavailable(_enabled, monkeypatch):
    import urllib.error
    import io

    def _urlopen(req, timeout=None):
        body = '{"detail":"卡未放行"}'.encode("utf-8")
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(body))
    monkeypatch.setattr(cv.urllib.request, "urlopen", _urlopen)
    with pytest.raises(cv.CloudVideoUnavailable, match="未放行"):
        cv._request("GET", "/api/v1/tasks/x", key="sk-test")


def test_request_400_is_error(_enabled, monkeypatch):
    import urllib.error
    import io

    def _urlopen(req, timeout=None):
        body = '{"detail":"参数错误"}'.encode("utf-8")
        raise urllib.error.HTTPError(req.full_url, 400, "Bad", {}, io.BytesIO(body))
    monkeypatch.setattr(cv.urllib.request, "urlopen", _urlopen)
    with pytest.raises(cv.CloudVideoError, match="参数错误"):
        cv._request("POST", "/api/v1/tasks", key="sk-test", fields={"prompt": "x"})


def test_request_success_false_is_error(_enabled, monkeypatch):
    class _Resp:
        def read(self):
            return '{"success": false, "error": "worker 未受理"}'.encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
    monkeypatch.setattr(cv.urllib.request, "urlopen", lambda req, timeout=None: _Resp())
    with pytest.raises(cv.CloudVideoError, match="worker"):
        cv._request("GET", "/api/v1/tasks/x", key="sk-test")


# ── ping ────────────────────────────────────────────────────────────────────

def test_ping_403_returns_false(_enabled, monkeypatch):
    async def _call(**kw):
        raise cv.CloudVideoUnavailable("卡密钥无效/未放行（HTTP 403）")
    monkeypatch.setattr(cv, "_call", _call)
    assert _run(cv.ping()) is False


def test_ping_404_returns_true(_enabled, monkeypatch):
    async def _call(**kw):
        raise cv.CloudVideoError("鼠鼠工具 HTTP 404: 任务不存在")
    monkeypatch.setattr(cv, "_call", _call)
    assert _run(cv.ping()) is True


# ── 一站式编排 ──────────────────────────────────────────────────────────────

def test_generate_video_completed(_enabled, monkeypatch, _no_sleep, tmp_path):
    states = iter([
        {"status": "queued"}, {"status": "processing"}, {"status": "completed"},
    ])

    async def _call(method, path, *, key, fields=None, files=None, timeout=None):
        if method == "POST":
            return {"success": True, "data": {"task_id": "T3", "status": "queued", "credit_cost": 30}}
        if path.endswith("/file-url"):
            return {"success": True, "data": {"url": "https://cdn/x.mp4", "filename": "x.mp4"}}
        return {"success": True, "data": next(states)}
    monkeypatch.setattr(cv, "_call", _call)

    async def _dl(url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"MP4")
        return 3
    monkeypatch.setattr(cv, "download", _dl)

    dest = tmp_path / "clip.mp4"
    r = _run(cv.generate_video(prompt="一只猫", dest=dest))
    assert r["task_id"] == "T3" and r["url"] == "https://cdn/x.mp4"
    assert r["downloaded"] is True and r["bytes"] == 3
    assert r["status"] == "completed"


def test_generate_video_failed_state(_enabled, monkeypatch, _no_sleep):
    async def _call(method, path, *, key, fields=None, files=None, timeout=None):
        if method == "POST":
            return {"success": True, "data": {"task_id": "T4", "status": "queued"}}
        return {"success": True, "data": {"status": "failed", "error": "Workflow returned no output"}}
    monkeypatch.setattr(cv, "_call", _call)
    with pytest.raises(cv.CloudVideoError, match="no output"):
        _run(cv.generate_video(prompt="x"))


def test_generate_video_poll_timeout(_enabled, monkeypatch, _no_sleep):
    monkeypatch.setattr(settings, "MINIMAX_H3_MAX_POLLS", 2, raising=False)

    async def _call(method, path, *, key, fields=None, files=None, timeout=None):
        if method == "POST":
            return {"success": True, "data": {"task_id": "T5", "status": "queued"}}
        return {"success": True, "data": {"status": "processing"}}
    monkeypatch.setattr(cv, "_call", _call)
    with pytest.raises(cv.CloudVideoError, match="轮询超时") as e:
        _run(cv.generate_video(prompt="x"))
    assert "T5" in str(e.value)     # 保留 task_id 供后续自行查
