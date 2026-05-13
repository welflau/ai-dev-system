"""
Hook 类型定义 — HookEvent 枚举 + ToolHookContext 数据类
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class HookEvent(str, Enum):
    PRE_TOOL_USE  = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    TOOL_ERROR    = "ToolError"
    SESSION_START = "SessionStart"
    SESSION_END   = "SessionEnd"


@dataclass
class ToolHookContext:
    """传给每个 Hook 的上下文信息"""
    event:       HookEvent
    tool_name:   str
    input:       dict          = field(default_factory=dict)
    output:      Any           = None   # POST_TOOL_USE 时填充
    error:       Optional[Exception] = None   # TOOL_ERROR 时填充
    duration_ms: Optional[float] = None       # POST_TOOL_USE / TOOL_ERROR 时填充
    project_id:  Optional[str] = None
    ticket_id:   Optional[str] = None
    agent_type:  Optional[str] = None
