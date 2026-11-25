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
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware

from config import APP_VERSION, settings
from database import db

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info("=" * 60)
    logger.info("  AI 自动开发系统 v%s", APP_VERSION)
    logger.info("  工单管理 + Git 仓库集成 + AI 聊天面板 + 智能 Roadmap")
    logger.info("=" * 60)

    await db.connect()
    await db.init_tables()
    logger.info("SQLite 数据库就绪")

    # Phase 1 Hooks：注册内置审计/限流/失败追踪 Hook
    from hooks.builtin import register_builtin_hooks
    register_builtin_hooks()

    # Phase 3 权限审批：初始化 PermissionGate（单例，热身一下确保导入正确）
    from permissions.gate import permission_gate as _pg
    logger.info("权限审批 PermissionGate 就绪（超时=%ds，高风险规则 %d 条）",
                _pg.APPROVAL_TIMEOUT_SECONDS if hasattr(_pg, 'APPROVAL_TIMEOUT_SECONDS') else 300,
                len(getattr(_pg, '_HIGH_RISK_RULES', [])))

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

    # 清理僵尸环境记录：预览服务是 subprocess，随后端进程退出而死，
    # 但 project_environments.status 仍停留在 'running'，前端会显示"运行中"
    # 并给出一个点进去 404 的链接。启动时统一重置。
    # 状态值与 api/projects.py 的自愈逻辑保持一致（inactive，不是 stopped）。
    try:
        stale = await db.fetch_all(
            "SELECT id FROM project_environments WHERE status = 'running'"
        )
        if stale:
            await db.execute(
                "UPDATE project_environments SET status = 'inactive' WHERE status = 'running'"
            )
            logger.info("已重置 %d 条僵尸环境记录（上次退出时未清理的 running）", len(stale))
    except Exception as e:
        logger.warning("清理僵尸环境记录失败（非致命）: %s", e)

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

    # 同步美术资产库（G_ArtRes → art_assets 表）
    try:
        from scripts.sync_art_assets import sync_art_assets_from_manifest
        art_path = settings.ART_ASSETS_LOCAL_PATH
        if art_path:
            n = await sync_art_assets_from_manifest(art_path)
            if n:
                logger.info("美术资产库同步完成: %d 条", n)
        else:
            logger.debug("ART_ASSETS_LOCAL_PATH 未配置，跳过美术资产库同步")
    except Exception as e:
        logger.warning("美术资产库同步失败（忽略）: %s", e)

    # 同步策划知识库（G_DesignKnowledge → planning_knowledge 等表）
    try:
        from scripts.sync_design_knowledge import sync_design_knowledge
        kb_path = settings.GLOBAL_KNOWLEDGE_LOCAL_PATH
        if kb_path:
            n = await sync_design_knowledge(kb_path)
            if n:
                logger.info("策划知识库同步完成: %d 篇", n)
        else:
            logger.debug("GLOBAL_KNOWLEDGE_LOCAL_PATH 未配置，跳过知识库同步")
    except Exception as e:
        logger.warning("策划知识库同步失败（忽略）: %s", e)

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

    # 启动图片生成调度器（LightAI 异步处理队列）
    from image_processor import image_processor_loop
    asyncio.create_task(image_processor_loop(interval=10))
    logger.info("🖼️ 图片生成调度器已启动 (10s 轮询)")

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

    # 启动自动化任务调度器
    from automation_scheduler import automation_loop
    auto_task = asyncio.create_task(automation_loop())
    logger.info("自动化任务调度器已启动（60s 轮询）")

    # Checkpoint GC：启动时跑一次，之后每 6 小时
    async def _checkpoint_gc_loop():
        await asyncio.sleep(30)
        while True:
            try:
                from checkpoint.service import checkpoint_service
                stats = await checkpoint_service.gc_expired(ttl_days=14)
                if stats.get("checkpoints_deleted") or stats.get("blobs_deleted"):
                    logger.info("Checkpoint GC: %s", stats)
            except Exception as e:
                logger.debug("Checkpoint GC 跳过: %s", e)
            await asyncio.sleep(6 * 3600)

    gc_task = asyncio.create_task(_checkpoint_gc_loop())
    logger.info("Checkpoint GC 已调度（TTL 14 天，6h 轮询）")

    async def _session_materials_gc_loop():
        await asyncio.sleep(45)
        while True:
            try:
                from materials.gc import gc_expired as sm_gc
                stats = await sm_gc()
                if stats.get("expired") or stats.get("trimmed"):
                    logger.info("Session materials GC: %s", stats)
            except Exception as e:
                logger.debug("Session materials GC 跳过: %s", e)
            await asyncio.sleep(6 * 3600)

    sm_gc_task = asyncio.create_task(_session_materials_gc_loop())
    logger.info("会话素材 GC 已调度（TTL 14 天，6h 轮询）")

    logger.info("Server: http://localhost:%s", settings.PORT)
    logger.info("App:    http://localhost:%s/app", settings.PORT)
    logger.info("=" * 60)

    yield

    # 关闭时
    bus_task.cancel()
    poll_task.cancel()
    ci_task.cancel()
    auto_task.cancel()
    gc_task.cancel()
    sm_gc_task.cancel()
    try:
        from mcp_client import mcp_client
        await mcp_client.stop_all_servers()
    except Exception as e:
        logger.warning("MCP 客户端关闭异常: %s", e)
    await db.disconnect()
    logger.info("数据库连接已关闭")


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
from api.system import (
    router as system_router,
    health_check as health_check,
    get_available_paths as get_available_paths,
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


# ==================== 系统端点 ====================


@app.get("/api/events/global")
async def global_events_stream():
    """全局 SSE 频道——全局聊天 AI 工具日志、跨项目事件"""
    from sse_starlette.sse import EventSourceResponse
    from events import event_manager
    return EventSourceResponse(event_manager.event_generator("global"))


@app.post("/api/system/open_path")
async def open_path_in_explorer(body: dict):
    """在系统文件管理器中打开指定路径。"""
    import os, sys, subprocess
    from pathlib import Path
    raw = (body.get("path") or "").strip()
    if not raw:
        from fastapi import HTTPException
        raise HTTPException(400, "path 不能为空")
    p = Path(raw)
    target = p.parent if p.is_file() else p
    if not target.exists():
        from fastapi import HTTPException
        raise HTTPException(404, f"路径不存在: {target}")
    try:
        if sys.platform == "win32":
            if p.is_file():
                subprocess.Popen(["explorer", "/select,", str(p)])
            else:
                os.startfile(str(target))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R" if p.is_file() else "", str(p if p.is_file() else target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
        return {"ok": True, "opened": str(target)}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(500, f"打开失败: {e}")


app.include_router(system_router)
app.include_router(sop_config_router)


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
    """LLM 状态。

    display_model = 当前**实际生效**的模型名：CLI 模式用 cli_model，API 模式用 model。
    顶栏徽标、聊天头像等「展示当前模型」的位置一律用它，不要用 model —— CLI 模式下
    model 只是 API 模式遗留的主模型名（例如切到 CLI 前留下的 hy4），并不参与实际调用，
    直接展示会误导用户以为在用 hy4。model 字段保留原语义供 API 模式输入框回填。
    """
    from llm_client import llm_client, get_cli_model_options, _CLI_ADAPTERS
    is_cli = llm_client.api_format == "cli"
    display_model = (
        (llm_client.cli_model or llm_client.model) if is_cli else llm_client.model
    )
    return {
        "configured":  llm_client.is_configured,
        "api_format":  llm_client.api_format,
        "base_url":    llm_client.base_url if not is_cli else None,
        "model":       llm_client.model,
        "display_model": display_model,
        "timeout":     llm_client.timeout,
        "max_retries": llm_client.max_retries,
        # CLI 专属字段（非 CLI 模式时为 None）
        "cli_type":    llm_client.cli_type    if is_cli else None,
        "cli_cmd":     llm_client.cli_cmd     if is_cli else None,
        "cli_model":   llm_client.cli_model   if is_cli else None,
        "cli_timeout": llm_client.cli_timeout if is_cli else None,
        # 前端联动用：各 CLI 工具的模型列表 + 默认命令名（始终返回，方便弹窗初始化）
        "cli_model_options": get_cli_model_options(),
        "cli_default_cmds":  {k: v["default_cmd"] for k, v in _CLI_ADAPTERS.items()},
    }


@app.post("/api/llm/cli-models/refresh")
async def llm_cli_models_refresh(body: dict = None):
    """从本地 CLI 实时查询模型列表（刷新下拉）"""
    from llm_client import llm_client, fetch_cli_models
    body = body or {}
    cli_type = body.get("cli_type") or llm_client.cli_type or "claude"
    cli_cmd = body.get("cli_cmd") or llm_client.cli_cmd or ""
    result = await fetch_cli_models(cli_type, cli_cmd)
    return {
        "cli_type": cli_type,
        "cli_cmd": cli_cmd,
        **result,
    }


@app.post("/api/llm/config")
async def llm_config(body: dict):
    """动态更新 LLM 配置并持久化到 .env"""
    from llm_client import llm_client
    from config import BASE_DIR

    # 更新运行时
    if "api_format" in body:
        llm_client.api_format = body["api_format"] or "anthropic"
    # CLI 模式下 model 是 API 模式遗留字段（可能是切换前残留的 hy4），
    # 实际调用只用 cli_model。此时忽略前端提交的 model，避免把陈旧主模型名固化回来。
    is_cli = llm_client.api_format == "cli"
    if "base_url" in body:
        llm_client.base_url = (body["base_url"] or "").rstrip("/")
    if "api_key" in body:
        llm_client.api_key = body["api_key"] or ""
    if "model" in body and not is_cli:
        llm_client.model = body["model"] or "gpt-4"
    if "timeout" in body:
        llm_client.timeout = int(body.get("timeout", 60))
    if "max_retries" in body:
        llm_client.max_retries = int(body.get("max_retries", 3))
    # CLI 专属字段
    if "cli_type" in body:
        llm_client.cli_type = body["cli_type"] or "claude"
    if "cli_cmd" in body:
        llm_client.cli_cmd = body["cli_cmd"] or "claude"
    if "cli_model" in body:
        llm_client.cli_model = body["cli_model"] or llm_client.model
    if "cli_timeout" in body:
        llm_client.cli_timeout = int(body.get("cli_timeout", 120))

    # 同步更新 settings
    settings.LLM_API_FORMAT  = llm_client.api_format
    settings.LLM_BASE_URL    = llm_client.base_url
    settings.LLM_API_KEY     = llm_client.api_key
    settings.LLM_MODEL       = llm_client.model
    settings.LLM_TIMEOUT     = llm_client.timeout
    settings.LLM_MAX_RETRIES = llm_client.max_retries
    settings.LLM_CLI_TYPE    = llm_client.cli_type
    settings.LLM_CLI_CMD     = llm_client.cli_cmd
    settings.LLM_CLI_MODEL   = llm_client.cli_model
    settings.LLM_CLI_TIMEOUT = llm_client.cli_timeout

    # 持久化到 .env
    env_path = BASE_DIR / ".env"
    env_lines = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env_lines[k.strip()] = v.strip()

    env_lines["LLM_API_FORMAT"]  = llm_client.api_format
    env_lines["LLM_BASE_URL"]    = llm_client.base_url
    env_lines["LLM_API_KEY"]     = llm_client.api_key
    # CLI 模式不写 LLM_MODEL：保留 .env 里已有的值（或让用户手动清），
    # 避免把切换前残留的 hy4 一遍遍写回。cli_model 才是实际生效的字段。
    if not is_cli:
        env_lines["LLM_MODEL"] = llm_client.model
    env_lines["LLM_TIMEOUT"]     = str(llm_client.timeout)
    env_lines["LLM_MAX_RETRIES"] = str(llm_client.max_retries)
    env_lines["LLM_CLI_TYPE"]    = llm_client.cli_type
    env_lines["LLM_CLI_CMD"]     = llm_client.cli_cmd
    env_lines["LLM_CLI_MODEL"]   = llm_client.cli_model
    env_lines["LLM_CLI_TIMEOUT"] = str(llm_client.cli_timeout)

    # Pexels API Key（资产网络搜索）
    if "pexels_api_key" in body and body["pexels_api_key"]:
        settings.PEXELS_API_KEY = body["pexels_api_key"]
        env_lines["PEXELS_API_KEY"] = body["pexels_api_key"]

    # LightAI 配置（可选）
    if "lightai_api_key" in body and body["lightai_api_key"]:
        settings.LIGHTAI_API_KEY = body["lightai_api_key"]
        env_lines["LIGHTAI_API_KEY"] = body["lightai_api_key"]
    if "lightai_api_base" in body and body["lightai_api_base"]:
        settings.LIGHTAI_API_BASE = body["lightai_api_base"]
        env_lines["LIGHTAI_API_BASE"] = body["lightai_api_base"]
    if "lightai_engine" in body:
        settings.LIGHTAI_IMAGE_ENGINE = body["lightai_engine"] or "gemini"
        env_lines["LIGHTAI_IMAGE_ENGINE"] = settings.LIGHTAI_IMAGE_ENGINE
    if "lightai_timeout" in body:
        settings.LIGHTAI_IMAGE_TIMEOUT = int(body["lightai_timeout"] or 300)
        env_lines["LIGHTAI_IMAGE_TIMEOUT"] = str(settings.LIGHTAI_IMAGE_TIMEOUT)

    env_path.write_text(
        "\n".join(f"{k}={v}" for k, v in env_lines.items()) + "\n",
        encoding="utf-8",
    )

    # 同步 LIGHTAI_API_KEY 到已安装 ue5-dev（含 LightAI 集成）的项目 scripts/env.json
    _lightai_key_to_sync = settings.LIGHTAI_API_KEY
    if _lightai_key_to_sync:
        try:
            import json as _json
            from database import db as _db
            from pathlib import Path as _Path
            _rows = await _db.fetch_all(
                "SELECT p.git_repo_path FROM projects p "
                "JOIN project_packs pp ON pp.project_id = p.id "
                "WHERE pp.pack_name = 'ue5-dev' AND p.git_repo_path IS NOT NULL AND p.git_repo_path != ''"
            )
            _synced = []
            for _row in _rows:
                _repo = _Path(_row["git_repo_path"])
                # 新格式：.codebuddy/.workbuddy/packs/ue5-dev/scripts/env.json
                # 旧格式：.codebuddy/.workbuddy/scripts/env.json（兼容）
                for _env_path in [
                    _repo / ".codebuddy" / "packs" / "ue5-dev" / "scripts" / "env.json",
                    _repo / ".workbuddy" / "packs" / "ue5-dev" / "scripts" / "env.json",
                    _repo / ".claude"    / "packs" / "ue5-dev" / "scripts" / "env.json",
                    _repo / ".codebuddy" / "scripts" / "env.json",
                    _repo / ".workbuddy" / "scripts" / "env.json",
                    _repo / ".claude"    / "scripts" / "env.json",
                ]:
                    if _env_path.exists():
                        try:
                            _cfg = _json.loads(_env_path.read_text(encoding="utf-8"))
                            _cfg["LIGHTAI_API_KEY"] = _lightai_key_to_sync
                            _env_path.write_text(_json.dumps(_cfg, ensure_ascii=False, indent=2), encoding="utf-8")
                            _synced.append(str(_env_path))
                        except Exception as _e:
                            logger.warning("同步 LightAI key 到 %s 失败: %s", _env_path, _e)
            if _synced:
                logger.info("LightAI API key 已同步到 %d 个 skill env.json: %s", len(_synced), _synced)

            # 同步到系统用户 lightai-skill（.codebuddy、.workbuddy 和 .claude 三端）
            for _skill_env in [
                _Path.home() / ".codebuddy" / "skills" / "lightai-skill" / "scripts" / "env.json",
                _Path.home() / ".workbuddy" / "skills" / "lightai-skill" / "scripts" / "env.json",
                _Path.home() / ".claude"    / "skills" / "lightai-skill" / "scripts" / "env.json",
            ]:
                if _skill_env.exists():
                    try:
                        _skill_cfg = _json.loads(_skill_env.read_text(encoding="utf-8"))
                        _skill_cfg["LIGHTAI_API_KEY"] = _lightai_key_to_sync
                        _skill_env.write_text(_json.dumps(_skill_cfg, ensure_ascii=False, indent=2), encoding="utf-8")
                        logger.info("LightAI API key 已同步到 lightai-skill: %s", _skill_env)
                    except Exception as _e:
                        logger.warning("同步 LightAI key 到 lightai-skill 失败: %s", _e)
        except Exception as _e:
            logger.warning("LightAI key 同步失败: %s", _e)

    return {
        "status": "ok",
        "configured":         llm_client.is_configured,
        "api_format":         llm_client.api_format,
        "model":              llm_client.model,
        "lightai_configured": bool(settings.LIGHTAI_API_KEY),
    }


@app.post("/api/llm/test")
async def llm_test():
    """测试 LLM 连接"""
    from llm_client import llm_client
    result = await llm_client.test_connection()
    return result


# ==================== Agent 级 LLM 配置 ====================

def _public_llm_fields(client, has_api_key: bool = False) -> dict:
    """暴露给前端的 LLM 配置字段（api_key 不外泄，只给 has_api_key 标记）"""
    api_format = getattr(client, "api_format", None)
    model = getattr(client, "model", None)
    cli_model = getattr(client, "cli_model", None)
    display_model = (cli_model or model) if api_format == "cli" else model
    return {
        "api_format": api_format,
        "base_url": getattr(client, "base_url", None),
        "model": model,
        "display_model": display_model,
        "cli_type": getattr(client, "cli_type", None),
        "cli_cmd": getattr(client, "cli_cmd", None),
        "cli_model": cli_model,
        "cli_timeout": getattr(client, "cli_timeout", None),
        "has_api_key": has_api_key,
    }


@app.get("/api/llm/agents")
async def llm_agents():
    """枚举所有 Agent + 各自 LLM 生效配置（覆盖 or 继承全局）"""
    from agent_registry import discover_agents, get_registry
    from llm_client import (
        LLMClient, llm_client, get_agent_llm_config, get_cli_model_options, _CLI_ADAPTERS,
    )

    discover_agents()
    names = sorted(get_registry().keys())

    agents = []
    for name in names:
        override = await get_agent_llm_config(name)
        if override is not None:
            effective = _public_llm_fields(
                LLMClient(config=override),
                has_api_key=bool(override.get("api_key")),
            )
            has_override = True
        else:
            effective = _public_llm_fields(llm_client, has_api_key=bool(llm_client.api_key))
            has_override = False
        agents.append({
            "agent_type": name,
            "has_override": has_override,
            "effective": effective,
        })

    return {
        "agents": agents,
        "global": _public_llm_fields(llm_client, has_api_key=bool(llm_client.api_key)),
        "cli_model_options": get_cli_model_options(),
        "cli_default_cmds": {k: v["default_cmd"] for k, v in _CLI_ADAPTERS.items()},
    }


@app.post("/api/llm/agents/{agent_type}/config")
async def llm_agent_config(agent_type: str, body: dict):
    """写/更新某 Agent 的 LLM 覆盖（upsert）。空 body 各字段为空串 = 显式继承全局语义不再适用，
    调用方要"恢复继承"请用 DELETE。"""
    from llm_client import _invalidate_agent_client
    from database import db
    from utils import generate_id, now_iso

    agent_type = (agent_type or "").strip()
    if not agent_type:
        raise HTTPException(400, "agent_type 不能为空")

    fields = {
        "api_format": (body.get("api_format") or "").strip(),
        "base_url": (body.get("base_url") or "").strip(),
        "api_key": (body.get("api_key") or "").strip(),
        "model": (body.get("model") or "").strip(),
        "cli_type": (body.get("cli_type") or "").strip(),
        "cli_cmd": (body.get("cli_cmd") or "").strip(),
        "cli_model": (body.get("cli_model") or "").strip(),
        "cli_timeout": body.get("cli_timeout"),
    }
    # api_key 留空 = 沿用已有的（更新时）；新增且留空 = 继承全局（表里存空串）
    existing = await db.fetch_one(
        "SELECT id, api_key FROM agent_llm_config WHERE agent_type = ?", (agent_type,)
    )
    if existing:
        await db.execute(
            "UPDATE agent_llm_config SET api_format=?, base_url=?, api_key=?, model=?, "
            "cli_type=?, cli_cmd=?, cli_model=?, cli_timeout=?, updated_at=? WHERE agent_type=?",
            (fields["api_format"], fields["base_url"],
             fields["api_key"] if fields["api_key"] else existing.get("api_key"),
             fields["model"], fields["cli_type"], fields["cli_cmd"], fields["cli_model"],
             int(fields["cli_timeout"]) if fields["cli_timeout"] else None,
             now_iso(), agent_type),
        )
    else:
        await db.insert("agent_llm_config", {
            "id": generate_id("ALC"),
            "agent_type": agent_type,
            "api_format": fields["api_format"],
            "base_url": fields["base_url"],
            "api_key": fields["api_key"],
            "model": fields["model"],
            "cli_type": fields["cli_type"],
            "cli_cmd": fields["cli_cmd"],
            "cli_model": fields["cli_model"],
            "cli_timeout": int(fields["cli_timeout"]) if fields["cli_timeout"] else None,
            "updated_at": now_iso(),
        })

    _invalidate_agent_client(agent_type)
    return {"status": "ok", "agent_type": agent_type}


@app.delete("/api/llm/agents/{agent_type}/config")
async def llm_agent_config_delete(agent_type: str):
    """删除某 Agent 的覆盖 = 恢复继承全局配置"""
    from llm_client import _invalidate_agent_client
    from database import db

    agent_type = (agent_type or "").strip()
    if not agent_type:
        raise HTTPException(400, "agent_type 不能为空")
    await db.execute("DELETE FROM agent_llm_config WHERE agent_type = ?", (agent_type,))
    _invalidate_agent_client(agent_type)
    return {"status": "ok", "agent_type": agent_type}


app.include_router(metrics_router)


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

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        '<rect width="32" height="32" rx="6" fill="#7c6af7"/>'
        '<text x="16" y="23" font-size="20" text-anchor="middle" fill="white">🤖</text>'
        '</svg>'
    )
    return Response(content=svg, media_type="image/svg+xml")

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


@app.get("/api/local-file")
async def serve_local_file(path: str):
    """按需读取本地文件并以图片形式返回（仅限图片格式，供前端预览 AI 生成图片）"""
    import pathlib, mimetypes
    from fastapi.responses import FileResponse
    from fastapi import HTTPException
    fp = pathlib.Path(path)
    if not fp.exists() or not fp.is_file():
        raise HTTPException(404, "文件不存在")
    ext = fp.suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
        raise HTTPException(400, "不支持的文件类型")
    mt = mimetypes.types_map.get(ext, "image/png")
    return FileResponse(str(fp), media_type=mt)


@app.get("/api/open-in-browser")
async def open_in_browser(url: str):
    """用系统默认浏览器打开 URL（网页 Tab 被 X-Frame-Options 拒绝内嵌时的兜底出口）"""
    import webbrowser
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(400, "仅支持 http/https URL")
    if not webbrowser.open(url):
        raise HTTPException(500, "无法调起系统浏览器")
    return {"ok": True}


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

