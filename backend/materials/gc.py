"""会话素材 GC：TTL（会话空闲 14 天）+ 每会话 keep-N scratch。"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict

from database import db
from materials.registry import KEEP_SCRATCH, TTL_DAYS, material_registry

logger = logging.getLogger("materials.gc")


async def gc_expired(*, ttl_days: int = TTL_DAYS, keep_scratch: int = KEEP_SCRATCH) -> Dict[str, Any]:
    stats = {"expired": 0, "trimmed": 0, "errors": []}
    try:
        cutoff = (datetime.now() - timedelta(days=ttl_days)).isoformat()
        expired = await db.fetch_all(
            """
            SELECT m.id FROM session_materials m
            LEFT JOIN chat_sessions s ON s.id = m.session_id
            WHERE m.status = 'scratch'
              AND COALESCE(s.last_active_at, s.updated_at, m.created_at) < ?
            """,
            (cutoff,),
        )
        for row in expired or []:
            await material_registry._delete_scratch(row["id"])
            stats["expired"] += 1

        sessions = await db.fetch_all(
            "SELECT DISTINCT session_id FROM session_materials WHERE status='scratch'"
        )
        for srow in sessions or []:
            sid = srow["session_id"]
            rows = await db.fetch_all(
                "SELECT id FROM session_materials WHERE session_id=? AND status='scratch' "
                "ORDER BY created_at DESC",
                (sid,),
            )
            extra = (rows or [])[keep_scratch:]
            for old in extra:
                await material_registry._delete_scratch(old["id"])
                stats["trimmed"] += 1
    except Exception as e:
        logger.warning("session materials GC 失败: %s", e, exc_info=True)
        stats["errors"].append(str(e))
    return stats
