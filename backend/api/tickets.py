"""
AI 自动开发系统 - 工单 API
"""
import json
from fastapi import APIRouter, HTTPException, BackgroundTasks
from database import db
from models import (
    TicketStatus,
    TicketUpdate,
    TicketRejectRequest,
    validate_ticket_transition,
    STATUS_LABELS,
    BOARD_COLUMNS,
)
from utils import generate_id, now_iso
from events import event_manager

router = APIRouter(tags=["tickets"])


# ==================== 工单 CRUD ====================


@router.get("/api/projects/{project_id}/tickets")
async def list_tickets(
    project_id: str,
    status: str = None,
    module: str = None,
    requirement_id: str = None,
):
    """获取工单列表（支持筛选）"""
    sql = "SELECT * FROM tickets WHERE project_id = ?"
    params = [project_id]

    if status:
        sql += " AND status = ?"
        params.append(status)
    if module:
        sql += " AND module = ?"
        params.append(module)
    if requirement_id:
        sql += " AND requirement_id = ?"
        params.append(requirement_id)

    sql += " ORDER BY priority ASC, sort_order ASC, created_at ASC"
    tickets = await db.fetch_all(sql, tuple(params))

    # 附带子任务数 + 子工单数
    for t in tickets:
        st_count = await db.fetch_one(
            "SELECT COUNT(*) as count FROM subtasks WHERE ticket_id = ?", (t["id"],)
        )
        t["subtask_count"] = st_count["count"] if st_count else 0

        child_count = await db.fetch_one(
            "SELECT COUNT(*) as count FROM tickets WHERE parent_ticket_id = ?", (t["id"],)
        )
        t["child_ticket_count"] = child_count["count"] if child_count else 0
        t["status_label"] = STATUS_LABELS.get(t["status"], t["status"])

    return {"tickets": tickets, "total": len(tickets)}


@router.get("/api/projects/{project_id}/tickets/{ticket_id}")
async def get_ticket(project_id: str, ticket_id: str):
    """获取工单详情"""
    ticket = await db.fetch_one(
        "SELECT * FROM tickets WHERE id = ? AND project_id = ?",
        (ticket_id, project_id),
    )
    if not ticket:
        raise HTTPException(404, "工单不存在")

    # 子任务
    subtasks = await db.fetch_all(
        "SELECT * FROM subtasks WHERE ticket_id = ? ORDER BY sort_order, created_at",
        (ticket_id,),
    )

    # 日志
    logs = await db.fetch_all(
        "SELECT * FROM ticket_logs WHERE ticket_id = ? ORDER BY created_at DESC LIMIT 100",
        (ticket_id,),
    )

    # 产物
    artifacts = await db.fetch_all(
        "SELECT * FROM artifacts WHERE ticket_id = ? ORDER BY created_at DESC",
        (ticket_id,),
    )

    # 子工单
    child_tickets = await db.fetch_all(
        "SELECT * FROM tickets WHERE parent_ticket_id = ? ORDER BY sort_order, created_at",
        (ticket_id,),
    )
    for ct in child_tickets:
        ct["status_label"] = STATUS_LABELS.get(ct["status"], ct["status"])

    ticket["status_label"] = STATUS_LABELS.get(ticket["status"], ticket["status"])

    return {
        **ticket,
        "subtasks": subtasks,
        "logs": logs,
        "artifacts": artifacts,
        "child_tickets": child_tickets,
    }


@router.put("/api/projects/{project_id}/tickets/{ticket_id}")
async def update_ticket(project_id: str, ticket_id: str, req: TicketUpdate):
    """更新工单基本信息"""
    existing = await db.fetch_one(
        "SELECT * FROM tickets WHERE id = ? AND project_id = ?",
        (ticket_id, project_id),
    )
    if not existing:
        raise HTTPException(404, "工单不存在")

    update_data = {k: v for k, v in req.dict(exclude_unset=True).items() if v is not None}
    if update_data:
        update_data["updated_at"] = now_iso()
        await db.update("tickets", update_data, "id = ?", (ticket_id,))

    return await get_ticket(project_id, ticket_id)


