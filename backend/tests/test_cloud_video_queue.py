"""系统公共云端生视频：生成任务排队（时段感知 FIFO 信号量）单测。

参考 ComicAI frontend/src/api/index.ts:2551-2582，验证 ADS 服务端实现：
- 闲时 5 并发、白天不限、时区显式可配（不用服务器本地时区）
- FIFO 排队、名额覆盖提交+轮询全程、finally 必释放
- 取消即时唤醒、等待超时→CloudVideoUnavailable（不静默换后端）
- stats 可观测、统一 dispatch 层接入（两 provider 共用、无双重占用）

全部纯内存 + mock，不联网、不写真实文件。
"""
import asyncio
from datetime import datetime, timezone

import pytest

from config import settings
from cloud_video import client as cvc
from cloud_video.client import CloudVideoUnavailable
from cloud_video.queue import CloudVideoQueue, build_queue_from_settings, _resolve_tz


def _run(coro):
    return asyncio.run(coro)


async def _gather(n, factory):
    """在 loop 内 gather（Python 3.14 不允许在 asyncio.run 之外创建 gather 的协程）。"""
    return await asyncio.gather(*[factory(i) for i in range(n)])


class _FixedIdle(CloudVideoQueue):
    """测试用：无视当前时间，固定闲时上限。"""
    def limit_now(self, now=None):
        return self.idle_limit if self.enabled else 0


class _FixedUnlimited(CloudVideoQueue):
    def limit_now(self, now=None):
        return 0


# ── 时段 / 时区 ─────────────────────────────────────────────────────────────

def test_idle_window_default_0_to_8():
    q = CloudVideoQueue(tz_name="UTC", tz_offset_hours=0)
    tz = timezone.utc
    assert q._in_idle_window(datetime(2026, 1, 1, 0, tzinfo=tz)) is True
    assert q._in_idle_window(datetime(2026, 1, 1, 7, 59, tzinfo=tz)) is True
    assert q._in_idle_window(datetime(2026, 1, 1, 8, tzinfo=tz)) is False
    assert q._in_idle_window(datetime(2026, 1, 1, 23, tzinfo=tz)) is False
    assert q.limit_now(datetime(2026, 1, 1, 3, tzinfo=tz)) == 5
    assert q.limit_now(datetime(2026, 1, 1, 12, tzinfo=tz)) == 0


def test_idle_window_cross_midnight():
    q = CloudVideoQueue(idle_start_hour=22, idle_end_hour=6, tz_name="UTC", tz_offset_hours=0)
    tz = timezone.utc
    assert q._in_idle_window(datetime(2026, 1, 1, 23, tzinfo=tz)) is True
    assert q._in_idle_window(datetime(2026, 1, 1, 3, tzinfo=tz)) is True
    assert q._in_idle_window(datetime(2026, 1, 1, 12, tzinfo=tz)) is False


def test_timezone_is_explicit_not_server_local():
    q = CloudVideoQueue(idle_start_hour=0, idle_end_hour=8,
                        tz_name="Asia/Shanghai", tz_offset_hours=8)
    assert q.tz_name == "Asia/Shanghai"
    # 用带 tzinfo 的 now 验证：UTC 16:00 = 上海 00:00（闲时）
    utc = timezone.utc
    sh = q.tz
    now_utc = datetime(2026, 1, 1, 16, tzinfo=utc)
    assert now_utc.astimezone(sh).hour == 0
    assert q._in_idle_window(now_utc.astimezone(sh)) is True


def test_zoneinfo_fallback_to_offset():
    tz = _resolve_tz("Not/A_Real_Zone", 5.5)
    assert tz.utcoffset(None).total_seconds() == 5.5 * 3600


def test_stats_exposes_queue_state():
    q = _FixedIdle(idle_limit=2)
    s = q.stats()
    assert (s.active, s.waiting, s.limit, s.unlimited) == (0, 0, 2, False)
    assert s.tz


def test_disabled_queue_is_unlimited():
    q = CloudVideoQueue(enabled=False, idle_limit=5)
    assert q.limit_now() == 0
    assert q.stats().unlimited is True


