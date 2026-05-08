"""
CloseRequirementAction — 关闭/取消需求
关闭时会级联取消该需求下所有未完成的工单
"""
import json
import logging
from typing import Any, Dict

from actions.base import ActionBase, ActionResult
from database import db
from events import event_manager
from utils import generate_id, now_iso

logger = logging.getLogger("actions.chat.close_requirement")


class CloseRequirementAction(ActionBase):

    @property
    def name(self) -> str:
        return "close_requirement"

    @property
    def description(self) -> str:
        return "关闭/取消某个需求（终态需求不可关闭），同时取消未完成的工单"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "当用户想关闭/取消某个需求时使用。已完成或已取消的需求不可再关闭。"
                "关闭后会同时级联取消该需求下所有未完成的工单。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "requirement_id": {
                        "type": "string",
                        "description": "需求 ID 或标题关键词",
                    },
                    "reason": {
                        "type": "string",
                        "description": "关闭原因",
                    },
                },
                "required": ["requirement_id"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        from models import RequirementStatus

        project_id = context.get("project_id")
        if not project_id:
            return ActionResult(success=False, error="缺少 project_id")

        requirement_id = (context.get("requirement_id") or "").strip()
        reason = (context.get("reason") or "用户通过聊天助手关闭").strip()

        if not requirement_id:
            return ActionResult(success=False, data={"type": "error", "message": "需求 ID 不能为空"})

        req = await db.fetch_one(
            "SELECT * FROM requirements WHERE id = ? AND project_id = ?",
            (requirement_id, project_id),
        )
        if not req:
            req = await db.fetch_one(
                "SELECT * FROM requirements WHERE project_id = ? AND title LIKE ? AND status NOT IN ('completed', 'cancelled')",
                (project_id, f"%{requirement_id}%"),
            )
            if req:
                requirement_id = req["id"]
            else:
                return ActionResult(success=False, data={"type": "error", "message": f"未找到需求「{requirement_id}」"})

        current_status = req["status"]
        if current_status in ("completed", "cancelled"):
            status_label = "已完成" if current_status == "completed" else "已取消"
            return ActionResult(
                success=False,
                data={"type": "error", "message": f"需求已处于终态「{status_label}」，无需操作"},
            )

        # v0.20：返回确认卡片，由用户在前端点击后才真正执行
        # 前端检测到 type=confirm_close_requirement 时显示确认按钮
        pending_tickets = len([t for t in await db.fetch_all(
            "SELECT id FROM tickets WHERE requirement_id=? AND status NOT IN ('deployed','cancelled')",
            (requirement_id,),
        )])
        return ActionResult(
            success=True,
            data={
                "type": "confirm_close_requirement",
                "requirement_id": requirement_id,
                "title": req["title"],
                "reason": reason,
                "pending_tickets": pending_tickets,
                "message": f"确认关闭需求「{req['title']}」？这将取消 {pending_tickets} 个未完成工单。",
            },
        )



    @staticmethod
    async def execute_close(project_id: str, requirement_id: str, reason: str) -> ActionResult:
        """真正执行关闭需求（由前端用户确认后调用）"""
        from models import RequirementStatus
        req = await db.fetch_one("SELECT * FROM requirements WHERE id=? AND project_id=?",
                                  (requirement_id, project_id))
        if not req:
            return ActionResult(success=False, data={"type": "error", "message": "需求不存在"})

        current_status = req["status"]
        now = now_iso()
        await db.update("requirements", {
            "status": RequirementStatus.CANCELLED.value,
            "updated_at": now,
        }, "id = ?", (requirement_id,))

        cancelled_tickets = 0
        tickets = await db.fetch_all(
            "SELECT id FROM tickets WHERE requirement_id=? AND status NOT IN ('deployed','cancelled')",
            (requirement_id,),
        )
        for t in tickets:
            await db.update("tickets", {"status": "cancelled", "updated_at": now}, "id=?", (t["id"],))
            cancelled_tickets += 1

        detail_json = json.dumps({
            "message": f"通过聊天助手关闭需求，原因: {reason}",
            "cancelled_tickets": cancelled_tickets,
        }, ensure_ascii=False)
        await db.insert("ticket_logs", {
            "id": generate_id("LOG"), "ticket_id": None, "subtask_id": None,
            "requirement_id": requirement_id, "project_id": project_id,
            "agent_type": "ChatAssistant", "action": "update_status",
            "from_status": current_status, "to_status": "cancelled",
            "detail": detail_json, "level": "info", "created_at": now,
        })
        await event_manager.publish_to_project(
            project_id, "requirement_status_changed",
            {"id": requirement_id, "title": req["title"], "from": current_status,
             "to": "cancelled", "cancelled_tickets": cancelled_tickets},
        )
        logger.info("关闭需求: %s — %s (取消 %d 个工单)", requirement_id, req["title"], cancelled_tickets)
        msg = f"需求「{req['title']}」已关闭"
        if cancelled_tickets > 0:
            msg += f"，同时取消了 {cancelled_tickets} 个工单"
        return ActionResult(
            success=True,
            data={"type": "requirement_closed", "requirement_id": requirement_id,
                  "title": req["title"], "from_status": current_status,
                  "to_status": "cancelled", "reason": reason,
                  "cancelled_tickets": cancelled_tickets, "message": msg},
        )
