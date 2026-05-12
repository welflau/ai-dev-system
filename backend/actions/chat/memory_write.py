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
                "适合：用户偏好、项目约定、已解决的问题、重要决策等。\n"
                "category 可选：user（用户偏好）/ project（项目约定）/ technical（技术决策）"
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
                        "enum": ["user", "project", "technical"],
                        "description": "记忆类型，默认 project",
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

        if category not in ("user", "project", "technical"):
            category = "project"

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
