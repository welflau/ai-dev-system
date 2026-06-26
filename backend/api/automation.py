"""
自动化任务 API
"""
import json
import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from database import db
from utils import generate_id, now_iso

logger = logging.getLogger("api.automation")

router = APIRouter(prefix="/api/automation", tags=["automation"])

_TEMPLATES_FILE = Path(__file__).parent.parent / "automation_templates.json"


# ── Schemas ──────────────────────────────────────────────────────────────────

class AutomationTaskCreate(BaseModel):
    project_id: str
    name: str
    description: Optional[str] = None
    prompt: str
    model: str = "auto"
    schedule_type: str = "daily"   # daily | interval | once
    cron_expr: Optional[str] = None
    schedule_label: Optional[str] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    enabled: int = 1


class AutomationTaskUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    prompt: Optional[str] = None
    model: Optional[str] = None
    schedule_type: Optional[str] = None
    cron_expr: Optional[str] = None
    schedule_label: Optional[str] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    enabled: Optional[int] = None


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _compute_next_run(cron_expr: str) -> Optional[str]:
    from automation_scheduler import _compute_next_run as _cr
    return _cr(cron_expr)


def _task_row(row: dict) -> dict:
    return dict(row)


# ── Templates ─────────────────────────────────────────────────────────────────

@router.get("/templates")
async def get_templates():
    """获取内置模板列表"""
    try:
        templates = json.loads(_TEMPLATES_FILE.read_text(encoding="utf-8"))
    except Exception:
        templates = []
    return {"templates": templates}


# ── Tasks CRUD ────────────────────────────────────────────────────────────────

