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
    """POST_TOOL_USE + TOOL_ERROR + SESSION_END：记录到 tool_audit_log，并推 SSE log_added"""
    if ctx.event not in (HookEvent.POST_TOOL_USE, HookEvent.TOOL_ERROR, HookEvent.SESSION_END):
        return

    if ctx.event == HookEvent.SESSION_END:
        await _handle_session_end(ctx)
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
                if ctx.project_id:
                    # 項目聊天：推到項目 SSE 頻道
                    await event_manager.publish_to_project(
                        ctx.project_id, "log_added", log_entry
                    )
                else:
                    # 全局聊天（project_id=None）：推到 global 頻道
                    await event_manager.publish("global", "log_added", log_entry)
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


async def _handle_session_end(ctx: ToolHookContext) -> None:
    """SESSION_END：记录 QueryEngine 运行统计到 tool_audit_log"""
    try:
        from database import db
        from utils import now_iso
        import json

        inp    = ctx.input or {}
        rounds = inp.get("rounds", 0)
        tokens = inp.get("total_tokens", 0)
        elapsed_s = inp.get("elapsed_s", 0)
        reason = inp.get("reason", "done")
        max_tokens = inp.get("max_tokens", 0)

        token_pct = round(tokens / max_tokens * 100, 1) if max_tokens else 0
        now = now_iso()

        input_summary  = f"rounds:{rounds} tokens:{tokens}({token_pct}%) elapsed:{elapsed_s}s"
        output_summary = f"reason:{reason}"

        await db.execute(
            "INSERT INTO tool_audit_log "
            "(tool_name, project_id, ticket_id, agent_type, duration_ms, success, "
            " input_summary, output_summary, error_msg, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "query_engine:done",
                ctx.project_id, ctx.ticket_id, ctx.agent_type,
                round(elapsed_s * 1000, 1), 1,
                input_summary, output_summary, "",
                now,
            ),
        )

        # SSE 推送到日志面板（项目聊天推项目频道，全局聊天推 global 频道）
        try:
            from events import event_manager
            level = "warn" if reason != "done" else "info"
            log_entry = {
                "id":         f"qe-done-{now}",
                "agent_type": ctx.agent_type or "ChatAssistant",
                "action":     "query_engine:done",
                "detail":     json.dumps({
                    "message":       f"QueryEngine 完成 | {input_summary}",
                    "input_summary": input_summary,
                    "output_summary": output_summary,
                    "duration_ms":   round(elapsed_s * 1000, 1),
                }, ensure_ascii=False),
                "level":      level,
                "created_at": now,
                "ticket_id":  ctx.ticket_id,
            }
            if ctx.project_id:
                await event_manager.publish_to_project(ctx.project_id, "log_added", log_entry)
            else:
                await event_manager.publish("global", "log_added", log_entry)
        except Exception:
            pass
    except Exception as e:
        logger.warning("_handle_session_end 写库失败: %s", e)


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


async def chat_alert_hook(ctx: ToolHookContext) -> None:
    """TOOL_ERROR：向 AI 聊天面板推送 agent_alert 通知，让用户实时感知关键错误。

    只处理关键错误（git 操作失败、agent 执行报错），过滤掉普通工具调用失败。
    """
    if ctx.event != HookEvent.TOOL_ERROR:
        return

    tool = ctx.tool_name or ""
    # 只关心 git 操作失败和 agent 执行失败（chat 工具错误由用户直接看到）
    is_critical = tool.startswith("git:") or tool.startswith("agent:")
    if not is_critical:
        return

    project_id = ctx.project_id
    if not project_id:
        return

    error_msg = str(ctx.error) if ctx.error else f"工具 {tool} 执行失败（无详细错误信息）"
    ticket_id  = ctx.ticket_id
    agent_type = ctx.agent_type or "System"

    # 构建友好提示
    if tool.startswith("git:push"):
        title = "⚠️ Git Push 失败"
        body  = f"代码已提交但未推送到远端仓库。\n原因：{error_msg[:200]}"
    elif tool.startswith("git:commit"):
        title = "⚠️ Git Commit 失败"
        body  = f"文件写入失败，代码未提交。\n原因：{error_msg[:200]}"
    else:
        title = f"⚠️ {agent_type} 执行失败"
        body  = error_msg[:300]

    if ticket_id:
        body += f"\n\n工单 ID：`{ticket_id[-8:]}`，可发送「查看工单状态」了解详情。"

    try:
        from events import event_manager
        from utils import now_iso
        await event_manager.publish_to_project(project_id, "agent_alert", {
            "title":      title,
            "body":       body,
            "level":      "error",
            "tool":       tool,
            "ticket_id":  ticket_id,
            "agent_type": agent_type,
            "created_at": now_iso(),
        })
    except Exception as e:
        logger.debug("chat_alert_hook 推送失败: %s", e)


async def nudge_hook(ctx: ToolHookContext) -> None:
    """ASSISTANT_STOP：AI 回复完成后，若项目有未完成需求则推 SSE nudge 消息给聊天面板。
    让用户随时看到"还有 N 个需求待处理"，避免忘记跟进。
    只在项目聊天（project_id 有值）且有未完成需求时触发。
    """
    if ctx.event != HookEvent.ASSISTANT_STOP:
        return
    if not ctx.project_id:
        return
    try:
        from database import db
        from utils import now_iso
        import json

        # 查询未完成需求数
        row = await db.fetch_one(
            "SELECT COUNT(*) as cnt FROM requirements "
            "WHERE project_id=? AND status NOT IN ('completed','cancelled')",
            (ctx.project_id,),
        )
        pending_count = row["cnt"] if row else 0
        if pending_count == 0:
            return

        # 推 SSE nudge 事件（前端显示柔性提示，不阻塞对话）
        from events import event_manager
        await event_manager.publish_to_project(ctx.project_id, "assistant_nudge", {
            "message": f"项目还有 {pending_count} 个需求正在进行中，输入「查看进度」了解详情。",
            "pending_requirements": pending_count,
            "created_at": now_iso(),
        })
    except Exception as e:
        logger.debug("nudge_hook 失败（非致命）: %s", e)


def register_builtin_hooks(registry=None) -> None:
    """向 hook_registry 注册所有内置 Hook（在应用启动时调用）"""
    from hooks.registry import hook_registry as _default_registry
    reg = registry or _default_registry
    reg.register(audit_log_hook)
    reg.register(shell_rate_limit_hook)
    reg.register(failure_library_hook)
    reg.register(chat_alert_hook)
    reg.register(nudge_hook)
    logger.info("内置 Hooks 已注册（audit_log / shell_rate_limit / failure_library / chat_alert / nudge）")
