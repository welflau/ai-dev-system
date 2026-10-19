"""
外部 AI 编辑器会话 provider 抽象。

目前只实现 Cursor，后续可按同一接口加 CodeBuddy / WorkBuddy。
统一 schema 的宗旨：不给前端分四套渲染代码。各家特有字段统一塞进
ExternalMessage.raw / ExternalSessionSummary.extra，前端有需要再按 provider 判断。
"""
from __future__ import annotations

from typing import ClassVar, List, Literal, Optional, Protocol

from pydantic import BaseModel, Field


Role = Literal["user", "assistant", "system"]
Kind = Literal["text", "thinking", "tool_call", "files_changed"]


class ExternalMessage(BaseModel):
    id: str
    role: Role
    kind: Kind = "text"                     # 气泡形态：普通文本 / 模型思考 / 工具调用
    content: str = ""                       # markdown-ready 文本（代码块、路径等由前端 formatChatContent 再处理）
    created_at: Optional[str] = None        # ISO；拿不到也无妨
    tool_calls: Optional[List[dict]] = None # 原样 JSON，前端用折叠块兜底渲染
    images: Optional[List[dict]] = None     # 消息里附带的图片，[{uuid, width, height}]；二进制另走 images 端点拉取
    raw: Optional[dict] = None              # provider 特有字段的垃圾桶


class ExternalSessionSummary(BaseModel):
    id: str
    title: str = ""
    created_at: str = ""
    updated_at: str = ""
    message_count: int = 0
    is_archived: bool = False
    provider: str                           # 'cursor' / 'codebuddy' / 'workbuddy'
    extra: Optional[dict] = None            # provider 特有元数据（如 Cursor 的 forceMode/subtitle）


class ExternalSessionDetail(ExternalSessionSummary):
    messages: List[ExternalMessage] = Field(default_factory=list)


def contains_query(hay: Optional[str], query: str) -> bool:
    """大小写不敏感的子串匹配。query 为空视为不限制。"""
    if not query:
        return True
    return query.casefold() in (hay or "").casefold()


def match_snippet(hay: Optional[str], query: str, radius: int = 42) -> str:
    """命中处前后各留一段，压成一行。没命中返回空串。"""
    text = hay or ""
    if not query or not text:
        return ""
    idx = text.casefold().find(query.casefold())
    if idx < 0:
        return ""
    start = max(0, idx - radius)
    end = min(len(text), idx + len(query) + radius)
    snip = " ".join(text[start:end].split())
    if start > 0:
        snip = "…" + snip
    if end < len(text):
        snip = snip + "…"
    return snip


class SessionProvider(Protocol):
    """所有 provider 的鸭子型接口。candidate_roots 都是绝对本地路径字符串。"""

    name: ClassVar[str]

    def list_sessions(self, candidate_roots: List[str], query: str = "") -> List[ExternalSessionSummary]:
        """按候选根路径（主路径 + extra_paths）前缀匹配，返回命中的所有会话摘要。

        query 非空时，标题 / 副标题没命中的会话还要再查消息正文；
        正文命中的摘要把片段放在 extra.match_snippet。
        """
        ...

    def get_session(self, session_id: str) -> Optional[ExternalSessionDetail]:
        """按 session_id 返回完整详情（含消息），拿不到返回 None。"""
        ...