@router.delete("/api/projects/{project_id}/tickets/{ticket_id}")
async def cancel_ticket(project_id: str, ticket_id: str):
    """取消工单"""
    existing = await db.fetch_one(
        "SELECT * FROM tickets WHERE id = ? AND project_id = ?",
        (ticket_id, project_id),
    )
    if not existing:
        raise HTTPException(404, "工单不存在")

    if existing["status"] in ("deployed", "cancelled"):
        raise HTTPException(400, "工单已完成或已取消")

    old_status = existing["status"]
    await db.update(
        "tickets",
        {"status": "cancelled", "updated_at": now_iso()},
        "id = ?",
        (ticket_id,),
    )

    await _log_ticket(
        project_id, existing["requirement_id"], ticket_id,
        None, "update_status", old_status, "cancelled", "工单已取消"
    )

    return {"message": "工单已取消"}


# ==================== 工单操作 ====================


@router.post("/api/projects/{project_id}/tickets/{ticket_id}/start")
async def start_ticket(project_id: str, ticket_id: str, background_tasks: BackgroundTasks):
    """启动工单（触发 Agent 流转）"""
    existing = await db.fetch_one(
        "SELECT * FROM tickets WHERE id = ? AND project_id = ?",
        (ticket_id, project_id),
    )
    if not existing:
        raise HTTPException(404, "工单不存在")

    if existing["status"] != TicketStatus.PENDING.value:
        raise HTTPException(400, f"当前状态「{existing['status']}」不允许启动")

    # 后台启动 Agent 流转
    from orchestrator import orchestrator
    background_tasks.add_task(orchestrator.process_ticket, project_id, ticket_id)

    return {"message": "工单已启动", "ticket_id": ticket_id}


@router.post("/api/projects/{project_id}/tickets/{ticket_id}/reject")
async def reject_ticket(project_id: str, ticket_id: str, req: TicketRejectRequest):
    """打回工单（验收/测试不通过时使用）"""
    existing = await db.fetch_one(
        "SELECT * FROM tickets WHERE id = ? AND project_id = ?",
        (ticket_id, project_id),
    )
    if not existing:
        raise HTTPException(404, "工单不存在")

    # 只有 development_done 和 testing_in_progress 状态允许打回
    allowed_reject_from = [
        TicketStatus.DEVELOPMENT_DONE.value,
        TicketStatus.TESTING_IN_PROGRESS.value,
    ]
    if existing["status"] not in allowed_reject_from:
        raise HTTPException(400, f"当前状态「{existing['status']}」不允许打回")

    old_status = existing["status"]

    if old_status == TicketStatus.DEVELOPMENT_DONE.value:
        new_status = TicketStatus.ACCEPTANCE_REJECTED.value
        message = f"验收不通过: {req.reason}"
    else:
        new_status = TicketStatus.TESTING_FAILED.value
        message = f"测试不通过: {req.reason}"

    await db.update(
        "tickets",
        {"status": new_status, "updated_at": now_iso()},
        "id = ?",
        (ticket_id,),
    )

    await _log_ticket(
        project_id, existing["requirement_id"], ticket_id,
        "ProductAgent" if old_status == TicketStatus.DEVELOPMENT_DONE.value else "TestAgent",
        "reject", old_status, new_status, message,
    )

    await event_manager.publish_to_project(
        project_id,
        "ticket_rejected",
        {"ticket_id": ticket_id, "from": old_status, "to": new_status, "reason": req.reason},
    )

    return {"message": message, "new_status": new_status}


# ==================== 子任务 ====================


@router.get("/api/tickets/{ticket_id}/subtasks")
async def list_subtasks(ticket_id: str):
    """获取子任务列表"""
    subtasks = await db.fetch_all(
        "SELECT * FROM subtasks WHERE ticket_id = ? ORDER BY sort_order, created_at",
        (ticket_id,),
    )
    return {"subtasks": subtasks, "total": len(subtasks)}


@router.put("/api/tickets/{ticket_id}/subtasks/{subtask_id}")
async def update_subtask(ticket_id: str, subtask_id: str, status: str = None):
    """更新子任务状态"""
    existing = await db.fetch_one(
        "SELECT * FROM subtasks WHERE id = ? AND ticket_id = ?",
        (subtask_id, ticket_id),
    )
    if not existing:
        raise HTTPException(404, "子任务不存在")

    update_data = {"updated_at": now_iso()}
    if status:
        update_data["status"] = status
        if status == "completed":
            update_data["completed_at"] = now_iso()

    await db.update("subtasks", update_data, "id = ?", (subtask_id,))
    return {"message": "子任务已更新"}


