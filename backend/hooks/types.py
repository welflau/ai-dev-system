"""
Hook 类型定义 — HookEvent 枚举 + ToolHookContext 数据类
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class HookEvent(str, Enum):
    PRE_TOOL_USE        = "PreToolUse"
    POST_TOOL_USE       = "PostToolUse"
    TOOL_ERROR          = "ToolError"
    SESSION_START       = "SessionStart"
    SESSION_END         = "SessionEnd"
    USER_PROMPT_SUBMIT  = "UserPromptSubmit"   # 用户消息到达，LLM 调用前
    ASSISTANT_STOP      = "AssistantStop"      # AI 回复完成，MessageDone 后


@dataclass
class ToolHookContext:
    """传给每个 Hook 的上下文信息"""
    event:       HookEvent
    tool_name:   str           = ""
    input:       dict          = field(default_factory=dict)
    output:      Any           = None   # POST_TOOL_USE 时填充
    error:       Optional[Exception] = None   # TOOL_ERROR 时填充
    duration_ms: Optional[float] = None       # POST_TOOL_USE / TOOL_ERROR 时填充
    project_id:  Optional[str] = None
    ticket_id:   Optional[str] = None
    agent_type:  Optional[str] = None
    # USER_PROMPT_SUBMIT / ASSISTANT_STOP 时的额外字段
    user_message:   Optional[str] = None      # 用户输入的消息
    assistant_reply: Optional[str] = None     # AI 回复的完整文本
    rounds:         Optional[int] = None      # ASSISTANT_STOP 时完成的轮次数
