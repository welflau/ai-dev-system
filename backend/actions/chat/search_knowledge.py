"""
SearchKnowledgeAction — 搜索项目知识库和全局知识库文档

对 LLM 暴露为 tool。AI 助手在以下场景主动调用：
- 遇到不确定的 API 用法、架构约束
- 编译错误查已知问题列表
- 用户询问规范、设计文档、接口定义
- 询问版本更新、开发日志、技术方案

基于 SQLite FTS5 trigram 索引，支持中英文关键词检索。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from actions.base import ActionBase, ActionResult
from database import db

logger = logging.getLogger("action.search_knowledge")


def _sanitize_fts_query(q: str) -> str:
    """转义 FTS5 不支持的特殊字符，保留搜索意图"""
    # FTS5 trigram 模式下直接用引号包裹整个 query 最安全
    # 去掉 query 本身含有的引号，防止嵌套
    clean = q.replace('"', ' ').strip()
    # 若包含特殊字符（点、括号等）则整体用双引号包裹做短语搜索
    if re.search(r'[.\-+*():!]', clean):
        return f'"{clean}"'
    return clean


class SearchKnowledgeAction(ActionBase):

    @property
    def name(self) -> str:
        return "search_knowledge"

    @property
    def description(self) -> str:
        return "搜索项目知识库和全局知识库文档"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "搜索项目知识库文档，查找已有的规范、设计说明、版本更新、已知错误修复方法。\n"
                "当遇到以下情况时主动调用：\n"
                "· 用户询问版本更新内容（如 v0.19 做了什么）\n"
                "· 用户询问某个功能的设计方案或开发日志\n"
                "· 不确定某个 API / 类型 / 模块的用法\n"
                "· 编译或运行时出现错误，想查是否有历史解决方案\n"
                "支持关键词搜索，例如：'v0.19'、'知识库'、'UE 编译错误'、'Hermes'"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，如 'v0.19' 或 'UE 编译错误'",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回结果数量，默认 3，最多 8",
                        "default": 3,
                    },
                },
                "required": ["query"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        query = (context.get("query") or "").strip()
        project_id = context.get("project_id")
        limit = min(int(context.get("limit") or 3), 8)

        if not query:
            return ActionResult(success=False, error="query 不能为空")

        fts_query = _sanitize_fts_query(query)

        try:
            if project_id:
                rows = await db.fetch_all("""
                    SELECT ki.filename,
                           ki.project_id,
                           snippet(knowledge_fts, 0, '**', '**', '...', 64) AS snippet,
                           substr(ki.content, 1, 1500)                       AS preview
                    FROM knowledge_fts
                    JOIN knowledge_index ki ON knowledge_fts.rowid = ki.id
                    WHERE knowledge_fts MATCH ?
                      AND (ki.project_id = ? OR ki.project_id IS NULL)
                    ORDER BY rank
                    LIMIT ?
                """, (fts_query, project_id, limit))
            else:
                rows = await db.fetch_all("""
                    SELECT ki.filename,
                           ki.project_id,
                           snippet(knowledge_fts, 0, '**', '**', '...', 64) AS snippet,
                           substr(ki.content, 1, 1500)                       AS preview
                    FROM knowledge_fts
                    JOIN knowledge_index ki ON knowledge_fts.rowid = ki.id
                    WHERE knowledge_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                """, (fts_query, limit))
        except Exception as e:
            logger.warning("knowledge_fts 搜索出错 (query=%r): %s", fts_query, e)
            return ActionResult(success=False, error=f"搜索失败: {e}")

        if not rows:
            return ActionResult(success=True, data={
                "query": query,
                "results": [],
                "message": f"知识库中未找到与「{query}」相关的内容",
            })

        results = [
            {
                "filename": r["filename"],
                "scope": "project" if r["project_id"] else "global",
                "snippet": r["snippet"],
                "preview": r["preview"],
            }
            for r in rows
        ]

        return ActionResult(success=True, data={
            "query": query,
            "results": results,
            "count": len(results),
        })
