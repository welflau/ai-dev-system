"""兼容转调：实现已迁到 ``plugins.ue5.actions.ue_playtest``。"""
from plugins.ue5.actions.ue_playtest import UEPlaytestAction, _parse_automation_output

__all__ = ["UEPlaytestAction", "_parse_automation_output"]
