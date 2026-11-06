"""会话临时素材 API。项目会话与全局会话各挂一套路径。"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from materials.registry import material_registry

logger = logging.getLogger("api.session_materials")

project_router = APIRouter(
    prefix="/api/projects/{project_id}/chat/sessions/{session_id}/materials",
    tags=["session-materials"],
)
global_router = APIRouter(
    prefix="/api/chat/sessions/{session_id}/materials",
    tags=["session-materials-global"],
)


class PinBody(BaseModel):
    pinned: bool = True


class PromoteBody(BaseModel):
    sink: str = Field(..., description="art / repo / knowledge / ticket")
    ticket_id: Optional[str] = None
    scope: str = Field(default="project", description="art 提升：project 或 global")


class AttachBody(BaseModel):
    urls: List[str] = Field(default_factory=list)
    origin: str = "upload"
    message_id: Optional[str] = None


async def _ensure_session(session_id: str, project_id: Optional[str]) -> None:
    from database import db
    if project_id and project_id != "__global__":
        row = await db.fetch_one(
            "SELECT id FROM chat_sessions WHERE id=? AND (project_id=? OR project_id IS NULL)",
            (session_id, project_id),
        )
    else:
        row = await db.fetch_one("SELECT id FROM chat_sessions WHERE id=?", (session_id,))
    if not row:
        raise HTTPException(404, "会话不存在")


def _pid(project_id: Optional[str]) -> Optional[str]:
    if not project_id or project_id == "__global__":
        return None
    return project_id


async def _list_materials(session_id: str, project_id: Optional[str]):
    await _ensure_session(session_id, project_id)
    try:
        await material_registry.sync_inline_docs_from_session(session_id, _pid(project_id))
    except Exception as e:
        logger.debug("补登聊天附件到会话素材失败: %s", e)
    items = await material_registry.list(session_id)
    return {"materials": items, "count": len(items)}


async def _pin_material(session_id: str, material_id: str, project_id: Optional[str], pinned: bool):
    await _ensure_session(session_id, project_id)
    rec = await material_registry.get(material_id)
    if not rec or rec["session_id"] != session_id:
        raise HTTPException(404, "素材不存在")
    try:
        return await material_registry.pin(material_id, pinned)
    except FileNotFoundError:
        raise HTTPException(404, "素材不存在")


async def _promote_material(session_id: str, material_id: str, project_id: Optional[str], body: PromoteBody):
    await _ensure_session(session_id, project_id)
    rec = await material_registry.get(material_id)
    if not rec or rec["session_id"] != session_id:
        raise HTTPException(404, "素材不存在")
    if body.sink in {"art", "ticket", "repo"} and not _pid(project_id) and body.sink != "knowledge":
        if body.sink != "art" or body.scope != "global":
            raise HTTPException(400, "全局会话只能提升到全局资产或知识库")
    try:
        return await material_registry.promote(
            material_id, body.sink, ticket_id=body.ticket_id, scope=body.scope,
        )
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))


async def _file(session_id: str, material_id: str, project_id: Optional[str]):
    await _ensure_session(session_id, project_id)
    rec = await material_registry.get(material_id)
    if not rec or rec["session_id"] != session_id or rec["status"] == "deleted":
        raise HTTPException(404, "素材不存在")
    path = material_registry.resolve_file(rec)
    if not path.is_file():
        raise HTTPException(404, "文件已丢失")
    return FileResponse(path, media_type=rec.get("mime") or None, filename=rec.get("name"))


@project_router.get("")
async def list_project_materials(project_id: str, session_id: str):
    return await _list_materials(session_id, project_id)


@project_router.post("/attach-urls")
async def attach_project_urls(project_id: str, session_id: str, body: AttachBody):
    await _ensure_session(session_id, project_id)
    items = await material_registry.attach_urls(
        session_id=session_id, project_id=project_id,
        urls=body.urls, origin=body.origin, message_id=body.message_id,
    )
    return {"materials": items, "count": len(items)}


@project_router.post("/{material_id}/pin")
async def pin_project_material(project_id: str, session_id: str, material_id: str, body: PinBody):
    return await _pin_material(session_id, material_id, project_id, body.pinned)


@project_router.post("/{material_id}/promote")
async def promote_project_material(project_id: str, session_id: str, material_id: str, body: PromoteBody):
    return await _promote_material(session_id, material_id, project_id, body)


@project_router.get("/{material_id}/file")
async def file_project_material(project_id: str, session_id: str, material_id: str):
    return await _file(session_id, material_id, project_id)


@global_router.get("")
async def list_global_materials(session_id: str):
    return await _list_materials(session_id, None)


@global_router.post("/attach-urls")
async def attach_global_urls(session_id: str, body: AttachBody):
    await _ensure_session(session_id, None)
    items = await material_registry.attach_urls(
        session_id=session_id, project_id=None,
        urls=body.urls, origin=body.origin, message_id=body.message_id,
    )
    return {"materials": items, "count": len(items)}


@global_router.post("/{material_id}/pin")
async def pin_global_material(session_id: str, material_id: str, body: PinBody):
    return await _pin_material(session_id, material_id, None, body.pinned)


@global_router.post("/{material_id}/promote")
async def promote_global_material(session_id: str, material_id: str, body: PromoteBody):
    return await _promote_material(session_id, material_id, None, body)


@global_router.get("/{material_id}/file")
async def file_global_material(session_id: str, material_id: str):
    return await _file(session_id, material_id, None)