# ── 并发上限 / FIFO / 全程占用 ───────────────────────────────────────────────

def test_idle_limit_caps_concurrency():
    q = _FixedIdle(idle_limit=2, wait_timeout=5)
    running = {"cur": 0, "max": 0}

    async def worker(_i):
        async with q.slot():
            running["cur"] += 1
            running["max"] = max(running["max"], running["cur"])
            await asyncio.sleep(0.02)
            running["cur"] -= 1

    _run(_gather(7, worker))
    assert running["max"] == 2, running
    assert q.stats().active == 0 and q.stats().waiting == 0


def test_daytime_unlimited():
    q = _FixedUnlimited(wait_timeout=5)
    running = {"cur": 0, "max": 0}

    async def worker(_i):
        async with q.slot():
            running["cur"] += 1
            running["max"] = max(running["max"], running["cur"])
            await asyncio.sleep(0.02)
            running["cur"] -= 1

    _run(_gather(7, worker))
    assert running["max"] == 7
    assert q.stats().unlimited is True


def test_fifo_order():
    q = _FixedIdle(idle_limit=1, wait_timeout=5)
    order = []

    async def worker(i):
        async with q.slot():
            order.append(i)
            await asyncio.sleep(0.001)

    # 顺序启动，确保入队顺序确定
    async def main():
        tasks = []
        for i in range(5):
            tasks.append(asyncio.create_task(worker(i)))
            await asyncio.sleep(0)  # 让前面的先拿到名额/入队
        await asyncio.gather(*tasks)

    _run(main())
    assert order == [0, 1, 2, 3, 4], order


def test_slot_releases_on_exception():
    q = _FixedIdle(idle_limit=1, wait_timeout=5)

    async def boom():
        async with q.slot():
            raise RuntimeError("生成失败")

    with pytest.raises(RuntimeError):
        _run(boom())
    assert q.stats().active == 0, "异常路径名额泄漏"


def test_slot_covers_whole_submit_and_poll():
    """名额在慢任务期间一直被占用，第 2 个任务必须等（全程占用）。"""
    q = _FixedIdle(idle_limit=1, wait_timeout=5)
    events = []

    async def slow():
        async with q.slot():
            events.append("slow-start")
            await asyncio.sleep(0.05)
            events.append("slow-end")

    async def quick():
        await asyncio.sleep(0.005)
        async with q.slot():
            events.append("quick-start")

    async def main():
        await asyncio.gather(slow(), quick())
    _run(main())
    # quick 必须等 slow 释放名额后才 start（全程占用）
    assert events.index("slow-end") < events.index("quick-start"), events


# ── 取消 / 超时 ─────────────────────────────────────────────────────────────

def test_waiting_task_cancel_is_immediate_and_no_leak():
    q = _FixedIdle(idle_limit=1, wait_timeout=30)

    async def main():
        hold = asyncio.create_task(_hold(q))
        await asyncio.sleep(0)            # 让 hold 拿到名额
        waiter = asyncio.create_task(_hold(q))
        await asyncio.sleep(0.01)
        assert q.stats().waiting == 1
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert q.stats().waiting == 0, "取消后 waiter 未清理"
        hold.cancel()
        with pytest.raises(asyncio.CancelledError):
            await hold
        assert q.stats().active == 0, "取消后名额泄漏"

    async def _hold(queue):
        async with queue.slot():
            await asyncio.sleep(10)

    _run(main())


def test_wait_timeout_raises_unavailable():
    q = _FixedIdle(idle_limit=1, wait_timeout=0.05)

    async def main():
        hold = asyncio.create_task(_hold(q))
        await asyncio.sleep(0)
        with pytest.raises(CloudVideoUnavailable, match="排队超时"):
            async with q.slot():
                pass
        hold.cancel()
        try:
            await hold
        except asyncio.CancelledError:
            pass
        assert q.stats().active == 0

    async def _hold(queue):
        async with queue.slot():
            await asyncio.sleep(10)

    _run(main())


