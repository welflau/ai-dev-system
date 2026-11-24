"""AI 生成任务统一统计 API（顶栏「AI 任务」指标）。

数据来自 ai_gen_tasks 表（各生图/生视频入口埋点写入）。
  GET /api/ai-gen-tasks          明细 + 三态计数（面板用）
  GET /api/ai-gen-tasks/summary  轻量计数（/api/metrics 与徽标用，不查明细）
"""
from __future__ import annotations

from fastapi import APIRouter

from ai_gen_tasks import counts, recent

router = APIRouter(prefix="/api/ai-gen-tasks", tags=["ai-gen-tasks"])


@router.get("")
async def list_tasks(limit: int = 50):
    """最近提交的任务明细 + 全表分状态计数。

    counts 用全表 GROUP BY（不随 limit 变化）；tasks 只取最近 limit 条。
    """
    c = await counts()
    return {
        "counts": {
            "waiting": c["waiting"],
            "running": c["running"],
            "done": c["done"],
            "failed": c["failed"],
        },
        "total": sum(c.values()),
        "active": c["waiting"] + c["running"],
        "tasks": await recent(limit),
    }


@router.get("/summary")
async def summary():
    """轻量计数：给徽标与 /api/metrics 用，不查明细表。"""
    c = await counts()
    return {
        "total": sum(c.values()),
        "waiting": c["waiting"],
        "running": c["running"],
        "done": c["done"],
        "failed": c["failed"],
    }
