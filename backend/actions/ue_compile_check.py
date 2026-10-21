"""兼容转调：实现已迁到 ``plugins.ue5.actions.ue_compile_check``。

新代码请用 ``plugins.registry.create_action("ue_compile_check")``。
"""
from plugins.ue5.actions.ue_compile_check import UECompileCheckAction

__all__ = ["UECompileCheckAction"]
