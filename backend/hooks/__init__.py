"""
ADS Hooks 模块 — Pre/Post Tool Hooks 系统

提供统一的工具调用拦截点，支持审计日志、限流、错误追踪等横切逻辑。

用法：
    from hooks.registry import hook_registry
    from hooks.types import HookEvent, ToolHookContext
"""
from hooks.registry import hook_registry
from hooks.types import HookEvent, ToolHookContext

__all__ = ["hook_registry", "HookEvent", "ToolHookContext"]
