"""兼容转调：实现已迁到 ``plugins.ue5.actions.instantiate_ue_template``。"""
from plugins.ue5.actions.instantiate_ue_template import (
    InstantiateUETemplateAction,
    pick_template_by_traits,
)

__all__ = ["InstantiateUETemplateAction", "pick_template_by_traits"]
