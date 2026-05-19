"""SearchDesignKnowledgeAction — 搜索设计/UX 知识库"""
import logging
from typing import Any, Dict
from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.chat.search_design_knowledge")


class SearchDesignKnowledgeAction(ActionBase):

    @property
    def name(self) -> str:
        return "search_design_knowledge"

    @property
    def description(self) -> str:
        return "搜索设计/UX 知识库（UI 规范、交互模式、设计原则）"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "搜索设计和 UX 知识库，获取 UI 规范、交互模式、设计原则等内容。\n"
                "支持全文搜索和分类过滤。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "category": {"type": "string", "description": "分类过滤（可选）"},
                    "limit": {"type": "integer", "description": "返回数量，默认 8"},
                },
                "required": ["query"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        query = (context.get("query") or "").strip()
        category = (context.get("category") or "").strip()
        limit = min(int(context.get("limit") or 8), 20)

        if not query:
            return ActionResult(success=False, error="query 不能为空")

        try:
            from database import db

            # 优先 FTS5
            try:
                rows = await db.fetch_all(
                    """SELECT d.id, d.title, d.category, d.summary, d.content, d.tags
                       FROM design_knowledge_fts f
                       JOIN design_knowledge d ON d.id = f.rowid
                       WHERE design_knowledge_fts MATCH ?
                       ORDER BY rank LIMIT ?""",
                    (query, limit),
                )
            except Exception:
                rows = await db.fetch_all(
                    """SELECT id, title, category, summary, content, tags FROM design_knowledge
                       WHERE title LIKE ? OR content LIKE ? OR tags LIKE ?
                       LIMIT ?""",
                    (f"%{query}%", f"%{query}%", f"%{query}%", limit),
                )

            if category:
                rows = [r for r in rows if (r.get("category") or "").lower() == category.lower()]

            if not rows:
                return ActionResult(success=True, message=f"没有找到关于「{query}」的设计知识",
                                    data={"type": "design_knowledge", "results": [], "total": 0})

            lines = [f"找到 {len(rows)} 条设计知识：\n"]
            results = []
            for r in rows:
                snippet = r.get("summary") or (r.get("content") or "")[:150]
                lines.append(f"• **{r['title']}**（{r.get('category', '')}）")
                if snippet:
                    lines.append(f"  {snippet[:120]}")
                results.append({"title": r["title"], "category": r.get("category", ""),
                                 "summary": snippet[:200], "tags": r.get("tags", "")})

            return ActionResult(success=True, message="\n".join(lines),
                                data={"type": "design_knowledge", "results": results, "total": len(results)})
        except Exception as e:
            logger.error("search_design_knowledge 失败: %s", e)
            return ActionResult(success=False, error=str(e))
