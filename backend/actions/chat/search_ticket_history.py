"""
SearchTicketHistoryAction — 搜索历史工单的解决方案

对 LLM 暴露为 tool。AI 助手在以下场景主动调用：
- 遇到编译错误，搜索历史上类似错误是怎么解决的
- 遇到测试失败，查历史类似失败的根因
- 用户询问「之前有没有解决过类似问题」

基于 SQLite FTS5（tickets_fts 虚拟表），
返回历史工单标题、匹配片段、以及 Reflexion 根因分析（最有价值的部分）。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from actions.base import ActionBase, ActionResult
from database import db

logger = logging.getLogger("action.search_ticket_history")


class SearchTicketHistoryAction(ActionBase):

    @property
    def name(self) -> str:
        return "search_ticket_history"

    @property
    def description(self) -> str:
        return "搜索历史工单的解决方案"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "搜索历史工单，查找类似问题的解决方案和根因分析。\n"
                "当遇到以下情况时主动调用：\n"
                "· 编译错误（查是否曾经解决过同类错误）\n"
                "· 测试失败（查历史类似失败的根因）\n"
                "· 用户问「之前有没有遇到过 X 问题」\n"
                "返回匹配的历史工单和 AI 根因分析，帮助快速定位解决方向。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，如错误类型、类名、函数名、错误码",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回结果数量，默认 3，最多 5",
                        "default": 3,
                    },
                },
                "required": ["query"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        query = (context.get("query") or "").strip()
        project_id = context.get("project_id")
        limit = min(int(context.get("limit") or 3), 5)

        if not query:
            return ActionResult(status="fail", data={"error": "query 不能为空"})

        try:
            rows = await db.fetch_all("""
                SELECT tf.ticket_id,
                       snippet(tickets_fts, 0, '**', '**', '...', 40) AS snippet,
                       t.title, t.status, t.type, t.module,
                       (SELECT tl.detail
                        FROM ticket_logs tl
                        WHERE tl.ticket_id = tf.ticket_id
                          AND tl.action = 'reflection'
                        ORDER BY tl.created_at DESC
                        LIMIT 1) AS reflection_detail,
                       t.updated_at
                FROM tickets_fts tf
                JOIN tickets t ON tf.ticket_id = t.id
                WHERE tickets_fts MATCH ?
                  AND tf.project_id = ?
                  AND t.status IN (
                      'acceptance_passed', 'testing_done', 'deployed', 'development_done'
                  )
                ORDER BY rank
                LIMIT ?
            """, (query, project_id, limit))
        except Exception as e:
            logger.warning("tickets_fts 搜索出错: %s", e)
            return ActionResult(status="fail", data={"error": f"搜索失败: {e}"})

        if not rows:
            return ActionResult(status="success", data={
                "query": query,
                "results": [],
                "message": f"未找到与「{query}」相关的历史工单",
            })

        results = []
        for r in rows:
            root_cause = ""
            if r["reflection_detail"]:
                try:
                    d = json.loads(r["reflection_detail"])
                    root_cause = d.get("reflection", {}).get("root_cause", "")
                except Exception:
                    pass

            results.append({
                "ticket_id": r["ticket_id"],
                "title": r["title"],
                "type": r["type"],
                "module": r["module"],
                "snippet": r["snippet"],
                "root_cause": root_cause,
                "status": r["status"],
                "updated_at": r["updated_at"],
            })

        return ActionResult(status="success", data={
            "query": query,
            "results": results,
            "count": len(results),
        })
