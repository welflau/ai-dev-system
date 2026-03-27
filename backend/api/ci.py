"""
AI 自动开发系统 - CI/CD Pipeline API
"""
import logging
from fastapi import APIRouter, HTTPException
from database import db
from models import CIBuildTrigger
from ci_pipeline import ci_pipeline

logger = logging.getLogger("api.ci")

router = APIRouter(prefix="/api/projects/{project_id}/ci", tags=["ci"])


@router.get("/status")
async def get_ci_status(project_id: str):
    """获取项目 CI/CD Pipeline 总览"""
    project = await db.fetch_one("SELECT id FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")
    return await ci_pipeline.get_pipeline_status(project_id)


@router.get("/builds")
async def list_builds(project_id: str, build_type: str = None, limit: int = 20, offset: int = 0):
    """获取构建历史"""
    builds = await ci_pipeline.get_build_history(project_id, build_type, limit, offset)
    return {"builds": builds, "total": len(builds)}


@router.get("/builds/{build_id}")
async def get_build(project_id: str, build_id: str):
    """获取单个构建详情"""
    build = await ci_pipeline.get_build_detail(build_id)
    if not build or build["project_id"] != project_id:
        raise HTTPException(404, "构建记录不存在")
    return build


@router.post("/builds/trigger")
async def trigger_build(project_id: str, body: CIBuildTrigger):
    """手动触发构建"""
    project = await db.fetch_one("SELECT id FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    valid_types = ("develop_build", "master_build", "deploy")
    if body.build_type not in valid_types:
        raise HTTPException(400, f"无效的构建类型，可选: {', '.join(valid_types)}")

    result = await ci_pipeline.trigger_build(project_id, body.build_type, trigger="manual")
    return result


@router.post("/builds/{build_id}/cancel")
async def cancel_build(project_id: str, build_id: str):
    """取消构建"""
    ok = await ci_pipeline.cancel_build(build_id)
    if not ok:
        raise HTTPException(400, "无法取消（构建已完成或不存在）")
    return {"status": "cancelled"}
