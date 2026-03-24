"""
AI 自动开发系统 - Agent 基类
所有 Agent 统一接口
"""
from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseAgent(ABC):
    """Agent 基类 — 统一接口"""

    @property
    @abstractmethod
    def agent_type(self) -> str:
        """Agent 类型标识"""
        pass

    @abstractmethod
    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行任务

        Args:
            task_name: 任务名称（如 analyze_and_decompose, design_architecture 等）
            context: 上下文信息

        Returns:
            执行结果字典
        """
        pass
