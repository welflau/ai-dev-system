"""工单的各种记录：操作日志，Agent 思考过程，阶段评论，里程碑通知，执行命令，Agent Memory。

`log` 写 ticket_logs 并推 SSE，是整个编排器里调用最多的函数。`log_agent_thought` 把 Agent 执行的
开始和完成写成 thought_* 或 tool_* 日志，`add_layer_log` 写带 layer 标注的日志。
`write_phase_comment` 和 `post_milestone_comment` 往工单评论区写 Agent 评论和系统通知。
`record_command` 写 ticket_commands 表，`write_memory` 写 Agent Memory。

约定（`orchestration` 包里按职责拆出的模块都一样）：

- 函数体从 `TicketOrchestrator` 的同名方法原样搬来，函数名去掉了前导下划线。改动只有
  `self` 写成 `orch`，以及下面单独列出的几处。
- `TicketOrchestrator` 上保留同名方法，只做转发。这里的函数互相调用、调用别的模块里的
  逻辑都走 `orch.xxx`，测试给实例打的桩才会生效。
- `db` 由转发方法在调用时传入，这里不导入它。测试用
  `monkeypatch.setattr(orchestrator, "db", test_db)` 换库，函数必须拿到同一个对象。
- 状态都放在 `orch` 上，这个模块自己不存状态。
- 函数内的延迟导入保持原样，测试的打桩打在这些源模块上。
"""
import json
import logging
from typing import Dict, Optional

from events import event_manager
from utils import generate_id, now_iso

logger = logging.getLogger("orchestrator")


async def record_command(
    orch, db,
    project_id: str,
    ticket_id: Optional[str],
    requirement_id: Optional[str],
    agent_type: str,
    action: str,
    step_order: int,
    command_type: str,
    command: str,
    status: str = "success",
    duration_ms: int = None,
):
    """记录执行命令到 ticket_commands 表"""
    await db.insert("ticket_commands", {
        "id": generate_id("CMD"),
        "ticket_id": ticket_id,
        "requirement_id": requirement_id,
        "project_id": project_id,
        "agent_type": agent_type,
        "action": action,
        "step_order": step_order,
        "command_type": command_type,
        "command": command,
        "result": None,
        "status": status,
        "duration_ms": duration_ms,
        "created_at": now_iso(),
    })


async def write_memory(
    orch, db,
    project_id: str,
    mem_type: str,
    title: str,
    content: str,
    agent_type: str = "",
    requirement_id: str = None,
    ticket_id: str = None,
    tags: list = None,
) -> None:
    """写入 Agent Memory（决策/交接/项目状态/经验）"""
    try:
        mem_id = generate_id("MEM")
        await db.insert("agent_memory", {
            "id": mem_id,
            "project_id": project_id,
            "type": mem_type,
            "agent_type": agent_type,
            "title": title[:200],
            "content": content,
            "tags": json.dumps(tags or [], ensure_ascii=False),
            "requirement_id": requirement_id,
            "ticket_id": ticket_id,
            "created_at": now_iso(),
        })
    except Exception as e:
        logger.debug("_write_memory 失败（忽略）: %s", e)


# 本地工具动作（不走 LLM，直接执行 shell/CLI）
LOCAL_TOOL_ACTIONS = frozenset({
    "run_engine_compile", "run_engine_compile_check",
    "run_uat", "run_ci_deploy", "playtest",
    "write_html_prototype",  # 轻量本地生成，不走 ReAct LLM
    "run_h5_typecheck",
    "run_h5_playtest",
})


