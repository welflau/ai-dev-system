"""
AI 自动开发系统 - 项目 API
"""
import json
from fastapi import APIRouter, HTTPException
from database import db
from models import ProjectCreate, ProjectUpdate
from utils import generate_id, now_iso
from git_manager import git_manager

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.post("")
async def create_project(req: ProjectCreate):
    """创建项目"""
    project_id = generate_id("PRJ")
    now = now_iso()

    # 初始化 Git 仓库
    repo_path = await git_manager.init_repo(project_id, req.name, req.description or "")

    # 如果提供了远程仓库 URL，立即配置
    remote_url = req.git_remote_url or ""
    if remote_url:
        await git_manager.set_remote(project_id, remote_url)

    data = {
        "id": project_id,
        "name": req.name,
        "description": req.description or "",
        "status": "active",
        "tech_stack": req.tech_stack or "",
        "config": "{}",
        "git_repo_path": repo_path,
        "git_remote_url": remote_url,
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
        "git_repo_exists": git_manager.repo_exists(project_id),
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


# ==================== Git 仓库 API ====================


@router.post("/{project_id}/git/remote")
async def set_git_remote(project_id: str, body: dict):
    """设置项目 Git 远程仓库"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    url = body.get("url", "")
    if not url:
        raise HTTPException(400, "远程仓库 URL 不能为空")

    # 确保仓库已初始化
    if not git_manager.repo_exists(project_id):
        await git_manager.init_repo(project_id, project["name"], project.get("description", ""))

    await git_manager.set_remote(project_id, url)
    await db.update("projects", {
        "git_remote_url": url,
        "updated_at": now_iso(),
    }, "id = ?", (project_id,))

    return {"status": "ok", "remote_url": url}


@router.get("/{project_id}/git/tree")
async def get_git_tree(project_id: str):
    """获取项目仓库文件树"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    tree = await git_manager.get_file_tree(project_id)
    return tree


@router.get("/{project_id}/git/log")
async def get_git_log(project_id: str, limit: int = 20):
    """获取项目 Git 提交日志"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    logs = await git_manager.get_log(project_id, limit)
    return {"commits": logs, "total": len(logs)}


@router.get("/{project_id}/git/file")
async def get_git_file(project_id: str, path: str):
    """读取仓库中的文件内容"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    content = await git_manager.get_file_content(project_id, path)
    if content is None:
        raise HTTPException(404, "文件不存在")

    return {"path": path, "content": content}


@router.get("/{project_id}/git/diff")
async def get_git_diff(project_id: str, commit: str = None):
    """获取 Git diff"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    diff = await git_manager.get_diff(project_id, commit)
    return {"diff": diff}
