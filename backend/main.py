"""
AI 自动开发系统 - 主入口
FastAPI 应用启动
"""
import asyncio
import logging
import os
import sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware

from config import APP_VERSION, settings
from database import db
from app_runtime.lifecycle import application_lifespan

# ==================== 统一日志配置 ====================
LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s  %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"

# Windows 控制台默认 GBK 编码，无法输出 emoji —— 强制 UTF-8
# 打包为 windowed exe 时 sys.stdout 可能为 None，需兜底
_console_stream = sys.stdout
if sys.platform == "win32" and _console_stream is not None and hasattr(_console_stream, "buffer"):
    import io
    try:
        _console_stream = io.TextIOWrapper(
            _console_stream.buffer, encoding="utf-8", errors="replace", line_buffering=True,
        )
    except Exception:
        _console_stream = sys.stdout
if _console_stream is None:
    _console_stream = open(os.devnull, "w", encoding="utf-8")
_console_handler = logging.StreamHandler(_console_stream)
_console_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))

# 同时输出到日志文件（便于排查；打包后写到 cwd/runtime，避免写 _MEIPASS）
_LOG_DIR = Path(os.getcwd()) if getattr(sys, "frozen", False) else Path(__file__).parent
try:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    _LOG_DIR = Path(os.getcwd())
_file_handler = logging.FileHandler(
    _LOG_DIR / "server.log", encoding="utf-8", mode="a",
)
_file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))

logging.basicConfig(
    level=logging.INFO,
    handlers=[_console_handler, _file_handler],
)
# 降低第三方库日志级别，避免刷屏
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

logger = logging.getLogger("main")

# Windows 上需要 Proactor 事件循环来支持 asyncio subprocess。
# Proactor 从 3.8 起就是 Windows 默认，这里显式设置是为了盖掉外部先行设置的
# Selector 策略（旧版 uvicorn 在 --reload / 多 worker 模式下会这么做）。
# 策略 API 自 3.14 起弃用、计划 3.16 移除：读取类名和调用都会报 DeprecationWarning，
# 所以放进 catch_warnings 里，并用 getattr 兜住类被移除后的 AttributeError。
if sys.platform == "win32":
    import warnings as _warnings
    with _warnings.catch_warnings():
        _warnings.simplefilter("ignore", DeprecationWarning)
        _proactor_policy = getattr(asyncio, "WindowsProactorEventLoopPolicy", None)
        if _proactor_policy is not None and hasattr(asyncio, "set_event_loop_policy"):
            asyncio.set_event_loop_policy(_proactor_policy())


def lifespan(app: FastAPI):
    return application_lifespan(db)


app = FastAPI(
    title="AI 自动开发系统",
    version=APP_VERSION,
    description="工单驱动的 AI 自动开发管理平台 + Git 仓库集成 + AI 聊天面板 + 智能 Roadmap",
    lifespan=lifespan,
)

# CORS：只放行本机来源（任意端口）+ CORS_ALLOW_ORIGINS 显式列出的来源。
# 前端由本服务同源托管（/app），同源请求不受 CORS 约束；此前的 allow_origins=["*"]
# 让用户浏览器里打开的任意网页都能跨域调用并读取本机 API 的返回。
# 注意 CORS 只管「浏览器里的跨域读取」，不是鉴权：非浏览器客户端不受它限制。
CORS_LOCAL_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.CORS_ALLOW_ORIGINS),
    allow_origin_regex=CORS_LOCAL_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局异常处理
_LOOPBACK_CLIENTS = frozenset({"127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"})


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """兜底 500。

    异常文本里可能带本机路径、SQL 片段或上游返回内容：
    - 本机调用方（回环地址）照旧拿到 str(exc)，方便在界面上直接看到原因；
    - 其他来源只拿到通用提示 + error_id，凭 error_id 到 server.log 里查详情。
    注意：前面若挂了同机反向代理，所有请求的来源都会是回环地址。
    """
    import uuid
    error_id = uuid.uuid4().hex[:12]
    logging.getLogger("main").error(
        "Unhandled exception [error_id=%s]: %s %s -> %s",
        error_id, request.method, request.url.path, exc, exc_info=exc,
    )
    client_host = (request.client.host if request.client else "") or ""
    if client_host in _LOOPBACK_CLIENTS:
        detail = str(exc)
    else:
        detail = f"服务器内部错误（error_id={error_id}），详情见服务端日志"
    return JSONResponse(status_code=500, content={"detail": detail, "error_id": error_id})

