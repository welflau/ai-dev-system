"""Agent 结果进入业务处理器之前的公共操作。数据库由编排器在调用时传入。"""
import asyncio
import json
import logging

from events import event_manager
from models import TicketStatus
from utils import now_iso

logger = logging.getLogger("orchestrator")


class StaleAgentResult(Exception):
    """在途结果已失去写入权；由编排入口结束本轮，不走错误处理。"""


async def update_current_ticket(db, ticket_id: str, expected_status: str, changes: dict, *, run_id) -> None:
    """核对状态和批次；同态收尾也消费本次派单。无批次直调只匹配 NULL。"""
    count = await db.update("tickets", {**changes, "active_run_id": None},
                            "id = ? AND status = ? AND active_run_id IS ?",
                            (ticket_id, expected_status, run_id))
    if count == 0:
        raise StaleAgentResult


def serialize_result(result: dict) -> str:
    """生成可落库的 JSON；非空二进制产物仍留给稍后的 Git 写入。"""
    media_files_temp = result.pop("_media_files", None)  # 暂存，稍后写入 Git
    if isinstance(media_files_temp, dict) and media_files_temp:
        result["media_paths"] = list(media_files_temp.keys())
    result_json = json.dumps(result, ensure_ascii=False)
    if media_files_temp:
        result["_media_files"] = media_files_temp  # 写完 JSON 后放回，供 _handle_git_files 使用
    return result_json


async def block_agent_error(
    orch, db, *, project_id, ticket_id, requirement_id, ticket_snapshot,
    agent_name, action, result, current_status, run_id,
) -> None:
    """先落库并发布阻塞事件，再尝试错误 Hook，最后启动后台诊断。"""
    err_msg = str(result.get("message") or result.get("error") or "Agent 返回 error")
    blocked_status = TicketStatus.BLOCKED.value
    await update_current_ticket(db, ticket_id, current_status, {
        "status": blocked_status,
        "result": json.dumps(result, ensure_ascii=False),
        "updated_at": now_iso(),
    }, run_id=run_id)
    await orch._log(
        project_id, requirement_id, ticket_id, agent_name,
        "blocked", current_status, blocked_status,
        f"{agent_name}.{action} 返回 error，工单已标记 blocked 等待人工介入 | {err_msg[:300]}",
        "error",
        detail_data={"action": action, "error": err_msg, "raw_result": result},
    )
    await event_manager.publish_to_project(
        project_id,
        "ticket_blocked",
        {
            "ticket_id": ticket_id,
            "from": current_status,
            "to": blocked_status,
            "agent": agent_name,
            "action": action,
            "error": err_msg[:300],
        },
    )
    logger.warning(
        "🚧 工单 blocked: %s %s.%s → %s",
        ticket_id[:12], agent_name, action, err_msg[:120],
    )

    # Hook emit：让 chat_alert_hook 把错误推到 AI 聊天面板
    try:
        from hooks.registry import hook_registry
        from hooks.types import HookEvent, ToolHookContext
        await hook_registry.emit(ToolHookContext(
            event=HookEvent.TOOL_ERROR,
            tool_name=f"agent:{agent_name}.{action}",
            input={},
            error=RuntimeError(err_msg[:300]),
            project_id=project_id,
            ticket_id=ticket_id,
            agent_type=agent_name,
        ))
    except Exception:
        pass

    # fire-and-forget：后台跑 LLM 诊断，不阻塞主 poll 循环
    # 结果写回 tickets.diagnosis，SSE 推前端
    asyncio.create_task(orch._diagnose_blocked_ticket(
        project_id=project_id,
        ticket_id=ticket_id,
        current_ticket=dict(ticket_snapshot),
        agent_name=agent_name,
        action=action,
        error_msg=err_msg,
        blocked_from_status=current_status,
    ))
