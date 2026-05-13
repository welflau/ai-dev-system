"""
ADS QueryEngine 模块 — 统一的 LLM 调用循环抽象

核心类：
  - QueryEngine  : 工具调用循环引擎（run() 异步生成器）
  - Budget       : 三重安全阀（Token / 轮次 / 时间）
  - QueryEvent   : 标准事件流类型
"""
from query_engine.budget import Budget
from query_engine.engine import QueryEngine
from query_engine.events import (
    ActionEvent,
    BudgetExceededEvent,
    ErrorEvent,
    MessageDoneEvent,
    QueryEvent,
    TextDeltaEvent,
    ToolDoneEvent,
    ToolErrorEvent,
    ToolStartEvent,
)
from query_engine.executor import (
    ChatToolExecutorAdapter,
    OrchestratorToolExecutorAdapter,
    ToolExecutorProtocol,
)

__all__ = [
    "QueryEngine", "Budget", "QueryEvent",
    "TextDeltaEvent", "ToolStartEvent", "ToolDoneEvent", "ToolErrorEvent",
    "ActionEvent", "MessageDoneEvent", "BudgetExceededEvent", "ErrorEvent",
    "ToolExecutorProtocol", "ChatToolExecutorAdapter", "OrchestratorToolExecutorAdapter",
]
