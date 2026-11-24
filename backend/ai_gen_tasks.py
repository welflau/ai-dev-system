"""AI 生成任务统一记录层（生图 / 生视频）。

供顶栏「AI 任务」指标统计：累计提交数、进行中/等待/完成/失败数、任务明细列表。

设计要点：
- **记录失败绝不影响生成**：所有函数全程 try/except 静默降级。埋点散布在多个入口，
  任何一处 DB 异常都不能把生图/生视频带下水（与 command_log.py:134-137 同一原则）。
- 公共层 `cloud_video/` 顶层不 import database，用**函数内延迟 import** 调用本模块，
  保持「公共层零业务依赖」（见 cloud_video/lightai.py 的既有做法）。
- 状态 4 态：waiting（排队/待处理）、running（提交后执行中）、done、failed。
  update_task 自动维护 started_at / finished_at，调用方只传 status 与其它业务字段。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("ai_gen_tasks")

_STATUSES = ("waiting", "running", "done", "failed")


async def record_task(
    *,
    kind: str,
    provider: str,
    status: str = "waiting",
    prompt: str = "",
    engine: str = "",
    project_id: str = "",
    ticket_id: str = "",
    session_id: str = "",
    message_id: str = "",
    source: str = "",
    external_task_id: str = "",
    result_url: str = "",
    result_path: str = "",
    error: str = "",
) -> str:
    """新建一条 AI 生成任务记录，返回 task_id（AIGEN-...）；失败返回空串。"""
    try:
        from database import db
        from utils import generate_id, now_iso

        now = now_iso()
        tid = generate_id("AIGEN")
        if status not in _STATUSES:
            status = "waiting"
        row: Dict[str, Any] = {
            "id": tid,
            "kind": kind,
            "provider": provider,
            "engine": engine,
            "status": status,
            "prompt": (prompt or "")[:2000],
            "project_id": project_id,
            "ticket_id": ticket_id,
            "session_id": session_id,
            "message_id": message_id,
            "source": source,
            "external_task_id": external_task_id,
            "result_url": result_url,
            "result_path": result_path,
            "error": (error or "")[:1000],
            "queued_at": now if status == "waiting" else "",
            "started_at": now if status == "running" else "",
            "finished_at": now if status in ("done", "failed") else "",
            "created_at": now,
            "updated_at": now,
        }
        await db.insert("ai_gen_tasks", row)
        return tid
    except Exception as e:
        logger.debug("record_task 跳过: %s", e)
        return ""


async def update_task(task_id: str, **fields) -> bool:
    """更新任务状态/产物；自动维护时间戳。task_id 为空或无字段时静默跳过。"""
    if not task_id or not fields:
        return False
    try:
        from database import db
        from utils import now_iso

        data = dict(fields)
        now = now_iso()
        status = data.get("status")
        if status:
            if status not in _STATUSES:
                return False
            if status == "running" and "started_at" not in data:
                data["started_at"] = now
            if status in ("done", "failed") and "finished_at" not in data:
                data["finished_at"] = now
        if "prompt" in data and data["prompt"]:
            data["prompt"] = str(data["prompt"])[:2000]
        if "error" in data and data["error"]:
            data["error"] = str(data["error"])[:1000]
        data["updated_at"] = now
        await db.update("ai_gen_tasks", data, "id = ?", (task_id,))
        return True
    except Exception as e:
        logger.debug("update_task 跳过: %s", e)
        return False


async def update_by_external(external_task_id: str, **fields) -> int:
    """按 external_task_id（如 image_requests 的 IMG-* id）更新，返回更新行数。

    image_requests 表没有 AI 任务外键列，用 external_task_id 关联可零改动原表结构。
    """
    if not external_task_id or not fields:
        return 0
    try:
        from database import db
        from utils import now_iso

        rows = await db.fetch_all(
            "SELECT id FROM ai_gen_tasks WHERE external_task_id = ? ORDER BY created_at DESC",
            (external_task_id,),
        )
        if not rows:
            return 0
        n = 0
        for r in rows:
            if await update_task(r["id"], **fields):
                n += 1
        return n
    except Exception as e:
        logger.debug("update_by_external 跳过: %s", e)
        return 0


async def counts() -> Dict[str, int]:
    """按 status 聚合全表计数；供 /api/metrics 与面板使用。"""
    out = {s: 0 for s in _STATUSES}
    try:
        from database import db
        rows = await db.fetch_all(
            "SELECT status, COUNT(*) AS n FROM ai_gen_tasks GROUP BY status"
        )
        for r in rows:
            s = r.get("status")
            if s in out:
                out[s] = int(r.get("n") or 0)
    except Exception as e:
        logger.debug("counts 跳过: %s", e)
    return out


async def total() -> int:
    c = await counts()
    return sum(c.values())


async def recent(limit: int = 50) -> list:
    """最近提交的任务明细（created_at DESC）。"""
    try:
        from database import db
        rows = await db.fetch_all(
            "SELECT * FROM ai_gen_tasks ORDER BY created_at DESC LIMIT ?",
            (max(1, min(int(limit), 200)),),
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.debug("recent 跳过: %s", e)
        return []
