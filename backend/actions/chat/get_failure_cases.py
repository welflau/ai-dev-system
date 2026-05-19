"""
GetFailureCasesAction — 查询失败案例库
"""
import logging
from typing import Any, Dict

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.chat.get_failure_cases")


class GetFailureCasesAction(ActionBase):

    @property
    def name(self) -> str:
        return "get_failure_cases"

    @property
    def description(self) -> str:
        return "查询项目失败案例库（历史失败根因、修复策略）"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "查询当前项目积累的失败案例库（Reflexion 机制记录）。\n"
                "包含：失败根因、漏掉的需求点、策略调整方案。\n"
                "适合回答「这类问题之前踩过哪些坑」「有什么经验教训」等问题。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "关键词搜索（标题、根因、策略）",
                    },
                    "failure_type": {
                        "type": "string",
                        "description": "失败类型过滤（如 compile_error / test_failed / acceptance_rejected）",
                    },
                    "resolved": {
                        "type": "boolean",
                        "description": "true=已解决 / false=未解决 / 不传=全部",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回数量，默认 10",
                    },
                },
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        project_id = context.get("project_id")
        if not project_id:
            return ActionResult(success=False, error="需要在项目内使用")

        query = (context.get("query") or "").strip()
        failure_type = (context.get("failure_type") or "").strip()
        resolved = context.get("resolved")
        limit = min(int(context.get("limit") or 10), 30)

        try:
            from database import db

            conditions = ["project_id = ?"]
            params: list = [project_id]

            if failure_type:
                conditions.append("failure_type = ?")
                params.append(failure_type)
            if resolved is not None:
                conditions.append("resolved = ?")
                params.append(1 if resolved else 0)
            if query:
                conditions.append(
                    "(ticket_title LIKE ? OR root_cause LIKE ? OR strategy_change LIKE ?)"
                )
                params.extend([f"%{query}%", f"%{query}%", f"%{query}%"])

            where = " AND ".join(conditions)
            rows = await db.fetch_all(
                f"""SELECT id, failure_type, ticket_title, root_cause,
                           strategy_change, specific_changes, confidence,
                           resolved, created_at
                    FROM failure_cases
                    WHERE {where}
                    ORDER BY created_at DESC
                    LIMIT ?""",
                tuple(params) + (limit,),
            )

            if not rows:
                return ActionResult(
                    success=True,
                    message="没有找到符合条件的失败案例",
                    data={"type": "failure_cases", "cases": [], "total": 0},
                )

            cases = []
            for r in rows:
                cases.append({
                    "id": r["id"][-8:],
                    "failure_type": r["failure_type"] or "",
                    "title": r["ticket_title"] or "",
                    "root_cause": (r["root_cause"] or "")[:200],
                    "strategy": (r["strategy_change"] or "")[:200],
                    "changes": (r["specific_changes"] or "")[:150],
                    "confidence": r["confidence"] or 0,
                    "resolved": bool(r["resolved"]),
                    "created_at": (r["created_at"] or "")[:10],
                })

            lines = [f"共找到 {len(cases)} 条失败案例：\n"]
            for c in cases:
                mark = "✅" if c["resolved"] else "⏳"
                lines.append(
                    f"• {mark} [{c['failure_type']}] **{c['title']}**（{c['created_at']}）"
                )
                if c["root_cause"]:
                    lines.append(f"  根因：{c['root_cause'][:100]}")
                if c["strategy"]:
                    lines.append(f"  策略：{c['strategy'][:100]}")

            return ActionResult(
                success=True,
                message="\n".join(lines),
                data={"type": "failure_cases", "cases": cases, "total": len(cases)},
            )
        except Exception as e:
            logger.error("get_failure_cases 失败: %s", e)
            return ActionResult(success=False, error=str(e))
