"""
AI 自动开发系统 - 需求 API
"""
import json
import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks
from database import db

logger = logging.getLogger("api.requirements")
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
async def create_requirement(project_id: str, req: RequirementCreate, background_tasks: BackgroundTasks):
    """提交需求（创建后自动触发拆单）"""
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

    # === 自动触发拆单 ===
    await db.update(
        "requirements",
        {"status": RequirementStatus.ANALYZING.value, "updated_at": now_iso()},
        "id = ?",
        (req_id,),
    )
    data["status"] = RequirementStatus.ANALYZING.value

    await _log_requirement(
        project_id, req_id, "ProductAgent", "start",
        "submitted", "analyzing", "ProductAgent 开始分析需求（自动触发）"
    )

    await event_manager.publish_to_project(
        project_id, "requirement_analyzing", {"id": req_id, "title": req.title}
    )

    from orchestrator import orchestrator
    background_tasks.add_task(orchestrator.handle_requirement, project_id, req_id)

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

    # 为每个工单附加子工单数和状态标签
    from models import STATUS_LABELS
    for t in tickets:
        child_count = await db.fetch_one(
            "SELECT COUNT(*) as count FROM tickets WHERE parent_ticket_id = ?", (t["id"],)
        )
        t["child_ticket_count"] = child_count["count"] if child_count else 0
        t["status_label"] = STATUS_LABELS.get(t["status"], t["status"])

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


