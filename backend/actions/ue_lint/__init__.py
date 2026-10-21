"""兼容转调：实现已迁到 ``plugins.ue5.actions.ue_lint``。"""
from plugins.ue5.actions.ue_lint import run_all_rules, Issue

__all__ = ["run_all_rules", "Issue"]
