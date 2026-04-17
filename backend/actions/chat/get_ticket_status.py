"""
GetTicketStatusAction — 查看工单详细状态

两种调用方式：
- 给 ticket_id → 返回那一个工单的详细状态
- 给 requirement_id → 返回该需求下所有工单的状态列表（卡片式）

每个工单返回：
- 基本信息：id/title/status/assigned_agent/current_owner
- 时间：created_at/updated_at/停滞分钟数
- 最近一条日志（用于判断为什么卡住）
- 子任务数量分布
"""
import logging
from datetime import datetime
from typing import Any, Dict, List

from actions.base import ActionBase, ActionResult
from database import db

logger = logging.getLogger("actions.chat.get_ticket_status")


def _minutes_since(iso_str: str) -> int:
    if not iso_str:
        return -1
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        return max(0, int((now - dt).total_seconds() / 60))
    except Exception:
        return -1


async def _build_ticket_snapshot(t: Dict[str, Any]) -> Dict[str, Any]:
    """单工单的状态快照"""
    # 子任务状态分布
    subtasks = await db.fetch_all(
        "SELECT status FROM subtasks WHERE ticket_id = ?", (t["id"],),
    )
    subtask_counts: Dict[str, int] = {}
    for s in subtasks:
        subtask_counts[s["status"]] = subtask_counts.get(s["status"], 0) + 1

    # 最近一条日志
    last_log = await db.fetch_one(
        """SELECT agent_type, action, from_status, to_status, level, detail, created_at
           FROM ticket_logs WHERE ticket_id = ? ORDER BY created_at DESC LIMIT 1""",
        (t["id"],),
    )
    last_activity = None
    if last_log:
        last_activity = {
            "agent": last_log["agent_type"],
            "action": last_log["action"],
            "transition": f"{last_log['from_status']} → {last_log['to_status']}" if last_log["to_status"] else None,
            "level": last_log["level"],
            "at": last_log["created_at"],
            "minutes_ago": _minutes_since(last_log["created_at"]),
            "detail": (last_log["detail"] or "")[:200],
        }

    return {
        "id": t["id"],
        "title": t["title"],
        "status": t["status"],
        "assigned_agent": t.get("assigned_agent"),
        "current_owner": t.get("current_owner"),
        "priority": t.get("priority"),
        "module": t.get("module"),
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "idle_minutes": _minutes_since(t["updated_at"]),
        "subtask_counts": subtask_counts,
        "last_activity": last_activity,
    }


class GetTicketStatusAction(ActionBase):

    @property
    def name(self) -> str:
        return "get_ticket_status"

    @property
    def description(self) -> str:
        return "查看工单详细状态（可按 ticket_id 查单个、按 requirement_id 查某需求下全部）"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "查看工单详细状态。二选一：ticket_id 查单个工单 / requirement_id 查该需求下所有工单。"
                "每个工单返回：当前状态、当前 Agent/Owner、停滞分钟数、最近一条日志（含 level/detail）。"
                "用于定位『哪个工单卡住了』『为什么这条工单没动』类问题。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "string",
                        "description": "工单 ID（TKT-...），填写则只查这一个",
                    },
                    "requirement_id": {
                        "type": "string",
                        "description": "需求 ID（REQ-...），填写则查该需求下所有工单",
                    },
                },
                "required": [],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        project_id = context.get("project_id")
        if not project_id:
            return ActionResult(success=False, error="缺少 project_id")

        ticket_id = (context.get("ticket_id") or "").strip()
        requirement_id = (context.get("requirement_id") or "").strip()

        if not ticket_id and not requirement_id:
            return ActionResult(
                success=False,
                data={"type": "error", "message": "ticket_id 和 requirement_id 必须提供其一"},
            )

        # 单工单查询
        if ticket_id:
            t = await db.fetch_one(
                "SELECT * FROM tickets WHERE id = ? AND project_id = ?",
                (ticket_id, project_id),
            )
            if not t:
                return ActionResult(
                    success=False,
                    data={"type": "error", "message": f"未找到工单「{ticket_id}」"},
                )
            snap = await _build_ticket_snapshot(t)
            logger.info("查询单工单状态: %s (%s)", ticket_id, t["status"])
            return ActionResult(
                success=True,
                data={"type": "ticket_status", "mode": "single", "ticket": snap},
            )

        # 按需求查一批
        # 需求也支持模糊匹配
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

        tickets = await db.fetch_all(
            "SELECT * FROM tickets WHERE requirement_id = ? ORDER BY sort_order, created_at",
            (req["id"],),
        )

        snapshots: List[Dict[str, Any]] = []
        for t in tickets:
            snapshots.append(await _build_ticket_snapshot(t))

        logger.info("查询需求工单状态: %s（%d 个工单）", req["id"], len(tickets))

        return ActionResult(
            success=True,
            data={
                "type": "ticket_status",
                "mode": "by_requirement",
                "requirement_id": req["id"],
                "requirement_title": req["title"],
                "ticket_count": len(tickets),
                "tickets": snapshots,
            },
        )
