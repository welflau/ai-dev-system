"""顶栏监控：高频摘要只计数，展开明细时才读取任务栈。"""
import asyncio
import os
import time
from collections import Counter
from datetime import datetime, timezone

from config import BASE_DIR


def _active_tasks():
    return (task for task in asyncio.all_tasks(asyncio.get_running_loop()) if not task.done())


def _task_detail(task, current):
    try:
        name = task.get_name()
    except Exception:
        name = ""
    try:
        coro = task.get_coro()
        coro_name = getattr(coro, "__qualname__", None) or type(coro).__name__
    except Exception:
        coro_name = ""
    frame = ""
    try:
        stack = task.get_stack()
        if stack:
            f = stack[-1]
            fname = str(f.f_code.co_filename).replace("\\", "/").rsplit("/", 1)[-1]
            frame = f"{fname}:{f.f_code.co_name}:{f.f_lineno}"
    except Exception:
        pass
    try:
        cancelling = task.cancelling()
    except Exception:
        cancelling = 0
    return {"name": name or "", "coro": coro_name or "", "done": False,
            "cancelling": cancelling, "stack": frame, "self": task is current}


def asyncio_tasks_detail():
    current = asyncio.current_task()
    tasks = [_task_detail(t, current) for t in _active_tasks()]
    grouped = Counter(t["coro"] or "(unknown)" for t in tasks)
    return {"count": len(tasks), "tasks": tasks,
            "summary": [{"coro": k, "count": v} for k, v in grouped.most_common()]}


def _memory_mb():
    try:
        import psutil
        return psutil.Process(os.getpid()).memory_info().rss // (1024 * 1024)
    except ImportError:
        try:
            with open(f"/proc/{os.getpid()}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) // 1024
        except Exception:
            pass
        return 0


async def system_metrics(db):
    active_tasks = sum(1 for _ in _active_tasks())
    mem_mb = _memory_mb()
    wal_file = BASE_DIR / "ai_dev_system.db-wal"
    wal_kb = int(wal_file.stat().st_size / 1024) if wal_file.exists() else 0

    # 维持原有的独立降级：一项暂不可用时，仍返回其余指标。
    try:
        from orchestrator import orchestrator
        processing = len(orchestrator._processing)
    except Exception:
        processing = 0
    try:
        from llm_client import llm_client
        llm_pending = getattr(llm_client, "_pending_requests", 0)
    except Exception:
        llm_pending = 0
    try:
        t0 = time.monotonic()
        await db.fetch_one("SELECT 1")
        db_ms = round((time.monotonic() - t0) * 1000, 1)
    except Exception:
        db_ms = 0
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = await db.fetch_one(
            "SELECT COALESCE(SUM(cost_usd), 0) as total FROM llm_conversations "
            "WHERE created_at >= ?", (today + "T00:00:00",)
        )
        cost_today = round(row["total"] if row else 0.0, 4)
    except Exception:
        cost_today = 0.0
    try:
        from ai_gen_tasks import total
        ai_gen_tasks_total = await total()
    except Exception:
        ai_gen_tasks_total = 0

    return {"processing": processing, "asyncio_tasks": active_tasks, "mem_mb": mem_mb,
            "wal_kb": wal_kb, "llm_pending": llm_pending, "db_ms": db_ms,
            "cost_today_usd": cost_today, "ai_gen_tasks": ai_gen_tasks_total}
