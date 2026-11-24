"""系统公共云端生视频：时段感知 FIFO 信号量（生成任务排队）。

参考 ComicAI `frontend/src/api/index.ts:2551-2582` 的 `_h3cloudAcquire/Release`，
但按 ADS 服务端语义重写，并修正 ComicAI 的三个缺陷：

1. **时区**：ComicAI 用 `new Date().getHours()`（浏览器本地时区），多用户/多机不一致。
   这里显式由系统配置指定 IANA 时区（如 Asia/Shanghai），ZoneInfo 不可用时回退到
   固定 UTC 偏移，绝不隐式用服务器本地时区。
2. **取消**：ComicAI 排队期间不监听 abort，只在被唤醒时才发现取消（延迟取消）。
   这里等待 `asyncio.Future`，`task.cancel()` 即时唤醒并清理 waiter、归还名额。
3. **等待超时**：ComicAI 无上限会永久挂起；这里 `wait_timeout` 到点抛
   `CloudVideoUnavailable`（调用方转 blocked，绝不静默改打别的后端）。

规则（上游 `Docs/鼠鼠工具-视频生成API文档.md:22`）：
  闲时（默认 0-8 点，配置时区）每账号最多 5 个任务在排队/生成；白天不限。
  一个名额从「提交 → 429 退避 → 轮询 → 取直链」全程占用（ComicAI :2720/:2791）。

并发安全说明：所有共享状态（_active / _waiters）的读写都在**不含 await 的同步段**内，
asyncio 单线程事件循环下天然原子，无需 Lock —— 也避免了 Lock 绑定到某个 event loop
后在测试里跨 loop 复用的问题。
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Deque, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cloud_video.errors import CloudVideoUnavailable

logger = logging.getLogger("cloud_video.queue")

_UNLIMITED = 0  # limit<=0 表示不限


def _resolve_tz(name: str, fallback_offset_hours: float):
    """IANA 时区名 → tzinfo；失败回退固定 UTC 偏移，不用服务器本地时区。"""
    name = (name or "").strip()
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError, OSError) as e:
            logger.warning("ZoneInfo(%s) 不可用，回退固定 UTC%+.1f: %s", name, fallback_offset_hours, e)
    return timezone(timedelta(hours=fallback_offset_hours))


@dataclass
class QueueStats:
    """队列可观测性（ComicAI 只显示计数，这里补齐排队位置与上限）。"""
    active: int
    waiting: int
    limit: int
    unlimited: bool
    idle_window: bool
    tz: str


class CloudVideoQueue:
    """时段感知 FIFO 信号量。

    与 `asyncio.Semaphore` 的区别：上限是**动态**的（按时段变），
    Semaphore 的上限在构造时固定，无法表达「白天不限、闲时 5」。
    """

    def __init__(
        self,
        *,
        idle_limit: int = 5,
        idle_start_hour: int = 0,
        idle_end_hour: int = 8,
        tz_name: str = "Asia/Shanghai",
        tz_offset_hours: float = 8.0,
        wait_timeout: float = 900.0,
        enabled: bool = True,
    ):
        self.idle_limit = max(0, int(idle_limit))
        self.idle_start = int(idle_start_hour) % 24
        self.idle_end = int(idle_end_hour) % 24
        self.tz_name = tz_name
        self.tz = _resolve_tz(tz_name, tz_offset_hours)
        self.wait_timeout = float(wait_timeout)
        self.enabled = bool(enabled)
        self._active = 0
        self._waiters: Deque[asyncio.Future] = deque()

    # ── 时段判定 ────────────────────────────────────────────────────────────
    def _in_idle_window(self, now: Optional[datetime] = None) -> bool:
        h = (now or datetime.now(self.tz)).hour
        if self.idle_start <= self.idle_end:
            return self.idle_start <= h < self.idle_end
        # 跨午夜（如 22-6）
        return h >= self.idle_start or h < self.idle_end

    def limit_now(self, now: Optional[datetime] = None) -> int:
        """返回当前并发上限；0 = 不限。"""
        if not self.enabled or self.idle_limit <= 0:
            return _UNLIMITED
        return self.idle_limit if self._in_idle_window(now) else _UNLIMITED

    def stats(self) -> QueueStats:
        limit = self.limit_now()
        return QueueStats(
            active=self._active,
            waiting=len(self._waiters),
            limit=limit,
            unlimited=limit == _UNLIMITED,
            idle_window=self._in_idle_window(),
            tz=self.tz_name,
        )

    # ── acquire / release（状态段内无 await）────────────────────────────────
    async def acquire(self) -> None:
        """占用一个名额；排队可被 cancel 即时唤醒，超时抛 CloudVideoUnavailable。

        wait_for 在超时/取消时会 cancel 这个 fut，_wake() 通过 fut.done() 跳过已取消的
        waiter，因此不会把名额授予一个已经放弃的任务（无名额泄漏）。
        """
        limit = self.limit_now()
        if limit == _UNLIMITED or self._active < limit:
            self._active += 1
            return
        fut = asyncio.get_running_loop().create_future()
        self._waiters.append(fut)
        timeout = self.wait_timeout if self.wait_timeout > 0 else None
        try:
            await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            if fut in self._waiters:
                self._waiters.remove(fut)
            raise CloudVideoUnavailable(
                f"生成任务排队超时（等待 {self.wait_timeout:g}s，当前并发 {self._active}/"
                f"{self.limit_now()}，等待 {len(self._waiters)} 个）；未提交，不会改打别的后端"
            )
        except asyncio.CancelledError:
            if fut in self._waiters:
                self._waiters.remove(fut)
            raise
        # 被 release 唤醒：名额已由 _wake() 记在 _active 上，此处不再 +1

    def release(self) -> None:
        """释放名额，唤醒 FIFO 队首。"""
        self._active = max(0, self._active - 1)
        self._wake()

    def _wake(self) -> None:
        """按当前上限唤醒尽可能多的等待者（无 await，原子）。"""
        limit = self.limit_now()
        while self._waiters and (limit == _UNLIMITED or self._active < limit):
            fut = self._waiters.popleft()
            if fut.done():
                continue
            self._active += 1
            fut.set_result(True)

    @asynccontextmanager
    async def slot(self):
        """`async with queue.slot():` —— 名额覆盖提交+轮询全程，finally 必释放。"""
        await self.acquire()
        try:
            yield self.stats()
        finally:
            self.release()


def build_queue_from_settings() -> "CloudVideoQueue":
    """从系统配置构造队列（模块级单例在 client.py 里持有）。

    读 `settings.*` 而非 `os.getenv`：AI 配置面板保存时会热更新 `settings`，
    若这里仍读环境变量，重建队列就拿不到刚改的值（曾导致配置保存不生效）。
    """
    from config import settings
    return CloudVideoQueue(
        idle_limit=int(settings.MINIMAX_H3_QUEUE_IDLE_LIMIT),
        idle_start_hour=int(settings.MINIMAX_H3_QUEUE_IDLE_START),
        idle_end_hour=int(settings.MINIMAX_H3_QUEUE_IDLE_END),
        tz_name=str(settings.MINIMAX_H3_QUEUE_TZ),
        tz_offset_hours=float(settings.MINIMAX_H3_QUEUE_TZ_OFFSET),
        wait_timeout=float(settings.MINIMAX_H3_QUEUE_WAIT_TIMEOUT),
        enabled=bool(settings.MINIMAX_H3_QUEUE_ENABLED),
    )
