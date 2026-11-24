"""Agent 结果处理器：每个 Agent 一个函数，加一张注册表。

从 `TicketOrchestrator._handle_agent_result` 拆出（重构方案 R2 第 1 步）。
公共前置（终态门闩、error 止血、媒体与 Git、片段 closeout）和尾部（发状态事件、
继续流转）仍在 orchestrator.py。

分发顺序和拆分前一致：

1. `pre_skill_handler`：按 (Agent, action) 精确匹配，排在 skill 判断之前；
2. `handle_skill`：调用方用 `is_skill_run_result` 认出 skill 结果后直接取它，不查表；
3. `agent_handler`：按 Agent 名查，个别 Agent 还要求 action 匹配。

三步都没命中时，调用方保持原状态并照常走尾部，和拆分前的 `else` 分支一样。

新增 Agent 时在这里登记处理器。漏登记的后果是状态不推进、同一条规则反复命中。
"""
from typing import Dict, Optional, Tuple

from orchestration.result_handlers.architect import handle_architect
from orchestration.result_handlers.art import handle_art
from orchestration.result_handlers.artist import handle_artist
from orchestration.result_handlers.context import HANDLED, ResultContext, ResultHandler
from orchestration.result_handlers.deploy import handle_deploy
from orchestration.result_handlers.dev import handle_dev, handle_html_prototype
from orchestration.result_handlers.planner import handle_planner
from orchestration.result_handlers.product import handle_acceptance_review
from orchestration.result_handlers.review import handle_review
from orchestration.result_handlers.skill import (
    handle_skill,
    skill_gate_file_paths,
    skill_produces_satisfied,
)
from orchestration.result_handlers.tester import handle_test
from orchestration.result_handlers.ue_editor import handle_ue_editor
from orchestration.result_handlers.ux import handle_ux

__all__ = [
    "HANDLED", "ResultContext", "ResultHandler",
    "pre_skill_handler", "handle_skill", "agent_handler",
    "skill_gate_file_paths", "skill_produces_satisfied",
]

# 排在 skill 判断之前的处理器。
_PRE_SKILL_HANDLERS: Dict[Tuple[str, str], ResultHandler] = {
    ("DevAgent", "write_html_prototype"): handle_html_prototype,
}

# 按 Agent 名分发，不看 action。
_AGENT_HANDLERS: Dict[str, ResultHandler] = {
    "ArtistAgent": handle_artist,
    "ArtAgent": handle_art,
    "UXAgent": handle_ux,
    "PlannerAgent": handle_planner,
    "UEEditorAgent": handle_ue_editor,
    "ArchitectAgent": handle_architect,
    "DevAgent": handle_dev,
    "ReviewAgent": handle_review,
    "TestAgent": handle_test,
    "DeployAgent": handle_deploy,
}

# 只在指定 action 下才有处理器的 Agent。其余 action 不命中，走调用方的兜底。
_AGENT_ACTION_HANDLERS: Dict[Tuple[str, str], ResultHandler] = {
    ("ProductAgent", "acceptance_review"): handle_acceptance_review,
}


def pre_skill_handler(agent_name: str, action: str) -> Optional[ResultHandler]:
    """排在 skill 判断之前的处理器，按 (Agent, action) 精确匹配。"""
    return _PRE_SKILL_HANDLERS.get((agent_name, action))


def agent_handler(agent_name: str, action: str) -> Optional[ResultHandler]:
    """排在 skill 判断之后的处理器。没有登记时返回 None。"""
    handler = _AGENT_HANDLERS.get(agent_name)
    if handler is not None:
        return handler
    return _AGENT_ACTION_HANDLERS.get((agent_name, action))
