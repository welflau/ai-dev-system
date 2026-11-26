"""组合应用的启动步骤，拥有并回收本次 lifespan 创建的后台任务。"""
import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
import logging

from config import APP_VERSION, settings
from . import startup_data

logger = logging.getLogger("main")


def _initialize_integrations():
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


def _start_dispatchers(tasks):
    from orchestrator import orchestrator
    tasks.append(asyncio.create_task(orchestrator.start_event_bus(), name="event-bus"))
    tasks.append(asyncio.create_task(orchestrator.poll_loop(interval=30), name="ticket-poll"))
    from ci_pipeline import ci_pipeline
    tasks.append(asyncio.create_task(ci_pipeline.start_scheduler(), name="ci-scheduler"))
    from image_processor import image_processor_loop
    tasks.append(asyncio.create_task(image_processor_loop(interval=10), name="image-scheduler"))


async def _start_mcp():
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


def _start_maintenance(tasks):
    from automation_scheduler import automation_loop
    tasks.append(asyncio.create_task(automation_loop(), name="automation"))
    tasks.append(asyncio.create_task(_checkpoint_gc_loop(), name="checkpoint-gc"))
    tasks.append(asyncio.create_task(_session_materials_gc_loop(), name="session-materials-gc"))


async def _stop_workers(tasks):
    for task in tasks:
        task.cancel()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for task, result in zip(tasks, results):
        if isinstance(result, Exception):
            logger.warning("后台任务 %s 已异常结束：%s", task.get_name(), type(result).__name__)
    logger.info("生命周期后台任务已结束：%d 个", len(tasks))


async def _stop_mcp():
    logger.info("正在停止 MCP 客户端")
    try:
        from mcp_client import mcp_client
        await mcp_client.stop_all_servers()
    except Exception as e:
        logger.warning("MCP 客户端关闭异常: %s", e)


async def _disconnect_database(db):
    logger.info("正在断开数据库")
    await db.disconnect()
    logger.info("数据库连接已关闭")


@asynccontextmanager
async def application_lifespan(db):
    """先回收调度器，再停止 MCP、断开 SQLite；启动中途退出也按已取得的资源清理。"""
    logger.info("AI 自动开发系统 v%s 启动", APP_VERSION)
    async with AsyncExitStack() as resources:
        # connect 初始化 PRAGMA 也可能在取得连接后失败；disconnect 允许空连接。
        resources.push_async_callback(_disconnect_database, db)
        await db.connect()
        await db.init_tables()
        logger.info("SQLite 数据库就绪")
        _initialize_integrations()
        await startup_data.restore_project_repositories(db)
        await startup_data.reset_stale_environments(db)
        await startup_data.index_knowledge_documents(db)
        await startup_data.index_finished_tickets(db)
        await startup_data.sync_art_assets()
        await startup_data.sync_design_library()
        tasks = []
        try:
            _start_dispatchers(tasks)
            resources.push_async_callback(_stop_mcp)
            await _start_mcp()
            _start_maintenance(tasks)
            logger.info("后台任务已启动：%s", ", ".join(t.get_name() for t in tasks))
            logger.info("App: http://localhost:%s/app", settings.PORT)
            yield
        finally:
            await _stop_workers(tasks)
