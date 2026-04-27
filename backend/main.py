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
from fastapi import FastAPI, HTTPException
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
    logger.info("  AI 自动开发系统 v0.10.0")
    logger.info("  工单管理 + Git 仓库集成 + AI 聊天面板 + 智能 Roadmap")
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

    # 从数据库恢复自定义 git_repo_path 映射 + push remote 配置
    import json as _json
    projects = await db.fetch_all(
        "SELECT id, git_repo_path, git_remote_url, git_remotes, git_push_remote FROM projects"
    )
    restored = 0
    for p in projects:
        repo_path = p.get("git_repo_path") or ""
        if repo_path:
            default_path = str(PROJECTS_DIR / p["id"])
            if repo_path != default_path:
                git_manager.set_project_path(p["id"], repo_path)
                restored += 1

        # 恢复 push remote 配置
        push_remote = p.get("git_push_remote") or "origin"
        git_manager.set_push_remote(p["id"], push_remote)

        # 补全旧数据：git_remotes 空但 git_remote_url 有值 → 自动迁移
        git_remotes_raw = p.get("git_remotes") or "[]"
        if (git_remotes_raw == "[]" or not git_remotes_raw) and p.get("git_remote_url"):
            await db.update("projects", {
                "git_remotes": _json.dumps([{"name": "origin", "url": p["git_remote_url"]}])
            }, "id = ?", (p["id"],))

    if restored:
        logger.info("已恢复 %d 个项目的自定义仓库路径映射", restored)

    # 补录现有 docs 文件到 knowledge_index（首次启动迁移）
    try:
        from api.knowledge import _upsert_knowledge_index, GLOBAL_DOCS_DIR, PROJECTS_DIR as K_PROJECTS_DIR
        from config import BASE_DIR as _BDIR
        SYSTEM_ROOT = _BDIR.parent  # F:\A_Works\ai-dev-system
        indexed = 0

        # 1. 系统自身的 docs/ 和 dev-notes/（全局知识，filename 带前缀区分）
        for sys_dir, prefix in [
            (SYSTEM_ROOT / "docs",      "sys_docs__"),
            (SYSTEM_ROOT / "dev-notes", "sys_devnotes__"),
        ]:
            if sys_dir.is_dir():
                for md in sorted(sys_dir.glob("*.md")):
                    fname = prefix + md.name
                    await _upsert_knowledge_index(None, fname, md.read_text(encoding="utf-8", errors="replace"))
                    indexed += 1

        # 2. 用户在全局知识库 Tab 手动写入的文档
        for md in GLOBAL_DOCS_DIR.glob("*.md"):
            await _upsert_knowledge_index(None, md.name, md.read_text(encoding="utf-8", errors="replace"))
            indexed += 1

        # 3. 各项目的 docs/
        for pid_dir in K_PROJECTS_DIR.iterdir():
            docs_dir = pid_dir / "docs"
            if docs_dir.is_dir():
                for md in docs_dir.glob("*.md"):
                    await _upsert_knowledge_index(pid_dir.name, md.name, md.read_text(encoding="utf-8", errors="replace"))
                    indexed += 1
        # 强制 rebuild（确保 tokenizer 变更后旧数据被重建）
        # 先 integrity-check 刷新 FTS5 schema 缓存，再 rebuild
        await db.execute("INSERT INTO knowledge_fts(knowledge_fts) VALUES('integrity-check')")
        await db.execute("INSERT INTO knowledge_fts(knowledge_fts) VALUES('rebuild')")
        if indexed:
            logger.info("知识库 FTS5 索引：补录 %d 个文档", indexed)
    except Exception as e:
        logger.warning("知识库 FTS5 补录失败（忽略）: %s", e)

    # 补录已完成工单到 tickets_fts（首次启动迁移）
    try:
        from api.knowledge import _upsert_tickets_fts
        done_tickets = await db.fetch_all("""
            SELECT t.id, t.project_id, t.title, t.description,
                   (SELECT tl.detail FROM ticket_logs tl
                    WHERE tl.ticket_id = t.id AND tl.action = 'reflection'
                    ORDER BY tl.created_at DESC LIMIT 1) AS reflection_detail
            FROM tickets t
            WHERE t.status IN ('acceptance_passed', 'testing_done', 'deployed', 'development_done')
        """)
        fts_indexed = 0
        for t in done_tickets:
            text = f"{t['title']} {t['description'] or ''}"
            if t["reflection_detail"]:
                try:
                    ref = _json.loads(t["reflection_detail"])
                    root_cause = ref.get("reflection", {}).get("root_cause", "")
                    if root_cause:
                        text += f" {root_cause}"
                except Exception:
                    pass
            await _upsert_tickets_fts(t["id"], t["project_id"], text)
            fts_indexed += 1
        if fts_indexed:
            logger.info("工单历史 FTS5 索引：补录 %d 个工单", fts_indexed)
    except Exception as e:
        logger.warning("工单历史 FTS5 补录失败（忽略）: %s", e)
    # tickets_fts 无需 rebuild（internal content，INSERT 后直接可搜）

    # 启动工单轮询调度器
    from orchestrator import orchestrator
    # 启动内部事件总线（事件驱动，主调度方式）
    bus_task = asyncio.create_task(orchestrator.start_event_bus())
    logger.info("内部事件总线已启动")

    # 轮询调度器降为兜底（30s 间隔）
    poll_task = asyncio.create_task(orchestrator.poll_loop(interval=30))
    logger.info("工单轮询调度器已启动 (30s 兜底)")

    # 启动 CI/CD Pipeline 调度器
    from ci_pipeline import ci_pipeline
    ci_task = asyncio.create_task(ci_pipeline.start_scheduler())
    logger.info("CI/CD Pipeline 调度器已启动")

    # 启动 MCP 客户端（可选：只启动 mcp_servers.json 里 enabled=true 的 server）
    try:
        from mcp_client import mcp_client
        await mcp_client.start_enabled_servers()
        active = [n for n, s in mcp_client.get_status().get("servers", {}).items()
                  if s.get("status") == "running"]
        if active:
            logger.info("MCP 客户端就绪：%d 个 server 运行中 (%s)", len(active), ", ".join(active))
    except Exception as e:
        logger.warning("MCP 客户端启动失败（ChatAssistant 仍可用内部工具）: %s", e)

    logger.info("Server: http://localhost:%s", settings.PORT)
    logger.info("App:    http://localhost:%s/app", settings.PORT)
    logger.info("=" * 60)

    yield

    # 关闭时
    bus_task.cancel()
    poll_task.cancel()
    ci_task.cancel()
    try:
        from mcp_client import mcp_client
        await mcp_client.stop_all_servers()
    except Exception as e:
        logger.warning("MCP 客户端关闭异常: %s", e)
    await db.disconnect()
    logger.info("数据库连接已关闭")


