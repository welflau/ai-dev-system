"""
内置 Hook 清单：
  - audit_log_hook     : 每次工具调用写 tool_audit_log 表（POST_TOOL_USE）
  - shell_rate_limit_hook : ShellAction 每 Ticket 调用超 50 次时 raise（PRE_TOOL_USE）
  - failure_library_hook  : 工具报错自动写入 failure_library 表（TOOL_ERROR）
"""
import logging
from collections import defaultdict

from hooks.types import HookEvent, ToolHookContext

logger = logging.getLogger("hooks.builtin")

# ── Shell 调用计数器（内存，进程级，ticket 粒度）──────────────────────────
_shell_call_counts: dict = defaultdict(int)
_SHELL_LIMIT_PER_TICKET = 50


async def audit_log_hook(ctx: ToolHookContext) -> None:
    """POST_TOOL_USE：记录工具调用到 tool_audit_log 表"""
    if ctx.event != HookEvent.POST_TOOL_USE:
        return
    try:
        from database import db
        from utils import now_iso
        await db.execute(
            "INSERT INTO tool_audit_log "
            "(tool_name, project_id, ticket_id, agent_type, duration_ms, success, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                ctx.tool_name,
                ctx.project_id,
                ctx.ticket_id,
                ctx.agent_type,
                round(ctx.duration_ms or 0, 2),
                1,
                now_iso(),
            ),
        )
    except Exception as e:
        logger.warning("audit_log_hook 写库失败: %s", e)


async def shell_rate_limit_hook(ctx: ToolHookContext) -> None:
    """PRE_TOOL_USE：ShellAction 每 Ticket 超 50 次时中断"""
    if ctx.event != HookEvent.PRE_TOOL_USE:
        return
    if ctx.tool_name != "ShellAction":
        return

    key = ctx.ticket_id or "__global__"
    _shell_call_counts[key] += 1
    count = _shell_call_counts[key]

    if count > _SHELL_LIMIT_PER_TICKET:
        raise RuntimeError(
            f"Shell 调用次数超限（ticket={key}, count={count}, limit={_SHELL_LIMIT_PER_TICKET}）"
        )


async def failure_library_hook(ctx: ToolHookContext) -> None:
    """TOOL_ERROR：工具报错自动写入 ticket_logs 表（level=error）"""
    if ctx.event != HookEvent.TOOL_ERROR:
        return
    if not ctx.error:
        return
    try:
        from database import db
        from utils import now_iso
        import json
        import uuid

        error_msg = str(ctx.error)
        detail = json.dumps({
            "tool_name": ctx.tool_name,
            "error": error_msg[:500],
            "duration_ms": round(ctx.duration_ms or 0, 2),
            "agent_type": ctx.agent_type,
        }, ensure_ascii=False)

        project_id = ctx.project_id or "__global__"
        await db.execute(
            "INSERT INTO ticket_logs "
            "(id, ticket_id, project_id, agent_type, action, detail, level, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                ctx.ticket_id,
                project_id,
                ctx.agent_type or "hook",
                f"ToolError:{ctx.tool_name}",
                detail,
                "error",
                now_iso(),
            ),
        )
    except Exception as e:
        logger.warning("failure_library_hook 写库失败: %s", e)


def register_builtin_hooks(registry=None) -> None:
    """向 hook_registry 注册所有内置 Hook（在应用启动时调用）"""
    from hooks.registry import hook_registry as _default_registry
    reg = registry or _default_registry
    reg.register(audit_log_hook)
    reg.register(shell_rate_limit_hook)
    reg.register(failure_library_hook)
    logger.info("内置 Hooks 已注册（audit_log / shell_rate_limit / failure_library）")
