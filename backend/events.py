"""
AI 自动开发系统 - SSE 事件管理器
服务端推送，前端实时更新
"""
import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator, Dict, Set, Tuple
from datetime import datetime

logger = logging.getLogger("events")

# 「无订阅者」日志的节流状态：(channel, event_type) -> [上次打印时刻, 期间抑制条数]
_NOSUB_LOG_STATE: Dict[Tuple[str, str], list] = {}
_NOSUB_LOG_INTERVAL = 60.0          # 每个频道每 60s 最多提醒一次
_NOSUB_LOG_MAX_KEYS = 500           # 长跑进程兜底，别让 dict 无上限增长

# 流式 token 这类高频事件，没订阅者是**常态**（浏览器没开着那个项目页面而已），
# 不是异常，不该用 WARNING 刷屏；其余事件仍按 WARNING 提醒。
_HIGH_FREQ_EVENTS = {"ticket_llm_token", "chat_token", "heartbeat"}


class EventManager:
    """SSE 事件管理器 — 支持按项目/工单订阅"""

    def __init__(self):
        # channel_id -> set of asyncio.Queue
        self._subscribers: Dict[str, Set[asyncio.Queue]] = {}

    def subscribe(self, channel: str) -> asyncio.Queue:
        """订阅频道"""
        queue = asyncio.Queue()
        if channel not in self._subscribers:
            self._subscribers[channel] = set()
        self._subscribers[channel].add(queue)
        return queue

    def unsubscribe(self, channel: str, queue: asyncio.Queue):
        """取消订阅"""
        if channel in self._subscribers:
            self._subscribers[channel].discard(queue)
            if not self._subscribers[channel]:
                del self._subscribers[channel]

    def _log_no_subscriber(self, channel: str, event_type: str) -> None:
        """无订阅者时提醒一句，但**按频道节流**。

        原来这里是每次 publish 都打一条 WARNING。而 `ticket_llm_token` 是每
        `_TOK_THRESHOLD`（60 字符）推一次 —— 一次 agent 流式回答就能刷上千行，
        把真正的错误全埋掉（实测跑一张工单时后台几乎只剩这一条在滚）。

        级别也分了档：流式 token 没订阅者是**常态**（无头跑工单时浏览器压根没开），
        当异常报出来是误报；状态变更类事件没人收才值得注意。
        """
        level = logging.DEBUG if event_type in _HIGH_FREQ_EVENTS else logging.WARNING
        if not logger.isEnabledFor(level):
            return

        now = time.monotonic()
        key = (channel, event_type)
        st = _NOSUB_LOG_STATE.get(key)
        if st is None:
            if len(_NOSUB_LOG_STATE) >= _NOSUB_LOG_MAX_KEYS:
                _NOSUB_LOG_STATE.clear()
            _NOSUB_LOG_STATE[key] = [now, 0]
        elif now - st[0] < _NOSUB_LOG_INTERVAL:
            st[1] += 1
            return
        else:
            suppressed = st[1]
            st[0], st[1] = now, 0
            if suppressed:
                logger.log(level, "SSE publish 无订阅者 channel=%s event=%s"
                                  "（过去 %.0fs 另有 %d 条同类，已折叠）",
                           channel, event_type, _NOSUB_LOG_INTERVAL, suppressed)
                return
        logger.log(level, "SSE publish 无订阅者 channel=%s event=%s", channel, event_type)

    async def publish(self, channel: str, event_type: str, data: Any):
        """发布事件到频道"""
        message = {
            "event": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }
        subs = self._subscribers.get(channel) or set()
        if not subs:
            # 无人订阅时确认卡会"推了但前端看不到"——打日志便于排查（已节流，见上）
            self._log_no_subscriber(channel, event_type)
        for queue in list(subs):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                pass  # 队列满了就跳过

    async def publish_to_project(self, project_id: str, event_type: str, data: Any):
        """发布项目级事件"""
        await self.publish(f"project:{project_id}", event_type, data)

    async def publish_to_ticket(self, ticket_id: str, event_type: str, data: Any):
        """发布工单级事件"""
        await self.publish(f"ticket:{ticket_id}", event_type, data)

    async def event_generator(self, channel: str) -> AsyncGenerator[dict, None]:
        """SSE 事件生成器 — 产出 dict 供 sse_starlette 正确编码 event/data 字段"""
        queue = self.subscribe(channel)
        try:
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=30)
                    yield {
                        "event": message["event"],
                        "data": json.dumps(message["data"], ensure_ascii=False),
                    }
                except asyncio.TimeoutError:
                    # 心跳保活
                    yield {"event": "heartbeat", "data": ""}
        finally:
            self.unsubscribe(channel, queue)


# 全局事件管理器
event_manager = EventManager()
