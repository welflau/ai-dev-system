"""ArchitectAgent 的结果处理器。

从 `TicketOrchestrator._handle_agent_result` 原样搬出（重构方案 R2 第 1 步），逻辑未改。
和原文的差别只有三处：`self` 写成 `orch`；共享的局部变量从 `ctx` 取；
`return` 写成 `return HANDLED`，落到函数尾部的路径写成 `return new_status`。
"""
import json
from datetime import datetime, timedelta
from typing import Optional

from models import TicketStatus
from orchestration.result_handlers.context import ResultContext
from utils import generate_id, now_iso


async def handle_architect(ctx: ResultContext) -> Optional[str]:
    """ArchitectAgent：架构设计，状态写成 architecture_done。返回新状态。"""
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
    git_result = ctx.git_result

    # 架构完成
    new_status = TicketStatus.ARCHITECTURE_DONE.value
    est_hours = result.get("estimated_hours", 4)
    est_completion = (datetime.now() + timedelta(hours=est_hours)).isoformat()

    await db.update("tickets", {
        "status": new_status,
        "result": result_json,
        "estimated_hours": est_hours,
        "estimated_completion": est_completion,
        "updated_at": now_iso(),
    }, "id = ?", (ticket_id,))

    # Self-Consistency 投票留痕（如果开启）
    vote = result.get("_consistency_vote")
    if vote:
        await orch._log(
            project_id, requirement_id, ticket_id, agent_name,
            "consistency_vote", None, None,
            f"🗳️ 架构投票: {vote['n_candidates']} 候选 → 选 #{vote['best_index']}"
            f"{' (judge fallback)' if vote.get('fallback') else ''} | {vote.get('reasoning', '')[:150]}",
            "info", detail_data={"consistency_vote": vote},
        )

    await orch._log(
        project_id, requirement_id, ticket_id, agent_name,
        "complete", current_status, new_status,
        f"架构设计完成，预计开发 {est_hours} 小时",
        detail_data={
            "estimated_hours": est_hours,
            "result_summary": str(result.get("architecture", ""))[:500],
            "git_commit": git_result.get("commit_hash") if git_result else None,
            "git_files": git_result.get("files", []) if git_result else [],
        },
    )
    await orch._write_phase_comment(
        project_id, ticket_id, agent_name,
        f"✅ 架构设计完成，预计开发 {est_hours} 小时。"
        + (f" 架构摘要：{str(result.get('architecture',''))[:150]}" if result.get("architecture") else ""),
        phase=new_status,
    )

    # 写入 Agent Memory（架构决策记录）
    try:
        arch_summary = str(result.get("architecture", ""))[:300]
        if arch_summary:
            await orch._write_memory(
                project_id=project_id,
                mem_type="decision",
                title=f"架构设计: {ticket['title'][:40]}",
                content=json.dumps({"summary": arch_summary, "ticket_id": ticket_id,
                                    "estimated_hours": est_hours}, ensure_ascii=False),
                agent_type="ArchitectAgent",
                requirement_id=requirement_id,
                ticket_id=ticket_id,
                tags=["architecture", "decision"],
            )
    except Exception:
        pass

    # 保存架构产物
    await db.insert("artifacts", {
        "id": generate_id("ART"),
        "project_id": project_id,
        "requirement_id": requirement_id,
        "ticket_id": ticket_id,
        "type": "architecture",
        "name": f"架构设计 - {ticket['title']}",
        "path": None,
        "content": result_json,
        "metadata": json.dumps({"git": git_result}) if git_result else None,
        "created_at": now_iso(),
    })

    return new_status
