"""顶栏监控的只读 HTTP 接口。"""
from fastapi import APIRouter

import database
from services import metrics

router = APIRouter(prefix="/api/metrics")


@router.get("/asyncio-tasks")
async def get_asyncio_tasks_detail():
    """顶栏「异步任务」明细：进程内未完成的 asyncio 协程列表。

    与 /api/metrics 的 asyncio_tasks 同一枚举口径；按 coro 聚合出 summary 便于阅读。
    """
    return metrics.asyncio_tasks_detail()


@router.get("")
async def get_system_metrics():
    """系统性能指标：用于顶栏实时监控"""
    return await metrics.system_metrics(database.db)
