"""PlannerAgent 的结果处理器。

从 `TicketOrchestrator._handle_agent_result` 原样搬出（重构方案 R2 第 1 步），逻辑未改。
和原文的差别只有三处：`self` 写成 `orch`；共享的局部变量从 `ctx` 取；
`return` 写成 `return HANDLED`，落到函数尾部的路径写成 `return new_status`。
"""
from typing import Optional

from models import TicketStatus
from orchestration.result_handlers.context import HANDLED, ResultContext
from utils import generate_id, now_iso


async def handle_planner(ctx: ResultContext) -> Optional[str]:
    """PlannerAgent：PRD，状态写成 planning_done。在处理器内收尾。"""
    orch = ctx.orch
    db = ctx.db
    project_id = ctx.project_id
    ticket_id = ctx.ticket_id
    ticket = ctx.ticket
    agent_name = ctx.agent_name
    action = ctx.action
    result = ctx.result
    result_json = ctx.result_json
    current_status = ctx.current_status
    requirement_id = ctx.requirement_id

    # 策划完成：保存 PRD 产物，写 knowledge_index（agent_scope=planner）
    new_status = TicketStatus.PLANNING_DONE.value
    await db.update("tickets", {
        "status": new_status,
        "result": result_json,
        "updated_at": now_iso(),
    }, "id = ?", (ticket_id,))
    await db.insert("artifacts", {
        "id": generate_id("ART"),
        "project_id": project_id,
        "requirement_id": requirement_id,
        "ticket_id": ticket_id,
        "type": "prd",
        "name": f"PRD - {ticket['title']}",
        "path": None,
        "content": result.get("prd_content", result_json),
        "metadata": None,
        "created_at": now_iso(),
    })
    await orch._log(
        project_id, requirement_id, ticket_id, agent_name,
        action, current_status, new_status,
        f"PRD 已生成，验收标准：{len(result.get('acceptance_criteria',''))} 字符",
    )
    await orch._write_phase_comment(
        project_id, ticket_id, agent_name,
        f"✅ PRD 已生成。验收标准：{str(result.get('acceptance_criteria','无'))[:200]}",
        phase=new_status,
    )
    return HANDLED
