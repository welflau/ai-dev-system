"""
自动化任务调度器
asyncio 循环，每分钟 tick 一次，到期任务直接调 LLM，结果通过 SSE 推送
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from database import db
from utils import generate_id, now_iso

logger = logging.getLogger("automation")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _compute_next_run(cron_expr: str, after: Optional[datetime] = None) -> Optional[str]:
    """用 croniter 计算下次触发时间（ISO 8601 UTC）"""
    try:
        from croniter import croniter
        base = after or _now_utc()
        it = croniter(cron_expr, base)
        nxt: datetime = it.get_next(datetime)
        return nxt.strftime("%Y-%m-%dT%H:%M:%S")
    except Exception as e:
        logger.warning("cron 解析失败 '%s': %s", cron_expr, e)
        return None


async def _run_task(task: dict) -> None:
    """执行单个自动化任务：调 LLM → 存结果 → 推 SSE"""
    task_id = task["id"]
    project_id = task["project_id"]
    run_id = generate_id("run")
    started_at = now_iso()
    start_ts = time.monotonic()

    # 写 running 记录
    await db.insert("automation_runs", {
        "id": run_id,
        "task_id": task_id,
        "status": "running",
        "triggered_by": "auto",
        "started_at": started_at,
        "created_at": started_at,
    })
    await db.update("automation_tasks", {"last_run_status": "running"}, "id = ?", (task_id,))

    # SSE: 开始
    try:
        from events import event_manager
        await event_manager.publish_to_project(project_id, "automation_task_started", {
            "task_id": task_id,
            "task_name": task["name"],
            "run_id": run_id,
        })
    except Exception:
        pass

    status = "failed"
    result_msg: Optional[str] = None
    error_msg: Optional[str] = None

    try:
        from llm_client import llm_client
        model = task.get("model") or "auto"
        kwargs = {}
        if model and model != "auto":
            kwargs["model"] = model

        reply = await llm_client.chat(
            messages=[{"role": "user", "content": task["prompt"]}],
            max_tokens=2048,
            **kwargs,
        )
        result_msg = reply[:500] if reply else ""
        status = "success"
    except Exception as e:
        error_msg = str(e)[:300]
        logger.error("自动化任务执行失败 task=%s: %s", task_id[:12], e)

    finished_at = now_iso()
    duration_ms = int((time.monotonic() - start_ts) * 1000)

    await db.update("automation_runs", {
        "status": status,
        "finished_at": finished_at,
        "duration_ms": duration_ms,
        "result_msg": result_msg,
        "error_msg": error_msg,
    }, "id = ?", (run_id,))

    await db.update("automation_tasks", {
        "last_run_at": finished_at,
        "last_run_status": status,
        "updated_at": finished_at,
    }, "id = ?", (task_id,))

    # SSE: 完成
    try:
        from events import event_manager
        await event_manager.publish_to_project(project_id, "automation_task_finished", {
            "task_id": task_id,
            "task_name": task["name"],
            "run_id": run_id,
            "status": status,
            "result_msg": result_msg,
            "duration_ms": duration_ms,
        })
    except Exception:
        pass

    logger.info("自动化任务完成 task=%s status=%s duration=%dms", task_id[:12], status, duration_ms)


async def _tick() -> None:
    """单次轮询：找到期任务并派发"""
    now_str = _now_utc().strftime("%Y-%m-%dT%H:%M:%S")
    today_str = _now_utc().strftime("%Y-%m-%d")

    try:
        tasks = await db.fetch_all(
            """SELECT * FROM automation_tasks
               WHERE enabled = 1
                 AND next_run_at IS NOT NULL
                 AND next_run_at <= ?""",
            (now_str,),
        )
    except Exception as e:
        logger.error("自动化轮询 DB 查询失败: %s", e)
        return

    for task in tasks:
        # 检查有效日期范围
        valid_from = task.get("valid_from")
        valid_until = task.get("valid_until")
        if valid_from and today_str < valid_from:
            continue
        if valid_until and today_str > valid_until:
            # 超出有效期，禁用任务
            await db.update("automation_tasks", {
                "enabled": 0,
                "updated_at": now_iso(),
            }, "id = ?", (task["id"],))
            continue

        schedule_type = task.get("schedule_type", "daily")

        # 计算下次触发时间
        if schedule_type == "once":
            # 单次任务：执行后禁用
            await db.update("automation_tasks", {
                "enabled": 0,
                "next_run_at": None,
                "updated_at": now_iso(),
            }, "id = ?", (task["id"],))
        else:
            cron_expr = task.get("cron_expr")
            if cron_expr:
                next_run = _compute_next_run(cron_expr)
                await db.update("automation_tasks", {
                    "next_run_at": next_run,
                    "updated_at": now_iso(),
                }, "id = ?", (task["id"],))
            else:
                # cron 表达式缺失，跳过并禁用
                logger.warning("自动化任务 %s 缺少 cron_expr，已禁用", task["id"][:12])
                await db.update("automation_tasks", {"enabled": 0}, "id = ?", (task["id"],))
                continue

        asyncio.create_task(_run_task(dict(task)))
        logger.info("自动化任务触发 task=%s '%s'", task["id"][:12], task.get("name", ""))


async def automation_loop() -> None:
    """主调度循环，每 60s 执行一次 tick"""
    logger.info("自动化调度器已启动（每 60s 轮询）")
    while True:
        try:
            await _tick()
        except Exception as e:
            logger.error("自动化调度 tick 异常: %s", e, exc_info=True)
        await asyncio.sleep(60)
