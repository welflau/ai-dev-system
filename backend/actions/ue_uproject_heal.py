"""兼容转调：实现已迁到 ``plugins.ue5.actions.ue_uproject_heal``。"""
from plugins.ue5.actions.ue_uproject_heal import (
    UEUprojectHealAction,
    _extract_missing_modules,
)

__all__ = ["UEUprojectHealAction", "_extract_missing_modules"]
