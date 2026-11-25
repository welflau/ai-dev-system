"""全局、项目和工单的 SSE 订阅入口。"""
from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

import events


class _EventStreamResponse(EventSourceResponse):
    # FastAPI 生成 OpenAPI 时读取类属性；sse-starlette 默认只在实例上设置它。
    media_type = "text/event-stream"


global_router = APIRouter(default_response_class=_EventStreamResponse)
scoped_router = APIRouter(default_response_class=_EventStreamResponse)


def _stream(channel: str):
    return _EventStreamResponse(events.event_manager.event_generator(channel))


@global_router.get("/api/events/global")
async def global_events_stream():
    """全局 SSE 频道——全局聊天 AI 工具日志、跨项目事件"""
    return _stream("global")


@scoped_router.get("/api/projects/{project_id}/events")
async def project_events(project_id: str):
    """项目事件流（SSE）"""
    return _stream(f"project:{project_id}")


@scoped_router.get("/api/tickets/{ticket_id}/events")
async def ticket_events(ticket_id: str):
    """工单事件流（SSE）"""
    return _stream(f"ticket:{ticket_id}")
