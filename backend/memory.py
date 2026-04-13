"""
Agent Memory — 统一记忆接口
整合 artifacts / ticket_logs / llm_conversations / git 文件
Agent 通过 Memory 获取历史信息，不直接查数据库
"""
import json
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger("memory")


@dataclass
class MemoryItem:
    """一条记忆"""
    source: str          # "artifact" | "log" | "conversation" | "code"
    content: str         # 内容摘要
    metadata: Dict = field(default_factory=dict)
    created_at: str = ""


class AgentMemory:
    """Agent 记忆管理器"""

    def __init__(self, project_id: str):
        self.project_id = project_id

    async def get_recent(self, k: int = 5, ticket_id: str = None) -> List[MemoryItem]:
        """获取最近 k 条记忆（跨 artifacts + logs + conversations）"""
        from database import db

        items = []

        # 最近的 artifacts
        where = "project_id = ?"
        params = [self.project_id]
        if ticket_id:
            where += " AND ticket_id = ?"
            params.append(ticket_id)

        artifacts = await db.fetch_all(
            f"SELECT type, name, content, created_at FROM artifacts WHERE {where} ORDER BY created_at DESC LIMIT ?",
            (*params, k),
        )
        for a in artifacts:
            items.append(MemoryItem(
                source="artifact",
                content=f"[{a['type']}] {a['name']}",
                metadata={"type": a["type"]},
                created_at=a["created_at"],
            ))

        # 最近的 ticket_logs
        logs = await db.fetch_all(
            f"SELECT agent_type, action, detail, created_at FROM ticket_logs WHERE {where} ORDER BY created_at DESC LIMIT ?",
            (*params, k),
        )
        for l in logs:
            detail_msg = ""
            try:
                d = json.loads(l["detail"]) if l["detail"] else {}
                detail_msg = d.get("message", "")
            except Exception:
                detail_msg = l["detail"] or ""
            items.append(MemoryItem(
                source="log",
                content=f"[{l['agent_type']}] {l['action']}: {detail_msg[:100]}",
                metadata={"agent": l["agent_type"], "action": l["action"]},
                created_at=l["created_at"],
            ))

        # 按时间排序，取最近 k 条
        items.sort(key=lambda x: x.created_at, reverse=True)
        return items[:k]

    async def get_by_ticket(self, ticket_id: str) -> List[MemoryItem]:
        """获取某工单的全部记忆"""
        return await self.get_recent(k=50, ticket_id=ticket_id)

    async def get_code_context(self) -> Dict[str, Any]:
        """获取项目代码上下文（已有文件列表 + 入口代码）"""
        from git_manager import git_manager

        if not git_manager.repo_exists(self.project_id):
            return {"file_list": [], "code": {}}

        tree = await git_manager.get_file_tree(self.project_id)
        children = tree.get("children", [])

        # 扁平化文件列表
        file_list = []
        def _flatten(nodes, prefix=""):
            for n in nodes:
                path = f"{prefix}{n['name']}" if not prefix else f"{prefix}/{n['name']}"
                if n["type"] == "file":
                    file_list.append(path)
                elif n.get("children"):
                    _flatten(n["children"], path)
        _flatten(children)

        # 读取关键文件内容
        code = {}
        ENTRY_FILES = {"index.html", "main.py", "app.py", "package.json"}
        CODE_EXTS = {".html", ".js", ".jsx", ".ts", ".tsx", ".py", ".css", ".json"}
        total_chars = 0
        MAX_TOTAL = 15000
        MAX_PER_FILE = 3000

        for fp in file_list:
            if total_chars >= MAX_TOTAL:
                break
            fname = fp.split("/")[-1]
            ext = "." + fname.rsplit(".", 1)[-1] if "." in fname else ""
            should_read = fname in ENTRY_FILES or (fp.startswith("src/") and ext in CODE_EXTS)
            if not should_read:
                continue

            content = await git_manager.get_file_content(self.project_id, fp)
            if content:
                truncated = content[:MAX_PER_FILE]
                if len(content) > MAX_PER_FILE:
                    truncated += f"\n... (truncated, {len(content)} chars)"
                code[fp] = truncated
                total_chars += len(truncated)

        return {"file_list": file_list, "code": code}

    async def get_sibling_tickets(self, requirement_id: str, exclude_ticket_id: str = None) -> List[Dict]:
        """获取同需求下的其他工单"""
        from database import db

        where = "requirement_id = ? AND status NOT IN ('pending', 'cancelled')"
        params = [requirement_id]
        if exclude_ticket_id:
            where += " AND id != ?"
            params.append(exclude_ticket_id)

        tickets = await db.fetch_all(
            f"SELECT id, title, status, module FROM tickets WHERE {where} ORDER BY created_at",
            tuple(params),
        )
        return [{"id": t["id"], "title": t["title"], "status": t["status"], "module": t.get("module", "")} for t in tickets]

    async def search(self, query: str, limit: int = 10) -> List[MemoryItem]:
        """关键词搜索历史记忆"""
        from database import db

        items = []
        query_like = f"%{query}%"

        # 搜索 artifacts
        arts = await db.fetch_all(
            "SELECT type, name, content, created_at FROM artifacts WHERE project_id = ? AND (name LIKE ? OR content LIKE ?) LIMIT ?",
            (self.project_id, query_like, query_like, limit),
        )
        for a in arts:
            items.append(MemoryItem(source="artifact", content=f"[{a['type']}] {a['name']}", created_at=a["created_at"]))

        # 搜索 ticket_logs
        logs = await db.fetch_all(
            "SELECT agent_type, action, detail, created_at FROM ticket_logs WHERE project_id = ? AND detail LIKE ? LIMIT ?",
            (self.project_id, query_like, limit),
        )
        for l in logs:
            items.append(MemoryItem(source="log", content=f"[{l['agent_type']}] {l['action']}", created_at=l["created_at"]))

        items.sort(key=lambda x: x.created_at, reverse=True)
        return items[:limit]
