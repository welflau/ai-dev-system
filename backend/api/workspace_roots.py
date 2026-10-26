"""插件声明的工作区根（引擎目录）浏览接口。

仓库页的 Git / P4 之外，UE、Unity 插件可以各贡献一个目录 Tab。
这里只按插件返回的根做一层列目录和读文件，相对路径越出根目录直接拒绝。
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from api.repos import _MAX_ENTRIES, _has_children, _safe_join
from database import db
from plugins.registry import collect_workspace_roots

logger = logging.getLogger("api.workspace_roots")

router = APIRouter(prefix="/api/projects", tags=["workspace-roots"])

_SEARCH_LIMIT = 200
_SEARCH_BUDGET = 40000
_TEXT_LIMIT = 5 * 1024 * 1024


async def _project_roots(project_id: str) -> list:
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")
    return await collect_workspace_roots(project)


async def _root_or_404(project_id: str, root_id: str) -> dict:
    for root in await _project_roots(project_id):
        if root["id"] == root_id:
            if not root.get("available") or not root.get("path"):
                raise HTTPException(404, root.get("message") or "目录不可用")
            return root
    raise HTTPException(404, "没有这个工作区根")


def _scan(target: Path, rel_base: str) -> tuple:
    try:
        items = list(os.scandir(target))
    except (PermissionError, OSError) as e:
        logger.debug("扫描目录失败 %s: %s", target, e)
        return [], False, 0

    dirs, files = [], []
    for it in items:
        if it.name.startswith(".") or it.name == "__pycache__":
            continue
        try:
            is_dir = it.is_dir(follow_symlinks=False)
        except OSError:
            continue
        (dirs if is_dir else files).append(it)
    dirs.sort(key=lambda x: x.name.lower())
    files.sort(key=lambda x: x.name.lower())
    ordered = [(it, True) for it in dirs] + [(it, False) for it in files]
    total = len(ordered)
    truncated = total > _MAX_ENTRIES
    ordered = ordered[:_MAX_ENTRIES]

    out = []
    for it, is_dir in ordered:
        child_rel = f"{rel_base}/{it.name}" if rel_base else it.name
        child_rel = child_rel.replace("\\", "/")
        if is_dir:
            out.append({
                "name": it.name,
                "path": child_rel,
                "type": "directory",
                "has_children": _has_children(it.path),
            })
        else:
            try:
                size = it.stat().st_size
            except OSError:
                size = 0
            out.append({
                "name": it.name, "path": child_rel, "type": "file", "size": size,
            })
    return out, truncated, total


def _search(root: Path, query: str, limit: int) -> dict:
    q = query.casefold()
    hits = []
    scanned = 0
    truncated = False
    queue: deque = deque([root])
    while queue:
        current = queue.popleft()
        try:
            entries = list(os.scandir(current))
        except (PermissionError, OSError):
            continue
        child_dirs = []
        for it in entries:
            if it.name.startswith(".") or it.name == "__pycache__":
                continue
            scanned += 1
            if scanned > _SEARCH_BUDGET:
                truncated = True
                break
            try:
                rel = str(Path(it.path).resolve().relative_to(root.resolve())).replace("\\", "/")
                is_dir = it.is_dir(follow_symlinks=False)
            except (OSError, ValueError):
                continue
            if q in it.name.casefold() or q in rel.casefold():
                size = 0
                if not is_dir:
                    try:
                        size = it.stat().st_size
                    except OSError:
                        size = 0
                hits.append({
                    "name": it.name,
                    "path": rel,
                    "type": "directory" if is_dir else "file",
                    "size": size,
                })
                if len(hits) >= limit:
                    truncated = True
                    break
            if is_dir:
                child_dirs.append(it.path)
        if truncated:
            break
        queue.extend(child_dirs)
    return {
        "query": query,
        "entries": hits[:limit],
        "truncated": truncated,
        "scanned": scanned,
        "limit": limit,
    }


@router.get("/{project_id}/workspace-roots")
async def list_workspace_roots(project_id: str):
    """当前项目各插件贡献的目录 Tab。不匹配的插件不会出现。"""
    return await _project_roots(project_id)


@router.get("/{project_id}/workspace-roots/{root_id}/tree")
async def get_workspace_tree(project_id: str, root_id: str, path: str = ""):
    """只列插件根下的一层。引擎目录很大，不能一次性递归。"""
    root = await _root_or_404(project_id, root_id)
    target = _safe_join(root["path"], path)
    if not target.is_dir():
        raise HTTPException(404, "目录不存在")
    rel_base = path.replace("\\", "/").strip("/")
    entries, truncated, total = await asyncio.to_thread(_scan, target, rel_base)
    return {
        "path": rel_base,
        "root": {"id": root["id"], "label": root["label"], "kind": root["kind"]},
        "entries": entries,
        "truncated": truncated,
        "total": total,
        "limit": _MAX_ENTRIES,
    }


@router.get("/{project_id}/workspace-roots/{root_id}/search")
async def search_workspace(project_id: str, root_id: str, q: str = "", limit: int = _SEARCH_LIMIT):
    """按文件名或相对路径过滤。广度优先，扫到预算就停，避免把整个引擎盘走完。"""
    query = (q or "").strip()
    if not query:
        return {"query": "", "entries": [], "truncated": False, "scanned": 0}
    root = await _root_or_404(project_id, root_id)
    cap = max(1, min(int(limit or _SEARCH_LIMIT), _SEARCH_LIMIT))
    return await asyncio.to_thread(_search, Path(root["path"]), query, cap)


@router.get("/{project_id}/workspace-roots/{root_id}/file")
async def get_workspace_file(project_id: str, root_id: str, path: str):
    root = await _root_or_404(project_id, root_id)
    target = _safe_join(root["path"], path)
    if not target.is_file():
        raise HTTPException(404, "文件不存在")
    try:
        size = target.stat().st_size
    except OSError:
        size = 0
    if size > _TEXT_LIMIT:
        raise HTTPException(413, f"文件过大（{size // 1024 // 1024}MB），请在本地打开")
    try:
        head = target.read_bytes()[:4096]
    except OSError as e:
        raise HTTPException(400, f"读取失败: {e}")
    rel = path.replace("\\", "/").lstrip("/")
    if b"\0" in head:
        return {
            "path": rel,
            "content": f"（二进制文件，{size} 字节，不预览文本）",
            "size": size,
            "binary": True,
        }
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise HTTPException(400, f"读取失败: {e}")
    return {"path": rel, "content": content, "size": size, "binary": False}


@router.get("/{project_id}/workspace-roots/{root_id}/file-raw")
async def get_workspace_file_raw(project_id: str, root_id: str, path: str):
    root = await _root_or_404(project_id, root_id)
    target = _safe_join(root["path"], path)
    if not target.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(str(target))
