"""UEEditorAgent 的结果处理器。

从 `TicketOrchestrator._handle_agent_result` 原样搬出（重构方案 R2 第 1 步），逻辑未改。
和原文的差别只有三处：`self` 写成 `orch`；共享的局部变量从 `ctx` 取；
`return` 写成 `return HANDLED`，落到函数尾部的路径写成 `return new_status`。
"""
from typing import Optional

from orchestration.result_handlers.context import HANDLED, ResultContext
from utils import generate_id, now_iso


async def handle_ue_editor(ctx: ResultContext) -> Optional[str]:
    """UEEditorAgent：UE 内容生成。成功写 ue_content_done，业务失败写 ue_content_failed。

    两种情况都在处理器内收尾。
    """
    orch = ctx.orch
    db = ctx.db
    project_id = ctx.project_id
    ticket_id = ctx.ticket_id
    ticket = ctx.ticket
    agent_name = ctx.agent_name
    result = ctx.result
    result_json = ctx.result_json
    current_status = ctx.current_status
    requirement_id = ctx.requirement_id

    # UE 内容生成（BP / 关卡 / Python）。没有这个分支的话会落到函数末尾的
    # else: new_status = current_status —— 状态不推进，同一条 rule 反复命中，
    # UEEditorAgent 被无限重跑。
    #
    # Agent 返回 status=error 的情况已在函数开头统一转 blocked，此处只需
    # 区分 success 与业务失败。
    if result.get("status") == "success":
        new_status = "ue_content_done"
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
            "type": "ue_content",
            "name": f"UE 内容 - {ticket['title']}",
            "path": None,
            "content": result_json,
            "metadata": None,
            "created_at": now_iso(),
        })
        await orch._log(
            project_id, requirement_id, ticket_id, agent_name,
            "complete", current_status, new_status,
            f"UE 内容已生成：{str(result.get('message', ''))[:120]}",
            detail_data={
                "imported": result.get("imported"),
                "assets": result.get("assets"),
            },
        )
        await orch._write_phase_comment(
            project_id, ticket_id, agent_name,
            f"✅ UE 内容已写入 Editor。{str(result.get('message', ''))[:150]}",
            phase=new_status,
        )
    else:
        new_status = "ue_content_failed"
        fail_msg = str(result.get("message") or "UE 内容生成未成功")
        await db.update("tickets", {
            "status": new_status,
            "result": result_json,
            "updated_at": now_iso(),
        }, "id = ?", (ticket_id,))
        await orch._log(
            project_id, requirement_id, ticket_id, agent_name,
            "reject", current_status, new_status,
            f"UE 内容生成失败 · {fail_msg[:200]}",
            "warning",
            detail_data={"error": fail_msg, "failed": result.get("failed")},
        )
    return HANDLED
