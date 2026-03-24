"""
AI 自动开发系统 - 需求 API
"""
import json
from fastapi import APIRouter, HTTPException, BackgroundTasks
from database import db
from models import (
    RequirementCreate,
    RequirementUpdate,
    RequirementStatus,
    validate_requirement_transition,
)
from utils import generate_id, now_iso
from events import event_manager

router = APIRouter(prefix="/api/projects/{project_id}/requirements", tags=["requirements"])


@router.post("")
async def create_requirement(project_id: str, req: RequirementCreate):
    """提交需求"""
    # 校验项目存在
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    req_id = generate_id("REQ")
    now = now_iso()
    data = {
        "id": req_id,
        "project_id": project_id,
        "title": req.title,
        "description": req.description,
        "priority": req.priority.value,
        "status": RequirementStatus.SUBMITTED.value,
        "submitter": "user",
        "prd_content": None,
        "module": req.module,
        "tags": json.dumps(req.tags) if req.tags else None,
        "estimated_hours": None,
        "actual_hours": None,
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
    }
    await db.insert("requirements", data)

    # 写日志
    await _log_requirement(project_id, req_id, None, "create", None, "submitted", f"需求「{req.title}」已提交")

    # 发 SSE 事件
    await event_manager.publish_to_project(
        project_id, "requirement_created", {"id": req_id, "title": req.title}
    )

    return {"id": req_id, **data}


@router.get("")
async def list_requirements(project_id: str, status: str = None):
    """获取需求列表"""
    if status:
        rows = await db.fetch_all(
            "SELECT * FROM requirements WHERE project_id = ? AND status = ? ORDER BY created_at DESC",
            (project_id, status),
        )
    else:
        rows = await db.fetch_all(
            "SELECT * FROM requirements WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        )

    # 每个需求附带工单数量
    for r in rows:
        ticket_count = await db.fetch_one(
            "SELECT COUNT(*) as count FROM tickets WHERE requirement_id = ?", (r["id"],)
        )
        r["ticket_count"] = ticket_count["count"] if ticket_count else 0

    return {"requirements": rows, "total": len(rows)}


@router.get("/{req_id}")
async def get_requirement(project_id: str, req_id: str):
    """获取需求详情"""
    req = await db.fetch_one(
        "SELECT * FROM requirements WHERE id = ? AND project_id = ?",
        (req_id, project_id),
    )
    if not req:
        raise HTTPException(404, "需求不存在")

    # 获取关联工单
    tickets = await db.fetch_all(
        "SELECT * FROM tickets WHERE requirement_id = ? ORDER BY sort_order, created_at",
        (req_id,),
    )

    # 获取日志
    logs = await db.fetch_all(
        "SELECT * FROM ticket_logs WHERE requirement_id = ? ORDER BY created_at DESC LIMIT 50",
        (req_id,),
    )

    return {**req, "tickets": tickets, "logs": logs}


@router.put("/{req_id}")
async def update_requirement(project_id: str, req_id: str, req: RequirementUpdate):
    """更新需求"""
    existing = await db.fetch_one(
        "SELECT * FROM requirements WHERE id = ? AND project_id = ?",
        (req_id, project_id),
    )
    if not existing:
        raise HTTPException(404, "需求不存在")

    update_data = {}
    if req.title is not None:
        update_data["title"] = req.title
    if req.description is not None:
        update_data["description"] = req.description
    if req.priority is not None:
        update_data["priority"] = req.priority
    if req.module is not None:
        update_data["module"] = req.module
    if req.tags is not None:
        update_data["tags"] = json.dumps(req.tags)

    if update_data:
        update_data["updated_at"] = now_iso()
        await db.update("requirements", update_data, "id = ?", (req_id,))

    return await get_requirement(project_id, req_id)


@router.delete("/{req_id}")
async def cancel_requirement(project_id: str, req_id: str):
    """取消需求"""
    existing = await db.fetch_one(
        "SELECT * FROM requirements WHERE id = ? AND project_id = ?",
        (req_id, project_id),
    )
    if not existing:
        raise HTTPException(404, "需求不存在")

    if existing["status"] in ("completed", "cancelled"):
        raise HTTPException(400, "需求已完成或已取消，无法操作")

    await db.update(
        "requirements",
        {"status": "cancelled", "updated_at": now_iso()},
        "id = ?",
        (req_id,),
    )

    await _log_requirement(
        project_id, req_id, None, "update_status",
        existing["status"], "cancelled", "需求已取消"
    )

    return {"message": "需求已取消"}


@router.post("/{req_id}/decompose")
async def decompose_requirement(project_id: str, req_id: str, background_tasks: BackgroundTasks):
    """触发需求拆单 — 由 ProductAgent 执行"""
    existing = await db.fetch_one(
        "SELECT * FROM requirements WHERE id = ? AND project_id = ?",
        (req_id, project_id),
    )
    if not existing:
        raise HTTPException(404, "需求不存在")

    if existing["status"] not in ("submitted",):
        raise HTTPException(400, f"当前状态「{existing['status']}」不允许拆单")

    # 更新状态为分析中
    await db.update(
        "requirements",
        {"status": RequirementStatus.ANALYZING.value, "updated_at": now_iso()},
        "id = ?",
        (req_id,),
    )

    await _log_requirement(
        project_id, req_id, "ProductAgent", "start",
        "submitted", "analyzing", "ProductAgent 开始分析需求"
    )

    await event_manager.publish_to_project(
        project_id, "requirement_analyzing", {"id": req_id, "title": existing["title"]}
    )

    # 后台执行拆单（由 Orchestrator 调度）
    from orchestrator import orchestrator
    background_tasks.add_task(orchestrator.handle_requirement, project_id, req_id)

    return {"message": "需求分析已启动", "status": "analyzing"}


# ==================== 内部方法 ====================

async def _log_requirement(
    project_id: str,
    requirement_id: str,
    agent_type: str,
    action: str,
    from_status: str,
    to_status: str,
    message: str,
    level: str = "info",
):
    """记录需求操作日志并推送 SSE 事件"""
    log_id = generate_id("LOG")
    created_at = now_iso()
    detail_json = json.dumps({"message": message}, ensure_ascii=False)

    await db.insert("ticket_logs", {
        "id": log_id,
        "ticket_id": None,
        "subtask_id": None,
        "requirement_id": requirement_id,
        "project_id": project_id,
        "agent_type": agent_type,
        "action": action,
        "from_status": from_status,
        "to_status": to_status,
        "detail": detail_json,
        "level": level,
        "created_at": created_at,
    })

    # 实时推送日志
    await event_manager.publish_to_project(
        project_id,
        "log_added",
        {
            "id": log_id,
            "ticket_id": None,
            "requirement_id": requirement_id,
            "agent_type": agent_type,
            "action": action,
            "from_status": from_status,
            "to_status": to_status,
            "detail": detail_json,
            "level": level,
            "created_at": created_at,
        },
    )
