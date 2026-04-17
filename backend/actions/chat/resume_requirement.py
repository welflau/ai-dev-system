"""
ResumeRequirementAction — 恢复已暂停的需求
恢复后会自动重新调度该需求下未完成的工单
"""
import asyncio
import json
import logging
from typing import Any, Dict

from actions.base import ActionBase, ActionResult
from database import db
from events import event_manager
from utils import generate_id, now_iso

logger = logging.getLogger("actions.chat.resume_requirement")


class ResumeRequirementAction(ActionBase):

    @property
    def name(self) -> str:
        return "resume_requirement"

    @property
    def description(self) -> str:
        return "恢复已暂停的需求（仅 paused 状态可恢复），恢复后自动继续处理未完成工单"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "当用户想恢复已暂停的需求时使用。需求必须处于 paused 状态。"
                "恢复后会自动继续处理该需求下未完成的工单。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "requirement_id": {
                        "type": "string",
                        "description": "需求 ID 或标题关键词",
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
        if not requirement_id:
            return ActionResult(success=False, data={"type": "error", "message": "需求 ID 不能为空"})

        req = await db.fetch_one(
            "SELECT * FROM requirements WHERE id = ? AND project_id = ?",
            (requirement_id, project_id),
        )
        if not req:
            req = await db.fetch_one(
                "SELECT * FROM requirements WHERE project_id = ? AND title LIKE ? AND status = 'paused'",
                (project_id, f"%{requirement_id}%"),
            )
            if req:
                requirement_id = req["id"]
            else:
                return ActionResult(
                    success=False,
                    data={"type": "error", "message": f"未找到需求「{requirement_id}」或需求不处于暂停状态"},
                )

        current_status = req["status"]
        if current_status != "paused":
            return ActionResult(
                success=False,
                data={"type": "error", "message": f"需求当前不处于暂停状态（当前: {current_status}），无法恢复"},
            )

        new_status = RequirementStatus.IN_PROGRESS.value
        now = now_iso()
        await db.update("requirements", {
            "status": new_status,
            "updated_at": now,
        }, "id = ?", (requirement_id,))

        log_id = generate_id("LOG")
        detail_json = json.dumps({"message": "通过聊天助手恢复需求执行"}, ensure_ascii=False)
        await db.insert("ticket_logs", {
            "id": log_id,
            "ticket_id": None,
            "subtask_id": None,
            "requirement_id": requirement_id,
            "project_id": project_id,
            "agent_type": "ChatAssistant",
            "action": "update_status",
            "from_status": current_status,
            "to_status": new_status,
            "detail": detail_json,
            "level": "info",
            "created_at": now,
        })

        await event_manager.publish_to_project(
            project_id, "requirement_status_changed",
            {"id": requirement_id, "title": req["title"], "from": current_status, "to": new_status},
        )

        logger.info("聊天助手恢复需求: %s — %s", requirement_id, req["title"])

        # 恢复需求后，自动继续处理未完成的工单
        try:
            from orchestrator import orchestrator
            pending_tickets = await db.fetch_all(
                "SELECT id FROM tickets WHERE requirement_id = ? AND status NOT IN ('deployed', 'cancelled')",
                (requirement_id,),
            )
            for t in pending_tickets:
                asyncio.create_task(orchestrator.process_ticket(project_id, t["id"]))
            if pending_tickets:
                logger.info("恢复需求后继续处理 %d 个工单", len(pending_tickets))
        except Exception as e:
            logger.warning("恢复工单流转失败: %s", e)

        return ActionResult(
            success=True,
            data={
                "type": "requirement_resumed",
                "requirement_id": requirement_id,
                "title": req["title"],
                "from_status": current_status,
                "to_status": new_status,
                "message": f"需求「{req['title']}」已恢复执行",
            },
        )