# 注册 API 路由
from api.projects import router as projects_router
from api.project_preview import router as project_preview_router, get_preview_url as get_preview_url
from api.repos import router as repos_router
from api.workspace_roots import router as workspace_roots_router
from api.requirements import router as requirements_router
from api.tickets import router as tickets_router
from api.agents import router as agents_router
from api.chat import router as chat_router
from api.chat import global_chat_router
from api.roadmap import router as roadmap_router
from api.milestones import router as milestones_router
from api.ci import router as ci_router
from api.bugs import router as bugs_router
from api.knowledge import router as knowledge_router
from api.mcp_status import router as mcp_status_router
from api.skills import router as skills_router
from api.traits import router as traits_router
from api.ue_engines import router as ue_engines_router
from api.commands import router as commands_router
from api.ue_framework import router as ue_framework_router
from api.image_gen import router as image_gen_router
from api.cloud_video_config import router as cloud_video_config_router
from api.ai_gen_tasks import router as ai_gen_tasks_router
from api.metrics import router as metrics_router
from api.local_images import router as local_images_router, serve_local_file as serve_local_file
from api.frontend_pages import (
    router as frontend_pages_router, frontend_dir,
    favicon as favicon, serve_frontend as serve_frontend,
)
from api.event_streams import global_router as global_events_router, global_events_stream as global_events_stream
from api.llm_config import (
    router as llm_config_router,
    llm_config as llm_config,
    llm_status as llm_status,
    llm_agents as llm_agents,
    llm_cli_models_refresh as llm_cli_models_refresh,
    llm_test as llm_test,
    llm_agent_config as llm_agent_config,
    llm_agent_config_delete as llm_agent_config_delete,
)
from services.llm_config import public_llm_fields as _public_llm_fields
from api.system import (
    router as system_router,
    health_check as health_check,
    get_available_paths as get_available_paths,
    open_path_in_explorer as open_path_in_explorer,
    open_in_browser as open_in_browser,
    get_agent_tools_status as get_agent_tools_status,
    set_agent_tools_status as set_agent_tools_status,
)
from api.sop_config import (
    router as sop_config_router,
    get_sop as get_sop,
    get_sop_config_full as get_sop_config_full,
    update_sop_config as update_sop_config,
    reload_sop as reload_sop,
)
# 保留这两个原有的 Python 调用入口。
from api.metrics import get_asyncio_tasks_detail as get_asyncio_tasks_detail, get_system_metrics as get_system_metrics
from api.art_assets import router as art_assets_router
from api.efficiency import router as efficiency_router
from api.competitor import router as competitor_router
from api.agent_test import router as agent_test_router, global_router as agent_test_global_router
from api.permissions import router as permissions_router
from api.hooks import router as hooks_router
from api.system_settings import router as system_settings_router
from api.automation import router as automation_router
from api.chat import internal_router as internal_router
from api.openspec import router as openspec_router
from api.plugins import router as plugins_router
from api.external_sessions import router as external_sessions_router
from api.session_materials import project_router as session_materials_project_router
from api.session_materials import global_router as session_materials_global_router

app.include_router(projects_router)
# repos 的前缀也是 /api/projects，但路径段（/repos/...）不和 projects 冲突
app.include_router(repos_router)
app.include_router(workspace_roots_router)
app.include_router(requirements_router)
app.include_router(tickets_router)
app.include_router(agents_router)
app.include_router(chat_router)
app.include_router(global_chat_router)
app.include_router(roadmap_router)
app.include_router(milestones_router)
app.include_router(ci_router)
app.include_router(bugs_router)
app.include_router(knowledge_router)
app.include_router(mcp_status_router)
app.include_router(skills_router)
app.include_router(traits_router)
app.include_router(ue_engines_router)
app.include_router(ue_framework_router)
app.include_router(image_gen_router)
app.include_router(cloud_video_config_router)
app.include_router(ai_gen_tasks_router)
app.include_router(art_assets_router)
app.include_router(commands_router)
app.include_router(efficiency_router)
app.include_router(competitor_router)
app.include_router(agent_test_router)
app.include_router(agent_test_global_router)
app.include_router(permissions_router)
app.include_router(hooks_router)
app.include_router(system_settings_router)
app.include_router(automation_router)
app.include_router(internal_router)
app.include_router(openspec_router)
app.include_router(plugins_router)
app.include_router(external_sessions_router)
app.include_router(session_materials_project_router)
app.include_router(session_materials_global_router)
app.include_router(global_events_router)


