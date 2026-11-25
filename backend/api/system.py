"""系统健康状态、本地项目目录建议与 Agent 工具开关。"""
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from config import APP_VERSION, agent_tools_enabled
from services.agent_tools_settings import save_agent_tools_enabled

router = APIRouter(prefix="/api")

PROJECT_PATH_SUGGESTIONS = (
    Path("D:/Projects"), Path("D:/AIProjects"), Path("D:/MyProjects"),
    Path("D:/A_Works"), Path("D:/Works"), Path("C:/Projects"),
    Path("C:/Users/admin/Documents/Projects"), Path("C:/Users/admin/Documents"),
)


@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "version": APP_VERSION}


@router.get("/filesystem/available-paths")
async def get_available_paths():
    """获取常用的本地路径列表"""
    return {"paths": [
        {"path": str(path), "label": path.name, "exists": path.exists() and path.is_dir()}
        for path in PROJECT_PATH_SUGGESTIONS
    ]}


class AgentToolsUpdate(BaseModel):
    enabled: bool = False


@router.get("/settings/agent-tools")
async def get_agent_tools_status():
    """获取 Agent Tool Use 开关状态"""
    return {"enabled": agent_tools_enabled()}


@router.post("/settings/agent-tools")
async def set_agent_tools_status(body: AgentToolsUpdate):
    """运行时切换 Agent Tool Use 开关（写入 .env 持久化）"""
    # 旧 Python 入口也接受 dict，和 HTTP 请求使用同一套布尔校验。
    enabled = AgentToolsUpdate.model_validate(body).enabled
    save_agent_tools_enabled(enabled)
    return {"enabled": enabled, "message": f"Agent Tool Use {'已开启' if enabled else '已关闭'}"}