app = FastAPI(
    title="AI 自动开发系统",
    version="0.10.0",
    description="工单驱动的 AI 自动开发管理平台 + Git 仓库集成 + AI 聊天面板 + 智能 Roadmap",
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

# 全局异常处理
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logging.getLogger("main").error("Unhandled exception: %s %s -> %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": str(exc)})

# 注册 API 路由
from api.projects import router as projects_router
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
from api.ue_framework import router as ue_framework_router

app.include_router(projects_router)
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


# ==================== 系统端点 ====================


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "version": "0.13.0"}


@app.get("/api/sop")
async def get_sop():
    """获取当前 SOP 配置（流程定义）"""
    from sop.loader import get_sop_stages, get_sop_metadata
    from orchestrator import orchestrator
    config = orchestrator._sop_config
    if not config:
        return {"metadata": {"name": "内置默认", "version": "1.0"}, "stages": [], "rules": orchestrator.transition_rules}
    return {
        "metadata": get_sop_metadata(config),
        "stages": get_sop_stages(config),
        "rules": orchestrator.transition_rules,
    }


@app.get("/api/sop/config")
async def get_sop_config_full():
    """获取 SOP 的完整原始配置（含 pipeline_view / global / 每个 stage 的 config 嵌套）

    供 SOP 编辑器使用，返回可直接回传 PUT 的完整结构。
    """
    from orchestrator import orchestrator
    return orchestrator._sop_config or {}


