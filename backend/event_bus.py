"""
内部事件总线 — 工单状态变更时直接触发下一个 Agent
替代轮询驱动，轮询降为兜底机制
"""
import asyncio
import logging
from typing import Callable, Dict, Any, Optional

logger = logging.getLogger("event_bus")


class InternalEventBus:
    """异步内部事件总线：工单状态变更 → 直接触发 Agent"""

    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._handler: Optional[Callable] = None

    def set_handler(self, handler: Callable):
        """设置事件处理函数（由 orchestrator 注册）"""
        self._handler = handler

    async def publish(self, event_type: str, data: Dict[str, Any]):
        """发布内部事件（非阻塞）"""
        await self._queue.put({"type": event_type, "data": data})
        logger.debug("📨 内部事件: %s (queue size: %d)", event_type, self._queue.qsize())

    async def start(self):
        """启动事件消费循环"""
        self._running = True
        logger.info("🚌 内部事件总线已启动")

        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=5.0)
                if self._handler:
                    try:
                        await self._handler(event["type"], event["data"])
                    except Exception as e:
                        logger.error("事件处理失败: %s → %s", event["type"], e, exc_info=True)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

        logger.info("🚌 内部事件总线已停止")

    def stop(self):
        """停止事件总线"""
        self._running = False


# 全局单例
internal_bus = InternalEventBus()
