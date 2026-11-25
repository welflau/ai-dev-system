"""系统健康状态、本地目录、桌面应用与 Agent 工具开关。"""
from pathlib import Path
import webbrowser

from fastapi import APIRouter, HTTPException
from pydantic import AnyHttpUrl, BaseModel, TypeAdapter, ValidationError
from starlette.concurrency import run_in_threadpool

from config import APP_VERSION, agent_tools_enabled
from services.agent_tools_settings import save_agent_tools_enabled
from services.file_manager import RevealPathNotFound, reveal_path

router = APIRouter(prefix="/api")
_WEB_URL = TypeAdapter(AnyHttpUrl)

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


class OpenPathRequest(BaseModel):
    path: str | None = None


@router.post("/system/open_path")
async def open_path_in_explorer(body: OpenPathRequest):
    """在系统文件管理器中打开指定路径。"""
    raw = (OpenPathRequest.model_validate(body).path or "").strip()
    if not raw:
        raise HTTPException(400, "path 不能为空")
    try:
        folder = await run_in_threadpool(reveal_path, Path(raw))
    except RevealPathNotFound as exc:
        raise HTTPException(404, f"路径不存在: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(500, f"打开失败: {exc}") from exc
    return {"ok": True, "opened": str(folder)}


@router.get("/open-in-browser")
async def open_in_browser(url: str):
    """用系统默认浏览器打开 URL（网页 Tab 被 X-Frame-Options 拒绝内嵌时的兜底出口）"""
    scheme, sep, rest = url.partition("://")
    if not sep or scheme.lower() not in {"http", "https"}:
        raise HTTPException(400, "仅支持 http/https URL")
    try:
        _WEB_URL.validate_python(url, strict=True)
    except ValidationError:
        raise HTTPException(400, "http/https URL 格式无效") from None
    # 只统一协议大小写；保留调用方的路径、查询编码及片段。
    target = f"{scheme.lower()}://{rest}"
    try:
        opened = await run_in_threadpool(webbrowser.open, target)
    except (webbrowser.Error, OSError) as exc:
        raise HTTPException(500, "无法调起系统浏览器") from exc
    if not opened:
        raise HTTPException(500, "无法调起系统浏览器")
    return {"ok": True}


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