app.include_router(system_router)
app.include_router(sop_config_router)


app.include_router(project_preview_router)
app.include_router(llm_config_router)


app.include_router(metrics_router)


# ==================== 前端静态文件 ====================

# 开发环境：禁用静态文件缓存
from starlette.middleware.base import BaseHTTPMiddleware

class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

app.add_middleware(NoCacheStaticMiddleware)


class ArtResGuardMiddleware(BaseHTTPMiddleware):
    """守卫 /art-res 静态服务：拦截敏感路径，防止私有/未入库资产被直接访问。

    G_ArtRes 根目录下存在 private/（含未授权角色模型）、.git/、node_modules/
    等不应通过 HTTP 暴露的内容。StaticFiles 挂载整个根目录时，这些路径必须
    在进入静态文件处理前拦掉，否则会通过 /art-res/private/... 直接下载。
    """
    _FORBIDDEN = ("/art-res/private", "/art-res/.git", "/art-res/node_modules")

    async def dispatch(self, request, call_next):
        path = request.url.path
        blocked = any(path == p or path.startswith(p + "/") for p in self._FORBIDDEN)
        if blocked:
            return Response(status_code=404)
        return await call_next(request)


app.add_middleware(ArtResGuardMiddleware)

if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

# 挂载聊天图片目录（用于历史消息图片回显）
from config import BASE_DIR as _BASE_DIR
_chat_images_dir = _BASE_DIR / "chat_images"
_chat_images_dir.mkdir(exist_ok=True)
app.mount("/chat-images", StaticFiles(directory=str(_chat_images_dir)), name="chat-images")

# 挂载截图目录（测试报告截图访问）
_screenshots_dir = _BASE_DIR / "screenshots"
_screenshots_dir.mkdir(exist_ok=True)
app.mount("/screenshots", StaticFiles(directory=str(_screenshots_dir)), name="screenshots")

# 挂载生成图片目录（AI 生图结果访问）
_generated_images_dir = _BASE_DIR / "generated-images"
_generated_images_dir.mkdir(exist_ok=True)
app.mount("/generated-images", StaticFiles(directory=str(_generated_images_dir)), name="generated-images")

# 挂载美术资产库目录（G_ArtRes，供资产库缩略图访问）。
# 文件路径格式为相对 G_ArtRes 根目录（如 icons/lucide/xxx.svg），前端用
# window.artAssetsBase + file_path 拼接访问。private/、.git/、node_modules/
# 由 ArtResGuardMiddleware 拦截。
_art_res_path = settings.ART_ASSETS_LOCAL_PATH
if _art_res_path and Path(_art_res_path).exists():
    app.mount("/art-res", StaticFiles(directory=str(_art_res_path)), name="art-res")
else:
    logger.warning("ART_ASSETS_LOCAL_PATH 未配置或目录不存在，跳过 /art-res 静态挂载（资产缩略图不可用）")


import mimetypes as _mimetypes
_mimetypes.add_type("model/gltf-binary", ".glb")
_mimetypes.add_type("model/gltf+json", ".gltf")
_mimetypes.add_type("image/webp", ".webp")


app.include_router(local_images_router)
app.include_router(frontend_pages_router)


# ==================== 启动入口 ====================

if __name__ == "__main__":
    import uvicorn, shutil as _sh
    # 每次启动清除 __pycache__，防止旧 .pyc 导致代码更改不生效
    for _pc in Path(__file__).parent.rglob("__pycache__"):
        _sh.rmtree(_pc, ignore_errors=True)
    # 注意：reload 模式下 uvicorn 会 fork 子进程并用字符串 "main:app" 重新 import，
    # 子进程的 sys.path 可能不包含 backend/，导致加载到错误的 main 模块。
    # 因此始终禁用 reload，改用外部工具（如 watchdog）或手动重启。
    uvicorn.run(
        app,                              # 直接传 app 对象，避免字符串解析路径问题
        host=settings.HOST,
        port=settings.PORT,
        reload=False,                     # 永远不开 reload
    )

