"""
AI 自动开发系统 - 外部 AI 编辑器会话 API（只读）

目前只支持 Cursor；按同一 provider 接口可扩展 CodeBuddy / WorkBuddy。
路由前缀和 projects / plugins 对齐（/api/projects/{project_id}/...）。
"""
from __future__ import annotations

import json as _json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

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
async def list_external_sessions(project_id: str, provider: str = "cursor", q: str = ""):
    """
    列出该项目下指定 provider 的所有会话（按 updated_at 倒序）。
    - 项目没设 git_repo_path 且 extra_paths 为空：返回 roots:[]，sessions:[]（前端据此显示空态）
    - provider 没装（Cursor User 目录不存在）：provider_available=False，sessions:[]
    - q 非空：标题 / 副标题 / 消息正文任一命中才留下；正文命中带 extra.match_snippet
    """
    p = PROVIDERS.get(provider)
    if not p:
        raise HTTPException(status_code=400, detail=f"unknown provider: {provider}")
    roots = await _collect_candidate_roots(project_id)
    sessions = p.list_sessions(roots, query=(q or "").strip()) if roots else []
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


# ==================== 导入外部会话为 ADS 聊天会话 ====================

class ImportExternalSessionRequest(BaseModel):
    scope: str = Field(default="all", description="all | last_n | last_days")
    n: Optional[int] = Field(default=None, description="scope=last_n 时取最近 N 条")
    days: Optional[int] = Field(default=None, description="scope=last_days 时取最近 N 天")


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _apply_scope(msgs, req: ImportExternalSessionRequest):
    """按 scope 裁剪文字轮次列表。"""
    if req.scope == "last_n" and req.n and req.n > 0:
        return msgs[-req.n:]
    if req.scope == "last_days" and req.days and req.days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=req.days)
        return [m for m in msgs if (dt := _parse_iso(m.created_at)) is None or dt >= cutoff]
    return msgs


def _coalesce_turns(msgs) -> list:
    """合并连续同 role 的文字消息，保证 user/assistant 交替；图片并到对应消息上。"""
    turns = []
    for m in msgs:
        images = [img for img in (m.images or []) if isinstance(img, dict) and img.get("uuid")]
        text = (m.content or "").strip()
        if not text and not images:
            continue
        if turns and turns[-1]["role"] == m.role:
            last = turns[-1]
            if text:
                last["text"] = (last["text"] + "\n" + text).strip()
            last["images"].extend(images)
            if not last.get("created_at") and m.created_at:
                last["created_at"] = m.created_at
        else:
            turns.append({"role": m.role, "text": text, "images": images, "created_at": m.created_at})
    return turns


def _ext_for_mime(media_type: str) -> str:
    return {
        "image/png": "png",
        "image/jpeg": "jpeg",
        "image/gif": "gif",
        "image/webp": "webp",
    }.get(media_type, "png")


def _save_external_images(project_id: str, provider, session_id: str, images: list) -> list:
    """把外部会话消息里的图片字节落盘到 chat_images，返回可访问 URL 列表。"""
    from config import BASE_DIR

    get_image = getattr(provider, "get_image", None)
    if not get_image or not images:
        return []
    chat_images_dir = BASE_DIR / "chat_images" / project_id
    chat_images_dir.mkdir(parents=True, exist_ok=True)
    urls = []
    for img in images:
        uid = img.get("uuid")
        if not uid:
            continue
        try:
            src = get_image(session_id, uid)
            if not src:
                continue
            data = Path(src).read_bytes()
        except Exception as e:
            logger.warning("读外部图片失败 %s: %s", uid, e)
            continue
        filename = f"{uuid.uuid4().hex}.{_ext_for_mime(_sniff_image_mime(Path(src)))}"
        try:
            (chat_images_dir / filename).write_bytes(data)
        except Exception as e:
            logger.warning("写图片失败 %s: %s", filename, e)
            continue
        urls.append(f"/chat-images/{project_id}/{filename}")
    return urls


@router.post("/{project_id}/external-sessions/{provider}/{session_id}/import")
async def import_external_session(
    project_id: str,
    provider: str,
    session_id: str,
    req: ImportExternalSessionRequest,
):
    """把一段外部会话整体导入为新的 ADS 聊天会话（文字 + 图片作为历史注入）。"""
    p = PROVIDERS.get(provider)
    if not p:
        raise HTTPException(status_code=400, detail=f"unknown provider: {provider}")
    row = await db.fetch_one("SELECT id FROM projects WHERE id=?", (project_id,))
    if not row:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")
    detail = p.get_session(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")

    # 只导真实对话轮（文字），跳过 thinking/tool_call/files_changed
    text_msgs = [m for m in detail.messages if m.role in ("user", "assistant") and m.kind == "text"]
    text_msgs = _apply_scope(text_msgs, req)
    turns = _coalesce_turns(text_msgs)
    if not turns:
        raise HTTPException(status_code=400, detail="该会话没有可导入的文字消息")

    from utils import generate_id, now_iso

    sid = generate_id("sess-")
    title = ((detail.title or "").strip() or "外部会话") + " · Cursor 导入"
    now = now_iso()
    await db.insert("chat_sessions", {
        "id": sid,
        "project_id": project_id,
        "title": title,
        "created_at": now,
        "updated_at": now,
    })

    imported = 0
    for t in turns:
        urls = _save_external_images(project_id, p, session_id, t["images"])
        await db.insert("chat_messages", {
            "id": generate_id("MSG"),
            "project_id": project_id,
            "role": t["role"],
            "content": t["text"],
            "images_json": _json.dumps(urls, ensure_ascii=False) if urls else None,
            "session_id": sid,
            "created_at": t.get("created_at") or now_iso(),
        })
        imported += 1

    await db.execute(
        "UPDATE chat_sessions SET message_count = ?, updated_at = ? WHERE id = ?",
        (imported, now_iso(), sid),
    )
    return {"session_id": sid, "title": title, "message_count": imported}
