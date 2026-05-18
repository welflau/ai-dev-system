"""
MemoryWriteAction — AI 主动写入记忆

与现有 GetMemoryAction（只读）配对，实现完整的记忆读写闭环。
"""
import logging
from typing import Any, Dict

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.chat.memory_write")


class MemoryWriteAction(ActionBase):

    @property
    def name(self) -> str:
        return "save_memory"

    @property
    def description(self) -> str:
        return "保存重要信息到 Agent 记忆，供后续对话使用"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "将重要信息保存到记忆中，供后续对话检索使用。\n"
                "适合：用户偏好、行为反馈、项目决策、外部资源指针等。\n"
                "category（4 类，对标 Claude Code）：\n"
                "  user_profile     — 用户角色、偏好、知识背景\n"
                "  behavior_feedback — 行为反馈（正向确认 or 纠正）\n"
                "  project_context  — 项目约定、技术决策、里程碑\n"
                "  external_ref     — 外部系统指针（Linear/Notion/文档链接）\n"
                "旧值兼容：user→user_profile, project→project_context, technical→project_context"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "记忆标题（简短，用于检索），如 '用户偏好：代码注释用中文'",
                    },
                    "content": {
                        "type": "string",
                        "description": "记忆内容（详细描述）",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["user_profile", "behavior_feedback", "project_context", "external_ref",
                                 "user", "project", "technical"],  # 旧值向后兼容
                        "description": "记忆类型，默认 project_context",
                    },
                },
                "required": ["title", "content"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        title      = (context.get("title") or "").strip()
        content    = (context.get("content") or "").strip()
        category   = context.get("category") or "project"
        project_id = context.get("project_id")

        if not title:
            return ActionResult(success=False, error="title 不能为空")
        if not content:
            return ActionResult(success=False, error="content 不能为空")

        # 類型映射：舊值向後兼容 + 標準化到 4 類
        _TYPE_MAP = {
            "user":     "user_profile",
            "project":  "project_context",
            "technical": "project_context",
        }
        category = _TYPE_MAP.get(category, category)
        _VALID = {"user_profile", "behavior_feedback", "project_context", "external_ref"}
        if category not in _VALID:
            category = "project_context"

        try:
            from database import db
            from utils import generate_id, now_iso

            mem_id = generate_id("MEM")
            await db.insert("agent_memory", {
                "id": mem_id,
                "project_id": project_id or "__global__",
                "type": category,
                "agent_type": "ChatAssistant",
                "title": title[:200],
                "content": content[:2000],
                "tags": "[]",
                "requirement_id": None,
                "ticket_id": None,
                "created_at": now_iso(),
                "updated_at": now_iso(),
            })
            logger.info("save_memory: %s (%s) project=%s", title[:60], category, project_id)
            return ActionResult(
                success=True,
                data={"type": "memory_saved", "id": mem_id, "title": title, "category": category},
                message=f"已记住：{title}",
            )
        except Exception as e:
            logger.error("save_memory 失败: %s", e)
            return ActionResult(success=False, error=f"保存记忆失败: {e}")
