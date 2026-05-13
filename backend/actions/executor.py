"""
Action 执行包装器 — 在 action.run() 前后注入 Pre/Post/Error Hooks

用法（在 BaseAgent.run_action 或 ChatAssistant.execute 中调用）:
    from actions.executor import run_action_with_hooks
    result = await run_action_with_hooks(action, context, hook_meta)
"""
import time
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("actions.executor")


async def run_action_with_hooks(
    action,
    context: Dict[str, Any],
    project_id: Optional[str] = None,
    ticket_id: Optional[str] = None,
    agent_type: Optional[str] = None,
):
    """
    执行 action.run(context)，并在前后触发 Pre/Post/Error Hooks。

    返回 ActionResult（与直接调用 action.run() 完全一致）。
    单个 Hook 失败不影响主流程（HookRegistry.emit 已保证 fail-open）。
    PRE_TOOL_USE Hook 抛错会中断 action 执行（如限流 Hook）。
    """
    from hooks.registry import hook_registry
    from hooks.types import HookEvent, ToolHookContext

    tool_name = getattr(action, "name", type(action).__name__)

    # 1. PRE_TOOL_USE（blocking=True：限流等 Hook 抛错可阻断 Action 执行）
    pre_ctx = ToolHookContext(
        event=HookEvent.PRE_TOOL_USE,
        tool_name=tool_name,
        input=dict(context),
        project_id=project_id,
        ticket_id=ticket_id,
        agent_type=agent_type,
    )
    await hook_registry.emit(pre_ctx, blocking=True)

    start = time.monotonic()
    try:
        result = await action.run(context)
        duration_ms = (time.monotonic() - start) * 1000

        # 2. POST_TOOL_USE
        post_ctx = ToolHookContext(
            event=HookEvent.POST_TOOL_USE,
            tool_name=tool_name,
            input=dict(context),
            output=result,
            duration_ms=duration_ms,
            project_id=project_id,
            ticket_id=ticket_id,
            agent_type=agent_type,
        )
        await hook_registry.emit(post_ctx)

        return result

    except Exception as exc:
        duration_ms = (time.monotonic() - start) * 1000

        # 3. TOOL_ERROR
        err_ctx = ToolHookContext(
            event=HookEvent.TOOL_ERROR,
            tool_name=tool_name,
            input=dict(context),
            error=exc,
            duration_ms=duration_ms,
            project_id=project_id,
            ticket_id=ticket_id,
            agent_type=agent_type,
        )
        await hook_registry.emit(err_ctx)

        raise
