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

_PAUSABLE_STATUSES = {"submitted", "analyzing", "decomposed", "in_progress"}


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


class PauseRequirementsBatchAction(ActionBase):
    """批量暂停多条需求（及其所有关联工单的 Orchestrator 调度）"""

    @property
    def name(self) -> str:
        return "pause_requirements_batch"

    @property
    def description(self) -> str:
        return "批量暂停多条需求及其工单的自动调度"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "当用户说「暂停所有工单」「暂停全部需求」「先停下来」等时使用。\n"
                "可传具体 requirement_ids 列表，或传 filter='all' 暂停项目所有可暂停需求。\n"
                "暂停后 Orchestrator 不再调度这些需求的工单，用户可随时 resume 恢复。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "requirement_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要暂停的需求 ID 列表（与 filter 二选一）",
                    },
                    "filter": {
                        "type": "string",
                        "enum": ["all", "in_progress", "decomposed"],
                        "description": "按状态批量暂停：all=全部可暂停 / in_progress=进行中 / decomposed=已拆单",
                    },
                    "reason": {
                        "type": "string",
                        "description": "暂停原因",
                    },
                },
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        project_id = context.get("project_id")
        if not project_id:
            return ActionResult(success=False, error="缺少 project_id")

        requirement_ids = context.get("requirement_ids") or []
        filter_mode = (context.get("filter") or "").strip()
        reason = (context.get("reason") or "用户通过聊天助手批量暂停").strip()

        # 确定要暂停的需求列表
        if requirement_ids:
            placeholders = ",".join("?" * len(requirement_ids))
            reqs = await db.fetch_all(
                f"SELECT * FROM requirements WHERE project_id = ? AND id IN ({placeholders})",
                (project_id, *requirement_ids),
            )
        elif filter_mode:
            if filter_mode == "all":
                statuses = list(_PAUSABLE_STATUSES)
            elif filter_mode == "in_progress":
                statuses = ["in_progress"]
            elif filter_mode == "decomposed":
                statuses = ["decomposed"]
            else:
                statuses = list(_PAUSABLE_STATUSES)
            placeholders = ",".join("?" * len(statuses))
            reqs = await db.fetch_all(
                f"SELECT * FROM requirements WHERE project_id = ? AND status IN ({placeholders})",
                (project_id, *statuses),
            )
        else:
            return ActionResult(success=False, error="必须提供 requirement_ids 或 filter")

        if not reqs:
            return ActionResult(
                success=True,
                data={"type": "requirement_paused", "count": 0,
                      "message": "没有找到可暂停的需求"},
            )

        now = now_iso()
        paused, skipped = [], []

        for req in reqs:
            if req["status"] not in _PAUSABLE_STATUSES:
                skipped.append(req["title"])
                continue

            await db.update("requirements",
                            {"status": "paused", "updated_at": now},
                            "id = ?", (req["id"],))

            log_id = generate_id("LOG")
            await db.insert("ticket_logs", {
                "id": log_id, "ticket_id": None, "subtask_id": None,
                "requirement_id": req["id"], "project_id": project_id,
                "agent_type": "ChatAssistant", "action": "update_status",
                "from_status": req["status"], "to_status": "paused",
                "detail": json.dumps({"message": f"批量暂停: {reason}"}, ensure_ascii=False),
                "level": "info", "created_at": now,
            })
            paused.append(req["title"])

        # 同步清理 Orchestrator 活跃集合
        try:
            from orchestrator import orchestrator
            orchestrator._project_active.pop(project_id, None)
            # 清理与这些需求关联的正在处理工单
            req_ids = {r["id"] for r in reqs if r["title"] in paused}
            to_remove = set()
            for tid in list(orchestrator._processing):
                t = await db.fetch_one(
                    "SELECT requirement_id FROM tickets WHERE id = ?", (tid,))
                if t and t["requirement_id"] in req_ids:
                    to_remove.add(tid)
            orchestrator._processing -= to_remove
            logger.info("批量暂停: 从 Orchestrator 移除 %d 个工单", len(to_remove))
        except Exception as oe:
            logger.warning("批量暂停清理 Orchestrator 失败: %s", oe)

        await event_manager.publish_to_project(
            project_id, "requirement_status_changed",
            {"batch": True, "count": len(paused), "action": "paused"},
        )

        msg = f"已暂停 {len(paused)} 条需求"
        if skipped:
            msg += f"（{len(skipped)} 条状态不允许暂停：{', '.join(skipped[:3])}）"

        logger.info("聊天助手批量暂停需求: %d 条 (project=%s)", len(paused), project_id)

        return ActionResult(
            success=True,
            data={
                "type": "requirement_paused",
                "count": len(paused),
                "paused_titles": paused,
                "skipped_titles": skipped,
                "message": msg,
            },
        )