async def log_agent_thought(
    orch,
    project_id: str,
    requirement_id: Optional[str],
    ticket_id: Optional[str],
    agent_name: str,
    action: str,
    phase: str,  # "start" | "done"
    title: str = "",
    result: Optional[Dict] = None,
    elapsed_ms: int = 0,
):
    """把 Agent 执行的开始/完成写入 ticket_logs，让操作日志可见思考过程。

    LLM 推理类动作 → thought_start / thought_done
    本地工具类动作 → tool_start  / tool_done
    """
    try:
        # 区分 LLM 推理 vs 本地工具
        is_local = action in orch.LOCAL_TOOL_ACTIONS
        log_prefix = "tool" if is_local else "thought"

        detail_data: Optional[Dict] = None
        if phase == "start":
            msg = f"[{agent_name}] 开始 {action}"
            if title:
                msg += f"：{title[:60]}"
        else:
            # 从 result 提取产出摘要
            status = (result or {}).get("status", "?")
            files = (result or {}).get("files") or {}
            file_names = [f.split("/")[-1] for f in list(files.keys())]
            file_summary = ", ".join(file_names[:4])
            if len(files) > 4:
                file_summary += f" 等 {len(files)} 个文件"

            notes = ""
            dev_r = (result or {}).get("dev_result") or {}
            if isinstance(dev_r, dict):
                notes = str(dev_r.get("notes") or "")[:60]
            elif isinstance(result, dict):
                notes = str(result.get("notes") or "")[:60]

            parts = [f"[{agent_name}] 完成 {action} ({elapsed_ms}ms) status={status}"]
            if file_summary:
                parts.append(f"产出: {file_summary}")
            if notes:
                parts.append(f"备注: {notes}")
            msg = " | ".join(parts)

            # 结构化文件列表，供前端渲染文件标签与图片缩略图
            detail_data = {}
            media_dict = (result or {}).get("_media_files") or {}
            media_paths = list(media_dict.keys()) if isinstance(media_dict, dict) else list((result or {}).get("media_paths") or [])
            all_paths = list(files.keys()) + [p for p in media_paths if p not in files]
            all_names = [p.replace("\\", "/").split("/")[-1] for p in all_paths]
            shots = list((result or {}).get("screenshots") or [])
            st_shots = ((result or {}).get("self_test") or {}).get("screenshots") or []
            tr_shots = ((result or {}).get("test_result") or {}).get("screenshots") or []
            for s in (st_shots + tr_shots):
                u = s.get("url") if isinstance(s, dict) else s
                if u and u not in shots:
                    shots.append(u)
            if all_paths or shots:
                detail_data = {
                    "files": all_names[:16],
                    "file_paths": all_paths[:16],
                    "file_count": len(all_paths),
                    "screenshots": shots[:10],
                    "media_paths": media_paths[:16],
                    "elapsed_ms": elapsed_ms,
                    "status": status,
                }

            # 本地工具类：把关键输出也存入 detail，供展开查看 + AI 上下文
            if is_local and isinstance(result, dict):
                # UBT 编译：errors / raw_tail
                errors = result.get("errors") or []
                raw_tail = (result.get("raw_tail") or "")[:4000]
                command = result.get("command", "")
                if errors or raw_tail:
                    detail_data["output_summary"] = raw_tail[-2000:] if raw_tail else ""
                    detail_data["errors_summary"] = json.dumps(
                        [{"msg": e.get("message", ""), "file": e.get("file", ""), "line": e.get("line", "")}
                         for e in errors[:10]],
                        ensure_ascii=False,
                    )
                    detail_data["command"] = command[:300]
                # Playtest：直接用 message（已含 pass/fail 信息）
                playtest_msg = result.get("message") or result.get("msg", "")
                if playtest_msg and not detail_data.get("output_summary"):
                    detail_data["output_summary"] = str(playtest_msg)[:2000]

        await orch._log(
            project_id, requirement_id, ticket_id,
            agent_name, f"{log_prefix}_{phase}",
            None, None,
            msg, "info",
            detail_data=detail_data,
        )
    except Exception as e:
        logger.debug("_log_agent_thought 失败（忽略）: %s", e)


