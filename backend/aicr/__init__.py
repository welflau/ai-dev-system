"""AICR — AI Code Review 子系统

两场景设计：
  - autoaicr: Agent 完成文件编辑后自动触发，轻量行为约束检查
  - precommit: 用户提交前触发，完整 bug pattern 扫描

入口：
  from aicr import aicr_engine
  result = await aicr_engine.run_autoaicr(diff, file_paths, traits)
"""
from .engine import AICREngine

aicr_engine = AICREngine()

__all__ = ["aicr_engine", "AICREngine"]
