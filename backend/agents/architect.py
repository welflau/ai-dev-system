"""
ArchitectAgent — 架构设计 Agent (Role)
Actions: DesignArchitectureAction
Mode: SINGLE (单步执行)
Watch: 无（由 orchestrator 触发）
"""
from typing import Any, Dict
from agents.base import BaseAgent, ReactMode
from actions.design_architecture import DesignArchitectureAction


class ArchitectAgent(BaseAgent):
    action_classes = [DesignArchitectureAction]
    react_mode = ReactMode.SINGLE
    watch_actions = set()

    @property
    def agent_type(self) -> str:
        return "ArchitectAgent"
