"""
Action 基类 — 所有 Action 的抽象接口
Action 是 Agent 的能力单元：一个 Action 做一件事
Agent (Role) 持有多个 Action，按 SOP 调度执行
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List, Set
from dataclasses import dataclass, field


def _match_traits(match_cfg: Optional[Dict[str, Any]], traits_set: Set[str]) -> bool:
    """跟 skills/loader.py 的 _match_traits 同语义。
    None / 空 → 视为无约束（永远可用）。
    """
    if not match_cfg:
        return True
    all_of = match_cfg.get("all_of") or []
    any_of = match_cfg.get("any_of") or []
    none_of = match_cfg.get("none_of") or []
    if all_of and not all(t in traits_set for t in all_of):
        return False
    if any_of and not any(t in traits_set for t in any_of):
        return False
    if none_of and any(t in traits_set for t in none_of):
        return False
    return True


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
        # 不覆盖 data 中已有的 status（如 acceptance_rejected/testing_failed）
        if "status" not in result:
            result["status"] = "success" if self.success else "error"
        if self.message:
            result["message"] = self.message
        if self.error:
            result["error"] = self.error
        return result


class ActionBase(ABC):
    """Action 抽象基类"""

    # v0.17 trait-first：声明 Action 适用的项目类型
    # None = 对所有项目可用（兼容现有所有 Action）
    # 例：UECompileCheckAction.available_for_traits = {"all_of": ["engine:ue5"]}
    # 校验时机：SOP fragment 编排时 lint（fragment.required_traits 应是此约束的子集）
    available_for_traits: Optional[Dict[str, Any]] = None

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

    @classmethod
    def is_available_for_traits(cls, traits: Optional[List[str]] = None) -> bool:
        """判断本 Action 是否可用于给定 project traits。
        None / 空 规则 → 永远可用；否则按 all_of/any_of/none_of 匹配。
        """
        return _match_traits(cls.available_for_traits, set(traits or []))

    def __repr__(self):
        return f"<Action:{self.name}>"
