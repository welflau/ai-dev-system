"""项目预览地址查询（兼容旧客户端）。"""
from fastapi import APIRouter

from runtime_facade import agents_deploy


router = APIRouter(prefix="/api/projects")


@router.get("/{project_id}/preview")
async def get_preview_url(project_id: str):
    """获取项目的本地预览 URL（兼容旧接口，优先返回 dev 环境）"""
    info = agents_deploy().DeployAgent.get_preview(project_id)
    if info is None:
        return {"preview_url": None}
    return {"preview_url": info["preview_url"], "port": info["port"], "env": info["env"]}
