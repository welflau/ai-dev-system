"""
AI 自动开发系统 - SSE 事件管理器
服务端推送，前端实时更新
"""
import asyncio
import json
from typing import Any, AsyncGenerator, Dict, Set
from datetime import datetime


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

    async def publish(self, channel: str, event_type: str, data: Any):
        """发布事件到频道"""
        message = {
            "event": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }
        if channel in self._subscribers:
            for queue in self._subscribers[channel]:
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
