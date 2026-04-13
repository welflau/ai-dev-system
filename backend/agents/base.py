"""
AI 自动开发系统 - Agent 基类 (Role)
Agent = Role + Actions
Role 定义身份，Actions 定义能力
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Type
import logging

logger = logging.getLogger("agent.base")


class BaseAgent(ABC):
    """Agent 基类 (Role) — 持有 Action 列表，按任务名分发执行"""

    # 子类可声明关联的 Action 类列表（可选，向后兼容）
    action_classes: List[Type] = []

    def __init__(self):
        # 实例化 Action 对象
        self._actions = {}
        for cls in self.action_classes:
            action = cls()
            self._actions[action.name] = action

    @property
    @abstractmethod
    def agent_type(self) -> str:
        """Agent 类型标识"""
        pass

    @abstractmethod
    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """执行任务（子类实现，可调用 self.run_action）"""
        pass

    async def run_action(self, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """通过 Action 名称执行（新方式：Action 组合）"""
        action = self._actions.get(action_name)
        if not action:
            return {"status": "error", "message": f"Agent {self.agent_type} 没有 Action: {action_name}"}

        result = await action.run(context)
        return result.to_dict()

    def list_actions(self) -> List[str]:
        """列出此 Agent 持有的所有 Action"""
        return list(self._actions.keys())

    def has_action(self, name: str) -> bool:
        return name in self._actions
