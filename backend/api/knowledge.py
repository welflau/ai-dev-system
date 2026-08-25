"""
知识库管理 API
- 全局知识库：BASE_DIR/docs/                  （所有项目共享）
- 项目知识库：BASE_DIR/projects/{id}/docs/    （仅该项目使用）
- FTS5 全文索引：knowledge_index + knowledge_fts 表
"""
import json
import logging
import re
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from config import BASE_DIR
from database import db
from utils import now_iso

logger = logging.getLogger("api.knowledge")

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

# ==================== 路径辅助 ====================

GLOBAL_DOCS_DIR = BASE_DIR / "docs"
GLOBAL_DOCS_DIR.mkdir(exist_ok=True)

PROJECTS_DIR = BASE_DIR / "projects"

_DEFAULT_SCAN_PATHS = ["docs", "Design", "Spec", "Docs"]
_MAX_SCAN_DEPTH = 3
_MAX_FILE_SIZE = 500_000  # 500KB 单文件上限


def _safe_filename(name: str) -> str:
    name = re.sub(r"[^\w\-. ]", "", name).strip()
    if not name.endswith(".md"):
        name += ".md"
    return name


def _get_docs_dir(project_id: Optional[str]) -> Path:
    if project_id:
        d = PROJECTS_DIR / project_id / "docs"
    else:
        d = GLOBAL_DOCS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _doc_info(path: Path) -> dict:
    stat = path.stat()
    return {
        "filename": path.name,
        "size": stat.st_size,
        "modified_at": stat.st_mtime,
    }


# ==================== 安全扫描（借鉴 Hermes _CONTEXT_THREAT_PATTERNS）====================

_INJECTION_PATTERNS = [
    re.compile(r'ignore\s+(previous|all|above|prior)\s+instructions', re.I),
    re.compile(r'you\s+are\s+now\s+a\b', re.I),
    re.compile(r'disregard\s+(all|your|previous)', re.I),
    re.compile(r'do\s+not\s+tell\s+the\s+user', re.I),
    re.compile(r'curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD)', re.I),
    re.compile(r'authorized_keys', re.I),
    re.compile(r'act\s+as\s+(a\s+)?(different|new|another)\s+(AI|assistant|model)', re.I),
]


def _check_injection(content: str) -> Optional[str]:
    """返回命中的模式描述，无风险返回 None"""
    for p in _INJECTION_PATTERNS:
        m = p.search(content)
        if m:
            return f"疑似 prompt injection：{m.group()[:60]}"
    return None


# ==================== FTS5 索引辅助 ====================

# 文件名 → agent_scope 映射（docs/ 下的 Agent 产出文档）
_FILENAME_SCOPE_MAP = {
    "PRD.md": "planner",
    "UX设计.md": "ux",
    "视觉规范.md": "art",
    "asset_manifest.yaml": "art",
    "design_tokens.json": "art",
    "架构设计.md": "arch",
    "architecture.md": "arch",
    "test-report.md": "test",
    "code-review.md": "review",
    "acceptance-review.md": "review",
    "deploy.md": "deploy",
    "dev-notes.md": "dev",
}


def _infer_agent_scope(filename: str) -> Optional[str]:
    """从文件名推断 agent_scope，用于 knowledge_index 分类检索"""
    import os
    basename = os.path.basename(filename)
    return _FILENAME_SCOPE_MAP.get(basename)


async def _upsert_knowledge_index(project_id: Optional[str], filename: str, content: str,
                                   agent_scope: Optional[str] = None):
    """写入/更新 knowledge_index（触发器自动维护 FTS5）"""
    scope = agent_scope or _infer_agent_scope(filename)
    try:
        if project_id is None:
            # NULL 在 SQLite UNIQUE 约束里不生效，用 DELETE + INSERT 保证幂等
            await db.execute(
                "DELETE FROM knowledge_index WHERE project_id IS NULL AND filename = ?",
                (filename,)
            )
            await db.execute(
                "INSERT INTO knowledge_index (project_id, filename, content, updated_at, agent_scope) VALUES (NULL, ?, ?, ?, ?)",
                (filename, content, now_iso(), scope)
            )
        else:
            await db.execute("""
                INSERT INTO knowledge_index (project_id, filename, content, updated_at, agent_scope)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id, filename) DO UPDATE SET
                    content=excluded.content, updated_at=excluded.updated_at,
                    agent_scope=excluded.agent_scope
            """, (project_id, filename, content, now_iso(), scope))
    except Exception as e:
        logger.warning("knowledge_index 写入失败（忽略）: %s", e)


