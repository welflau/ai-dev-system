"""
HookRegistry — 全局单例，支持注册/反注册 Hook 函数，并在 emit 时依次调用。

单个 Hook 抛错不影响主流程（fail-open）。
"""
import asyncio
import inspect
import logging
import time
from typing import Callable, Dict, List

from hooks.types import HookEvent, ToolHookContext

logger = logging.getLogger("hooks.registry")


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


class HookRegistry:
    def __init__(self):
        self._hooks: List[Callable] = []
        # 调用统计：fn.__name__ → {calls, errors, last_at, total_ms}
        self._stats: Dict[str, dict] = {}

    def register(self, fn: Callable) -> None:
        """注册一个 Hook 函数（同步或异步均可）"""
        if fn not in self._hooks:
            self._hooks.append(fn)
            self._stats.setdefault(fn.__name__, {
                "calls": 0, "errors": 0, "last_at": None, "total_ms": 0.0
            })
            logger.debug("Hook 已注册: %s", fn.__name__)

    def unregister(self, fn: Callable) -> None:
        self._hooks = [h for h in self._hooks if h is not fn]

    def get_stats(self) -> List[dict]:
        """返回所有已注册 Hook 的调用统计"""
        result = []
        for fn in self._hooks:
            name = fn.__name__
            stat = self._stats.get(name, {})
            calls = stat.get("calls", 0)
            avg_ms = round(stat.get("total_ms", 0) / calls, 1) if calls > 0 else 0
            result.append({
                "name":     name,
                "calls":    calls,
                "errors":   stat.get("errors", 0),
                "last_at":  stat.get("last_at"),
                "avg_ms":   avg_ms,
            })
        return result

    async def emit(self, ctx: ToolHookContext, blocking: bool = False) -> None:
        """触发所有已注册的 Hook。

        blocking=False（默认）：任何 Hook 失败只记日志，不中断主流程（fail-open）。
        blocking=True：Hook 抛出的第一个异常会在所有 Hook 执行完后重新抛出，
                       用于 PRE_TOOL_USE 场景（如限流 Hook 需要阻断 Action 执行）。
        """
        first_error: Exception | None = None
        for fn in list(self._hooks):
            name = fn.__name__
            stat = self._stats.setdefault(name, {"calls": 0, "errors": 0, "last_at": None, "total_ms": 0.0})
            t0 = time.monotonic()
            try:
                if inspect.iscoroutinefunction(fn):
                    await fn(ctx)
                else:
                    fn(ctx)
                elapsed = (time.monotonic() - t0) * 1000
                stat["calls"]    += 1
                stat["total_ms"] += elapsed
                stat["last_at"]   = _now_iso()
            except Exception as exc:
                stat["errors"] += 1
                stat["last_at"] = _now_iso()
                if blocking and first_error is None:
                    first_error = exc
                else:
                    logger.warning("Hook %s 执行失败（%s %s）: %s",
                                   fn.__name__, ctx.event, ctx.tool_name, exc)
        if blocking and first_error is not None:
            raise first_error


# 全局单例
hook_registry = HookRegistry()
