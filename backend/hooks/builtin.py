"""
内置 Hook 清单：
  - audit_log_hook     : 每次工具调用写 tool_audit_log 表（POST_TOOL_USE + TOOL_ERROR）
  - shell_rate_limit_hook : ShellAction 每 Ticket 调用超 50 次时 raise（PRE_TOOL_USE）
  - failure_library_hook  : 工具报错写 ticket_logs（TOOL_ERROR，用于工单流程追踪）
"""
import logging
from collections import defaultdict

from hooks.types import HookEvent, ToolHookContext

logger = logging.getLogger("hooks.builtin")

# ── 工具 input 的主要参数 key 映射（与 QueryEngine 的 _ARGS_HINT_KEY 保持一致）─
_INPUT_KEY: dict = {
    "search_knowledge": "query", "search_ticket_history": "query",
    "fetch_url": "url", "git_read_file": "path",
    "get_requirement_pipeline": "requirement_id",
    "get_ticket_status": "ticket_id", "get_requirement_logs": "requirement_id",
    "git_log": "branch", "git_switch_branch": "branch",
    "generate_document": "filename", "confirm_save_doc": "filename",
    "confirm_requirement": "title", "confirm_bug": "title",
    "load_skill": "skill_id", "read_local_file": "path", "ue_call": "command",
    "glob": "pattern", "grep": "pattern", "list_directory": "path",
    "shell": "command", "web_search": "query",
    "save_memory": "title", "read_files": "paths",
    "browse_marketplace": "dir_name", "install_project_skill": "dir_name",
    "manage_skill": "action", "dispatch_subtask": "title",
    "git_merge": "target_branch", "git_list_branches": "remote",
    "competitor_analysis": "product_name", "get_build_logs": "ticket_id",
    "ShellAction": "command",
}


def _extract_input_summary(tool_name: str, tool_input: dict) -> str:
    """从 tool_input 提取最重要的一个参数值，限 120 字符"""
    if not tool_input:
        return ""
    key = _INPUT_KEY.get(tool_name)
    if key and key in tool_input:
        val = str(tool_input[key])
        return val[:120]
    # fallback：取第一个非空值
    for v in tool_input.values():
        if v:
            return str(v)[:120]
    return ""


def _extract_output_summary(output) -> str:
    """截取输出的前 200 字符，去掉多余空白"""
    if not output:
        return ""
    text = str(output)
    text = " ".join(text.split())  # 压缩空白
    return text[:200]

# ── Shell 调用计数器（内存，进程级，ticket 粒度）──────────────────────────
_shell_call_counts: dict = defaultdict(int)
_SHELL_LIMIT_PER_TICKET = 50


async def audit_log_hook(ctx: ToolHookContext) -> None:
    """POST_TOOL_USE + TOOL_ERROR：记录详细工具调用到 tool_audit_log，并推 SSE log_added"""
    if ctx.event not in (HookEvent.POST_TOOL_USE, HookEvent.TOOL_ERROR):
        return
    try:
        from database import db
        from utils import now_iso
        import json

        now = now_iso()
        duration_ms = round(ctx.duration_ms or 0, 2)
        success = 0 if ctx.event == HookEvent.TOOL_ERROR else 1

        input_summary  = _extract_input_summary(ctx.tool_name, ctx.input or {})
        output_summary = _extract_output_summary(ctx.output) if success else ""
        error_msg      = str(ctx.error)[:300] if ctx.error else ""

        await db.execute(
            "INSERT INTO tool_audit_log "
            "(tool_name, project_id, ticket_id, agent_type, duration_ms, success, "
            " input_summary, output_summary, error_msg, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ctx.tool_name, ctx.project_id, ctx.ticket_id, ctx.agent_type,
                duration_ms, success,
                input_summary, output_summary, error_msg,
                now,
            ),
        )

        # 实时推送到操作日志面板（仅有 project_id 时推）
        if ctx.project_id:
            try:
                from events import event_manager
                # 构建可读的详情：工具名 + 耗时 + 主参数 + 结果摘要
                parts = [f"{ctx.tool_name} ({int(duration_ms)}ms)"]
                if input_summary:
                    parts.append(f"→ {input_summary[:60]}")
                if error_msg:
                    parts.append(f"❌ {error_msg[:80]}")
                elif output_summary:
                    parts.append(f"✓ {output_summary[:80]}")

                log_entry = {
                    "id":            f"tal-chat-{now}",
                    "agent_type":    ctx.agent_type or "ChatAssistant",
                    "action":        f"chat:{ctx.tool_name}",
                    "detail":        json.dumps({
                        "message":        " | ".join(parts),
                        "input_summary":  input_summary,
                        "output_summary": output_summary,
                        "error_msg":      error_msg,
                        "duration_ms":    duration_ms,
                    }, ensure_ascii=False),
                    "level":         "error" if error_msg else "info",
                    "created_at":    now,
                    "ticket_id":     ctx.ticket_id,
                }
                await event_manager.publish_to_project(
                    ctx.project_id, "log_added", log_entry
                )
            except Exception as sse_err:
                logger.debug("audit_log_hook SSE 推送失败（非致命）: %s", sse_err)

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
