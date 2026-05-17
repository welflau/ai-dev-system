"""
GetMemoryAction — 查询项目 Agent Memory（决策/交接/经验记录）

让 ChatAssistant 能回答「当初为什么这样设计」「这个需求踩过什么坑」等问题。
"""
from typing import Any, Dict
from actions.base import ActionBase, ActionResult
from database import db


class GetMemoryAction(ActionBase):

    @property
    def name(self) -> str:
        return "get_memory"

    @property
    def description(self) -> str:
        return "查询项目历史决策、交接记录和经验教训"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "当用户询问「当初为什么这样设计」「这个功能踩过什么坑」「之前的决策是什么」时调用。\n"
                "支持按类型筛选：decision（架构/方案决策）/ insight（经验教训）/ handoff（交接记录）"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "memory_type": {
                        "type": "string",
                        "enum": ["decision", "handoff", "project_status", "insight", "all"],
                        "description": "记忆类型，默认 all",
                    },
                    "limit": {"type": "integer", "description": "返回条数，默认 5", "default": 5},
                },
                "required": ["query"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        project_id   = context.get("project_id", "")
        query        = (context.get("query") or "").strip()
        memory_type  = context.get("memory_type", "all")
        limit        = min(int(context.get("limit") or 5), 20)

        if not project_id:
            return ActionResult(success=False, error="缺少 project_id")

        # FTS5 语义搜索（优先），降级 LIKE
        try:
            if memory_type == "all":
                rows = await db.fetch_all(
                    """SELECT m.* FROM agent_memory m
                       JOIN agent_memory_fts fts ON m.rowid = fts.rowid
                       WHERE m.project_id = ?
                         AND agent_memory_fts MATCH ?
                       ORDER BY rank, m.created_at DESC LIMIT ?""",
                    (project_id, query, limit),
                )
            else:
                rows = await db.fetch_all(
                    """SELECT m.* FROM agent_memory m
                       JOIN agent_memory_fts fts ON m.rowid = fts.rowid
                       WHERE m.project_id = ? AND m.type = ?
                         AND agent_memory_fts MATCH ?
                       ORDER BY rank, m.created_at DESC LIMIT ?""",
                    (project_id, memory_type, query, limit),
                )
        except Exception:
            # FTS5 不可用时降级 LIKE（兼容旧数据未建 FTS 索引的情况）
            if memory_type == "all":
                rows = await db.fetch_all(
                    """SELECT * FROM agent_memory
                       WHERE project_id = ? AND (title LIKE ? OR content LIKE ? OR tags LIKE ?)
                       ORDER BY created_at DESC LIMIT ?""",
                    (project_id, f"%{query}%", f"%{query}%", f"%{query}%", limit),
                )
            else:
                rows = await db.fetch_all(
                    """SELECT * FROM agent_memory
                       WHERE project_id = ? AND type = ?
                         AND (title LIKE ? OR content LIKE ? OR tags LIKE ?)
                       ORDER BY created_at DESC LIMIT ?""",
                    (project_id, memory_type, f"%{query}%", f"%{query}%", f"%{query}%", limit),
                )

        if not rows:
            return ActionResult(
                success=True,
                data={"memories": [], "message": f"没有找到与「{query}」相关的记忆"},
            )

        memories = []
        for r in rows:
            memories.append({
                "id": r["id"],
                "type": r["type"],
                "title": r["title"],
                "content": r["content"],
                "agent_type": r["agent_type"],
                "created_at": r["created_at"][:10],
            })

        return ActionResult(
            success=True,
            data={
                "memories": memories,
                "count": len(memories),
                "message": f"找到 {len(memories)} 条相关记忆",
            },
        )
