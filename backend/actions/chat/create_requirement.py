"""
CreateRequirementAction — 真正创建需求并自动触发拆单

与 ConfirmRequirementAction 的区别：
- ConfirmRequirementAction 只生成草稿卡片，不碰数据库
- CreateRequirementAction 直接写库 + 状态 submitted → analyzing + 调度 ProductAgent 拆单

调用来源：
1. 用户在前端点击确认创建按钮（走 /confirm-create 端点）
2. 旧 [ACTION:CREATE_REQUIREMENT] 路径（当前 prompt 已禁止，但解析器仍支持作为兜底）
"""
import asyncio
import json
import logging
from typing import Any, Dict

from actions.base import ActionBase, ActionResult
from database import db
from events import event_manager
from utils import generate_id, now_iso

logger = logging.getLogger("actions.chat.create_requirement")


_VALID_PRIORITIES = ("critical", "high", "medium", "low")


class CreateRequirementAction(ActionBase):

    @property
    def name(self) -> str:
        return "create_requirement"

    @property
    def description(self) -> str:
        return "直接创建需求并自动触发 ProductAgent 分析拆单（用于用户确认后的实际落库）"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        # 注意：本 Action 不对 LLM 暴露为 tool——LLM 只应调用 confirm_requirement 产出草稿。
        # 此 schema 保留只是为了接口一致，P2 接入 tool_use 时会从 action_classes 里排除本项。
        return {
            "name": self.name,
            "description": "（内部用）直接创建需求——LLM 不应直接调用此工具，应通过 confirm_requirement 让用户确认。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "priority": {"type": "string", "enum": list(_VALID_PRIORITIES)},
                },
                "required": ["title", "description"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        project_id = context.get("project_id")
        if not project_id:
            return ActionResult(success=False, error="缺少 project_id")

        title = (context.get("title") or "").strip()
        description = (context.get("description") or "").strip()
        priority = context.get("priority") or "medium"

        if not title or not description:
            return ActionResult(
                success=False,
                data={"type": "error", "message": "需求标题和描述不能为空"},
            )

        if priority not in _VALID_PRIORITIES:
            priority = "medium"

        req_id = generate_id("REQ")
        now = now_iso()
        req_data = {
            "id": req_id,
            "project_id": project_id,
            "title": title,
            "description": description,
            "priority": priority,
            "status": "submitted",
            "submitter": "chat_assistant",
            "prd_content": None,
            "module": None,
            "tags": None,
            "estimated_hours": None,
            "actual_hours": None,
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
        }
        await db.insert("requirements", req_data)

        log_id = generate_id("LOG")
        detail_json = json.dumps({"message": f"通过聊天助手创建需求「{title}」"}, ensure_ascii=False)
        await db.insert("ticket_logs", {
            "id": log_id,
            "ticket_id": None,
            "subtask_id": None,
            "requirement_id": req_id,
            "project_id": project_id,
            "agent_type": "ChatAssistant",
            "action": "create",
            "from_status": None,
            "to_status": "submitted",
            "detail": detail_json,
            "level": "info",
            "created_at": now,
        })

        await event_manager.publish_to_project(
            project_id, "requirement_created", {"id": req_id, "title": title}
        )

        logger.info("聊天助手创建需求: %s — %s", req_id, title)

        # === 自动触发拆单 ===
        from models import RequirementStatus
        analyze_time = now_iso()
        await db.update(
            "requirements",
            {"status": RequirementStatus.ANALYZING.value, "updated_at": analyze_time},
            "id = ?",
            (req_id,),
        )

        start_log_id = generate_id("LOG")
        start_detail = json.dumps({"message": "ProductAgent 开始分析需求"}, ensure_ascii=False)
        await db.insert("ticket_logs", {
            "id": start_log_id,
            "ticket_id": None,
            "subtask_id": None,
            "requirement_id": req_id,
            "project_id": project_id,
            "agent_type": "ProductAgent",
            "action": "start",
            "from_status": "submitted",
            "to_status": "analyzing",
            "detail": start_detail,
            "level": "info",
            "created_at": analyze_time,
        })

        await event_manager.publish_to_project(
            project_id, "requirement_analyzing", {"id": req_id, "title": title}
        )

        # 后台执行拆单（Orchestrator 调度）
        from orchestrator import orchestrator
        asyncio.create_task(orchestrator.handle_requirement(project_id, req_id))
        logger.info("自动触发需求拆单: %s", req_id)

        return ActionResult(
            success=True,
            data={
                "type": "requirement_created",
                "requirement_id": req_id,
                "title": title,
                "description": description,
                "priority": priority,
                "message": f"需求「{title}」已创建，正在自动分析拆单...",
            },
        )
