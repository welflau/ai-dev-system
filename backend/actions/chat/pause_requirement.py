"""
PauseRequirementAction — 暂停需求执行
"""
import json
import logging
from typing import Any, Dict

from actions.base import ActionBase, ActionResult
from database import db
from events import event_manager
from utils import generate_id, now_iso

logger = logging.getLogger("actions.chat.pause_requirement")


_STATUS_LABEL = {
    "submitted": "已提交", "analyzing": "分析中", "decomposed": "已拆单",
    "in_progress": "进行中", "paused": "已暂停", "completed": "已完成",
    "cancelled": "已取消",
}


class PauseRequirementAction(ActionBase):

    @property
    def name(self) -> str:
        return "pause_requirement"

    @property
    def description(self) -> str:
        return "暂停某个进行中的需求（analyzing / decomposed / in_progress 状态可暂停）"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "当用户想暂停某个需求的执行时使用。需求必须处于 analyzing / decomposed / in_progress 状态。"
                "requirement_id 不明确时可传标题关键词，会自动模糊匹配。"
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
                        "description": "暂停原因",
                    },
                },
                "required": ["requirement_id"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        from models import RequirementStatus, validate_requirement_transition

        project_id = context.get("project_id")
        if not project_id:
            return ActionResult(success=False, error="缺少 project_id")

        requirement_id = (context.get("requirement_id") or "").strip()
        reason = (context.get("reason") or "用户通过聊天助手暂停").strip()

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
        if not validate_requirement_transition(current_status, "paused"):
            status_label = _STATUS_LABEL.get(current_status, current_status)
            return ActionResult(
                success=False,
                data={"type": "error", "message": f"需求当前状态为「{status_label}」，无法暂停"},
            )

        now = now_iso()
        await db.update("requirements", {
            "status": RequirementStatus.PAUSED.value,
            "updated_at": now,
        }, "id = ?", (requirement_id,))

        log_id = generate_id("LOG")
        detail_json = json.dumps({"message": f"通过聊天助手暂停需求，原因: {reason}"}, ensure_ascii=False)
        await db.insert("ticket_logs", {
            "id": log_id,
            "ticket_id": None,
            "subtask_id": None,
            "requirement_id": requirement_id,
            "project_id": project_id,
            "agent_type": "ChatAssistant",
            "action": "update_status",
            "from_status": current_status,
            "to_status": "paused",
            "detail": detail_json,
            "level": "info",
            "created_at": now,
        })

        await event_manager.publish_to_project(
            project_id, "requirement_status_changed",
            {"id": requirement_id, "title": req["title"], "from": current_status, "to": "paused"},
        )

        logger.info("聊天助手暂停需求: %s — %s", requirement_id, req["title"])

        return ActionResult(
            success=True,
            data={
                "type": "requirement_paused",
                "requirement_id": requirement_id,
                "title": req["title"],
                "from_status": current_status,
                "to_status": "paused",
                "reason": reason,
                "message": f"需求「{req['title']}」已暂停",
            },
        )
