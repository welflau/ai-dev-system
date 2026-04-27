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

async def _upsert_knowledge_index(project_id: Optional[str], filename: str, content: str):
    """写入/更新 knowledge_index（触发器自动维护 FTS5）"""
    try:
        await db.execute("""
            INSERT INTO knowledge_index (project_id, filename, content, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(project_id, filename) DO UPDATE SET
                content=excluded.content, updated_at=excluded.updated_at
        """, (project_id, filename, content, now_iso()))
    except Exception as e:
        logger.warning("knowledge_index 写入失败（忽略）: %s", e)


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