# ==================== 看板 ====================


@router.get("/api/projects/{project_id}/board")
async def get_board(project_id: str, requirement_id: str = None):
    """获取看板数据（按状态分组）"""
    sql = "SELECT * FROM tickets WHERE project_id = ?"
    params = [project_id]
    if requirement_id:
        sql += " AND requirement_id = ?"
        params.append(requirement_id)
    sql += " ORDER BY priority ASC, sort_order ASC"

    tickets = await db.fetch_all(sql, tuple(params))

    # 按看板列分组
    board = {}
    for col_name, statuses in BOARD_COLUMNS.items():
        status_values = [s.value for s in statuses]
        board[col_name] = [
            {**t, "status_label": STATUS_LABELS.get(t["status"], t["status"])}
            for t in tickets
            if t["status"] in status_values
        ]

    # 已取消的单独放
    board["cancelled"] = [
        {**t, "status_label": "已取消"}
        for t in tickets
        if t["status"] == "cancelled"
    ]

    return {"board": board}


@router.get("/api/projects/{project_id}/board/by-module")
async def get_board_by_module(project_id: str):
    """按模块分组视图"""
    tickets = await db.fetch_all(
        "SELECT * FROM tickets WHERE project_id = ? AND status != 'cancelled' ORDER BY priority, sort_order",
        (project_id,),
    )

    by_module = {}
    for t in tickets:
        module = t["module"] or "other"
        if module not in by_module:
            by_module[module] = []
        t["status_label"] = STATUS_LABELS.get(t["status"], t["status"])
        by_module[module].append(t)

    return {"modules": by_module}


# ==================== 日志 ====================


@router.get("/api/projects/{project_id}/logs")
async def get_project_logs(project_id: str, limit: int = 100, offset: int = 0):
    """项目级日志"""
    logs = await db.fetch_all(
        "SELECT * FROM ticket_logs WHERE project_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (project_id, limit, offset),
    )
    total = await db.fetch_one(
        "SELECT COUNT(*) as count FROM ticket_logs WHERE project_id = ?",
        (project_id,),
    )
    return {"logs": logs, "total": total["count"] if total else 0}


@router.get("/api/tickets/{ticket_id}/logs")
async def get_ticket_logs(ticket_id: str):
    """工单级日志"""
    logs = await db.fetch_all(
        "SELECT * FROM ticket_logs WHERE ticket_id = ? ORDER BY created_at DESC",
        (ticket_id,),
    )
    return {"logs": logs, "total": len(logs)}


@router.get("/api/requirements/{req_id}/logs")
async def get_requirement_logs(req_id: str):
    """需求级日志"""
    logs = await db.fetch_all(
        "SELECT * FROM ticket_logs WHERE requirement_id = ? ORDER BY created_at DESC",
        (req_id,),
    )
    return {"logs": logs, "total": len(logs)}


# ==================== 统计 ====================


@router.get("/api/projects/{project_id}/stats")
async def get_project_stats(project_id: str):
    """项目统计数据"""
    # 需求统计
    req_stats = await db.fetch_all(
        "SELECT status, COUNT(*) as count FROM requirements WHERE project_id = ? GROUP BY status",
        (project_id,),
    )

    # 工单统计
    ticket_stats = await db.fetch_all(
        "SELECT status, COUNT(*) as count FROM tickets WHERE project_id = ? GROUP BY status",
        (project_id,),
    )

    # 模块统计
    module_stats = await db.fetch_all(
        "SELECT module, COUNT(*) as count FROM tickets WHERE project_id = ? GROUP BY module",
        (project_id,),
    )

    # Agent 工作量统计
    agent_stats = await db.fetch_all(
        "SELECT agent_type, COUNT(*) as count FROM ticket_logs WHERE project_id = ? AND agent_type IS NOT NULL GROUP BY agent_type",
        (project_id,),
    )

    # 总数
    total_tickets = await db.fetch_one(
        "SELECT COUNT(*) as count FROM tickets WHERE project_id = ?", (project_id,)
    )
    completed_tickets = await db.fetch_one(
        "SELECT COUNT(*) as count FROM tickets WHERE project_id = ? AND status = 'deployed'",
        (project_id,),
    )

    total = total_tickets["count"] if total_tickets else 0
    completed = completed_tickets["count"] if completed_tickets else 0
    completion_rate = round(completed / total * 100, 1) if total > 0 else 0

    return {
        "total_tickets": total,
        "completed_tickets": completed,
        "completion_rate": completion_rate,
        "requirement_stats": {r["status"]: r["count"] for r in req_stats},
        "ticket_stats": {t["status"]: t["count"] for t in ticket_stats},
        "module_stats": {m["module"] or "other": m["count"] for m in module_stats},
        "agent_stats": {a["agent_type"]: a["count"] for a in agent_stats},
    }


