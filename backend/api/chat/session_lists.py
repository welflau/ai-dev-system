"""项目和全局聊天面板的只读会话列表。"""
from fastapi import APIRouter

from services.chat.session_lists import fetch_session_summaries

project_router = APIRouter()
global_router = APIRouter()


@project_router.get("/sessions")
async def list_sessions(project_id: str, limit: int = 50):
    """列出项目的会话列表（按最新活跃倒序）"""
    return {"sessions": await fetch_session_summaries(project_id, limit)}


@global_router.get("/sessions")
async def list_global_sessions(limit: int = 50):
    """列出全局会话（project_id IS NULL）"""
    return {"sessions": await fetch_session_summaries(None, limit)}
