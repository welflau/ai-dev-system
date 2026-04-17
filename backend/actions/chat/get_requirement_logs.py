"""
GetRequirementLogsAction — 返回指定需求最近 N 条活动日志

面向"最近发生了什么 / 有没有错误 / 为什么重试"类问题。
数据来自 ticket_logs 表——包含所有 Agent 的状态转换、开始/完成、以及 AI 调用摘要。
"""
import json
import logging
from datetime import datetime
from typing import Any, Dict, List

from actions.base import ActionBase, ActionResult
from database import db

logger = logging.getLogger("actions.chat.get_requirement_logs")


def _minutes_since(iso_str: str) -> int:
    if not iso_str:
        return -1
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        return max(0, int((now - dt).total_seconds() / 60))
    except Exception:
        return -1


def _summarize_detail(detail_raw: str) -> str:
    """日志 detail 是 JSON 字符串，提取 message 字段给 LLM 看；解析失败则截断原文"""
    if not detail_raw:
        return ""
    try:
        obj = json.loads(detail_raw)
        if isinstance(obj, dict):
            msg = obj.get("message") or obj.get("reason") or ""
            if msg:
                return msg[:200]
            # 没 message 字段就序列化前几个键
            return json.dumps({k: obj[k] for k in list(obj.keys())[:3]}, ensure_ascii=False)[:200]
        return str(obj)[:200]
    except Exception:
        return detail_raw[:200]


class GetRequirementLogsAction(ActionBase):

    @property
    def name(self) -> str:
        return "get_requirement_logs"

    @property
    def description(self) -> str:
        return "查看指定需求的最近活动日志（Agent 状态转换、LLM 调用摘要、错误等）"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "返回指定需求的最近 N 条活动记录（ticket_logs 表），包括各 Agent 的状态转换、"
                "LLM 调用、执行错误等。用于诊断『最近发生了什么』『为什么卡住』『有无错误』类问题。"
                "默认 20 条、最多 50 条。支持按 level (info/warning/error) 过滤。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "requirement_id": {
                        "type": "string",
                        "description": "需求 ID（REQ-...）或标题关键词",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回条数，默认 20，上限 50",
                    },
                    "level": {
                        "type": "string",
                        "enum": ["info", "warning", "error"],
                        "description": "只看某个级别的日志；不填则全部",
                    },
                },
                "required": ["requirement_id"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        project_id = context.get("project_id")
        if not project_id:
            return ActionResult(success=False, error="缺少 project_id")

        requirement_id = (context.get("requirement_id") or "").strip()
        if not requirement_id:
            return ActionResult(
                success=False,
                data={"type": "error", "message": "requirement_id 不能为空"},
            )

        limit = min(int(context.get("limit") or 20), 50)
        level_filter = (context.get("level") or "").strip().lower() or None

        # 定位需求（含模糊匹配）
        req = await db.fetch_one(
            "SELECT id, title FROM requirements WHERE id = ? AND project_id = ?",
            (requirement_id, project_id),
        )
        if not req:
            req = await db.fetch_one(
                "SELECT id, title FROM requirements WHERE project_id = ? AND title LIKE ? ORDER BY created_at DESC LIMIT 1",
                (project_id, f"%{requirement_id}%"),
            )
            if not req:
                return ActionResult(
                    success=False,
                    data={"type": "error", "message": f"未找到需求「{requirement_id}」"},
                )

        # 查日志
        if level_filter:
            logs = await db.fetch_all(
                """SELECT * FROM ticket_logs WHERE requirement_id = ? AND level = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (req["id"], level_filter, limit),
            )
        else:
            logs = await db.fetch_all(
                """SELECT * FROM ticket_logs WHERE requirement_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (req["id"], limit),
            )

        entries: List[Dict[str, Any]] = []
        for log in logs:
            entries.append({
                "at": log["created_at"],
                "minutes_ago": _minutes_since(log["created_at"]),
                "agent": log.get("agent_type"),
                "action": log.get("action"),
                "transition": (
                    f"{log['from_status']} → {log['to_status']}"
                    if log.get("to_status") else None
                ),
                "level": log.get("level"),
                "ticket_id": log.get("ticket_id"),
                "summary": _summarize_detail(log.get("detail") or ""),
            })

        logger.info(
            "查询需求日志: %s（level=%s, 返回 %d 条）",
            req["id"], level_filter or "all", len(entries),
        )

        return ActionResult(
            success=True,
            data={
                "type": "requirement_logs",
                "requirement_id": req["id"],
                "requirement_title": req["title"],
                "level_filter": level_filter,
                "count": len(entries),
                "logs": entries,
            },
        )
