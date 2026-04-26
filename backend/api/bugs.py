"""
AI 自动开发系统 - BUG 管理 API
BUG 流程：open → in_dev → in_test → fixed
跳过 PM / 架构设计，直接 DevAgent → TestAgent
"""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List

from database import db
from utils import generate_id, now_iso
from events import event_manager

logger = logging.getLogger("bugs")

router = APIRouter(prefix="/api/projects/{project_id}/bugs", tags=["bugs"])

# BUG 状态流转
BUG_STATUS_FLOW = {
    "open": "in_dev",
    "in_dev": "in_test",
    "in_test": "fixed",
}

PRIORITY_LABELS = {
    "critical": "🔴 紧急",
    "high": "🟠 高",
    "medium": "🟡 中",
    "low": "🟢 低",
}

STATUS_LABELS = {
    "open": "待处理",
    "in_dev": "修复中",
    "in_test": "测试中",
    "fixed": "已修复",
}


# ==================== 请求模型 ====================

class BugCreate(BaseModel):
    title: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    priority: str = Field(default="medium")
    requirement_id: Optional[str] = None


class BugUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    requirement_id: Optional[str] = None
    fix_notes: Optional[str] = None


# ==================== 接口 ====================

@router.get("")
async def list_bugs(project_id: str, status: Optional[str] = None):
    """获取项目 BUG 列表"""
    await _check_project_exists(project_id)
    if status:
        bugs = await db.fetch_all(
            "SELECT * FROM bugs WHERE project_id = ? AND status = ? ORDER BY created_at DESC",
            (project_id, status),
        )
    else:
        bugs = await db.fetch_all(
            "SELECT * FROM bugs WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        )
    return {"bugs": bugs, "total": len(bugs)}


@router.post("")
async def create_bug(project_id: str, req: BugCreate):
    """创建 BUG"""
    await _check_project_exists(project_id)
    if req.priority not in ("critical", "high", "medium", "low"):
        raise HTTPException(400, "priority 无效")

    bug_id = generate_id("bug")
    now = now_iso()
    await db.insert("bugs", {
        "id": bug_id,
        "project_id": project_id,
        "requirement_id": req.requirement_id,
        "title": req.title,
        "description": req.description,
        "priority": req.priority,
        "status": "open",
        "version_id": None,
        "fix_notes": None,
        "created_at": now,
        "updated_at": now,
        "fixed_at": None,
    })
    bug = await db.fetch_one("SELECT * FROM bugs WHERE id = ?", (bug_id,))
    await event_manager.emit("bug_created", {"project_id": project_id, "bug": bug})
    logger.info("BUG 已创建: %s [%s]", req.title, bug_id)
    return bug


@router.get("/{bug_id}")
async def get_bug(project_id: str, bug_id: str):
    """获取 BUG 详情"""
    bug = await _get_bug_or_404(project_id, bug_id)
    return bug


@router.patch("/{bug_id}")
async def update_bug(project_id: str, bug_id: str, req: BugUpdate):
    """更新 BUG 信息"""
    bug = await _get_bug_or_404(project_id, bug_id)

    update_data = {"updated_at": now_iso()}
    if req.title is not None:
        update_data["title"] = req.title
    if req.description is not None:
        update_data["description"] = req.description
    if req.priority is not None:
        if req.priority not in ("critical", "high", "medium", "low"):
            raise HTTPException(400, "priority 无效")
        update_data["priority"] = req.priority
    if req.status is not None:
        if req.status not in ("open", "in_dev", "in_test", "fixed"):
            raise HTTPException(400, "status 无效")
        update_data["status"] = req.status
        if req.status == "fixed":
            update_data["fixed_at"] = now_iso()
    if req.requirement_id is not None:
        update_data["requirement_id"] = req.requirement_id
    if req.fix_notes is not None:
        update_data["fix_notes"] = req.fix_notes

    await db.update("bugs", update_data, "id = ?", (bug_id,))
    bug = await db.fetch_one("SELECT * FROM bugs WHERE id = ?", (bug_id,))
    await event_manager.emit("bug_updated", {"project_id": project_id, "bug": bug})
    return bug


@router.delete("/{bug_id}")
async def delete_bug(project_id: str, bug_id: str):
    """删除 BUG"""
    await _get_bug_or_404(project_id, bug_id)
    await db.delete("bugs", "id = ?", (bug_id,))
    return {"status": "ok", "message": "BUG 已删除"}


@router.post("/{bug_id}/start-fix")
async def start_bug_fix(project_id: str, bug_id: str):
    """触发 BUG 修复工作流（DevAgent → TestAgent）"""
    bug = await _get_bug_or_404(project_id, bug_id)
    if bug["status"] != "open":
        raise HTTPException(400, f"BUG 当前状态为 {bug['status']}，只有 open 状态才能触发修复")

    # 更新状态为 in_dev
    await db.update("bugs", {
        "status": "in_dev",
        "updated_at": now_iso(),
    }, "id = ?", (bug_id,))

    # 异步触发 orchestrator
    import asyncio
    from orchestrator import orchestrator
    asyncio.create_task(orchestrator.run_bug_fix(project_id, bug_id))

    bug = await db.fetch_one("SELECT * FROM bugs WHERE id = ?", (bug_id,))
    logger.info("BUG 修复工作流已触发: %s", bug_id)
    return {"status": "ok", "message": "修复工作流已启动", "bug": bug}


# ==================== 内部工具 ====================

async def _check_project_exists(project_id: str):
    project = await db.fetch_one("SELECT id FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")
    return project


async def _get_bug_or_404(project_id: str, bug_id: str) -> dict:
    bug = await db.fetch_one(
        "SELECT * FROM bugs WHERE id = ? AND project_id = ?",
        (bug_id, project_id),
    )
    if not bug:
        raise HTTPException(404, "BUG 不存在")
    return bug
