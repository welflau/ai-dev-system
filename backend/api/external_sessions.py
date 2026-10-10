"""
AI 自动开发系统 - 外部 AI 编辑器会话 API（只读）

目前只支持 Cursor；按同一 provider 接口可扩展 CodeBuddy / WorkBuddy。
路由前缀和 projects / plugins 对齐（/api/projects/{project_id}/...）。
"""
from __future__ import annotations

import json as _json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from database import db
from external_sessions import PROVIDERS
from external_sessions.cursor import _sniff_image_mime

logger = logging.getLogger("api.external_sessions")

router = APIRouter(prefix="/api/projects", tags=["external-sessions"])


async def _collect_candidate_roots(project_id: str) -> list[str]:
    """
    从 projects 表拿 git_repo_path + extra_paths，拼成候选根目录列表。
    和 backend/actions/chat/load_skill.py:197-210 的套路一致，这里本地化。
    """
    row = await db.fetch_one(
        "SELECT git_repo_path, extra_paths FROM projects WHERE id=?",
        (project_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")
    roots: list[str] = []
    if row.get("git_repo_path"):
        roots.append(row["git_repo_path"])
    try:
        extra = _json.loads(row.get("extra_paths") or "[]")
        roots += [
            p["path"]
            for p in extra
            if isinstance(p, dict) and p.get("path")
        ]
    except Exception as e:
        logger.debug("parse extra_paths failed for %s: %s", project_id, e)
    return roots


@router.get("/{project_id}/external-sessions")
async def list_external_sessions(project_id: str, provider: str = "cursor"):
    """
    列出该项目下指定 provider 的所有会话（按 updated_at 倒序）。
    - 项目没设 git_repo_path 且 extra_paths 为空：返回 roots:[]，sessions:[]（前端据此显示空态）
    - provider 没装（Cursor User 目录不存在）：provider_available=False，sessions:[]
    """
    p = PROVIDERS.get(provider)
    if not p:
        raise HTTPException(status_code=400, detail=f"unknown provider: {provider}")
    roots = await _collect_candidate_roots(project_id)
    sessions = p.list_sessions(roots) if roots else []
    return {
        "provider": provider,
        "provider_available": getattr(p, "available", True),
        "roots": roots,
        "sessions": [s.model_dump() for s in sessions],
    }


@router.get("/{project_id}/external-sessions/{provider}/{session_id}")
async def get_external_session(project_id: str, provider: str, session_id: str):
    """
    返回单个会话的完整气泡。project_id 这里仅做"该项目在库里存在"的轻校验 ——
    session 真正的归属是靠 workspace path 匹配判定的（Cursor 的 workspaceId 不等于我们的 project_id）。
    """
    p = PROVIDERS.get(provider)
    if not p:
        raise HTTPException(status_code=400, detail=f"unknown provider: {provider}")
    # 校验项目存在
    row = await db.fetch_one("SELECT id FROM projects WHERE id=?", (project_id,))
    if not row:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")
    detail = p.get_session(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")
    return detail.model_dump()


@router.get("/{project_id}/external-sessions/{provider}/{session_id}/images/{image_id}")
async def get_external_session_image(project_id: str, provider: str, session_id: str, image_id: str):
    """返回消息里附带图片的原始字节（粘贴截图等）。image_id 来自 ExternalMessage.images[*].uuid。"""
    p = PROVIDERS.get(provider)
    if not p:
        raise HTTPException(status_code=400, detail=f"unknown provider: {provider}")
    row = await db.fetch_one("SELECT id FROM projects WHERE id=?", (project_id,))
    if not row:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")
    get_image = getattr(p, "get_image", None)
    path = get_image(session_id, image_id) if get_image else None
    if not path:
        raise HTTPException(status_code=404, detail=f"image not found: {image_id}")
    return FileResponse(path, media_type=_sniff_image_mime(path))
