"""
Hooks 可观测性 API

GET /api/hooks/status   — 注册列表 + Shell 限流计数 + 今日调用总量
GET /api/hooks/stats    — 近 N 小时工具调用统计（from tool_audit_log）
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/hooks", tags=["hooks"])


@router.get("/status")
async def hooks_status():
    """返回 Hook 注册列表、调用统计、Shell 限流计数器"""
    from hooks.registry import hook_registry
    from hooks.builtin import _shell_call_counts, _SHELL_LIMIT_PER_TICKET
    from database import db
    from utils import now_iso

    # Hook 调用统计
    hook_list = hook_registry.get_stats()

    # Shell 限流计数（内存）
    shell_limits = {
        tid: {"count": cnt, "limit": _SHELL_LIMIT_PER_TICKET,
              "pct": round(cnt / _SHELL_LIMIT_PER_TICKET * 100)}
        for tid, cnt in _shell_call_counts.items()
        if cnt > 0
    }

    # 今日工具调用总量
    try:
        today = now_iso()[:10]  # YYYY-MM-DD
        row = await db.fetch_one(
            "SELECT COUNT(*) as total, SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) as errors "
            "FROM tool_audit_log WHERE created_at >= ?",
            (today + "T00:00:00",),
        )
        today_calls  = row["total"]  if row else 0
        today_errors = row["errors"] if row else 0
    except Exception:
        today_calls = today_errors = 0

    return {
        "hooks":        hook_list,
        "hook_count":   len(hook_list),
        "shell_limits": shell_limits,
        "today_calls":  today_calls,
        "today_errors": today_errors,
    }


@router.get("/stats")
async def hooks_stats(hours: int = 1):
    """近 N 小时各工具调用次数、错误数、平均耗时"""
    from database import db
    from datetime import datetime, timedelta, timezone

    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")

    try:
        rows = await db.fetch_all(
            """SELECT tool_name,
                      COUNT(*)                                       AS calls,
                      SUM(CASE WHEN success=0 THEN 1 ELSE 0 END)   AS errors,
                      ROUND(AVG(duration_ms), 1)                    AS avg_ms
               FROM tool_audit_log
               WHERE created_at >= ?
               GROUP BY tool_name
               ORDER BY calls DESC
               LIMIT 20""",
            (since,),
        )
        by_tool = [dict(r) for r in rows]
    except Exception:
        by_tool = []

    return {
        "period_hours": hours,
        "since":        since,
        "by_tool":      by_tool,
        "total_calls":  sum(r["calls"] for r in by_tool),
    }
