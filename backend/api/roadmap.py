"""
AI 自动开发系统 - Roadmap API
提供甘特图 / 时间线所需的里程碑+需求+工单聚合数据
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
from database import db

router = APIRouter(prefix="/api/projects/{project_id}/roadmap", tags=["roadmap"])


# ==================== 辅助函数 ====================

def _parse_iso(iso_str: str | None) -> datetime | None:
    """安全解析 ISO 时间字符串"""
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except Exception:
        return None


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _calc_progress(tickets: list[dict]) -> int:
    """根据工单状态计算进度百分比"""
    if not tickets:
        return 0
    total = len(tickets)
    done = sum(1 for t in tickets if t["status"] in (
        "deployed", "testing_done",
    ))
    partial = sum(1 for t in tickets if t["status"] in (
        "development_done", "acceptance_passed",
        "testing_in_progress", "deploying",
    ))
    in_dev = sum(1 for t in tickets if t["status"] in (
        "architecture_in_progress", "architecture_done",
        "development_in_progress", "acceptance_rejected",
        "testing_failed",
    ))
    score = done * 1.0 + partial * 0.7 + in_dev * 0.3
    return min(100, int(score / total * 100))


# 需求状态到阶段映射
_REQ_PHASE_MAP = {
    "submitted": "planned",
    "analyzing": "analyzing",
    "decomposed": "planned",
    "in_progress": "in_progress",
    "paused": "paused",
    "completed": "completed",
    "cancelled": "cancelled",
}

# 工单状态到阶段映射
_TICKET_PHASE_MAP = {
    "pending": "planned",
    "architecture_in_progress": "architecture",
    "architecture_done": "architecture",
    "development_in_progress": "development",
    "development_done": "development",
    "acceptance_passed": "development",
    "acceptance_rejected": "development",
    "testing_in_progress": "testing",
    "testing_done": "testing",
    "testing_failed": "testing",
    "deploying": "deployment",
    "deployed": "completed",
    "cancelled": "cancelled",
}


@router.get("")
async def get_roadmap(project_id: str):
    """获取 Roadmap 数据 — 里程碑+需求+工单聚合时间轴

    返回:
    - milestones: 里程碑列表（含关联需求+工单）
    - unassigned_requirements: 未关联里程碑的需求
    - summary: 汇总统计
    - time_range: 整体时间范围
    """
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    # 查询里程碑
    milestones = await db.fetch_all(
        "SELECT * FROM milestones WHERE project_id = ? ORDER BY sort_order, created_at",
        (project_id,),
    )

    # 查询所有需求
    requirements = await db.fetch_all(
        "SELECT * FROM requirements WHERE project_id = ? ORDER BY created_at ASC",
        (project_id,),
    )

    # 查询所有工单
    all_tickets = await db.fetch_all(
        "SELECT * FROM tickets WHERE project_id = ? ORDER BY sort_order, created_at ASC",
        (project_id,),
    )

    # 按需求 ID 分组工单
    ticket_map: dict[str, list[dict]] = {}
    for t in all_tickets:
        rid = t["requirement_id"]
        ticket_map.setdefault(rid, []).append(t)

    # 按里程碑 ID 分组需求
    ms_req_map: dict[str, list[dict]] = {}
    unassigned_reqs = []
    for req in requirements:
        ms_id = req.get("milestone_id")
        if ms_id:
            ms_req_map.setdefault(ms_id, []).append(req)
        else:
            unassigned_reqs.append(req)

    # 时间边界
    now = datetime.now()
    global_start = now
    global_end = now

    def update_bounds(start_dt, end_dt):
        nonlocal global_start, global_end
        if start_dt and start_dt < global_start:
            global_start = start_dt
        if end_dt and end_dt > global_end:
            global_end = end_dt

    # === 构建里程碑数据 ===
    milestone_items = []
    for ms in milestones:
        ms_reqs = ms_req_map.get(ms["id"], [])

        # 里程碑时间范围
        ms_start = _parse_iso(ms.get("actual_start") or ms.get("planned_start")) or now
        ms_end = _parse_iso(ms.get("actual_end") or ms.get("planned_end")) or (ms_start + timedelta(days=14))

        # 构建里程碑下的需求列表
        req_items = []
        for req in ms_reqs:
            req_item = _build_req_item(req, ticket_map, now)
            req_items.append(req_item)
            update_bounds(
                _parse_iso(req_item["start"]),
                _parse_iso(req_item["end"]),
            )

        # 里程碑进度
        if ms_reqs:
            all_ms_tickets = []
            for req in ms_reqs:
                all_ms_tickets.extend(ticket_map.get(req["id"], []))
            ms_progress = _calc_progress(all_ms_tickets) if all_ms_tickets else ms.get("progress", 0)
        else:
            ms_progress = ms.get("progress", 0)

        update_bounds(ms_start, ms_end)

        # 延期检测
        is_delayed = False
        planned_end_dt = _parse_iso(ms.get("planned_end"))
        if planned_end_dt and now > planned_end_dt and ms_progress < 100 and ms["status"] not in ("completed", "cancelled"):
            is_delayed = True

        milestone_items.append({
            "id": ms["id"],
            "title": ms["title"],
            "description": ms.get("description", ""),
            "status": ms["status"],
            "source": ms.get("source", "ai_generated"),
            "progress": ms_progress,
            "is_delayed": is_delayed,
            "planned_start": ms.get("planned_start"),
            "planned_end": ms.get("planned_end"),
            "actual_start": ms.get("actual_start"),
            "actual_end": ms.get("actual_end"),
            "start": _iso(ms_start),
            "end": _iso(ms_end),
            "requirement_count": len(ms_reqs),
            "requirements": req_items,
        })

    # === 构建未关联里程碑的需求列表 ===
    unassigned_items = []
    for req in unassigned_reqs:
        req_item = _build_req_item(req, ticket_map, now)
        unassigned_items.append(req_item)
        update_bounds(
            _parse_iso(req_item["start"]),
            _parse_iso(req_item["end"]),
        )

    # 汇总
    total_reqs = len(requirements)
    completed_reqs = sum(1 for r in requirements if r["status"] == "completed")
    in_progress_reqs = sum(1 for r in requirements if r["status"] == "in_progress")
    total_tickets = len(all_tickets)
    done_tickets = sum(1 for t in all_tickets if t["status"] in ("deployed", "testing_done"))
    active_tickets = sum(1 for t in all_tickets if t["status"] not in ("pending", "deployed", "cancelled", "testing_done"))
    total_milestones = len(milestones)
    completed_milestones = sum(1 for m in milestones if m["status"] == "completed")
    delayed_milestones = sum(1 for m in milestone_items if m["is_delayed"])

    return {
        "milestones": milestone_items,
        "unassigned_requirements": unassigned_items,
        "summary": {
            "total_requirements": total_reqs,
            "completed_requirements": completed_reqs,
            "in_progress_requirements": in_progress_reqs,
            "total_tickets": total_tickets,
            "done_tickets": done_tickets,
            "active_tickets": active_tickets,
            "overall_progress": int(completed_reqs / total_reqs * 100) if total_reqs > 0 else 0,
            "total_milestones": total_milestones,
            "completed_milestones": completed_milestones,
            "delayed_milestones": delayed_milestones,
        },
        "time_range": {
            "start": _iso(global_start),
            "end": _iso(global_end),
        },
    }


def _build_req_item(req: dict, ticket_map: dict, now: datetime) -> dict:
    """构建单个需求的 Roadmap 数据"""
    req_tickets = ticket_map.get(req["id"], [])

    # 计算需求时间范围
    start_dt = _parse_iso(req["created_at"]) or now
    end_dt = _parse_iso(req.get("completed_at")) or None

    if not end_dt:
        latest = start_dt
        for t in req_tickets:
            t_end = _parse_iso(t.get("completed_at")) or _parse_iso(t.get("updated_at"))
            if t_end and t_end > latest:
                latest = t_end
        if req["status"] in ("completed", "cancelled"):
            end_dt = latest
        else:
            end_dt = max(latest, now) + timedelta(days=1)

    # 构建工单子项
    ticket_items = []
    for t in req_tickets:
        t_start = _parse_iso(t.get("started_at")) or _parse_iso(t["created_at"]) or start_dt
        t_end = _parse_iso(t.get("completed_at")) or None
        if not t_end:
            if t["status"] in ("deployed", "cancelled"):
                t_end = _parse_iso(t.get("updated_at")) or t_start
            else:
                t_end = max(t_start, now)

        ticket_items.append({
            "id": t["id"],
            "title": t["title"],
            "status": t["status"],
            "phase": _TICKET_PHASE_MAP.get(t["status"], "planned"),
            "type": t.get("type", "feature"),
            "module": t.get("module"),
            "priority": t.get("priority", 3),
            "assigned_agent": t.get("assigned_agent"),
            "start": _iso(t_start),
            "end": _iso(t_end),
            "dependencies": t.get("dependencies"),
        })

    progress = _calc_progress(req_tickets)

    return {
        "id": req["id"],
        "title": req["title"],
        "description": req.get("description", ""),
        "status": req["status"],
        "phase": _REQ_PHASE_MAP.get(req["status"], "planned"),
        "priority": req.get("priority", "medium"),
        "module": req.get("module"),
        "milestone_id": req.get("milestone_id"),
        "progress": progress,
        "start": _iso(start_dt),
        "end": _iso(end_dt),
        "ticket_count": len(req_tickets),
        "tickets": ticket_items,
    }