async def log(
    orch, db,
    project_id: str,
    requirement_id: Optional[str],
    ticket_id: Optional[str],
    agent_type: str,
    action: str,
    from_status: Optional[str],
    to_status: Optional[str],
    message: str,
    level: str = "info",
    detail_data: Optional[Dict] = None,
):
    """记录日志并推送 SSE 实时事件"""
    log_id = generate_id("LOG")
    created_at = now_iso()

    # 构建丰富的 detail JSON
    detail_obj = {"message": message}
    if detail_data:
        detail_obj.update(detail_data)
    detail_json = json.dumps(detail_obj, ensure_ascii=False)

    await db.insert("ticket_logs", {
        "id": log_id,
        "ticket_id": ticket_id,
        "subtask_id": None,
        "requirement_id": requirement_id,
        "project_id": project_id,
        "agent_type": agent_type,
        "action": action,
        "from_status": from_status,
        "to_status": to_status,
        "detail": detail_json,
        "level": level,
        "created_at": created_at,
    })

    # 实时推送日志到前端底部面板
    await event_manager.publish_to_project(
        project_id,
        "log_added",
        {
            "id": log_id,
            "ticket_id": ticket_id,
            "requirement_id": requirement_id,
            "agent_type": agent_type,
            "action": action,
            "from_status": from_status,
            "to_status": to_status,
            "detail": detail_json,
            "level": level,
            "created_at": created_at,
        },
    )

    # Session Transcript 镜像（backend/logs/session_<req_id>/）
    try:
        from session_logger import session_logger
        await session_logger.log_event(
            requirement_id=requirement_id,
            kind="log",
            agent=agent_type,
            action=action,
            ticket_id=ticket_id,
            from_status=from_status,
            to_status=to_status,
            message=message,
            detail=detail_data,
        )
    except Exception as e:
        logger.warning("SessionLogger.log_event 失败: %s", e)


async def write_phase_comment(
    orch, db,
    project_id: str,
    ticket_id: str,
    agent_type: str,
    summary: str,
    phase: Optional[str] = None,
    reply_to_comment_id: Optional[str] = None,
):
    """Agent 阶段完成后写一条 agent 类型评论，供时间轴展示和下游 Agent 感知"""
    try:
        comment_id = "CMT-" + generate_id()
        await db.insert("ticket_comments", {
            "id": comment_id,
            "ticket_id": ticket_id,
            "project_id": project_id,
            "author": agent_type,
            "author_type": "agent",
            "content": summary,
            "phase": phase,
            "reply_to_comment_id": reply_to_comment_id,
            "created_at": now_iso(),
        })
        await event_manager.publish_to_project(project_id, "comment_added", {
            "ticket_id": ticket_id,
            "comment_id": comment_id,
            "author_type": "agent",
            "author": agent_type,
            "content": summary,
            "phase": phase,
        })
    except Exception as e:
        logger.debug("_write_phase_comment 失败（忽略）: %s", e)


async def post_milestone_comment(
    orch, db,
    ticket_id: str,
    project_id: str,
    message: str,
    level: str = "info",
):
    """发送里程碑系统通知到工单评论区（SSE 实时推送 + DB 持久化）"""
    try:
        comment_id = "CMT-" + generate_id()
        await db.insert("ticket_comments", {
            "id": comment_id,
            "ticket_id": ticket_id,
            "project_id": project_id,
            "author": "System",
            "author_type": "system",
            "content": message,
            "phase": "milestone",
            "created_at": now_iso(),
        })
        await event_manager.publish_to_project(project_id, "comment_added", {
            "ticket_id": ticket_id,
            "comment_id": comment_id,
            "author_type": "system",
            "author": "System",
            "content": message,
            "level": level,
        })
    except Exception as e:
        logger.debug("post_milestone_comment 失败（忽略）: %s", e)


async def add_layer_log(
    orch, db,
    ticket_id: str,
    project_id: str,
    action: str,
    layer: str,
    detail: dict,
    level: str = "info",
):
    """写带 layer 标注的 ticket_log（三层时间轴显示用）"""
    try:
        import json as _json
        log_id = generate_id("LOG")
        await db.insert("ticket_logs", {
            "id": log_id,
            "ticket_id": ticket_id,
            "project_id": project_id,
            "agent_type": layer,
            "action": action,
            "detail": _json.dumps(detail, ensure_ascii=False),
            "level": level,
            "layer": layer,
            "created_at": now_iso(),
        })
    except Exception as e:
        logger.debug("_add_layer_log 失败（忽略）: %s", e)
