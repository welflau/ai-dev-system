"""
AI 自动开发系统 - Agent 基类 (Role)
Agent = Role + Actions + State Machine
移植 MetaGPT 的 Role 状态机：支持 SINGLE / BY_ORDER / REACT 三种执行模式
"""
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Type, Set
import logging

logger = logging.getLogger("agent.base")


class ReactMode(str, Enum):
    """Agent 执行模式（移植自 MetaGPT RoleReactMode）"""
    SINGLE = "single"         # 单步执行（orchestrator 指定 action）
    BY_ORDER = "by_order"     # 按顺序执行所有 Action
    REACT = "react"           # LLM 动态选择下一步（未来扩展）


class BaseAgent(ABC):
    """Agent 基类 (Role) — 持有 Action 列表 + 状态机 + Watch 过滤

    三种执行模式:
    - SINGLE: orchestrator 指定执行哪个 action（默认，向后兼容）
    - BY_ORDER: 按 action_classes 顺序依次执行所有 action
    - REACT: LLM 动态决定下一步（预留接口）
    """

    # 子类声明
    action_classes: List[Type] = []
    react_mode: ReactMode = ReactMode.SINGLE
    watch_actions: Set[str] = set()  # 关心的上游 Action（用于消息过滤）
    max_react_loop: int = 5

    def __init__(self):
        self._actions = {}
        for cls in self.action_classes:
            action = cls()
            self._actions[action.name] = action
        self._state: int = -1  # 当前 Action 索引（BY_ORDER 模式用）

    @property
    @abstractmethod
    def agent_type(self) -> str:
        pass

    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """根据 react_mode 分发执行"""
        if self.react_mode == ReactMode.SINGLE:
            # 单步：orchestrator 指定 action
            if self.has_action(task_name):
                return await self.run_action(task_name, context)
            # 兼容旧模式：子类自己实现 execute
            return await self._execute_legacy(task_name, context)

        elif self.react_mode == ReactMode.BY_ORDER:
            return await self._react_by_order(task_name, context)

        elif self.react_mode == ReactMode.REACT:
            return await self._react_with_think(task_name, context)

        return {"status": "error", "message": f"未知 react_mode: {self.react_mode}"}

    async def _execute_legacy(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """旧模式兼容：子类没有用 Action 组合时的 fallback"""
        return {"status": "error", "message": f"Agent {self.agent_type} 没有 Action: {task_name}"}

    async def run_action(self, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """执行指定 Action"""
        action = self._actions.get(action_name)
        if not action:
            return {"status": "error", "message": f"Agent {self.agent_type} 没有 Action: {action_name}"}
        result = await action.run(context)
        return result.to_dict()

    async def _react_by_order(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """BY_ORDER 模式：按顺序执行所有 Action，前一步输出注入后一步"""
        result = {}
        action_names = list(self._actions.keys())
        logger.info("🔄 %s BY_ORDER: %s", self.agent_type, " → ".join(action_names))

        for i, action_name in enumerate(action_names):
            action = self._actions[action_name]
            logger.info("  [%d/%d] %s.%s", i + 1, len(action_names), self.agent_type, action_name)

            action_result = await action.run(context)
            step_dict = action_result.to_dict()

            # 合并结果
            if action_result.files:
                result.setdefault("files", {}).update(action_result.files)
            result.update(step_dict)

            # 前一步输出注入后一步上下文
            context.update(action_result.data)
            if action_result.files:
                context["_files"] = {**context.get("_files", {}), **action_result.files}

        result["status"] = result.get("status", "success")
        return result

    async def _react_with_think(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """REACT 模式：LLM 动态选择下一步 Action（预留接口）"""
        # 简化版：先按顺序执行，后续可接入 LLM 决策
        return await self._react_by_order(task_name, context)

    # ==================== 查询接口 ====================

    def list_actions(self) -> List[str]:
        return list(self._actions.keys())

    def has_action(self, name: str) -> bool:
        return name in self._actions

    def is_watch(self, cause_by: str) -> bool:
        """检查是否关心某个 Action 的输出"""
        if not self.watch_actions:
            return True  # 未声明 watch = 关心所有
        return cause_by in self.watch_actions

    @property
    def important_memory(self):
        """获取自己关心的记忆（需要外部设置 _memory）"""
        mem = getattr(self, "_memory", None)
        if mem and self.watch_actions:
            return mem.get_by_actions(self.watch_actions)
        return []
