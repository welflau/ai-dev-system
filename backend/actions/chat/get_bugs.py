"""
GetBugsAction — 查询项目 Bug 列表
"""
import logging
from typing import Any, Dict

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.chat.get_bugs")

_STATUS_LABELS = {
    "open": "待处理", "in_dev": "修复中", "fixed": "已修复",
    "closed": "已关闭", "wontfix": "不修复",
}
_PRIORITY_LABELS = {
    "critical": "🔴 严重", "high": "🟠 高", "medium": "🟡 中", "low": "🟢 低",
}


class GetBugsAction(ActionBase):

    @property
    def name(self) -> str:
        return "get_bugs"

    @property
    def description(self) -> str:
        return "查询项目的 Bug 列表（状态、优先级、修复情况）"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "查询当前项目的 Bug 列表。\n"
                "可按状态过滤（open/in_dev/fixed/closed），支持关键词搜索。\n"
                "返回：Bug ID、标题、优先级、状态、创建时间等。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "状态过滤：open（待处理）/ in_dev（修复中）/ fixed（已修复）/ closed / all（默认 all）",
                        "enum": ["open", "in_dev", "fixed", "closed", "all"],
                    },
                    "priority": {
                        "type": "string",
                        "description": "优先级过滤：critical / high / medium / low / all（默认 all）",
                        "enum": ["critical", "high", "medium", "low", "all"],
                    },
                    "query": {
                        "type": "string",
                        "description": "关键词搜索（标题或描述）",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回数量上限，默认 20",
                    },
                },
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        project_id = context.get("project_id")
        if not project_id:
            return ActionResult(success=False, error="需要在项目内使用")

        status = context.get("status", "all")
        priority = context.get("priority", "all")
        query = (context.get("query") or "").strip()
        limit = min(int(context.get("limit") or 20), 50)

        try:
            from database import db

            conditions = ["b.project_id = ?"]
            params: list = [project_id]

            if status and status != "all":
                conditions.append("b.status = ?")
                params.append(status)
            if priority and priority != "all":
                conditions.append("b.priority = ?")
                params.append(priority)
            if query:
                conditions.append("(b.title LIKE ? OR b.description LIKE ?)")
                params.extend([f"%{query}%", f"%{query}%"])

            where = " AND ".join(conditions)
            rows = await db.fetch_all(
                f"""SELECT b.id, b.title, b.priority, b.status,
                           b.fix_notes, b.created_at, b.fixed_at,
                           t.title as ticket_title
                    FROM bugs b
                    LEFT JOIN tickets t ON t.id = b.ticket_id
                    WHERE {where}
                    ORDER BY
                      CASE b.priority WHEN 'critical' THEN 1 WHEN 'high' THEN 2
                                      WHEN 'medium' THEN 3 ELSE 4 END,
                      b.created_at DESC
                    LIMIT ?""",
                tuple(params) + (limit,),
            )

            if not rows:
                return ActionResult(
                    success=True,
                    message="没有找到符合条件的 Bug",
                    data={"type": "bug_list", "bugs": [], "total": 0},
                )

            bugs = []
            for r in rows:
                pri = _PRIORITY_LABELS.get(r["priority"], r["priority"])
                sta = _STATUS_LABELS.get(r["status"], r["status"])
                bugs.append({
                    "id": r["id"],
                    "title": r["title"],
                    "priority": pri,
                    "status": sta,
                    "fix_notes": r["fix_notes"] or "",
                    "created_at": (r["created_at"] or "")[:10],
                    "fixed_at": (r["fixed_at"] or "")[:10],
                    "ticket": r["ticket_title"] or "",
                })

            lines = [f"共找到 {len(bugs)} 个 Bug：\n"]
            for b in bugs:
                lines.append(f"• {b['priority']} [{b['status']}] **{b['title']}**（{b['created_at']}）")
                if b["fix_notes"]:
                    lines.append(f"  修复说明：{b['fix_notes'][:80]}")

            return ActionResult(
                success=True,
                message="\n".join(lines),
                data={"type": "bug_list", "bugs": bugs, "total": len(bugs)},
            )
        except Exception as e:
            logger.error("get_bugs 失败: %s", e)
            return ActionResult(success=False, error=str(e))