@router.delete("/{req_id}/permanent")
async def delete_requirement(project_id: str, req_id: str):
    """永久删除需求（物理删除，同时清理关联工单、子任务、日志、产物、LLM会话）"""
    existing = await db.fetch_one(
        "SELECT * FROM requirements WHERE id = ? AND project_id = ?",
        (req_id, project_id),
    )
    if not existing:
        raise HTTPException(404, "需求不存在")

    # 获取关联工单 ID
    tickets = await db.fetch_all(
        "SELECT id FROM tickets WHERE requirement_id = ?", (req_id,)
    )
    ticket_ids = [t["id"] for t in tickets]

    # 删除关联数据（按依赖顺序：先删最底层子表）
    for tid in ticket_ids:
        await db.delete("subtasks", "ticket_id = ?", (tid,))
        await db.delete("ticket_commands", "ticket_id = ?", (tid,))
        await db.delete("llm_conversations", "ticket_id = ?", (tid,))
        await db.delete("artifacts", "ticket_id = ?", (tid,))
        await db.delete("ticket_logs", "ticket_id = ?", (tid,))

    # 删除需求级关联（不关联工单的）
    await db.delete("ticket_logs", "requirement_id = ?", (req_id,))
    await db.delete("ticket_commands", "requirement_id = ?", (req_id,))
    await db.delete("llm_conversations", "requirement_id = ?", (req_id,))
    await db.delete("artifacts", "requirement_id = ?", (req_id,))
    await db.delete("chat_messages", "project_id = ?", (project_id,))  # 聊天记录按项目清理可能过度，这里只清需求相关的

    # 删除工单
    await db.delete("tickets", "requirement_id = ?", (req_id,))

    # 删除需求本身
    await db.delete("requirements", "id = ?", (req_id,))

    return {"message": "需求已永久删除"}


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

    # Pipeline 5 阶段定义 —— 由 SOP 配置派生（sop/loader.py:build_pipeline_stages）
    # 原硬编码版本已移到 sop/loader.py 的 _legacy_pipeline_stages() 作兜底
    from sop.loader import build_pipeline_stages
    from orchestrator import orchestrator
    _pipeline = build_pipeline_stages(orchestrator._sop_config or {})
    # 将派生结果转为原先的数据结构，最小化下游改动
    STAGE_DEFS = [
        (d["key"], d["name"], d.get("icon", ""), d.get("in_statuses", []))
        for d in _pipeline["defs"]
    ]
    PAST = _pipeline["past"]
    PRE = _pipeline["pre"]

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
    elif req_status == "paused":
        exec_status = "paused"
    elif req_status in ("submitted",):
        exec_status = "pending"
    else:
        exec_status = "running"

    # ---- 构建 stages ----
    stages = []

    # 阶段 1: 需求分析（特殊处理）
    if req_status == "analyzing":
        a_status = "running"
    elif req_status == "submitted":
        a_status = "pending"
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
        "has_warning": False,
        "has_error": False,
    })

    # 阶段 2-5: 每个阶段一个 Agent Job，子任务为各工单
    all_statuses = [t["status"] for t in tickets]

    # 每个阶段对应的 Agent 名称
    STAGE_AGENTS = {
        "architecture": "ArchitectAgent",
        "development": "DevAgent",
        "testing": "TestAgent",
    }

    for key, name, icon, stage_statuses_list in STAGE_DEFS[1:]:
        # "合入Develop" 特殊处理：基于需求状态而非工单状态
        if key == "merge_develop":
            DONE_STATUSES = {"testing_done", "deployed"}
            non_cancelled = [t for t in tickets if t["status"] != "cancelled"]
            all_tested = non_cancelled and all(t["status"] in DONE_STATUSES for t in non_cancelled)

            if req_status == "completed":
                m_status = "done"
            elif all_tested:
                m_status = "running"  # 正在合并中
            elif req_status in ("submitted", "analyzing", "decomposed"):
                m_status = "pending"
            else:
                m_status = "pending"

            branch_name = req.get("branch_name", "")
            merge_jobs = []
            if m_status in ("done", "running"):
                merge_jobs.append({
                    "id": f"job-merge-{req_id[-6:]}",
                    "title": "Orchestrator",
                    "status": "done" if m_status == "done" else "running",
                    "agent": "Orchestrator",
                    "duration": None,
                    "started_at": req.get("completed_at"),
                    "completed_at": req.get("completed_at") if m_status == "done" else None,
                    "subtasks": [{
                        "title": f"合并 {branch_name} → develop" if branch_name else "合并到 develop",
                        "status": "completed" if m_status == "done" else "in_progress",
                        "duration": None,
                    }],
                    "log_count": 0,
                })
            elif req_status not in ("submitted",):
                merge_jobs.append({
                    "id": f"expected-merge-{req_id[-6:]}",
                    "title": "Orchestrator",
                    "status": "pending",
                    "agent": "Orchestrator",
                    "duration": None,
                    "started_at": None,
                    "completed_at": None,
                    "subtasks": [{"title": "等待所有工单测试通过后合入 develop", "status": "pending", "duration": None}],
                    "log_count": 0,
                })

            stages.append({
                "key": key,
                "name": name,
                "icon": icon,
                "status": m_status,
                "jobs": merge_jobs,
                "has_warning": False,
                "has_error": False,
            })
            continue

        stage_statuses_set = set(stage_statuses_list)
        past_set = PAST.get(key, set())
        pre_set = PRE.get(key, set())

        # 判定阶段整体状态
        if not tickets:
            s_status = "pending"
        else:
            in_stage = any(s in stage_statuses_set for s in all_statuses)
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
                if any(s in pre_set for s in all_statuses):
                    s_status = "pending"
                else:
                    s_status = "done"

        # 构建 jobs — 每个阶段只有一个 Agent Job
        agent_for_stage = STAGE_AGENTS.get(key, name)
        active_tickets = [t for t in tickets if t["status"] != "cancelled"]

        if active_tickets:
            # 收集该阶段所有工单的状态
            ticket_stage_statuses = []
            for t in active_tickets:
                ts = _ticket_stage_status(t["status"], stage_statuses_set, past_set, pre_set)
                ticket_stage_statuses.append(ts)

            # 计算该 Agent Job 的整体状态
            if all(s == "done" for s in ticket_stage_statuses):
                job_status = "done"
            elif any(s == "failed" for s in ticket_stage_statuses):
                job_status = "failed"
            elif any(s == "running" for s in ticket_stage_statuses):
                job_status = "running"
            else:
                job_status = "pending"

            # 计算耗时：取所有工单中最早开始到最晚结束
            stage_start = None
            stage_end = None
            total_log_count = 0

            for t in active_tickets:
                ts = _ticket_stage_status(t["status"], stage_statuses_set, past_set, pre_set)
                if ts in ("done", "running", "failed"):
                    if t.get("started_at"):
                        if stage_start is None or t["started_at"] < stage_start:
                            stage_start = t["started_at"]
                    if t.get("completed_at"):
                        if stage_end is None or t["completed_at"] > stage_end:
                            stage_end = t["completed_at"]
                    total_log_count += len(t.get("logs", []))

            stage_duration = calc_duration(stage_start, stage_end) if stage_start else None

            # 子任务 = 各工单的名称 + 在该阶段的状态
            job_subtasks = []
            for idx, t in enumerate(active_tickets):
                ts = _ticket_stage_status(t["status"], stage_statuses_set, past_set, pre_set)
                st_status = {
                    "done": "completed",
                    "running": "in_progress",
                    "failed": "in_progress",
                    "pending": "pending",
                }.get(ts, "pending")

                t_duration = None
                if ts in ("done", "running", "failed"):
                    t_duration = calc_duration(t.get("started_at"), t.get("completed_at"))

                # 检测该工单在此阶段是否有警告 / 错误
                sub_has_error = t["status"] in ("testing_failed", "acceptance_rejected", "cancelled")
                sub_has_warning = False
                if not sub_has_error:
                    result_raw = t.get("result")
                    if result_raw:
                        try:
                            result_obj = json.loads(result_raw) if isinstance(result_raw, str) else result_raw
                            test_res = result_obj.get("test_result", {})
                            summ = test_res.get("summary", {}) if isinstance(test_res, dict) else {}
                            if isinstance(summ, dict):
                                if summ.get("pass_rate", 100) < 100 or summ.get("issues"):
                                    sub_has_warning = True
                        except Exception:
                            pass

                job_subtasks.append({
                    "title": t["title"],
                    "status": st_status,
                    "duration": t_duration,
                    "ticket_id": t["id"],
                    "has_warning": sub_has_warning,
                    "has_error": sub_has_error,
                })

            jobs = [{
                "id": f"job-{key}-{req_id[-6:]}",
                "title": agent_for_stage,
                "status": job_status,
                "agent": agent_for_stage,
                "duration": stage_duration,
                "started_at": stage_start if job_status in ("done", "running", "failed") else None,
                "completed_at": stage_end if job_status == "done" else None,
                "subtasks": job_subtasks,
                "log_count": total_log_count,
                "ticket_id": active_tickets[0]["id"] if len(active_tickets) == 1 else None,
                "ticket_title": active_tickets[0]["title"] if len(active_tickets) == 1 else f"{len(active_tickets)} 个工单",
                "ticket_status": active_tickets[0]["status"] if len(active_tickets) == 1 else None,
                "has_warning": any(s.get("has_warning") for s in job_subtasks),
                "has_error": any(s.get("has_error") for s in job_subtasks),
            }]
        elif req_status not in ("submitted",):
            # 没有工单但需求已进入分析，生成占位 Job
            jobs = [{
                "id": f"expected-{key}",
                "title": agent_for_stage,
                "status": "pending",
                "agent": agent_for_stage,
                "duration": None,
                "started_at": None,
                "completed_at": None,
                "subtasks": [{"title": name, "status": "pending", "duration": None}],
                "log_count": 0,
                "ticket_id": None,
                "ticket_title": name,
                "ticket_status": "pending",
            }]
        else:
            jobs = []

        stages.append({
            "key": key,
            "name": name,
            "icon": icon,
            "status": s_status,
            "jobs": jobs,
            "has_warning": any(j.get("has_warning") for j in jobs),
            "has_error": any(j.get("has_error") for j in jobs),
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


def _ticket_stage_status(ticket_status: str, stage_set: set, past_set: set, pre_set: set) -> str:
    """判定工单在某个阶段的 Job 状态: done / running / pending / failed"""
    # 工单已经过了这个阶段 → done
    if ticket_status in past_set:
        return "done"
    # 工单正在这个阶段
    if ticket_status in stage_set:
        if "rejected" in ticket_status or "failed" in ticket_status:
            return "failed"
        if "done" in ticket_status or "passed" in ticket_status:
            return "done"
        return "running"
    # 工单还没到这个阶段 → pending
    if ticket_status in pre_set or ticket_status == "pending":
        return "pending"
    # 兜底
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


@router.post("/{req_id}/rerun")
async def rerun_requirement(project_id: str, req_id: str, background_tasks: BackgroundTasks):
    """重新执行已完成的需求 — 重置工单状态，重新走开发流程"""
    existing = await db.fetch_one(
        "SELECT * FROM requirements WHERE id = ? AND project_id = ?",
        (req_id, project_id),
    )
    if not existing:
        raise HTTPException(404, "需求不存在")

    # 获取关联工单
    tickets = await db.fetch_all(
        "SELECT id, status FROM tickets WHERE requirement_id = ?", (req_id,),
    )

    # 重置所有工单为 pending
    for t in tickets:
        await db.update("tickets", {
            "status": "pending",
            "assigned_agent": None,
            "result": None,
            "updated_at": now_iso(),
        }, "id = ?", (t["id"],))

    # 重置需求状态为 decomposed（已拆单，等待工单执行）
    await db.update("requirements", {
        "status": "decomposed",
        "completed_at": None,
        "updated_at": now_iso(),
    }, "id = ?", (req_id,))

    await _log_requirement(
        project_id, req_id, "Orchestrator", "rerun",
        existing["status"], "decomposed", "需求重新执行：所有工单已重置"
    )

    await event_manager.publish_to_project(
        project_id, "requirement_status_changed",
        {"requirement_id": req_id, "title": existing["title"], "from": existing["status"], "to": "decomposed"},
    )

    logger.info("🔄 需求重新执行: %s (%s)", existing["title"], req_id)

    return {"message": "需求已重置，工单将重新执行", "status": "decomposed", "tickets_reset": len(tickets)}


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