# ==================== LLM 会话日志 ====================


@router.get("/api/tickets/{ticket_id}/llm-logs")
async def get_ticket_llm_logs(ticket_id: str):
    """获取工单关联的 LLM 会话记录"""
    logs = await db.fetch_all(
        "SELECT * FROM llm_conversations WHERE ticket_id = ? ORDER BY created_at DESC",
        (ticket_id,),
    )
    return {"conversations": logs, "total": len(logs)}


@router.get("/api/requirements/{req_id}/llm-logs")
async def get_requirement_llm_logs(req_id: str):
    """获取需求关联的 LLM 会话记录"""
    logs = await db.fetch_all(
        "SELECT * FROM llm_conversations WHERE requirement_id = ? ORDER BY created_at DESC",
        (req_id,),
    )
    return {"conversations": logs, "total": len(logs)}


# ==================== 产出文件 ====================


@router.get("/api/tickets/{ticket_id}/artifacts")
async def get_ticket_artifacts(ticket_id: str):
    """获取工单产出文件"""
    artifacts = await db.fetch_all(
        "SELECT * FROM artifacts WHERE ticket_id = ? ORDER BY created_at DESC",
        (ticket_id,),
    )
    return {"artifacts": artifacts, "total": len(artifacts)}


@router.get("/api/requirements/{req_id}/artifacts")
async def get_requirement_artifacts(req_id: str):
    """获取需求关联的全部产出文件"""
    artifacts = await db.fetch_all(
        "SELECT a.*, t.title as ticket_title FROM artifacts a LEFT JOIN tickets t ON a.ticket_id = t.id WHERE a.requirement_id = ? ORDER BY a.created_at DESC",
        (req_id,),
    )
    return {"artifacts": artifacts, "total": len(artifacts)}


# ==================== SSE 事件 ====================


@router.get("/api/projects/{project_id}/events")
async def project_events(project_id: str):
    """项目事件流（SSE）"""
    from sse_starlette.sse import EventSourceResponse

    return EventSourceResponse(
        event_manager.event_generator(f"project:{project_id}")
    )


@router.get("/api/tickets/{ticket_id}/events")
async def ticket_events(ticket_id: str):
    """工单事件流（SSE）"""
    from sse_starlette.sse import EventSourceResponse

    return EventSourceResponse(
        event_manager.event_generator(f"ticket:{ticket_id}")
    )


# ==================== 内部方法 ====================


async def _log_ticket(
    project_id: str,
    requirement_id: str,
    ticket_id: str,
    agent_type: str,
    action: str,
    from_status: str,
    to_status: str,
    message: str,
    level: str = "info",
):
    """记录工单操作日志并推送 SSE 事件"""
    log_id = generate_id("LOG")
    created_at = now_iso()
    detail_json = json.dumps({"message": message}, ensure_ascii=False)

    await db.insert("ticket_logs", {
        "id": log_id,
        "ticket_id": ticket_id,
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
            "ticket_id": ticket_id,
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


# ==================== 执行命令 (配置 Tab) ====================


@router.get("/api/tickets/{ticket_id}/commands")
async def get_ticket_commands(ticket_id: str):
    """获取工单执行命令列表"""
    commands = await db.fetch_all(
        "SELECT * FROM ticket_commands WHERE ticket_id = ? ORDER BY created_at, step_order",
        (ticket_id,),
    )
    return {"commands": commands, "total": len(commands)}


@router.get("/api/requirements/{requirement_id}/commands")
async def get_requirement_commands(requirement_id: str):
    """获取需求下所有执行命令"""
    commands = await db.fetch_all(
        "SELECT * FROM ticket_commands WHERE requirement_id = ? ORDER BY created_at, step_order",
        (requirement_id,),
    )
    return {"commands": commands, "total": len(commands)}