def test_timeout_does_not_submit_or_fallback():
    """排队超时的错误文案必须说明「未提交、不改打别的后端」。"""
    q = _FixedIdle(idle_limit=1, wait_timeout=0.05)

    async def main():
        hold = asyncio.create_task(_hold(q))
        await asyncio.sleep(0)
        try:
            async with q.slot():
                pass
        except CloudVideoUnavailable as e:
            assert "未提交" in str(e) and "不会改打" in str(e)
        else:
            pytest.fail("应抛排队超时")
        hold.cancel()
        try:
            await hold
        except asyncio.CancelledError:
            pass

    async def _hold(queue):
        async with queue.slot():
            await asyncio.sleep(10)

    _run(main())


# ── 配置构造 ────────────────────────────────────────────────────────────────

def test_build_queue_from_settings(monkeypatch):
    # 读 settings.*（AI 配置面板热更新的是 settings，不是 os.environ）
    from config import settings
    saved = {k: getattr(settings, k) for k in (
        "MINIMAX_H3_QUEUE_IDLE_LIMIT", "MINIMAX_H3_QUEUE_IDLE_START",
        "MINIMAX_H3_QUEUE_IDLE_END", "MINIMAX_H3_QUEUE_TZ", "MINIMAX_H3_QUEUE_WAIT_TIMEOUT",
    )}
    try:
        monkeypatch.setattr(settings, "MINIMAX_H3_QUEUE_IDLE_LIMIT", 3)
        monkeypatch.setattr(settings, "MINIMAX_H3_QUEUE_IDLE_START", 1)
        monkeypatch.setattr(settings, "MINIMAX_H3_QUEUE_IDLE_END", 7)
        monkeypatch.setattr(settings, "MINIMAX_H3_QUEUE_TZ", "UTC")
        monkeypatch.setattr(settings, "MINIMAX_H3_QUEUE_WAIT_TIMEOUT", 42)
        q = build_queue_from_settings()
        assert q.idle_limit == 3 and q.idle_start == 1 and q.idle_end == 7
        assert q.wait_timeout == 42 and q.tz_name == "UTC"
    finally:
        for k, v in saved.items():
            setattr(settings, k, v)


# ── 统一 dispatch 接入（两 provider 共用，无双重占用）────────────────────────

def test_dispatch_uses_queue_slot(monkeypatch):
    q = _FixedIdle(idle_limit=1, wait_timeout=5)
    cvc.set_queue(q)
    monkeypatch.setattr(settings, "MINIMAX_H3_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MINIMAX_H3_CARD_KEY", "sk-test", raising=False)
    seen = {}

    async def _fake_generate(**kw):
        seen["active_during_generate"] = q.stats().active
        return {"task_id": "T1", "url": "u", "downloaded": False}
    monkeypatch.setattr(cvc, "generate_video", _fake_generate)

    r = _run(cvc.generate_video_with_provider("minimax_h3", prompt="x"))
    assert r["provider"] == "minimax_h3"
    assert seen["active_during_generate"] == 1, "dispatch 未占用名额"
    assert q.stats().active == 0, "dispatch 未释放名额"
    cvc.set_queue(None)


def test_dispatch_lightai_shares_same_queue(monkeypatch):
    q = _FixedIdle(idle_limit=1, wait_timeout=5)
    cvc.set_queue(q)
    monkeypatch.setattr(settings, "LIGHTAI_API_KEY", "k", raising=False)
    import cloud_video.lightai as la
    seen = {}

    async def _fake(req, dest):
        seen["active"] = q.stats().active
        return {"provider": "lightai", "url": "u", "downloaded": False}
    monkeypatch.setattr(la, "generate", _fake)

    r = _run(cvc.generate_video_with_provider("lightai", prompt="x"))
    assert r["provider"] == "lightai"
    assert seen["active"] == 1
    assert q.stats().active == 0
    cvc.set_queue(None)


def test_queue_stats_public_api():
    q = _FixedIdle(idle_limit=4)
    cvc.set_queue(q)
    s = cvc.queue_stats()
    assert s.limit == 4 and s.active == 0
    cvc.set_queue(None)
