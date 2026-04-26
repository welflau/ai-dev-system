"""
AI 自动开发系统 - CI/CD Pipeline API

Phase A 改造：pipeline-definition 新端点 + 现有端点走 `ci_loader` 分派。
Web 项目行为零差异（strategy 内部委托到原 ci_pipeline + DeployAgent）。
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ci.loader import ci_loader
from ci_pipeline import ci_pipeline
from database import db
from models import CIBuildTrigger

logger = logging.getLogger("api.ci")

router = APIRouter(prefix="/api/projects/{project_id}/ci", tags=["ci"])


# ==================== Pipeline 定义（前端动态渲染用） ====================


@router.get("/pipeline-definition")
async def get_pipeline_definition(project_id: str):
    """返回按项目 traits 匹配的 CI 策略定义（stages / environments / build_types）

    前端首次打开「交付 & 环境」页调一次，根据返回动态生成 pipeline 进度条 +
    环境卡片 + "手动触发"下拉。
    """
    project = await db.fetch_one("SELECT id FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")
    strategy = await ci_loader.pick_for_project(project_id)
    return strategy.to_definition()


@router.get("/strategies")
async def list_strategies():
    """调试 / 管理 UI 用：列出所有已注册的 CI 策略"""
    return {"strategies": [s.to_definition() for s in ci_loader.all_strategies()]}


# ==================== CI 状态 & 构建（保留向后兼容） ====================


@router.get("/status")
async def get_ci_status(project_id: str):
    """获取项目 CI/CD Pipeline 总览"""
    project = await db.fetch_one("SELECT id FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")
    # pipeline_status 目前跟 strategy 无关（就是读 ci_builds 表），保持原调用
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
    """手动触发构建——通过 strategy 分派

    不再硬编码 build_type 白名单；由 strategy.build_types() 决定可用类型。
    """
    project = await db.fetch_one("SELECT id FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    strategy = await ci_loader.pick_for_project(project_id)
    valid_ids = {bt.id for bt in strategy.build_types()}
    if valid_ids and body.build_type not in valid_ids:
        raise HTTPException(
            400,
            f"策略 {strategy.name} 不支持构建类型 {body.build_type}；"
            f"可选: {sorted(valid_ids)}",
        )

    result = await strategy.trigger_build(project_id, body.build_type, trigger="manual")
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(400, result["error"])
    return result


@router.post("/builds/{build_id}/cancel")
async def cancel_build(project_id: str, build_id: str):
    """取消构建"""
    ok = await ci_pipeline.cancel_build(build_id)
    if not ok:
        raise HTTPException(400, "无法取消（构建已完成或不存在）")
    return {"status": "cancelled"}


# ==================== 环境管理（新：迁移自 api/projects.py） ====================
#
# 原端点 /projects/{pid}/environments 保留（兼容），这里新增 strategy 驱动版本：
#   GET    /projects/{pid}/ci/environments                 —— 所有环境状态
#   POST   /projects/{pid}/ci/environments/{env}/deploy    —— 部署
#   POST   /projects/{pid}/ci/environments/{env}/stop      —— 停止
#
# 内部都走 strategy.{deploy_environment, stop_environment, get_all_environments}。


class DeployEnvRequest(BaseModel):
    branch: str = Field(default="", description="强制部署指定分支；默认用 strategy 约定")


@router.get("/environments")
async def list_environments(project_id: str):
    """返回 strategy 定义的所有环境当前状态"""
    project = await db.fetch_one("SELECT id FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")
    strategy = await ci_loader.pick_for_project(project_id)
    envs = await strategy.get_all_environments(project_id)
    return {"strategy": strategy.name, "environments": envs}


@router.post("/environments/{env_name}/deploy")
async def deploy_environment(project_id: str, env_name: str, body: DeployEnvRequest = None):
    """手动触发环境部署（通过 strategy）"""
    project = await db.fetch_one("SELECT id FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    strategy = await ci_loader.pick_for_project(project_id)
    kwargs = {}
    if body and body.branch:
        kwargs["branch"] = body.branch

    result = await strategy.deploy_environment(project_id, env_name, **kwargs)
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(400, result["error"])
    if isinstance(result, dict) and result.get("status") == "error":
        raise HTTPException(500, result.get("message") or f"{env_name} 部署失败")
    return result


@router.post("/environments/{env_name}/stop")
async def stop_environment(project_id: str, env_name: str):
    """停止环境（通过 strategy）"""
    strategy = await ci_loader.pick_for_project(project_id)
    result = await strategy.stop_environment(project_id, env_name)
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(400, result["error"])
    return result