@router.get("/tasks")
async def list_tasks(project_id: Optional[str] = None):
    """获取自动化任务列表"""
    if project_id:
        rows = await db.fetch_all(
            "SELECT * FROM automation_tasks WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        )
    else:
        rows = await db.fetch_all(
            "SELECT * FROM automation_tasks ORDER BY created_at DESC"
        )
    return {"tasks": [dict(r) for r in rows]}


@router.post("/tasks", status_code=201)
async def create_task(body: AutomationTaskCreate):
    """创建自动化任务"""
    # 验证项目存在
    project = await db.fetch_one("SELECT id FROM projects WHERE id = ?", (body.project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 验证 cron 表达式（非 once 类型必填）
    if body.schedule_type != "once" and not body.cron_expr:
        raise HTTPException(status_code=400, detail="非单次任务需要提供 cron_expr")

    now = now_iso()
    task_id = generate_id("atask")

    # 计算首次执行时间
    next_run_at = None
    if body.schedule_type == "once":
        # 单次任务用 valid_from 或 cron_expr 作为执行时间
        next_run_at = body.valid_from or body.cron_expr
    elif body.cron_expr:
        next_run_at = _compute_next_run(body.cron_expr)

    await db.insert("automation_tasks", {
        "id": task_id,
        "project_id": body.project_id,
        "name": body.name,
        "description": body.description,
        "prompt": body.prompt,
        "model": body.model,
        "schedule_type": body.schedule_type,
        "cron_expr": body.cron_expr,
        "schedule_label": body.schedule_label,
        "valid_from": body.valid_from,
        "valid_until": body.valid_until,
        "enabled": body.enabled,
        "next_run_at": next_run_at,
        "created_at": now,
        "updated_at": now,
    })

    row = await db.fetch_one("SELECT * FROM automation_tasks WHERE id = ?", (task_id,))
    return dict(row)


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """获取任务详情"""
    row = await db.fetch_one("SELECT * FROM automation_tasks WHERE id = ?", (task_id,))
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    return dict(row)


@router.put("/tasks/{task_id}")
async def update_task(task_id: str, body: AutomationTaskUpdate):
    """更新任务"""
    row = await db.fetch_one("SELECT id FROM automation_tasks WHERE id = ?", (task_id,))
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")

    updates = {k: v for k, v in body.dict().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="无更新字段")

    updates["updated_at"] = now_iso()

    # 若更新了 cron_expr，重新计算 next_run_at
    if "cron_expr" in updates and updates.get("cron_expr"):
        updates["next_run_at"] = _compute_next_run(updates["cron_expr"])

    await db.update("automation_tasks", updates, "id = ?", (task_id,))
    row = await db.fetch_one("SELECT * FROM automation_tasks WHERE id = ?", (task_id,))
    return dict(row)


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: str):
    """删除任务（级联删除执行记录）"""
    row = await db.fetch_one("SELECT id FROM automation_tasks WHERE id = ?", (task_id,))
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    await db.execute("DELETE FROM automation_tasks WHERE id = ?", (task_id,))


@router.post("/tasks/{task_id}/enable")
async def enable_task(task_id: str):
    """启用任务"""
    row = await db.fetch_one("SELECT * FROM automation_tasks WHERE id = ?", (task_id,))
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    now = now_iso()
    updates = {"enabled": 1, "updated_at": now}
    # 重新计算 next_run_at
    cron_expr = dict(row).get("cron_expr")
    if cron_expr:
        updates["next_run_at"] = _compute_next_run(cron_expr)
    await db.update("automation_tasks", updates, "id = ?", (task_id,))
    row = await db.fetch_one("SELECT * FROM automation_tasks WHERE id = ?", (task_id,))
    return dict(row)


@router.post("/tasks/{task_id}/disable")
async def disable_task(task_id: str):
    """禁用任务"""
    row = await db.fetch_one("SELECT id FROM automation_tasks WHERE id = ?", (task_id,))
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    await db.update("automation_tasks", {"enabled": 0, "updated_at": now_iso()}, "id = ?", (task_id,))
    row = await db.fetch_one("SELECT * FROM automation_tasks WHERE id = ?", (task_id,))
    return dict(row)


@router.post("/tasks/{task_id}/run-now")
async def run_task_now(task_id: str):
    """立即执行任务"""
    row = await db.fetch_one("SELECT * FROM automation_tasks WHERE id = ?", (task_id,))
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")

    task = dict(row)

    import asyncio
    from automation_scheduler import _run_task

    async def _manual_run():
        # 临时把 triggered_by 改成 manual
        original_run = _run_task
        run_id = generate_id("run")
        now = now_iso()
        await db.insert("automation_runs", {
            "id": run_id,
            "task_id": task_id,
            "status": "running",
            "triggered_by": "manual",
            "started_at": now,
            "created_at": now,
        })
        await db.update("automation_tasks", {"last_run_status": "running"}, "id = ?", (task_id,))

        try:
            from events import event_manager
            await event_manager.publish_to_project(task["project_id"], "automation_task_started", {
                "task_id": task_id,
                "task_name": task["name"],
                "run_id": run_id,
            })
        except Exception:
            pass

        import time
        start_ts = time.monotonic()
        status = "failed"
        result_msg = None
        error_msg = None
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

        finished_at = now_iso()
        duration_ms = int((time.monotonic() - start_ts) * 1000)
        await db.update("automation_runs", {
            "status": status, "finished_at": finished_at,
            "duration_ms": duration_ms, "result_msg": result_msg, "error_msg": error_msg,
        }, "id = ?", (run_id,))
        await db.update("automation_tasks", {
            "last_run_at": finished_at, "last_run_status": status, "updated_at": finished_at,
        }, "id = ?", (task_id,))
        try:
            from events import event_manager
            await event_manager.publish_to_project(task["project_id"], "automation_task_finished", {
                "task_id": task_id, "task_name": task["name"], "run_id": run_id,
                "status": status, "result_msg": result_msg, "duration_ms": duration_ms,
            })
        except Exception:
            pass

    asyncio.create_task(_manual_run())
    return {"message": "已触发执行", "task_id": task_id}


# ── Runs ──────────────────────────────────────────────────────────────────────

@router.get("/tasks/{task_id}/runs")
async def get_task_runs(task_id: str, limit: int = 20):
    """获取执行历史"""
    row = await db.fetch_one("SELECT id FROM automation_tasks WHERE id = ?", (task_id,))
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    runs = await db.fetch_all(
        "SELECT * FROM automation_runs WHERE task_id = ? ORDER BY created_at DESC LIMIT ?",
        (task_id, min(limit, 50)),
    )
    return {"runs": [dict(r) for r in runs]}


@router.get("/runs")
async def get_recent_runs(project_id: Optional[str] = None, limit: int = 30):
    """获取近期所有执行记录（面板下方列表用）"""
    if project_id:
        rows = await db.fetch_all(
            """SELECT r.*, t.name as task_name, t.project_id
               FROM automation_runs r
               JOIN automation_tasks t ON r.task_id = t.id
               WHERE t.project_id = ?
               ORDER BY r.created_at DESC LIMIT ?""",
            (project_id, min(limit, 50)),
        )
    else:
        rows = await db.fetch_all(
            """SELECT r.*, t.name as task_name, t.project_id
               FROM automation_runs r
               JOIN automation_tasks t ON r.task_id = t.id
               ORDER BY r.created_at DESC LIMIT ?""",
            (min(limit, 50),),
        )
    return {"runs": [dict(r) for r in rows]}
