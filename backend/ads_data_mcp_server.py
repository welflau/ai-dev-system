"""
ADS Data MCP Server
将 ADS 数据库查询 Action 封装为标准 MCP tools，供 Multica Agent（Claude Code）调用。

启动方式：
  python ads_data_mcp_server.py

Multica Agent mcp_config 配置：
  {
    "servers": {
      "ads-data": {
        "command": "python",
        "args": ["F:/A_Works/ai-dev-system/backend/ads_data_mcp_server.py"],
        "env": { "ADS_DB_PATH": "F:/A_Works/ai-dev-system/backend/data/ai_dev_system.db" }
      }
    }
  }
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import aiosqlite
from mcp.server.fastmcp import FastMCP

# ── 配置 ──────────────────────────────────────────────────────────────────────
DB_PATH = os.environ.get(
    "ADS_DB_PATH",
    str(Path(__file__).parent / "data" / "ai_dev_system.db"),
)

# ADS 后端地址，用于 confirm_requirement 等需要推 SSE 的工具
ADS_BASE_URL = os.environ.get("ADS_BASE_URL", "http://localhost:8000")

# 当前会话的项目 ID（由 llm_client 注入，避免 DeepSeek 搜索 project_id）
ADS_PROJECT_ID = os.environ.get("ADS_PROJECT_ID", "")

mcp = FastMCP("ads-data")


# ── 工具函数 ──────────────────────────────────────────────────────────────────
def _sanitize_fts(q: str) -> str:
    clean = q.replace('"', " ").strip()
    if re.search(r'[.\-+*():!]', clean):
        return f'"{clean}"'
    return clean


async def _db_fetch(sql: str, params: tuple = ()) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def _db_execute(sql: str, params: tuple = ()) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(sql, params)
        await conn.commit()


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ── Tools：知识库搜索 ─────────────────────────────────────────────────────────
@mcp.tool()
async def search_knowledge(query: str, project_id: str = "", limit: int = 3) -> str:
    """
    搜索项目知识库和全局知识库文档。
    当遇到不确定的 API 用法、架构约束、编译错误、版本更新内容时调用。
    支持关键词搜索，例如：'v0.19'、'UE 编译错误'、'Hermes'。
    """
    limit = min(limit, 8)
    fts = _sanitize_fts(query)
    try:
        if project_id:
            rows = await _db_fetch(
                """SELECT ki.filename,
                          snippet(knowledge_fts, 0, '**', '**', '...', 64) AS snippet,
                          substr(ki.content, 1, 1500) AS preview
                   FROM knowledge_fts
                   JOIN knowledge_index ki ON knowledge_fts.rowid = ki.id
                   WHERE knowledge_fts MATCH ?
                     AND (ki.project_id = ? OR ki.project_id IS NULL)
                   ORDER BY rank LIMIT ?""",
                (fts, project_id, limit),
            )
        else:
            rows = await _db_fetch(
                """SELECT ki.filename,
                          snippet(knowledge_fts, 0, '**', '**', '...', 64) AS snippet,
                          substr(ki.content, 1, 1500) AS preview
                   FROM knowledge_fts
                   JOIN knowledge_index ki ON knowledge_fts.rowid = ki.id
                   WHERE knowledge_fts MATCH ?
                   ORDER BY rank LIMIT ?""",
                (fts, limit),
            )
    except Exception as e:
        return json.dumps({"error": f"搜索失败: {e}", "query": query})

    if not rows:
        return json.dumps({"message": f"知识库中未找到与「{query}」相关内容", "results": []})
    return json.dumps({"query": query, "count": len(rows), "results": rows}, ensure_ascii=False)


@mcp.tool()
async def search_design_knowledge(query: str, category: str = "", limit: int = 8) -> str:
    """
    搜索设计/UX 知识库，获取 UI 规范、交互模式、设计原则等内容。
    """
    limit = min(limit, 20)
    try:
        rows = await _db_fetch(
            """SELECT d.id, d.title, d.category, d.summary, substr(d.content,1,800) as content, d.tags
               FROM design_knowledge_fts f
               JOIN design_knowledge d ON d.id = f.rowid
               WHERE design_knowledge_fts MATCH ?
               ORDER BY rank LIMIT ?""",
            (_sanitize_fts(query), limit),
        )
    except Exception:
        cond = "title LIKE ? OR content LIKE ?"
        params: list = [f"%{query}%", f"%{query}%"]
        if category:
            cond += " AND category = ?"
            params.append(category)
        rows = await _db_fetch(
            f"SELECT id, title, category, summary, tags FROM design_knowledge WHERE {cond} LIMIT ?",
            (*params, limit),
        )
    return json.dumps({"query": query, "count": len(rows), "results": rows}, ensure_ascii=False)


@mcp.tool()
async def search_art_assets(query: str, asset_type: str = "", style: str = "", limit: int = 10) -> str:
    """
    搜索美术资产库（贴图/模型/特效等，33000+ 条）。
    支持按名称、类型、风格搜索，返回资产路径和基本信息。
    """
    limit = min(limit, 30)
    conditions = ["(name LIKE ? OR description LIKE ? OR tags LIKE ?)"]
    params: list = [f"%{query}%", f"%{query}%", f"%{query}%"]
    if asset_type:
        conditions.append("type LIKE ?")
        params.append(f"%{asset_type}%")
    if style:
        conditions.append("style LIKE ?")
        params.append(f"%{style}%")
    where = " AND ".join(conditions)
    rows = await _db_fetch(
        f"SELECT id, name, type, style, path, description, tags FROM art_assets WHERE {where} LIMIT ?",
        (*params, limit),
    )
    return json.dumps({"query": query, "count": len(rows), "results": rows}, ensure_ascii=False)


# ── Tools：历史工单 ───────────────────────────────────────────────────────────
@mcp.tool()
async def search_ticket_history(query: str, limit: int = 3) -> str:
    """
    搜索历史工单的解决方案和根因分析。
    遇到编译错误、测试失败或用户问「之前有没有解决过类似问题」时调用。
    """
    limit = min(limit, 5)
    fts = _sanitize_fts(query)
    try:
        rows = await _db_fetch(
            """SELECT t.id, t.title, t.status,
                      snippet(tickets_fts, 1, '**', '**', '...', 48) AS snippet,
                      t.reflexion_analysis
               FROM tickets_fts
               JOIN tickets t ON tickets_fts.rowid = t.id
               WHERE tickets_fts MATCH ?
               ORDER BY rank LIMIT ?""",
            (fts, limit),
        )
    except Exception:
        rows = await _db_fetch(
            "SELECT id, title, status, reflexion_analysis FROM tickets WHERE title LIKE ? LIMIT ?",
            (f"%{query}%", limit),
        )
    return json.dumps({"query": query, "count": len(rows), "results": rows}, ensure_ascii=False)


@mcp.tool()
async def get_ticket_status(ticket_id: str = "", requirement_id: str = "") -> str:
    """
    查看工单详细状态。
    给 ticket_id 返回单个工单详情；给 requirement_id 返回该需求下所有工单列表。
    """
    if ticket_id:
        rows = await _db_fetch(
            "SELECT id, title, status, assigned_agent, created_at, updated_at FROM tickets WHERE id = ?",
            (ticket_id,),
        )
        if not rows:
            return json.dumps({"error": f"工单 {ticket_id} 不存在"})
        ticket = rows[0]
        logs = await _db_fetch(
            "SELECT agent_type, action, level, detail, created_at FROM ticket_logs WHERE ticket_id = ? ORDER BY created_at DESC LIMIT 3",
            (ticket_id,),
        )
        ticket["recent_logs"] = logs
        return json.dumps(ticket, ensure_ascii=False)
    elif requirement_id:
        rows = await _db_fetch(
            "SELECT id, title, status, assigned_agent, updated_at FROM tickets WHERE requirement_id = ? ORDER BY created_at",
            (requirement_id,),
        )
        return json.dumps({"requirement_id": requirement_id, "tickets": rows, "count": len(rows)}, ensure_ascii=False)
    return json.dumps({"error": "需要提供 ticket_id 或 requirement_id"})


@mcp.tool()
async def get_requirement_logs(requirement_id: str, limit: int = 20) -> str:
    """查询需求的执行日志（各阶段 Agent 操作记录）。"""
    rows = await _db_fetch(
        """SELECT agent_type, action, from_status, to_status, level, detail, created_at
           FROM ticket_logs WHERE requirement_id = ?
           ORDER BY created_at DESC LIMIT ?""",
        (requirement_id, min(limit, 50)),
    )
    return json.dumps({"requirement_id": requirement_id, "logs": rows, "count": len(rows)}, ensure_ascii=False)


@mcp.tool()
async def get_requirement_pipeline(requirement_id: str) -> str:
    """查询需求的完整流水线状态（各阶段进度）。"""
    req = await _db_fetch("SELECT * FROM requirements WHERE id = ?", (requirement_id,))
    if not req:
        return json.dumps({"error": f"需求 {requirement_id} 不存在"})
    tickets = await _db_fetch(
        "SELECT id, title, status, assigned_agent, updated_at FROM tickets WHERE requirement_id = ? ORDER BY created_at",
        (requirement_id,),
    )
    return json.dumps({"requirement": req[0], "tickets": tickets}, ensure_ascii=False)


# ── Tools：Memory ─────────────────────────────────────────────────────────────
@mcp.tool()
async def get_memory(query: str, project_id: str = "", memory_type: str = "all", limit: int = 5) -> str:
    """
    查询项目历史决策、交接记录和经验教训。
    当用户询问「当初为什么这样设计」「踩过什么坑」「之前的决策是什么」时调用。
    memory_type: decision / handoff / project_status / insight / all
    """
    limit = min(limit, 20)
    try:
        if memory_type == "all":
            rows = await _db_fetch(
                """SELECT m.id, m.type, m.title, m.content, m.agent_type, m.created_at
                   FROM agent_memory m
                   JOIN agent_memory_fts fts ON m.rowid = fts.rowid
                   WHERE m.project_id = ? AND agent_memory_fts MATCH ?
                   ORDER BY rank, m.created_at DESC LIMIT ?""",
                (project_id or "__global__", _sanitize_fts(query), limit),
            )
        else:
            rows = await _db_fetch(
                """SELECT m.id, m.type, m.title, m.content, m.agent_type, m.created_at
                   FROM agent_memory m
                   JOIN agent_memory_fts fts ON m.rowid = fts.rowid
                   WHERE m.project_id = ? AND m.type = ? AND agent_memory_fts MATCH ?
                   ORDER BY rank, m.created_at DESC LIMIT ?""",
                (project_id or "__global__", memory_type, _sanitize_fts(query), limit),
            )
    except Exception:
        rows = await _db_fetch(
            "SELECT id, type, title, content, agent_type, created_at FROM agent_memory WHERE project_id = ? AND (title LIKE ? OR content LIKE ?) ORDER BY created_at DESC LIMIT ?",
            (project_id or "__global__", f"%{query}%", f"%{query}%", limit),
        )
    return json.dumps({"query": query, "count": len(rows), "memories": rows}, ensure_ascii=False)


@mcp.tool()
async def save_memory(title: str, content: str, project_id: str = "", category: str = "project_context") -> str:
    """
    将重要信息保存到记忆中，供后续对话检索使用。
    category: user_profile / behavior_feedback / project_context / external_ref
    """
    _TYPE_MAP = {"user": "user_profile", "project": "project_context", "technical": "project_context"}
    category = _TYPE_MAP.get(category, category)
    if category not in {"user_profile", "behavior_feedback", "project_context", "external_ref"}:
        category = "project_context"

    import uuid
    mem_id = "MEM-" + str(uuid.uuid4())[:8].upper()
    now = _now_iso()
    try:
        await _db_execute(
            """INSERT INTO agent_memory (id, project_id, type, agent_type, title, content, tags, created_at, updated_at)
               VALUES (?, ?, ?, 'ChatAssistant', ?, ?, '[]', ?, ?)""",
            (mem_id, project_id or "__global__", category, title[:200], content[:2000], now, now),
        )
        return json.dumps({"success": True, "id": mem_id, "title": title, "category": category})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


# ── Tools：Bug / 失败案例 ─────────────────────────────────────────────────────
@mcp.tool()
async def get_bugs(project_id: str, status: str = "all", priority: str = "all", limit: int = 20) -> str:
    """
    查询项目的 Bug 列表（状态、优先级、修复情况）。
    status: open / in_dev / fixed / closed / all
    priority: critical / high / medium / low / all
    """
    conditions = ["project_id = ?"]
    params: list = [project_id]
    if status != "all":
        conditions.append("status = ?")
        params.append(status)
    if priority != "all":
        conditions.append("priority = ?")
        params.append(priority)
    where = " AND ".join(conditions)
    rows = await _db_fetch(
        f"SELECT id, title, status, priority, created_at, updated_at FROM bugs WHERE {where} ORDER BY created_at DESC LIMIT ?",
        (*params, min(limit, 50)),
    )
    return json.dumps({"project_id": project_id, "count": len(rows), "bugs": rows}, ensure_ascii=False)


@mcp.tool()
async def get_failure_cases(project_id: str, query: str = "", failure_type: str = "", limit: int = 10) -> str:
    """
    查询项目失败案例库（Reflexion 机制积累的历史失败根因、修复策略）。
    适合回答「这类问题踩过哪些坑」「有什么经验教训」。
    """
    conditions = ["project_id = ?"]
    params: list = [project_id]
    if query:
        conditions.append("(title LIKE ? OR root_cause LIKE ? OR strategy LIKE ?)")
        params += [f"%{query}%", f"%{query}%", f"%{query}%"]
    if failure_type:
        conditions.append("failure_type = ?")
        params.append(failure_type)
    where = " AND ".join(conditions)
    rows = await _db_fetch(
        f"SELECT id, title, failure_type, root_cause, strategy, resolved, created_at FROM failure_cases WHERE {where} ORDER BY created_at DESC LIMIT ?",
        (*params, min(limit, 30)),
    )
    return json.dumps({"project_id": project_id, "count": len(rows), "cases": rows}, ensure_ascii=False)


# ── Tools：构建 / CI ──────────────────────────────────────────────────────────
@mcp.tool()
async def get_build_logs(project_id: str, limit: int = 5) -> str:
    """
    查询项目最近的构建/编译日志和错误详情。
    当用户说「编译报错了」「Build 失败」「UBT 出错」时自动调用，无需用户手动粘贴日志。
    """
    rows = await _db_fetch(
        """SELECT id, build_type, status, error_summary, log_path, created_at
           FROM ci_builds WHERE project_id = ?
           ORDER BY created_at DESC LIMIT ?""",
        (project_id, min(limit, 10)),
    )
    return json.dumps({"project_id": project_id, "count": len(rows), "builds": rows}, ensure_ascii=False)


@mcp.tool()
async def get_ci_builds(project_id: str, status: str = "all", limit: int = 10) -> str:
    """查询项目 CI 构建记录列表。status: success / failed / running / all"""
    conditions = ["project_id = ?"]
    params: list = [project_id]
    if status != "all":
        conditions.append("status = ?")
        params.append(status)
    where = " AND ".join(conditions)
    rows = await _db_fetch(
        f"SELECT id, build_type, status, branch, commit_hash, duration_s, created_at FROM ci_builds WHERE {where} ORDER BY created_at DESC LIMIT ?",
        (*params, min(limit, 20)),
    )
    return json.dumps({"project_id": project_id, "count": len(rows), "builds": rows}, ensure_ascii=False)


# ── Tools：里程碑 ─────────────────────────────────────────────────────────────
@mcp.tool()
async def get_milestones(project_id: str, status: str = "all") -> str:
    """
    查询项目里程碑列表（进度、计划时间、完成状态）。
    适合回答「项目进度如何」「下一个里程碑是什么」。
    status: pending / in_progress / completed / blocked / all
    """
    conditions = ["project_id = ?"]
    params: list = [project_id]
    if status != "all":
        conditions.append("status = ?")
        params.append(status)
    where = " AND ".join(conditions)
    rows = await _db_fetch(
        f"SELECT id, title, status, progress, target_date, description, created_at FROM milestones WHERE {where} ORDER BY target_date",
        (*params,),
    )
    return json.dumps({"project_id": project_id, "count": len(rows), "milestones": rows}, ensure_ascii=False)


# ── 入口 ──────────────────────────────────────────────────────────────────────

# ── Tools：Chat Action（需求/Bug 确认卡片）────────────────────────────────────

@mcp.tool()
async def confirm_requirement(
    title: str,
    description: str,
    priority: str = "medium",
    project_id: str = "",
) -> str:
    """
    识别到用户想新增或开发某个功能时调用。
    在 ADS 前端弹出需求草稿确认卡片，用户点「确认创建」后才真正创建需求。
    不直接创建需求，只产出草稿供用户确认。

    触发时机：用户说「帮我做…」「创建一个…」「新增…」「我需要…功能」
    不触发：用户在提问、报 Bug、描述现象、讨论方案
    project_id 留空则自动查询当前唯一激活项目。
    """
    import httpx as _httpx
    valid_priorities = ("critical", "high", "medium", "low")
    if priority not in valid_priorities:
        priority = "medium"
    pid = project_id or ADS_PROJECT_ID
    if not pid:
        # 兜底：从 DB 取唯一激活项目
        rows = await _db_fetch(
            "SELECT id FROM projects WHERE status = 'active' AND id != '__global__' ORDER BY updated_at DESC LIMIT 1"
        )
        pid = rows[0]["id"] if rows else ""
    if not pid:
        return json.dumps({"status": "error", "message": "未找到激活项目，请提供 project_id"}, ensure_ascii=False)

    payload = {
        "action": "confirm_requirement",
        "data": {
            "title": title.strip(),
            "description": description.strip(),
            "priority": priority,
        },
    }

    try:
        async with _httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{ADS_BASE_URL}/api/projects/{pid}/chat/mcp-action",
                json=payload,
            )
        if resp.status_code == 200:
            return json.dumps({"status": "ok", "message": f"需求草稿已推送到前端，等待用户确认：{title}"}, ensure_ascii=False)
        else:
            return json.dumps({"status": "error", "message": f"推送失败: HTTP {resp.status_code}"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


@mcp.tool()
async def confirm_bug(
    title: str,
    description: str,
    priority: str = "high",
    requirement_id: str = "",
    project_id: str = "",
) -> str:
    """
    用户描述 Bug、报错、崩溃、功能异常时调用。
    在 ADS 前端弹出 Bug 上报确认卡片，用户点「确认上报」后才真正创建 Bug。

    触发时机：用户描述已有功能出现问题（缺陷/报错/崩溃/白屏/接口报错）
    不触发：用户想新增功能
    project_id 留空则自动使用当前会话项目。
    """
    import httpx as _httpx
    valid_priorities = ("critical", "high", "medium", "low")
    if priority not in valid_priorities:
        priority = "high"
    pid = project_id or ADS_PROJECT_ID
    if not pid:
        rows = await _db_fetch(
            "SELECT id FROM projects WHERE status = 'active' AND id != '__global__' ORDER BY updated_at DESC LIMIT 1"
        )
        pid = rows[0]["id"] if rows else ""
    if not pid:
        return json.dumps({"status": "error", "message": "未找到激活项目，请提供 project_id"}, ensure_ascii=False)

    payload = {
        "action": "confirm_bug",
        "data": {
            "title": title.strip(),
            "description": description.strip(),
            "priority": priority,
            "requirement_id": requirement_id or None,
        },
    }

    try:
        async with _httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{ADS_BASE_URL}/api/projects/{pid}/chat/mcp-action",
                json=payload,
            )
        if resp.status_code == 200:
            return json.dumps({"status": "ok", "message": f"Bug 草稿已推送到前端，等待用户确认：{title}"}, ensure_ascii=False)
        else:
            return json.dumps({"status": "error", "message": f"推送失败: HTTP {resp.status_code}"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
