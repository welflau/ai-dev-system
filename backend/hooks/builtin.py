"""
内置 Hook 清单：
  - audit_log_hook     : 每次工具调用写 tool_audit_log 表（POST_TOOL_USE + TOOL_ERROR）
  - shell_rate_limit_hook : shell 每 Ticket 调用超 50 次时 raise（PRE_TOOL_USE）
  - failure_library_hook  : 工具报错写 ticket_logs（TOOL_ERROR，用于工单流程追踪）
  - command_record_hook   : 真实 CLI/shell 命令写 ticket_command_log + 时间轴（可重放）
"""
import logging
import time
from datetime import datetime, timedelta
from collections import defaultdict, deque

from hooks.types import HookEvent, ToolHookContext

logger = logging.getLogger("hooks.builtin")


def _iso_before(ms: float, base_iso: str) -> str:
    """base_iso 往前推 ms 毫秒，返回 ISO 字符串（用于补 started_at）。"""
    try:
        base = datetime.fromisoformat(base_iso)
        delta = max(float(ms or 0), 0.0)
        return (base - timedelta(milliseconds=delta)).isoformat()
    except Exception:
        return base_iso

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

# ── Shell 调用计数器（内存，进程级）──────────────────────────────────────
# 工单粒度用「终身计数」：一张工单跑满 50 次 shell 就是跑飞了，这正是要拦的。
# 但**没有 ticket_id 的调用**（全局 AI 助手对话）不能用终身计数 —— 后端进程
# 能活好几天，攒够 50 次之后所有对话里的 shell 就被永久锁死了。那种场景要的是
# 「短时间内爆发」而不是「累计多少次」，所以走滑动时间窗。
_shell_call_counts: dict = defaultdict(int)          # ticket_id → 终身次数
_shell_global_calls: deque = deque()                 # 无工单调用的时间戳（滑动窗）
_SHELL_LIMIT_PER_TICKET = 50
_SHELL_GLOBAL_LIMIT = 50                             # 每 _SHELL_GLOBAL_WINDOW 秒
_SHELL_GLOBAL_WINDOW = 3600.0
_SHELL_COUNTS_MAX_KEYS = 2000                        # 防 dict 无上限增长


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

        # turn_id 直接从 _llm_ctx 取：工具在触发它的那次 LLM 循环的同一个
        # 协程里跑，contextvars 看得见。hook context 里不另加字段，免得每个
        # 调用点都要记着传。
        try:
            from llm_client import _llm_ctx
            turn_id = _llm_ctx.turn_id
        except Exception:
            turn_id = None

        await db.execute(
            "INSERT INTO tool_audit_log "
            "(tool_name, project_id, ticket_id, agent_type, duration_ms, success, "
            " input_summary, output_summary, error_msg, created_at, turn_id, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ctx.tool_name, ctx.project_id, ctx.ticket_id, ctx.agent_type,
                duration_ms, success,
                input_summary, output_summary, error_msg,
                now, turn_id,
                _iso_before(duration_ms, now),
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
    """PRE_TOOL_USE：shell 调用超限时中断。

    历史上这里判的是 `ctx.tool_name != "ShellAction"`，而注册名是 `shell`
    （`ShellAction.name` 返回 "shell"，`skills/runner.py` 也是按 `actions["shell"]`
    注册的）—— 类名和工具名不是一回事，于是**这个限流从来没生效过**。
    而且它挂在 PRE_TOOL_USE 上，SkillRunner 那条路以前压根不发 hook，
    等于双重失效：名字对不上 + 事件根本不来。

    `GenericCLIAction` 不在限流范围：它的命令主干写死在 skill 的 command_template
    里，LLM 只能填白名单槽，跑飞的风险和「LLM 自由拼 shell 字符串」不是一个量级。
    """
    if ctx.event != HookEvent.PRE_TOOL_USE:
        return
    if ctx.tool_name != "shell":
        return

    if ctx.ticket_id:
        # 工单粒度：终身计数。一张工单跑满 50 次 shell 就是跑飞了。
        if (len(_shell_call_counts) >= _SHELL_COUNTS_MAX_KEYS
                and ctx.ticket_id not in _shell_call_counts):
            _shell_call_counts.clear()      # 长跑进程兜底，别让 dict 无限涨
        _shell_call_counts[ctx.ticket_id] += 1
        count = _shell_call_counts[ctx.ticket_id]
        if count > _SHELL_LIMIT_PER_TICKET:
            logger.warning("🛑 shell 限流：ticket=%s count=%d", ctx.ticket_id, count)
            raise RuntimeError(
                f"Shell 调用次数超限（ticket={ctx.ticket_id}, "
                f"count={count}, limit={_SHELL_LIMIT_PER_TICKET}）"
            )
        return

    # 无工单（全局 AI 助手对话）：滑动时间窗，不能用终身计数 ——
    # 后端能连跑几天，攒够 50 次之后所有对话里的 shell 就被永久锁死了。
    now = time.monotonic()
    cutoff = now - _SHELL_GLOBAL_WINDOW
    while _shell_global_calls and _shell_global_calls[0] < cutoff:
        _shell_global_calls.popleft()
    _shell_global_calls.append(now)
    if len(_shell_global_calls) > _SHELL_GLOBAL_LIMIT:
        logger.warning("🛑 shell 限流：无工单调用 %d 次/%.0fs",
                       len(_shell_global_calls), _SHELL_GLOBAL_WINDOW)
        raise RuntimeError(
            f"Shell 调用过于频繁（{len(_shell_global_calls)} 次/"
            f"{int(_SHELL_GLOBAL_WINDOW / 60)} 分钟，上限 {_SHELL_GLOBAL_LIMIT}）"
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

        try:
            from llm_client import _llm_ctx
            turn_id = _llm_ctx.turn_id
        except Exception:
            turn_id = None

        await db.execute(
            "INSERT INTO tool_audit_log "
            "(tool_name, project_id, ticket_id, agent_type, duration_ms, success, "
            " input_summary, output_summary, error_msg, created_at, turn_id, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "query_engine:done",
                ctx.project_id, ctx.ticket_id, ctx.agent_type,
                round(elapsed_s * 1000, 1), 1,
                input_summary, output_summary, "",
                now, turn_id,
                _iso_before(elapsed_s * 1000, now),
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
    diagnosis = (ctx.input or {}).get("diagnosis") if isinstance(ctx.input, dict) else None
    if not isinstance(diagnosis, dict):
        diagnosis = None

    # 构建友好提示：有诊断时给「下一步 + 按钮」，不要让用户自己猜
    actions = []
    if diagnosis:
        title = diagnosis.get("title") or "⚠️ Git 操作失败"
        body = diagnosis.get("summary") or error_msg[:200]
        next_step = diagnosis.get("next_step") or ""
        if next_step:
            body += f"\n\n下一步：{next_step}"
        detail = diagnosis.get("detail") or ""
        if detail:
            body += f"\n\n技术细节：{detail}"
        actions = diagnosis.get("actions") or []
    elif tool.startswith("git:push"):
        title = "⚠️ Git Push 失败"
        body  = f"代码已提交但未推送到远端仓库。\n原因：{error_msg[:200]}"
        actions = [
            {"id": "retry", "label": "重试推送", "primary": True},
            {"id": "create_github", "label": "创建 GitHub 仓库并推送"},
            {"id": "open_git", "label": "打开仓库设置"},
        ]
        body += "\n\n下一步：先点「重试推送」；若仓库不存在，点「创建 GitHub 仓库并推送」。"
    elif tool.startswith("git:commit"):
        title = "⚠️ Git Commit 失败"
        body  = f"文件写入失败，代码未提交。\n原因：{error_msg[:200]}"
    else:
        title = f"⚠️ {agent_type} 执行失败"
        body  = error_msg[:300]

    if ticket_id:
        body += f"\n\n工单 ID：`{ticket_id[-8:]}`"

    knowledge_hits = []
    try:
        from actions.chat.search_knowledge import compact_knowledge_hits, lookup_error_playbook
        extra = ""
        if diagnosis:
            extra = " ".join(
                str(x) for x in (
                    diagnosis.get("reason"),
                    diagnosis.get("title"),
                ) if x
            )
        knowledge_hits = compact_knowledge_hits(await lookup_error_playbook(
            error_msg,
            project_id,
            tool_name=tool,
            extra=extra,
        ))
        if knowledge_hits:
            cites = " · ".join(h.get("display_name") or "" for h in knowledge_hits if h.get("display_name"))
            if cites:
                body += f"\n\n知识库：{cites}"
    except Exception as e:
        logger.debug("chat_alert_hook 知识库检索失败: %s", e)
        knowledge_hits = []

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
            "actions":    actions,
            "knowledge_hits": knowledge_hits,
            "created_at": now_iso(),
        })
        # 持久化到 chat_messages，刷新后可还原
        try:
            from api.chat import _save_chat_message
            from database import db as _db
            # 找该项目最近的 session（alert 写入当前活跃会话）
            row = await _db.fetch_one(
                "SELECT id FROM chat_sessions WHERE project_id=? AND last_status NOT IN ('poisoned') "
                "ORDER BY updated_at DESC LIMIT 1",
                (project_id,),
            )
            if row:
                await _save_chat_message(
                    project_id, "assistant", "",  # content 为空，由 action card 展示
                    action={"type": "error_alert", "title": title, "body": body,
                            "tool": tool, "ticket_id": ticket_id or "",
                            "agent": agent_type, "actions": actions,
                            "knowledge_hits": knowledge_hits},
                    session_id=row["id"],
                )
        except Exception as _pe:
            logger.debug("chat_alert_hook 持久化失败: %s", _pe)
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


async def command_record_hook(ctx: ToolHookContext) -> None:
    """POST_TOOL_USE + TOOL_ERROR：把 Action offer 的真实命令记录落库 + 写一条时间轴。

    刻意**不并进 `audit_log_hook`**：那张表是**计数器**（`output_summary` 只留
    200 字符，5989 行全靠它统计调用次数/耗时），本 hook 要的是**可重放的控制台**
    （真 argv、cwd、完整输出）。两者写入量、保留策略、读者都不同，混一个函数里
    迟早互相妥协——一个想留全量，一个想省空间。

    没有 offer 的工具（绝大多数 Action 不跑命令）直接返回，不留骨架行：
    `tool_audit_log` 已经在记「谁调了什么工具」，这里再记一遍纯属重复。
    """
    if ctx.event not in (HookEvent.POST_TOOL_USE, HookEvent.TOOL_ERROR):
        return
    try:
        from command_log import take_command_record, record_command
        rec = take_command_record()
        if not rec:
            return

        from database import db
        from utils import generate_id, now_iso
        import json
        import uuid

        # 先生成 record_id 再写日志：两条记录在同一次调用里配好对，
        # `ticket_command_log.log_id` ↔ `ticket_logs.detail.task_id` 天然对齐，
        # 不必像 `_annotate_chat_anchors`（api/tickets.py:1468）那样按 ≤3s 时间差猜。
        record_id = generate_id("TCMD")
        log_id = str(uuid.uuid4())
        now = now_iso()

        command = str(rec.get("command") or "")
        tool = str(rec.get("tool") or ctx.tool_name or "shell")
        status = str(rec.get("status") or "success")
        exit_code = rec.get("exit_code")
        duration_ms = rec.get("duration_ms")
        if duration_ms is None and ctx.duration_ms is not None:
            duration_ms = int(ctx.duration_ms)

        if status == "timeout":
            head = f"⏱ {tool} 超时"
        elif status == "error":
            head = f"❌ {tool} exit={exit_code}"
        else:
            head = f"📟 {tool}"
        message = f"{head} · {command[:100]}"

        detail = json.dumps({
            "message": message,
            "tool": tool,
            "command": command,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "cwd": rec.get("cwd") or "",
            "status": status,
            "task_id": record_id,      # ← 前端据此点开后台记录
        }, ensure_ascii=False)

        # ticket_logs 有一堆外键（project_id NOT NULL REFERENCES projects(id)）。
        # 全局聊天没有 project_id 时这条会失败——但**命令记录本身不能跟着陪葬**，
        # 所以分开 try：日志写不进就退化成 log_id='' 的孤立记录，至少输出还在。
        log_ok = False
        try:
            await db.execute(
                "INSERT INTO ticket_logs "
                "(id, ticket_id, project_id, agent_type, action, detail, level, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    log_id, ctx.ticket_id, ctx.project_id or "__global__",
                    ctx.agent_type or rec.get("agent_type") or "hook",
                    "command_run", detail,
                    "error" if status != "success" else "info",
                    now,
                ),
            )
            log_ok = True
        except Exception as log_err:
            logger.debug("command_run 时间轴写入失败（记录仍会保留）: %s", log_err)

        await record_command(
            record_id=record_id, log_id=log_id if log_ok else "",
            source=str(rec.get("source") or "action"),
            tool=tool, command=command, cwd=rec.get("cwd") or "",
            exit_code=exit_code, status=status, duration_ms=duration_ms,
            output=str(rec.get("output") or ""),
            noise=bool(rec.get("noise")),
            ticket_id=ctx.ticket_id or "", project_id=ctx.project_id or "",
            requirement_id=str(rec.get("requirement_id") or ""),
            agent_type=ctx.agent_type or "",
        )

        # 实时推时间轴。这些都是**短命令**（git 单条 <1s，CLI 一次性 communicate
        # 返回），没有流式行可推，为不存在的流建新事件族不划算——复用 log_added，
        # 前端 appendLogEntry 已订阅。而且这是结束后落的一行，不是流式追加，
        # 后端崩了也不会丢 buffer（比现有 cli_task 的纯内存路径更耐崩）。
        if ctx.project_id and log_ok:
            try:
                from events import event_manager
                await event_manager.publish_to_project(ctx.project_id, "log_added", {
                    "id": log_id,
                    "agent_type": ctx.agent_type or "System",
                    "action": "command_run",
                    "detail": detail,
                    "level": "error" if status != "success" else "info",
                    "created_at": now,
                    "ticket_id": ctx.ticket_id,
                })
            except Exception as sse_err:
                logger.debug("command_record_hook SSE 推送失败（非致命）: %s", sse_err)

    except Exception as e:
        logger.warning("command_record_hook 失败: %s", e)


def register_builtin_hooks(registry=None) -> None:
    """向 hook_registry 注册所有内置 Hook（在应用启动时调用）"""
    from hooks.registry import hook_registry as _default_registry
    reg = registry or _default_registry
    reg.register(audit_log_hook)
    reg.register(shell_rate_limit_hook)
    reg.register(failure_library_hook)
    reg.register(chat_alert_hook)
    reg.register(nudge_hook)
    reg.register(command_record_hook)
    logger.info("内置 Hooks 已注册（audit_log / shell_rate_limit / failure_library / "
                "chat_alert / nudge / command_record）")