async def _upsert_tickets_fts(ticket_id: str, project_id: str, search_text: str):
    """写入/更新 tickets_fts（DELETE + INSERT，FTS5 不支持 ON CONFLICT）"""
    try:
        await db.execute("DELETE FROM tickets_fts WHERE ticket_id = ?", (ticket_id,))
        await db.execute(
            "INSERT INTO tickets_fts(search_text, ticket_id, project_id) VALUES (?, ?, ?)",
            (search_text, ticket_id, project_id)
        )
    except Exception as e:
        logger.warning("tickets_fts 写入失败（忽略）: %s", e)


async def _delete_knowledge_index(project_id: Optional[str], filename: str):
    """从 knowledge_index 删除（触发器自动维护 FTS5）"""
    try:
        await db.execute(
            "DELETE FROM knowledge_index WHERE project_id IS ? AND filename = ?",
            (project_id, filename)
        )
    except Exception as e:
        logger.warning("knowledge_index 删除失败（忽略）: %s", e)


# ==================== 列出文档 ====================

@router.get("/global")
async def list_global_docs():
    d = _get_docs_dir(None)
    files = sorted(d.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
    return {"docs": [_doc_info(f) for f in files]}


@router.get("/system")
async def list_system_docs():
    """列出系统自身 docs/ 和 dev-notes/ 的索引文档（只读，来自 knowledge_index）"""
    rows = await db.fetch_all("""
        SELECT filename, length(content) AS size, updated_at
        FROM knowledge_index
        WHERE project_id IS NULL
          AND (filename LIKE 'sys\\_docs\\_\\_%' ESCAPE '\\' OR filename LIKE 'sys\\_devnotes\\_\\_%' ESCAPE '\\')
        ORDER BY filename
    """)
    docs = []
    for r in rows:
        fname = r["filename"]
        if fname.startswith("sys_docs__"):
            group = "docs"
            display = fname[len("sys_docs__"):]
        else:
            group = "devnotes"
            display = fname[len("sys_devnotes__"):]
        docs.append({
            "filename": fname,
            "display_name": display,
            "group": group,
            "size": r["size"],
            "updated_at": r["updated_at"],
        })
    return {"docs": docs}


@router.get("/projects/{project_id}")
async def list_project_docs(project_id: str):
    d = _get_docs_dir(project_id)
    files = sorted(d.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
    return {"docs": [_doc_info(f) for f in files]}


# ==================== 特定路由（必须在通配 {filename} 路由之前）====================

@router.get("/search")
async def search_knowledge_get(q: str, project_id: str = None, limit: int = 5):
    """FTS5 全文搜索知识库（项目 + 全局）"""
    return await _do_search_knowledge(q, project_id, limit)


@router.get("/index")
async def list_knowledge_index(
    q: Optional[str] = None,
    scope: Optional[str] = None,
    project_id: Optional[str] = None,
    sort: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """浏览 knowledge_index / FTS 索引条目（可视化面板用）。

    scope: all | system | global | project
    q: 可选，走 FTS5 全文搜索并返回 snippet
    sort: updated | hits | rank（有 q 时默认 rank，否则默认 updated）
    """
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    scope = (scope or "all").strip().lower()
    if scope not in ("all", "system", "global", "project"):
        raise HTTPException(400, "scope 须为 all/system/global/project")
    q_stripped = (q or "").strip()
    sort = (sort or ("rank" if q_stripped else "updated")).strip().lower()
    if sort not in ("updated", "hits", "rank"):
        sort = "rank" if q_stripped else "updated"

    # ── 统计 ────────────────────────────────────────────────────────────
    stats_rows = await db.fetch_all("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN filename LIKE 'sys\\_docs\\_\\_%' ESCAPE '\\'
                       OR filename LIKE 'sys\\_devnotes\\_\\_%' ESCAPE '\\' THEN 1 ELSE 0 END) AS system_count,
            SUM(CASE WHEN project_id IS NULL
                      AND filename NOT LIKE 'sys\\_docs\\_\\_%' ESCAPE '\\'
                      AND filename NOT LIKE 'sys\\_devnotes\\_\\_%' ESCAPE '\\' THEN 1 ELSE 0 END) AS global_count,
            SUM(CASE WHEN project_id IS NOT NULL THEN 1 ELSE 0 END) AS project_count,
            COALESCE(SUM(length(content)), 0) AS total_chars,
            COALESCE(SUM(used_count), 0) AS total_hits
        FROM knowledge_index
    """)
    stats = dict(stats_rows[0]) if stats_rows else {
        "total": 0, "system_count": 0, "global_count": 0,
        "project_count": 0, "total_chars": 0, "total_hits": 0,
    }

    # ── 过滤条件（alias="" 用于直查 knowledge_index；alias="ki." 用于 FTS JOIN）──
    def _scope_where(alias: str = "") -> tuple:
        w, p = [], []
        col_fn = f"{alias}filename"
        col_pid = f"{alias}project_id"
        if scope == "system":
            w.append(
                f"({col_fn} LIKE 'sys\\_docs\\_\\_%' ESCAPE '\\'"
                f" OR {col_fn} LIKE 'sys\\_devnotes\\_\\_%' ESCAPE '\\')"
            )
        elif scope == "global":
            w.append(f"{col_pid} IS NULL")
            w.append(f"{col_fn} NOT LIKE 'sys\\_docs\\_\\_%' ESCAPE '\\'")
            w.append(f"{col_fn} NOT LIKE 'sys\\_devnotes\\_\\_%' ESCAPE '\\'")
        elif scope == "project":
            if project_id:
                w.append(f"{col_pid} = ?")
                p.append(project_id)
            else:
                w.append(f"{col_pid} IS NOT NULL")
        sql = (" AND " + " AND ".join(w)) if w else ""
        return sql, p

    # ── 列表 / 搜索 ─────────────────────────────────────────────────────
    q = q_stripped
    items = []
    total_filtered = 0

    def _order_sql(alias: str = "") -> str:
        """alias 如 'ki.'；无别名时传空串。"""
        col_hits = f"{alias}used_count"
        col_upd = f"{alias}updated_at"
        if sort == "hits":
            return f"{col_hits} DESC, {col_upd} DESC"
        if sort == "updated":
            return f"{col_upd} DESC"
        # rank：仅 FTS 有意义；无 q 时回退更新时间
        if q:
            return "rank"
        return f"{col_upd} DESC"

    if q:
        where_sql, params = _scope_where("ki.")
        try:
            fts_params = [q] + params + [limit, offset]
            count_params = [q] + params
            rows = await db.fetch_all(f"""
                SELECT ki.id, ki.project_id, ki.filename, ki.agent_scope, ki.confidence,
                       ki.used_count, ki.updated_at, length(ki.content) AS size,
                       snippet(knowledge_fts, 0, '**', '**', '...', 48) AS snippet
                FROM knowledge_fts
                JOIN knowledge_index ki ON knowledge_fts.rowid = ki.id
                WHERE knowledge_fts MATCH ?{where_sql}
                ORDER BY {_order_sql("ki.")}
                LIMIT ? OFFSET ?
            """, tuple(fts_params))
            count_row = await db.fetch_one(f"""
                SELECT COUNT(*) AS c
                FROM knowledge_fts
                JOIN knowledge_index ki ON knowledge_fts.rowid = ki.id
                WHERE knowledge_fts MATCH ?{where_sql}
            """, tuple(count_params))
            total_filtered = (count_row or {}).get("c") or 0
        except Exception as e:
            logger.warning("knowledge index FTS 失败: %s", e)
            raise HTTPException(500, f"搜索失败: {e}")
    else:
        where_sql, params = _scope_where("")
        rows = await db.fetch_all(f"""
            SELECT id, project_id, filename, agent_scope, confidence,
                   used_count, updated_at, length(content) AS size,
                   NULL AS snippet
            FROM knowledge_index
            WHERE 1=1{where_sql}
            ORDER BY {_order_sql("")}
            LIMIT ? OFFSET ?
        """, tuple(params + [limit, offset]))
        count_row = await db.fetch_one(
            f"SELECT COUNT(*) AS c FROM knowledge_index WHERE 1=1{where_sql}",
            tuple(params),
        )
        total_filtered = (count_row or {}).get("c") or 0

    for r in rows:
        fname = r["filename"] or ""
        if fname.startswith("sys_docs__"):
            item_scope = "system"
            display = fname[len("sys_docs__"):]
            group = "docs"
        elif fname.startswith("sys_devnotes__"):
            item_scope = "system"
            display = fname[len("sys_devnotes__"):]
            group = "devnotes"
        elif r["project_id"]:
            item_scope = "project"
            display = fname
            group = "project"
        else:
            item_scope = "global"
            display = fname
            group = "global"
        items.append({
            "id": r["id"],
            "filename": fname,
            "display_name": display,
            "scope": item_scope,
            "group": group,
            "project_id": r["project_id"],
            "size": r["size"] or 0,
            "agent_scope": r["agent_scope"],
            "confidence": r["confidence"],
            "used_count": r["used_count"] or 0,
            "updated_at": r["updated_at"],
            "snippet": r["snippet"],
        })

    return {
        "stats": stats,
        "items": items,
        "total_filtered": total_filtered,
        "limit": limit,
        "offset": offset,
        "q": q or None,
        "scope": scope,
        "sort": sort,
    }


@router.get("/index/lookup")
async def lookup_knowledge_index(name: str, project_id: Optional[str] = None):
    """按显示名 / 文件名查找知识库条目（聊天链接点击用）。"""
    raw = (name or "").strip()
    if not raw:
        raise HTTPException(400, "name 不能为空")
    # 去掉可能的路径与扩展
    base = raw.replace("\\", "/").split("/")[-1]
    candidates = []
    for c in (
        base,
        base if base.endswith(".md") else base + ".md",
        base[len("sys_docs__"):] if base.startswith("sys_docs__") else None,
        base[len("sys_devnotes__"):] if base.startswith("sys_devnotes__") else None,
    ):
        if c and c not in candidates:
            candidates.append(c)

    stem = base[:-3] if base.endswith(".md") else base
    for prefix in ("sys_docs__", "sys_devnotes__", ""):
        for s in (stem, stem + ".md"):
            cand = f"{prefix}{s}" if prefix else s
            if cand and cand not in candidates:
                candidates.append(cand)

    row = None
    for cand in candidates:
        if project_id:
            row = await db.fetch_one(
                """SELECT id, project_id, filename, agent_scope, used_count, updated_at,
                          length(content) AS size
                   FROM knowledge_index
                   WHERE filename = ? AND (project_id = ? OR project_id IS NULL)
                   ORDER BY CASE WHEN project_id = ? THEN 0 ELSE 1 END
                   LIMIT 1""",
                (cand, project_id, project_id),
            )
        else:
            row = await db.fetch_one(
                """SELECT id, project_id, filename, agent_scope, used_count, updated_at,
                          length(content) AS size
                   FROM knowledge_index WHERE filename = ? LIMIT 1""",
                (cand,),
            )
        if row:
            break

    # 后缀模糊：显示名不含前缀时
    if not row:
        if project_id:
            row = await db.fetch_one(
                """SELECT id, project_id, filename, agent_scope, used_count, updated_at,
                          length(content) AS size
                   FROM knowledge_index
                   WHERE (filename = ? OR filename LIKE ? OR filename LIKE ?)
                     AND (project_id = ? OR project_id IS NULL)
                   ORDER BY CASE WHEN project_id = ? THEN 0 ELSE 1 END, length(filename)
                   LIMIT 1""",
                (stem, f"%__{stem}", f"%__{stem}.md", project_id, project_id),
            )
        else:
            row = await db.fetch_one(
                """SELECT id, project_id, filename, agent_scope, used_count, updated_at,
                          length(content) AS size
                   FROM knowledge_index
                   WHERE filename = ? OR filename LIKE ? OR filename LIKE ?
                   ORDER BY length(filename) LIMIT 1""",
                (stem, f"%__{stem}", f"%__{stem}.md"),
            )

    if not row:
        raise HTTPException(404, f"未找到知识库文档：{raw}")

    fname = row["filename"] or ""
    if fname.startswith("sys_docs__"):
        display = fname[len("sys_docs__"):]
    elif fname.startswith("sys_devnotes__"):
        display = fname[len("sys_devnotes__"):]
    else:
        display = fname
    return {
        "id": row["id"],
        "filename": fname,
        "display_name": display[:-3] if display.endswith(".md") else display,
        "project_id": row["project_id"],
        "agent_scope": row["agent_scope"],
        "used_count": row["used_count"] or 0,
        "updated_at": row["updated_at"],
        "size": row["size"] or 0,
    }


@router.get("/index/{doc_id}")
async def get_knowledge_index_doc(doc_id: int):
    """读取单条索引文档正文（主舞台查看器用，最长 200KB）"""
    row = await db.fetch_one(
        """SELECT id, project_id, filename, agent_scope, confidence,
                  used_count, updated_at, content
           FROM knowledge_index WHERE id = ?""",
        (doc_id,),
    )
    if not row:
        raise HTTPException(404, "索引条目不存在")
    content = row["content"] or ""
    fname = row["filename"] or ""
    if fname.startswith("sys_docs__"):
        item_scope = "system"
        display = fname[len("sys_docs__"):]
    elif fname.startswith("sys_devnotes__"):
        item_scope = "system"
        display = fname[len("sys_devnotes__"):]
    elif row["project_id"]:
        item_scope = "project"
        display = fname
    else:
        item_scope = "global"
        display = fname
    if display.endswith(".md"):
        display = display[:-3]
    truncated = len(content) > 200_000
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "filename": fname,
        "display_name": display,
        "scope": item_scope,
        "agent_scope": row["agent_scope"],
        "confidence": row["confidence"],
        "used_count": row["used_count"] or 0,
        "updated_at": row["updated_at"],
        "size": len(content),
        "content": content[:200_000] + ("\n\n...(truncated)" if truncated else ""),
        "truncated": truncated,
    }


@router.get("/projects/{project_id}/scan-paths")
async def get_scan_paths(project_id: str):
    """获取项目知识库扫描路径配置"""
    project = await db.fetch_one("SELECT git_repo_path, knowledge_scan_paths FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    repo_path = project.get("git_repo_path") or ""
    raw = project.get("knowledge_scan_paths") or "[]"
    scan_paths = json.loads(raw)

    result = []
    for entry in scan_paths:
        p = entry.get("path", "")
        count = 0
        if repo_path and p:
            scan_dir = Path(repo_path) / p
            if scan_dir.is_dir():
                count = sum(1 for _ in scan_dir.rglob("*.md"))
        result.append({**entry, "file_count": count, "exists": bool(repo_path and (Path(repo_path) / p).is_dir())})

    configured_paths = {e["path"] for e in scan_paths}
    default_suggestions = []
    if repo_path:
        for dp in _DEFAULT_SCAN_PATHS:
            if dp not in configured_paths and (Path(repo_path) / dp).is_dir():
                default_suggestions.append({"path": dp, "exists": True, "file_count": sum(1 for _ in (Path(repo_path) / dp).rglob("*.md"))})

    return {"scan_paths": result, "default_suggestions": default_suggestions}


@router.get("/projects/{project_id}/sync-preview")
async def preview_sync(project_id: str):
    """预览将要同步的文件列表（不实际写入）"""
    project = await db.fetch_one("SELECT git_repo_path, knowledge_scan_paths FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    repo_path = Path(project.get("git_repo_path") or "")
    if not repo_path.is_dir():
        raise HTTPException(400, "项目本地仓库路径不存在，请先配置")

    scan_paths = json.loads(project.get("knowledge_scan_paths") or "[]")
    files = _collect_repo_files(repo_path, scan_paths)

    for f in files:
        if f["would_skip"]:
            continue
        try:
            content = (repo_path / f["path"]).read_text(encoding="utf-8", errors="ignore")
            reason = _check_injection(content)
            if reason:
                f["would_skip"] = True
                f["skip_reason"] = reason
        except Exception:
            pass

    return {
        "files": files,
        "total": len(files),
        "skipped_count": sum(1 for f in files if f["would_skip"]),
        "sync_count": sum(1 for f in files if not f["would_skip"]),
    }


# ==================== 读取文档内容（通配路由，必须在特定路由之后）====================

@router.get("/global/{filename}")
async def get_global_doc(filename: str):
    path = _get_docs_dir(None) / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "文档不存在")
    return {"filename": filename, "content": path.read_text(encoding="utf-8", errors="replace")}


@router.get("/projects/{project_id}/{filename}")
async def get_project_doc(project_id: str, filename: str):
    path = _get_docs_dir(project_id) / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "文档不存在")
    return {"filename": filename, "content": path.read_text(encoding="utf-8", errors="replace")}


# ==================== 保存文档（创建/更新） ====================

class DocBody(BaseModel):
    filename: str
    content: str


@router.put("/global")
async def save_global_doc(body: DocBody):
    fname = _safe_filename(body.filename)
    path = _get_docs_dir(None) / fname
    path.write_text(body.content, encoding="utf-8")
    await _upsert_knowledge_index(None, fname, body.content)
    return {"status": "ok", "filename": fname}


@router.put("/projects/{project_id}")
async def save_project_doc(project_id: str, body: DocBody):
    fname = _safe_filename(body.filename)
    path = _get_docs_dir(project_id) / fname
    path.write_text(body.content, encoding="utf-8")
    await _upsert_knowledge_index(project_id, fname, body.content)
    return {"status": "ok", "filename": fname}


# ==================== 上传文档 ====================

@router.post("/global/upload")
async def upload_global_doc(file: UploadFile = File(...)):
    fname = _safe_filename(file.filename or "document.md")
    content = (await file.read()).decode("utf-8", errors="replace")
    path = _get_docs_dir(None) / fname
    path.write_text(content, encoding="utf-8")
    await _upsert_knowledge_index(None, fname, content)
    return {"status": "ok", "filename": fname}


@router.post("/projects/{project_id}/upload")
async def upload_project_doc(project_id: str, file: UploadFile = File(...)):
    fname = _safe_filename(file.filename or "document.md")
    content = (await file.read()).decode("utf-8", errors="replace")
    path = _get_docs_dir(project_id) / fname
    path.write_text(content, encoding="utf-8")
    await _upsert_knowledge_index(project_id, fname, content)
    return {"status": "ok", "filename": fname}


# ==================== 删除文档 ====================

@router.delete("/global/{filename}")
async def delete_global_doc(filename: str):
    path = _get_docs_dir(None) / filename
    if not path.exists():
        raise HTTPException(404, "文档不存在")
    path.unlink()
    await _delete_knowledge_index(None, filename)
    return {"status": "ok"}


@router.delete("/projects/{project_id}/{filename}")
async def delete_project_doc(project_id: str, filename: str):
    path = _get_docs_dir(project_id) / filename
    if not path.exists():
        raise HTTPException(404, "文档不存在")
    path.unlink()
    await _delete_knowledge_index(project_id, filename)
    return {"status": "ok"}


# ==================== 全文搜索（实现函数，被前面的路由调用）====================

async def _do_search_knowledge(q: str, project_id: Optional[str], limit: int):
    if not q.strip():
        raise HTTPException(400, "查询不能为空")
    try:
        if project_id:
            # 项目内：该项目文档 + 全局文档
            rows = await db.fetch_all("""
                SELECT ki.filename, ki.project_id,
                       snippet(knowledge_fts, 0, '**', '**', '...', 40) AS snippet
                FROM knowledge_fts
                JOIN knowledge_index ki ON knowledge_fts.rowid = ki.id
                WHERE knowledge_fts MATCH ?
                  AND (ki.project_id = ? OR ki.project_id IS NULL)
                ORDER BY rank
                LIMIT ?
            """, (q, project_id, limit))
        else:
            # 全局模式：搜索所有项目 + 全局文档
            rows = await db.fetch_all("""
                SELECT ki.filename, ki.project_id,
                       snippet(knowledge_fts, 0, '**', '**', '...', 40) AS snippet
                FROM knowledge_fts
                JOIN knowledge_index ki ON knowledge_fts.rowid = ki.id
                WHERE knowledge_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (q, limit))
    except Exception as e:
        logger.warning("knowledge_fts 搜索失败: %s", e)
        raise HTTPException(500, f"搜索失败: {e}")
    return {"query": q, "results": [dict(r) for r in rows], "count": len(rows)}


# ==================== 扫描路径配置（PUT，其余 GET 已在前面定义）====================

class ScanPathsBody(BaseModel):
    scan_paths: List[dict]


@router.put("/projects/{project_id}/scan-paths")
async def update_scan_paths(project_id: str, body: ScanPathsBody):
    """更新项目知识库扫描路径配置"""
    project = await db.fetch_one("SELECT id FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")
    await db.update("projects", {
        "knowledge_scan_paths": json.dumps(body.scan_paths, ensure_ascii=False),
        "updated_at": now_iso(),
    }, "id = ?", (project_id,))
    return {"status": "ok", "scan_paths": body.scan_paths}


# ==================== 仓库同步 ====================

def _collect_repo_files(repo_path: Path, scan_paths: List[dict]) -> List[dict]:
    """扫描仓库，收集待同步文件列表（不写入）"""
    paths_to_scan = [e["path"] for e in scan_paths if e.get("enabled", True)] if scan_paths else []
    if not paths_to_scan:
        paths_to_scan = [p for p in _DEFAULT_SCAN_PATHS if (repo_path / p).is_dir()]

    files = []
    for rel_dir in paths_to_scan:
        scan_dir = repo_path / rel_dir
        if not scan_dir.is_dir():
            continue
        for md_file in scan_dir.rglob("*.md"):
            # 深度限制
            depth = len(md_file.relative_to(scan_dir).parts)
            if depth > _MAX_SCAN_DEPTH:
                continue
            stat = md_file.stat()
            if stat.st_size > _MAX_FILE_SIZE:
                files.append({"path": str(md_file.relative_to(repo_path)), "size": stat.st_size, "would_skip": True, "skip_reason": "文件过大（>500KB）"})
                continue
            files.append({"path": str(md_file.relative_to(repo_path)), "size": stat.st_size, "would_skip": False})
    return files


@router.post("/projects/{project_id}/sync-from-repo")
async def sync_from_repo(project_id: str):
    """从 git 仓库同步文档到知识库"""
    project = await db.fetch_one("SELECT git_repo_path, knowledge_scan_paths FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    repo_path = Path(project.get("git_repo_path") or "")
    if not repo_path.is_dir():
        raise HTTPException(400, "项目本地仓库路径不存在，请先配置")

    scan_paths = json.loads(project.get("knowledge_scan_paths") or "[]")
    files = _collect_repo_files(repo_path, scan_paths)

    docs_dir = _get_docs_dir(project_id)
    synced, skipped = [], []

    for f in files:
        if f["would_skip"]:
            skipped.append({"path": f["path"], "reason": f.get("skip_reason", "超出大小限制")})
            continue

        src = repo_path / f["path"]
        try:
            content = src.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            skipped.append({"path": f["path"], "reason": f"读取失败: {e}"})
            continue

        # 安全扫描
        reason = _check_injection(content)
        if reason:
            skipped.append({"path": f["path"], "reason": reason})
            logger.warning("[知识库同步] 跳过 %s：%s", f["path"], reason)
            continue

        # 目标文件名：路径中的 / 替换为 __（如 docs/架构说明.md → docs__架构说明.md）
        dest_name = f["path"].replace("\\", "/").replace("/", "__")
        dest_name = _safe_filename(dest_name)
        dest = docs_dir / dest_name

        dest.write_text(content, encoding="utf-8")
        await _upsert_knowledge_index(project_id, dest_name, content)
        synced.append({"path": f["path"], "saved_as": dest_name})

    logger.info("[知识库同步] 项目 %s：同步 %d 个，跳过 %d 个", project_id, len(synced), len(skipped))
    return {
        "status": "ok",
        "synced": synced,
        "skipped": skipped,
        "total": len(synced) + len(skipped),
    }