@app.put("/api/sop/config")
async def update_sop_config(body: dict):
    """更新 SOP 配置（SOP 编辑器用）

    流程：
    1. 校验入参（字段齐全、id 唯一、reject_goto / pipeline_view 引用合法）
    2. 备份当前 yaml 到 sop/backups/default_sop_YYYYMMDD-HHMMSS.yaml
    3. 写入新 yaml
    4. 热重载 orchestrator
    """
    from sop.loader import SOP_DIR
    from sop.validator import validate_sop_config
    from orchestrator import orchestrator
    from datetime import datetime

    # 1. 校验
    errors = validate_sop_config(body)
    if errors:
        raise HTTPException(400, {"detail": "SOP 配置校验失败", "errors": errors})

    # 2. 备份
    backup_dir = SOP_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    sop_file = SOP_DIR / "default_sop.yaml"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"default_sop_{ts}.yaml"

    if sop_file.exists():
        backup_path.write_text(sop_file.read_text(encoding="utf-8"), encoding="utf-8")

    # 3. 写新 yaml
    try:
        import yaml
        new_yaml = yaml.safe_dump(body, allow_unicode=True, sort_keys=False, indent=2)
        sop_file.write_text(new_yaml, encoding="utf-8")
    except Exception as e:
        raise HTTPException(500, f"写入 yaml 失败: {e}")

    # 4. 热重载
    try:
        orchestrator.reload_sop()
    except Exception as e:
        # reload 失败则还原备份
        if backup_path.exists():
            sop_file.write_text(backup_path.read_text(encoding="utf-8"), encoding="utf-8")
            orchestrator.reload_sop()
        raise HTTPException(500, f"热重载失败（已自动回滚）：{e}")

    return {
        "status": "ok",
        "backup": backup_path.name,
        "name": body.get("name", "?"),
        "stages_count": len(body.get("stages") or []),
    }


@app.post("/api/sop/reload")
async def reload_sop():
    """热重载 SOP 配置"""
    from orchestrator import orchestrator
    config = orchestrator.reload_sop()
    return {"status": "ok", "message": "SOP 已重载", "name": config.get("name", "?") if config else "内置默认"}


@app.get("/api/projects/{project_id}/preview")
async def get_preview_url(project_id: str):
    """获取项目的本地预览 URL（兼容旧接口，优先返回 dev 环境）"""
    from agents.deploy import DeployAgent
    info = DeployAgent.get_preview(project_id)
    if info:
        return {"preview_url": f"http://localhost:{info['port']}", "port": info["port"], "env": info.get("env")}
    return {"preview_url": None}


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


# ==================== Agent 技能系统开关 ====================

@app.get("/api/settings/agent-tools")
async def get_agent_tools_status():
    """获取 Agent Tool Use 开关状态"""
    import os
    enabled = os.getenv("ENABLE_AGENT_TOOLS", "false").lower() in ("1", "true", "yes")
    return {"enabled": enabled}


@app.post("/api/settings/agent-tools")
async def set_agent_tools_status(body: dict):
    """运行时切换 Agent Tool Use 开关（写入 .env 持久化）"""
    import os
    from config import BASE_DIR
    enabled = bool(body.get("enabled", False))
    os.environ["ENABLE_AGENT_TOOLS"] = "true" if enabled else "false"

    # 持久化到 .env
    env_path = BASE_DIR / ".env"
    key = "ENABLE_AGENT_TOOLS"
    value = "true" if enabled else "false"
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
        found = False
        new_lines = []
        for line in lines:
            if line.startswith(f"{key}=") or line.startswith(f"{key} ="):
                new_lines.append(f"{key}={value}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"{key}={value}")
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    else:
        env_path.write_text(f"{key}={value}\n", encoding="utf-8")

    return {"enabled": enabled, "message": f"Agent Tool Use {'已开启' if enabled else '已关闭'}"}


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

# 开发环境：禁用静态文件缓存
from starlette.middleware.base import BaseHTTPMiddleware

class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

app.add_middleware(NoCacheStaticMiddleware)

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


@app.get("/app")
@app.get("/app/{path:path}")
async def serve_frontend(path: str = ""):
    """提供前端页面"""
    index_file = frontend_dir / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file), headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
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
        reload_dirs=[str(Path(__file__).parent)],
    )

