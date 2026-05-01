"""
Action 输出 Schema 定义（Pydantic 模型）
每个 Action 的 LLM 输出都有对应的类型安全 Schema
"""
from pydantic import BaseModel, Field
from typing import Dict, List, Optional


class ArchitectureOutput(BaseModel):
    """架构设计输出"""
    architecture_type: str = ""
    tech_stack: Dict[str, str] = {}
    module_design: List[Dict] = []
    data_flow: str = ""
    estimated_hours: float = 4
    decisions: List[str] = []
    risks: List[str] = []


class DevOutput(BaseModel):
    """代码开发输出"""
    files: Dict[str, str] = {}
    notes: str = ""
    key_implementations: List[str] = []
    estimated_hours: float = 4


class ReviewOutput(BaseModel):
    """验收/审查输出"""
    passed: bool = True
    score: int = 6
    feedback: str = ""
    issues: List[str] = []


class TestReviewOutput(BaseModel):
    """代码审查输出（对抗性三级分类）"""
    score: int = 6
    # 对抗性审查三级分类（每级至少找1个）
    critical_issues: List[str] = []   # 🔴 严重：必须修复才能通过（安全漏洞/逻辑错误/崩溃风险）
    warnings: List[str] = []          # 🟡 警告：建议修复（性能问题/可维护性/边界条件）
    suggestions: List[str] = []       # 🟢 建议：可选优化（代码风格/命名/注释）
    # 向后兼容
    issues: List[str] = []


class DecomposeOutput(BaseModel):
    """需求拆单输出"""
    complexity: str = "medium"  # simple / medium / complex
    prd_summary: str = ""
    tickets: List[Dict] = []
