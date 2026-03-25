"""
AI 自动开发系统 - 主入口
FastAPI 应用启动
"""
import asyncio
import logging
import os
import sys
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from database import db

# ==================== 统一日志配置 ====================
LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s  %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"

# Windows 控制台默认 GBK 编码，无法输出 emoji —— 强制 UTF-8
_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
if sys.platform == "win32":
    import io
    _console_handler.stream = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True,
    )

# 同时输出到日志文件（便于排查）
_LOG_DIR = Path(__file__).parent
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

# Windows 上需要使用 WindowsProactorEventLoopPolicy 来支持 asyncio subprocess (Python 3.14)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info("=" * 60)
    logger.info("  AI 自动开发系统 v0.9.0")
    logger.info("  工单管理 + Git 仓库集成 + AI 聊天面板")
    logger.info("=" * 60)

    await db.connect()
    await db.init_tables()
    logger.info("SQLite 数据库就绪")

    from llm_client import llm_client
    if llm_client.is_configured:
        logger.info("LLM 已配置: %s / %s (format=%s)", llm_client.base_url, llm_client.model, llm_client.api_format)
    else:
        logger.warning("LLM 未配置，将使用规则引擎降级")

    from git_manager import PROJECTS_DIR, git_manager
    logger.info("Git 项目仓库目录: %s", PROJECTS_DIR)

    # 从数据库恢复自定义 git_repo_path 映射
    projects = await db.fetch_all(
        "SELECT id, git_repo_path FROM projects WHERE git_repo_path IS NOT NULL AND git_repo_path != ''"
    )
    restored = 0
    for p in projects:
        repo_path = p["git_repo_path"]
        default_path = str(PROJECTS_DIR / p["id"])
        if repo_path != default_path:
            git_manager.set_project_path(p["id"], repo_path)
            restored += 1
    if restored:
        logger.info("已恢复 %d 个项目的自定义仓库路径映射", restored)

    logger.info("Server: http://localhost:%s", settings.PORT)
    logger.info("App:    http://localhost:%s/app", settings.PORT)
    logger.info("=" * 60)

    yield

    # 关闭时
    await db.disconnect()
    logger.info("数据库连接已关闭")


app = FastAPI(
    title="AI 自动开发系统",
    version="0.9.0",
    description="工单驱动的 AI 自动开发管理平台 + Git 仓库集成 + AI 聊天面板",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 API 路由
from api.projects import router as projects_router
from api.requirements import router as requirements_router
from api.tickets import router as tickets_router
from api.agents import router as agents_router
from api.chat import router as chat_router

app.include_router(projects_router)
app.include_router(requirements_router)
app.include_router(tickets_router)
app.include_router(agents_router)
app.include_router(chat_router)


# ==================== 系统端点 ====================


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "version": "0.9.0"}


@app.get("/api/llm/status")
async def llm_status():
    """LLM 状态"""
    from llm_client import llm_client
    return {
        "configured": llm_client.is_configured,
        "base_url": llm_client.base_url if llm_client.is_configured else None,
        "model": llm_client.model if llm_client.is_configured else None,
        "timeout": llm_client.timeout,
        "max_retries": llm_client.max_retries,
    }


@app.post("/api/llm/config")
async def llm_config(body: dict):
    """动态更新 LLM 配置并持久化到 .env"""
    from llm_client import llm_client
    from config import BASE_DIR

    # 更新运行时
    if "base_url" in body:
        llm_client.base_url = (body["base_url"] or "").rstrip("/")
    if "api_key" in body:
        llm_client.api_key = body["api_key"] or ""
    if "model" in body:
        llm_client.model = body["model"] or "gpt-4"
    if "timeout" in body:
        llm_client.timeout = int(body.get("timeout", 60))
    if "max_retries" in body:
        llm_client.max_retries = int(body.get("max_retries", 3))

    # 同步更新 settings
    settings.LLM_BASE_URL = llm_client.base_url
    settings.LLM_API_KEY = llm_client.api_key
    settings.LLM_MODEL = llm_client.model
    settings.LLM_TIMEOUT = llm_client.timeout
    settings.LLM_MAX_RETRIES = llm_client.max_retries

    # 持久化到 .env
    env_path = BASE_DIR / ".env"
    env_lines = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env_lines[k.strip()] = v.strip()

    env_lines["LLM_BASE_URL"] = llm_client.base_url
    env_lines["LLM_API_KEY"] = llm_client.api_key
    env_lines["LLM_MODEL"] = llm_client.model
    env_lines["LLM_TIMEOUT"] = str(llm_client.timeout)
    env_lines["LLM_MAX_RETRIES"] = str(llm_client.max_retries)

    env_path.write_text(
        "\n".join(f"{k}={v}" for k, v in env_lines.items()) + "\n",
        encoding="utf-8",
    )

    return {
        "status": "ok",
        "configured": llm_client.is_configured,
        "model": llm_client.model,
    }


@app.post("/api/llm/test")
async def llm_test():
    """测试 LLM 连接"""
    from llm_client import llm_client
    result = await llm_client.test_connection()
    return result


@app.get("/api/filesystem/available-paths")
async def get_available_paths():
    """获取常用的本地路径列表"""
    import os
    from pathlib import Path

    # 定义常用的项目路径
    common_paths = [
        "D:/Projects/",
        "D:/AIProjects/",
        "D:/MyProjects/",
        "D:/A_Works/",
        "D:/Works/",
        "C:/Projects/",
        "C:/Users/admin/Documents/Projects/",
        "C:/Users/admin/Documents/",
    ]

    available_paths = []

    for path_str in common_paths:
        path = Path(path_str)
        if path.exists() and path.is_dir():
            available_paths.append({
                "path": str(path),
                "label": path.name,
                "exists": True
            })
        else:
            # 路径不存在，但可以作为建议
            available_paths.append({
                "path": str(path),
                "label": path.name,
                "exists": False
            })

    return {"paths": available_paths}


# ==================== 前端静态文件 ====================

# 挂载前端静态文件
frontend_dir = Path(settings.FRONTEND_DIR)
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


@app.get("/app")
@app.get("/app/{path:path}")
async def serve_frontend(path: str = ""):
    """提供前端页面"""
    index_file = frontend_dir / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return JSONResponse(
        {"message": "前端文件未找到，请确保 frontend/ 目录存在"},
        status_code=404,
    )


# ==================== 启动入口 ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
