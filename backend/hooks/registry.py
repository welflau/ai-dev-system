"""
HookRegistry — 全局单例，支持注册/反注册 Hook 函数，并在 emit 时依次调用。

单个 Hook 抛错不影响主流程（fail-open）。
"""
import asyncio
import inspect
import logging
from typing import Callable, List

from hooks.types import HookEvent, ToolHookContext

logger = logging.getLogger("hooks.registry")


class HookRegistry:
    def __init__(self):
        self._hooks: List[Callable] = []

    def register(self, fn: Callable) -> None:
        """注册一个 Hook 函数（同步或异步均可）"""
        if fn not in self._hooks:
            self._hooks.append(fn)
            logger.debug("Hook 已注册: %s", fn.__name__)

    def unregister(self, fn: Callable) -> None:
        self._hooks = [h for h in self._hooks if h is not fn]

    async def emit(self, ctx: ToolHookContext, blocking: bool = False) -> None:
        """触发所有已注册的 Hook。

        blocking=False（默认）：任何 Hook 失败只记日志，不中断主流程（fail-open）。
        blocking=True：Hook 抛出的第一个异常会在所有 Hook 执行完后重新抛出，
                       用于 PRE_TOOL_USE 场景（如限流 Hook 需要阻断 Action 执行）。
        """
        first_error: Exception | None = None
        for fn in list(self._hooks):
            try:
                if inspect.iscoroutinefunction(fn):
                    await fn(ctx)
                else:
                    fn(ctx)
            except Exception as exc:
                if blocking and first_error is None:
                    first_error = exc
                else:
                    # fail-open：Hook 失败只记日志
                    logger.warning("Hook %s 执行失败（%s %s）: %s",
                                   fn.__name__, ctx.event, ctx.tool_name, exc)
        if blocking and first_error is not None:
            raise first_error


# 全局单例
hook_registry = HookRegistry()
