"""
QueryEngine 事件类型定义。

QueryEngine.run() 产出的标准事件流，调用方按需消费：
  - HTTP 流式接口：TextDeltaEvent → SSE text_delta
  - Orchestrator：ToolDoneEvent → 更新进度面板
  - 单测：收集所有事件做断言
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


@dataclass
class TextDeltaEvent:
    """LLM 流式文本片段"""
    delta: str


@dataclass
class RoundStartEvent:
    """J-3b: 每轮 LLM 调用开始，用于前端分组显示"""
    round: int   # 从 1 开始


@dataclass
class ThinkingDeltaEvent:
    """J-3 Extended Thinking: 推理链流式片段"""
    delta: str


@dataclass
class ThinkingDoneEvent:
    """J-3 Extended Thinking: 完整推理文本"""
    text: str


@dataclass
class ToolStartEvent:
    """工具开始执行"""
    tool: str
    input: dict
    tool_use_id: str


@dataclass
class ToolDoneEvent:
    """工具执行完成"""
    tool: str
    summary: str
    args_hint: str
    duration_ms: float
    result: str = ""   # 完整工具返回内容（用于前端展开显示）


@dataclass
class ToolErrorEvent:
    """工具执行失败"""
    tool: str
    error: str
    duration_ms: float


@dataclass
class ActionEvent:
    """需要前端渲染卡片的 Action 结果（confirm_requirement 等）"""
    action_data: dict


@dataclass
class MessageDoneEvent:
    """本轮对话完成"""
    full_text: str
    thinking_steps: List[dict]
    final_action: Optional[dict]
    rounds: int
    total_tokens: int
    all_confirm_results: List[dict] = field(default_factory=list)


@dataclass
class BudgetExceededEvent:
    """预算超限，安全中断"""
    reason: str


@dataclass
class ErrorEvent:
    """执行错误"""
    message: str


# 联合类型，方便 isinstance 检查
QueryEvent = Union[
    TextDeltaEvent,
    RoundStartEvent,
    ThinkingDeltaEvent,
    ThinkingDoneEvent,
    ToolStartEvent,
    ToolDoneEvent,
    ToolErrorEvent,
    ActionEvent,
    MessageDoneEvent,
    BudgetExceededEvent,
    ErrorEvent,
]
