"""
外部 AI 编辑器会话 providers。

目前只有 Cursor；后续按同一 base.SessionProvider 接口加 CodeBuddy / WorkBuddy，
在 PROVIDERS 里注册一下即可。
"""
from .base import (
    ExternalMessage,
    ExternalSessionDetail,
    ExternalSessionSummary,
    SessionProvider,
)
from .cursor import CursorProvider

PROVIDERS: dict[str, SessionProvider] = {
    "cursor": CursorProvider(),
}

__all__ = [
    "ExternalMessage",
    "ExternalSessionDetail",
    "ExternalSessionSummary",
    "SessionProvider",
    "CursorProvider",
    "PROVIDERS",
]
