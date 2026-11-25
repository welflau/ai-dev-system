"""结果处理器的入参和返回约定。"""
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

# 处理器的返回值有两种含义，对应拆分前 `_handle_agent_result` 的两种出口：
#
# - 返回 HANDLED：已在处理器内收尾。调用方直接结束，不发 `ticket_status_changed`，
#   也不在这里继续派单。对应原来分支里的 `return`。
# - 返回状态字符串：调用方发 `ticket_status_changed`，并按规则表继续流转。
#   对应原来落到函数尾部的路径。
HANDLED = None


@dataclass
class ResultContext:
    """一次 Agent 结果处理的全部输入。

    业务字段和 `_handle_agent_result` 拆分前的局部变量一一对应。

    `db`、`fire_knowledge_distill` 和 `synthesize_blocked_diagnosis` 由 orchestrator
    在调用时传入，处理器模块不自己导入：

    - 测试用 `monkeypatch.setattr(orchestrator, "db", test_db)` 换库，处理器必须
      拿到同一个对象，否则会写到真实库里。
    - `_fire_knowledge_distill` 和 `_synthesize_blocked_diagnosis` 留在 orchestrator.py，由调用方传进来。
      测试按 orchestrator 的模块全局名给它们打桩，orchestrator 构造 `ResultContext` 时
      也按模块全局名取。它们用到的 L3 模块经 `runtime_facade` 在调用时才解析，没有静态导入。
    """

    orch: Any                               # TicketOrchestrator：写日志、评论、记忆，查 SOP
    db: Any
    project_id: str
    ticket_id: str
    ticket: Dict[str, Any]
    agent_name: str
    action: str
    result: Dict[str, Any]
    result_json: str
    current_status: str
    requirement_id: str
    git_result: Optional[Dict[str, Any]]
    fire_knowledge_distill: Callable[[str, str], None]
    synthesize_blocked_diagnosis: Callable[..., Dict[str, Any]]   # 只有 skill 处理器用
    run_id: Optional[str] = None


ResultHandler = Callable[[ResultContext], Awaitable[Optional[str]]]
