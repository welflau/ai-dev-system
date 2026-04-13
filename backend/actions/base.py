"""
Action 基类 — 所有 Action 的抽象接口
Action 是 Agent 的能力单元：一个 Action 做一件事
Agent (Role) 持有多个 Action，按 SOP 调度执行
"""
from abc import ABC, abstractmethod
from typing import Any, Dict
from dataclasses import dataclass, field


@dataclass
class ActionResult:
    """Action 执行结果"""
    success: bool = True
    data: Dict[str, Any] = field(default_factory=dict)
    files: Dict[str, str] = field(default_factory=dict)
    message: str = ""
    error: str = ""

    def to_dict(self) -> Dict:
        result = {**self.data}
        if self.files:
            result["files"] = self.files
        result["status"] = "success" if self.success else "error"
        if self.message:
            result["message"] = self.message
        if self.error:
            result["error"] = self.error
        return result


class ActionBase(ABC):
    """Action 抽象基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """Action 名称（唯一标识）"""
        ...

    @property
    def description(self) -> str:
        """Action 描述"""
        return ""

    @abstractmethod
    async def run(self, context: Dict[str, Any]) -> ActionResult:
        """执行 Action，返回 ActionResult"""
        ...

    def __repr__(self):
        return f"<Action:{self.name}>"
