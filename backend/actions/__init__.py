"""
Actions — Agent 能力单元注册表
每个 Action 是一个独立的能力，可被多个 Agent 复用
使用 ActionNode 实现结构化输出（移植自 MetaGPT）
"""
from actions.base import ActionBase, ActionResult
from actions.action_node import ActionNode
from actions.schemas import ArchitectureOutput, DevOutput, ReviewOutput, TestReviewOutput, DecomposeOutput
from actions.design_architecture import DesignArchitectureAction
from actions.write_code import WriteCodeAction
from actions.self_test import SelfTestAction
from actions.acceptance_review import AcceptanceReviewAction

# 所有可用 Action 注册表
ACTION_REGISTRY = {
    "design_architecture": DesignArchitectureAction,
    "write_code": WriteCodeAction,
    "self_test": SelfTestAction,
    "acceptance_review": AcceptanceReviewAction,
}


def get_action(name: str) -> ActionBase:
    cls = ACTION_REGISTRY.get(name)
    if cls:
        return cls()
    raise ValueError(f"未知 Action: {name}")


def list_actions():
    return [{"name": name, "description": cls().description} for name, cls in ACTION_REGISTRY.items()]
