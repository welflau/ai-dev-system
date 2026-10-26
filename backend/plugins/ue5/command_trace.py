"""UE Action 的命令落库与时间轴步骤。

UBT / Automation / RunUAT 由 Action 直接 Popen，不经过 SkillRunner 的
POST_TOOL_USE。这里按 H5 试玩同一方式写入 `ticket_logs` 与 `ticket_command_log`。
写库失败只记 debug，不影响编译或试玩本身的结果。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("plugins.ue5.command_trace")


def _as_command(command: Any) -> str:
    if isinstance(command, (list, tuple)):
        return " ".join(str(part) for part in command)
    return str(command or "")


async def emit_ue_step(
    context: Optional[Dict[str, Any]],
    step_name: str,
    phase: str,
    *,
    duration_ms: int = 0,
    reason: str = "",
    task_id: str = "",
) -> str:
    """写 `skill_step_start` / `skill_step_done` / `skill_step_error`。"""
    ticket_id = str((context or {}).get("ticket_id") or "")
    project_id = str((context or {}).get("project_id") or "")
    if not ticket_id or phase not in ("start", "done", "error"):
        return ""
    try:
        from database import db
        from events import event_manager
        from utils import generate_id, now_iso

        action = f"skill_step_{phase}"
        log_id = generate_id("LOG")
        created_at = now_iso()
        if phase == "start":
            message = f"{step_name} · 开始"
            level = "info"
        elif phase == "done":
            dur = f" ({int(duration_ms)}ms)" if duration_ms else ""
            message = f"{step_name} · 完成{dur}"
            level = "info"
        else:
            dur = f" ({int(duration_ms)}ms)" if duration_ms else ""
            message = f"{step_name} · 失败{dur}"
            if reason:
                message += f" — {reason[:120]}"
            level = "error"
        detail_obj: Dict[str, Any] = {
            "message": message,
            "step_name": step_name,
            "phase": phase,
            "duration_ms": duration_ms,
            "reason": reason,
        }
        if task_id:
            detail_obj["task_id"] = task_id
        detail_json = json.dumps(detail_obj, ensure_ascii=False)
        await db.execute(
            "INSERT INTO ticket_logs "
            "(id, ticket_id, requirement_id, project_id, agent_type, action, detail, level, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                log_id,
                ticket_id,
                (context or {}).get("requirement_id"),
                project_id or "__global__",
                str((context or {}).get("agent_type") or "DevAgent"),
                action,
                detail_json,
                level,
                created_at,
            ),
        )
        if project_id:
            await event_manager.publish_to_project(project_id, "log_added", {
                "id": log_id,
                "ticket_id": ticket_id,
                "agent_type": str((context or {}).get("agent_type") or "DevAgent"),
                "action": action,
                "detail": detail_json,
                "level": level,
                "created_at": created_at,
                "_task_ref": task_id or "",
            })
        return log_id
    except Exception as exc:
        logger.debug("UE 步骤打点失败（非致命）: %s", exc)
        return ""


async def trace_ue_command(
    *,
    source: str,
    tool: str,
    command: Any,
    cwd: str = "",
    exit_code: Optional[int] = None,
    status: str = "success",
    duration_ms: Optional[int] = None,
    output: str = "",
    ticket_id: str = "",
    project_id: str = "",
    requirement_id: str = "",
    agent_type: str = "",
) -> str:
    """把一次外部命令写成 TCMD。没有工单号时不落库。`command` 一律存成字符串。"""
    command_str = _as_command(command)
    if not ticket_id:
        return ""
    try:
        from command_log import record_traced_command
        record_id = await record_traced_command(
            source=source,
            tool=tool,
            command=command_str,
            cwd=cwd,
            exit_code=exit_code,
            status=status,
            duration_ms=duration_ms,
            output=output or "",
            ticket_id=ticket_id,
            project_id=project_id,
            requirement_id=requirement_id,
            agent_type=agent_type or "DevAgent",
        )
        return str(record_id or "")
    except Exception as exc:
        logger.debug("UE 命令记录失败（非致命）: %s", exc)
        return ""


async def seal_ue_command(
    context: Optional[Dict[str, Any]],
    result: Any,
    *,
    source: str,
    tool: str,
    step_name: str,
    command: Any,
    cwd: str = "",
    exit_code: Optional[int] = None,
    status: str = "success",
    duration_ms: int = 0,
    output: str = "",
    ok: bool = False,
    reason: str = "",
) -> Any:
    """进程结束后落命令日志，并把 `task_id` 写回 ActionResult.data。"""
    ctx = context or {}
    record_id = await trace_ue_command(
        source=source,
        tool=tool,
        command=command,
        cwd=cwd,
        exit_code=exit_code,
        status=status,
        duration_ms=duration_ms,
        output=output,
        ticket_id=str(ctx.get("ticket_id") or ""),
        project_id=str(ctx.get("project_id") or ""),
        requirement_id=str(ctx.get("requirement_id") or ""),
        agent_type=str(ctx.get("agent_type") or ""),
    )
    await emit_ue_step(
        ctx,
        step_name,
        "done" if ok else "error",
        duration_ms=duration_ms,
        reason=reason,
        task_id=record_id,
    )
    data = getattr(result, "data", None)
    if not isinstance(data, dict):
        data = {}
        try:
            result.data = data
        except Exception:
            return result
    data["task_id"] = record_id
    if not isinstance(data.get("command"), str):
        data["command"] = _as_command(command)
    return result
