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


@router.get("/{req_id}/pipeline")
async def get_requirement_pipeline(project_id: str, req_id: str):
    """获取需求的 Pipeline 视图数据 — 蓝盾风格，按阶段分组 + Job + 子任务 + 耗时"""
    from datetime import datetime as _dt

    req = await db.fetch_one(
        "SELECT * FROM requirements WHERE id = ? AND project_id = ?",
        (req_id, project_id),
    )
    if not req:
        raise HTTPException(404, "需求不存在")

    # 获取关联工单（按 sort_order 排列）
    tickets = await db.fetch_all(
        "SELECT * FROM tickets WHERE requirement_id = ? ORDER BY sort_order, created_at",
        (req_id,),
    )

    # 为每个工单附加子任务 + 日志
    for t in tickets:
        subtasks = await db.fetch_all(
            "SELECT * FROM subtasks WHERE ticket_id = ? ORDER BY sort_order",
            (t["id"],),
        )
        t["subtasks"] = subtasks
        # 获取该工单的日志
        t["logs"] = await db.fetch_all(
            "SELECT * FROM ticket_logs WHERE ticket_id = ? ORDER BY created_at",
            (t["id"],),
        )

    # 工具函数：计算耗时秒数
    def calc_duration(start_iso, end_iso):
        if not start_iso:
            return None
        try:
            start = _dt.fromisoformat(start_iso.replace("Z", "+00:00"))
            if end_iso:
                end = _dt.fromisoformat(end_iso.replace("Z", "+00:00"))
            else:
                end = _dt.now(start.tzinfo) if start.tzinfo else _dt.now()
            return max(0, int((end - start).total_seconds()))
        except Exception:
            return None

    # Pipeline 5 阶段定义
    STAGE_DEFS = [
        ("requirement_analysis", "需求分析", "📋", []),
        ("architecture", "架构设计", "🏗️",
         ["architecture_in_progress", "architecture_done"]),
        ("development", "开发实现", "💻",
         ["development_in_progress", "development_done",
          "acceptance_passed", "acceptance_rejected"]),
        ("testing", "测试验证", "🧪",
         ["testing_in_progress", "testing_done", "testing_failed"]),
        ("deployment", "部署上线", "🚀",
         ["deploying", "deployed"]),
    ]

    # 所有"已经过"阶段的状态集合（用于判定阶段已完成）
    PAST = {
        "architecture": {"architecture_done", "development_in_progress",
                         "development_done", "acceptance_passed",
                         "acceptance_rejected", "testing_in_progress",
                         "testing_done", "testing_failed", "deploying", "deployed"},
        "development": {"development_done", "acceptance_passed",
                        "acceptance_rejected", "testing_in_progress",
                        "testing_done", "testing_failed", "deploying", "deployed"},
        "testing": {"testing_done", "testing_failed", "deploying", "deployed"},
        "deployment": {"deployed"},
    }

    PRE = {
        "architecture": {"pending"},
        "development": {"pending", "architecture_in_progress", "architecture_done"},
        "testing": {"pending", "architecture_in_progress", "architecture_done",
                    "development_in_progress", "development_done",
                    "acceptance_passed", "acceptance_rejected"},
        "deployment": {"pending", "architecture_in_progress", "architecture_done",
                       "development_in_progress", "development_done",
                       "acceptance_passed", "acceptance_rejected",
                       "testing_in_progress", "testing_done", "testing_failed"},
    }

    # 构建总体时间线
    trigger_time = req["created_at"]
    start_time = req.get("updated_at") if req["status"] != "submitted" else None
    end_time = req.get("completed_at")
    total_duration = calc_duration(trigger_time, end_time)

    # 判定整体执行状态
    req_status = req["status"]
    if req_status == "completed":
        exec_status = "success"
    elif req_status == "cancelled":
        exec_status = "cancelled"
    elif req_status in ("submitted",):
        exec_status = "pending"
    else:
        exec_status = "running"

    # ---- 构建 stages ----
    stages = []

    # 阶段 1: 需求分析（特殊处理）
    if req_status in ("submitted", "analyzing"):
        a_status = "running"
    elif req_status in ("decomposed", "in_progress", "completed"):
        a_status = "done"
    elif req_status == "cancelled":
        a_status = "cancelled"
    else:
        a_status = "pending"

    analysis_jobs = []
    if req_status != "submitted":
        # ProductAgent Job
        job_status = "done" if a_status == "done" else ("running" if a_status == "running" else "pending")
        # 从日志推算 ProductAgent 耗时
        pa_logs = await db.fetch_all(
            "SELECT * FROM ticket_logs WHERE requirement_id = ? AND agent_type = 'ProductAgent' ORDER BY created_at",
            (req_id,),
        )
        pa_start = pa_logs[0]["created_at"] if pa_logs else req["created_at"]
        pa_end = pa_logs[-1]["created_at"] if pa_logs and job_status == "done" else None
        pa_duration = calc_duration(pa_start, pa_end)

        job_subtasks = [{
            "title": "PRD 需求分析",
            "status": "completed" if a_status == "done" else ("in_progress" if a_status == "running" else "pending"),
            "duration": pa_duration,
        }]
        if req.get("prd_content"):
            job_subtasks.append({
                "title": "需求拆单",
                "status": "completed",
                "duration": None,
            })

        analysis_jobs.append({
            "id": f"job-analysis-{req_id[-6:]}",
            "title": "ProductAgent",
            "status": job_status,
            "agent": "ProductAgent",
            "duration": pa_duration,
            "started_at": pa_start,
            "completed_at": pa_end,
            "subtasks": job_subtasks,
            "log_count": len(pa_logs),
        })

    stages.append({
        "key": "requirement_analysis",
        "name": "需求分析",
        "icon": "📋",
        "status": a_status,
        "jobs": analysis_jobs,
    })

    # 阶段 2-5: 基于工单
    all_statuses = [t["status"] for t in tickets]

    for key, name, icon, stage_statuses_list in STAGE_DEFS[1:]:
        stage_statuses_set = set(stage_statuses_list)
        stage_tickets = [t for t in tickets if t["status"] in stage_statuses_set]

        # 判定阶段整体状态
        if not tickets:
            s_status = "pending"
        else:
            in_stage = any(s in stage_statuses_set for s in all_statuses)
            past_set = PAST.get(key, set())
            non_cancelled = [s for s in all_statuses if s != "cancelled"]
            past_stage = (
                all(s in past_set for s in non_cancelled)
                if non_cancelled else False
            )
            if past_stage:
                s_status = "done"
            elif in_stage:
                s_status = "running"
            else:
                pre_set = PRE.get(key, set())
                if any(s in pre_set for s in all_statuses):
                    s_status = "pending"
                else:
                    s_status = "done"

        # 构建 jobs（每个工单 = 一个 job）
        jobs = []
        for t in stage_tickets:
            t_duration = calc_duration(t.get("started_at"), t.get("completed_at"))
            t_subtasks = []
            for st in t.get("subtasks", []):
                st_duration = calc_duration(st.get("created_at"), st.get("completed_at"))
                t_subtasks.append({
                    "id": st["id"],
                    "title": st["title"],
                    "status": st["status"],
                    "duration": st_duration,
                })

            # 如果工单没有子任务，用工单自身作为一个默认子任务
            if not t_subtasks:
                t_subtasks.append({
                    "title": t["title"],
                    "status": "completed" if t["status"] in past_set else (
                        "in_progress" if t["status"] in stage_statuses_set else "pending"
                    ),
                    "duration": t_duration,
                })

            jobs.append({
                "id": t["id"],
                "title": t.get("assigned_agent") or t["title"],
                "status": _ticket_to_job_status(t["status"], stage_statuses_set, past_set),
                "agent": t.get("assigned_agent"),
                "duration": t_duration,
                "started_at": t.get("started_at"),
                "completed_at": t.get("completed_at"),
                "subtasks": t_subtasks,
                "log_count": len(t.get("logs", [])),
                "ticket_id": t["id"],
                "ticket_title": t["title"],
                "ticket_status": t["status"],
            })

        stages.append({
            "key": key,
            "name": name,
            "icon": icon,
            "status": s_status,
            "jobs": jobs,
        })

    # 获取该需求的日志
    logs = await db.fetch_all(
        "SELECT * FROM ticket_logs WHERE requirement_id = ? ORDER BY created_at DESC LIMIT 100",
        (req_id,),
    )

    return {
        "requirement": req,
        "exec_status": exec_status,
        "trigger_time": trigger_time,
        "start_time": start_time,
        "end_time": end_time,
        "total_duration": total_duration,
        "stages": stages,
        "total_tickets": len(tickets),
        "logs": logs,
    }


def _ticket_to_job_status(ticket_status: str, stage_set: set, past_set: set) -> str:
    """将工单状态映射为 job 状态: done / running / pending / failed"""
    if ticket_status in past_set:
        return "done"
    if ticket_status in stage_set:
        if "rejected" in ticket_status or "failed" in ticket_status:
            return "failed"
        if "done" in ticket_status or "passed" in ticket_status:
            return "done"
        return "running"
    return "pending"


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
