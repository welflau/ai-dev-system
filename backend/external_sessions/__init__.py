"""
外部 AI 编辑器会话 providers。

目前有 Cursor / CodeBuddy / Claude Code；后续按同一 base.SessionProvider 接口加
WorkBuddy，在 PROVIDERS 里注册一下即可。
"""
from .base import (
    ExternalMessage,
    ExternalSessionDetail,
    ExternalSessionSummary,
    SessionProvider,
)
from .cursor import CursorProvider
from .codebuddy import CodeBuddyProvider
from .claude import ClaudeProvider

PROVIDERS: dict[str, SessionProvider] = {
    "cursor": CursorProvider(),
    "codebuddy": CodeBuddyProvider(),
    "claude": ClaudeProvider(),
}

__all__ = [
    "ExternalMessage",
    "ExternalSessionDetail",
    "ExternalSessionSummary",
    "SessionProvider",
    "CursorProvider",
    "CodeBuddyProvider",
    "ClaudeProvider",
    "PROVIDERS",
]
