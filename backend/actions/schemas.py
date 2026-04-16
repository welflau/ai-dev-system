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
    """代码审查输出（TestAgent 内部）"""
    score: int = 6
    issues: List[str] = []
    suggestions: List[str] = []


class DecomposeOutput(BaseModel):
    """需求拆单输出"""
    complexity: str = "medium"  # simple / medium / complex
    prd_summary: str = ""
    tickets: List[Dict] = []
