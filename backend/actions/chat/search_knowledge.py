"""
SearchKnowledgeAction — 搜索项目知识库和全局知识库文档

两条入口：
1. 聊天工具：模型主动调用 search_knowledge
2. Agent 报错流程（自动，不依赖模型自觉）：
   QueryEngine 工具失败 / 工单 blocked 诊断 / Dev 重试 / 关键 TOOL_ERROR 告警
   → lookup_error_playbook() 先查知识库，再进入下一步

基于 SQLite FTS5 trigram 索引，支持中英文关键词检索。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from actions.base import ActionBase, ActionResult
from database import db

logger = logging.getLogger("action.search_knowledge")

# 报错检索时跳过这些工具，避免递归/噪音
SKIP_ERROR_LOOKUP_TOOLS = frozenset({
    "search_knowledge", "web_search", "search_ticket_history",
})

_STOP_TOKENS = frozenset({
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "was",
    "error", "failed", "failure", "exception",
    "的", "了", "和", "或", "在", "是", "请", "检查", "失败", "错误",
    "agent", "action", "tool", "system",
})


def _sanitize_fts_query(q: str) -> str:
    """转义 FTS5 不支持的特殊字符，保留搜索意图"""
    # FTS5 trigram 模式下直接用引号包裹整个 query 最安全
    # 去掉 query 本身含有的引号，防止嵌套
    clean = q.replace('"', ' ').strip()
    # 若包含特殊字符（点、括号等）则整体用双引号包裹做短语搜索
    if re.search(r'[.\-+*():!]', clean):
        return f'"{clean}"'
    return clean


def _display_name(filename: str) -> str:
    fname = filename or ""
    if fname.startswith("sys_docs__"):
        display = fname[len("sys_docs__"):]
    elif fname.startswith("sys_devnotes__"):
        display = fname[len("sys_devnotes__"):]
    else:
        display = fname
    if display.endswith(".md"):
        display = display[:-3]
    return display


def _row_to_hit(r: Dict[str, Any]) -> Dict[str, Any]:
    display = _display_name(r.get("filename") or "")
    doc_id = r["id"]
    return {
        "id": doc_id,
        "filename": r.get("filename") or "",
        "display_name": display,
        "scope": "project" if r.get("project_id") else "global",
        "snippet": r.get("snippet") or "",
        "preview": r.get("preview") or "",
        "cite": f"[{display}](ads-kb:{doc_id})",
    }


async def lookup_knowledge(
    query: str,
    project_id: Optional[str] = None,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """FTS 检索知识库。失败返回空列表（fail-open）。"""
    query = (query or "").strip()
    if not query:
        return []
    fts_query = _sanitize_fts_query(query)
    limit = max(1, min(int(limit or 3), 8))
    try:
        if project_id:
            rows = await db.fetch_all("""
                SELECT ki.id, ki.filename, ki.project_id,
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
                SELECT ki.id, ki.filename, ki.project_id,
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
        return []
    return [_row_to_hit(r) for r in (rows or [])]


def build_error_search_query(
    error_text: str = "",
    *,
    tool_name: str = "",
    extra: str = "",
) -> str:
    """从报错文本抽出适合 FTS 的关键词，避免把整段堆栈当短语搜索。"""
    tool = (tool_name or "").replace(":", " ").replace("_", " ").replace(".", " ")
    if tool.lower().startswith("agent "):
        tool = tool[6:]
    raw = " ".join(x for x in (extra, tool, error_text) if x)
    raw = re.sub(r"https?://\S+", " ", raw)
    raw = re.sub(r"[0-9a-fA-F]{8,}", " ", raw)
    raw = re.sub(r"[\\/][^\s]{6,}", " ", raw)
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_-]{1,}", raw)
    seen: List[str] = []
    for t in tokens:
        low = t.lower()
        if low in _STOP_TOKENS:
            continue
        if low not in seen:
            seen.append(t if "\u4e00" <= t[0] <= "\u9fff" else low)
        if len(seen) >= 8:
            break
    return " ".join(seen[:6]).strip()[:80]


async def lookup_error_playbook(
    error_text: str = "",
    project_id: Optional[str] = None,
    *,
    tool_name: str = "",
    extra: str = "",
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """Agent 报错后的知识库检索：先按错误关键词查 FAQ/手册。"""
    short = (tool_name or "").rsplit("__", 1)[-1]
    if short in SKIP_ERROR_LOOKUP_TOOLS:
        return []
    query = build_error_search_query(error_text, tool_name=tool_name, extra=extra)
    if not query:
        return []
    hits = await lookup_knowledge(query, project_id, limit)
    if hits:
        logger.info("🔎 报错知识库命中 %d 条 query=%r", len(hits), query[:60])
        return hits
    parts = query.split()
    if len(parts) >= 2:
        fallback = " ".join(parts[:2])
        hits = await lookup_knowledge(fallback, project_id, limit)
        if hits:
            logger.info("🔎 报错知识库回退命中 %d 条 query=%r", len(hits), fallback)
    return hits


def format_playbooks_for_llm(hits: List[Dict[str, Any]]) -> str:
    if not hits:
        return ""
    lines = ["## 知识库相关条目（报错后自动检索，优先按此处理）"]
    for h in hits[:3]:
        snippet = (h.get("snippet") or h.get("preview") or "")[:240].replace("\n", " ")
        lines.append(f"- {h.get('cite') or h.get('display_name')}: {snippet}")
    lines.append("请按上述手册给出下一步，不要只复述错误原文。")
    return "\n".join(lines)


def compact_knowledge_hits(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """告警卡 / 诊断 JSON 用的精简字段。"""
    out = []
    for h in hits[:3]:
        out.append({
            "id": h.get("id"),
            "display_name": h.get("display_name") or "",
            "cite": h.get("cite") or "",
            "snippet": (h.get("snippet") or "")[:160],
        })
    return out


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

        results = await lookup_knowledge(query, project_id, limit)
        if not results:
            return ActionResult(success=True, data={
                "query": query,
                "results": [],
                "message": f"知识库中未找到与「{query}」相关的内容",
            })

        return ActionResult(success=True, data={
            "query": query,
            "results": results,
            "count": len(results),
            "citation_hint": "列举文档时请用 results[].cite 里的 Markdown 链接（如 [标题](ads-kb:123)），用户可点击打开",
        })
