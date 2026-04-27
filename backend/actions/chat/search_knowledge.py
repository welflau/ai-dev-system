"""
SearchKnowledgeAction — 搜索项目知识库和全局知识库文档

对 LLM 暴露为 tool。AI 助手在以下场景主动调用：
- 遇到不确定的 API 用法、架构约束
- 编译错误查已知问题列表
- 用户询问规范、设计文档、接口定义

基于 SQLite FTS5 全文索引（knowledge_fts 虚拟表）实现关键词检索，
支持 AND/OR/NOT 和前缀匹配（如 `UCapsule*`）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from actions.base import ActionBase, ActionResult
from database import db

logger = logging.getLogger("action.search_knowledge")


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
                "搜索项目知识库文档，查找已有的规范、设计说明、已知错误修复方法。\n"
                "当遇到以下情况时主动调用：\n"
                "· 不确定某个 API / 类型 / 模块的用法\n"
                "· 编译或运行时出现错误，想查是否有历史解决方案\n"
                "· 用户询问项目规范、架构说明、接口设计\n"
                "支持关键词搜索，例如：'UCapsuleComponent 头文件'、'OnRep UFUNCTION 冲突'、'登录 API'"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词或短语，如 'UCapsuleComponent 头文件' 或 'OnRep UFUNCTION'",
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
            return ActionResult(status="fail", data={"error": "query 不能为空"})

        try:
            if project_id:
                # 项目内：该项目文档 + 全局文档
                rows = await db.fetch_all("""
                    SELECT ki.filename,
                           ki.project_id,
                           snippet(knowledge_fts, 0, '**', '**', '...', 40) AS snippet,
                           substr(ki.content, 1, 500)                        AS preview
                    FROM knowledge_fts
                    JOIN knowledge_index ki ON knowledge_fts.rowid = ki.id
                    WHERE knowledge_fts MATCH ?
                      AND (ki.project_id = ? OR ki.project_id IS NULL)
                    ORDER BY rank
                    LIMIT ?
                """, (query, project_id, limit))
            else:
                # 全局模式：搜索所有项目 + 全局文档
                rows = await db.fetch_all("""
                    SELECT ki.filename,
                           ki.project_id,
                           snippet(knowledge_fts, 0, '**', '**', '...', 40) AS snippet,
                           substr(ki.content, 1, 500)                        AS preview
                    FROM knowledge_fts
                    JOIN knowledge_index ki ON knowledge_fts.rowid = ki.id
                    WHERE knowledge_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                """, (query, limit))
        except Exception as e:
            logger.warning("knowledge_fts 搜索出错: %s", e)
            return ActionResult(status="fail", data={"error": f"搜索失败: {e}"})

        if not rows:
            return ActionResult(status="success", data={
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

        return ActionResult(status="success", data={
            "query": query,
            "results": results,
            "count": len(results),
        })
