"""
AI 自动开发系统 - 项目 API
"""
import json
from fastapi import APIRouter, HTTPException
from database import db
from models import ProjectCreate, ProjectUpdate
from utils import generate_id, now_iso

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.post("")
async def create_project(req: ProjectCreate):
    """创建项目"""
    project_id = generate_id("PRJ")
    now = now_iso()
    data = {
        "id": project_id,
        "name": req.name,
        "description": req.description or "",
        "status": "active",
        "tech_stack": req.tech_stack or "",
        "config": "{}",
        "created_at": now,
        "updated_at": now,
    }
    await db.insert("projects", data)
    return {"id": project_id, **data}


@router.get("")
async def list_projects():
    """获取项目列表"""
    projects = await db.fetch_all(
        "SELECT * FROM projects ORDER BY created_at DESC"
    )
    return {"projects": projects, "total": len(projects)}


@router.get("/{project_id}")
async def get_project(project_id: str):
    """获取项目详情"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    # 附带统计信息
    req_count = await db.fetch_one(
        "SELECT COUNT(*) as count FROM requirements WHERE project_id = ?",
        (project_id,),
    )
    ticket_count = await db.fetch_one(
        "SELECT COUNT(*) as count FROM tickets WHERE project_id = ?",
        (project_id,),
    )
    ticket_stats = await db.fetch_all(
        "SELECT status, COUNT(*) as count FROM tickets WHERE project_id = ? GROUP BY status",
        (project_id,),
    )

    return {
        **project,
        "stats": {
            "requirements": req_count["count"] if req_count else 0,
            "tickets": ticket_count["count"] if ticket_count else 0,
            "ticket_by_status": {row["status"]: row["count"] for row in ticket_stats},
        },
    }


@router.put("/{project_id}")
async def update_project(project_id: str, req: ProjectUpdate):
    """更新项目"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    update_data = {k: v for k, v in req.dict(exclude_unset=True).items() if v is not None}
    if update_data:
        update_data["updated_at"] = now_iso()
        await db.update("projects", update_data, "id = ?", (project_id,))

    return await get_project(project_id)


@router.delete("/{project_id}")
async def delete_project(project_id: str):
    """删除项目（归档）"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    await db.update("projects", {"status": "archived", "updated_at": now_iso()}, "id = ?", (project_id,))
    return {"message": "项目已归档"}
