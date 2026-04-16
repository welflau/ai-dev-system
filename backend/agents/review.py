"""
ReviewAgent — 代码审查 Agent (Role)
Actions: CodeReviewAction (读取实际代码，非盲审)
Watch: write_code
"""
from typing import Any, Dict
from agents.base import BaseAgent, ReactMode
from actions.code_review import CodeReviewAction


class ReviewAgent(BaseAgent):

    action_classes = [CodeReviewAction]
    react_mode = ReactMode.SINGLE
    watch_actions = {"write_code"}

    @property
    def agent_type(self) -> str:
        return "ReviewAgent"
