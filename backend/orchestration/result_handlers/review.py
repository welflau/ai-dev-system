"""ReviewAgent 的结果处理器。

从 `TicketOrchestrator._handle_agent_result` 原样搬出（重构方案 R2 第 1 步），逻辑未改。
和原文的差别只有三处：`self` 写成 `orch`；共享的局部变量从 `ctx` 取；
`return` 写成 `return HANDLED`，落到函数尾部的路径写成 `return new_status`。
"""
import json
from typing import Optional

from models import TicketStatus
from orchestration.result_handlers.context import ResultContext
from utils import generate_id, now_iso


async def handle_review(ctx: ResultContext) -> Optional[str]:
    """ReviewAgent：代码审查，状态写成 review_passed（低分只记 warning）。返回新状态。"""
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

    # 代码审查阶段结果（新增：独立于 TestAgent 的盲审修复）
    new_status = TicketStatus.REVIEW_PASSED.value
    score = result.get("score", 7)
    issues = result.get("issues", []) or []
    suggestions = result.get("suggestions", []) or []
    sop_cfg = ticket.get("_sop_config") or {}  # 可能为空
    pass_score = sop_cfg.get("pass_score", 7)

    await db.update("tickets", {
        "status": new_status,
        "result": result_json,
        "updated_at": now_iso(),
    }, "id = ?", (ticket_id,))

    # 低分只记 warning，不阻塞（block_on_low_score=false 默认）
    try:
        score_num = float(score)
    except (TypeError, ValueError):
        score_num = 7.0
    log_level = "warning" if score_num < pass_score else "info"
    issues_summary = ("; ".join(str(i) for i in issues[:3]) if issues else "无")[:300]
    await orch._log(
        project_id, requirement_id, ticket_id, agent_name,
        "code_review", current_status, new_status,
        f"代码审查完成 {score}/10 → {'低于通过分 (warning)' if log_level == 'warning' else '通过'}"
        f" | 问题: {issues_summary}",
        log_level,
        detail_data={
            "score": score,
            "issues": issues[:5],
            "suggestions": suggestions[:5],
            "pass_score": pass_score,
            "git_commit": git_result.get("commit_hash") if git_result else None,
        },
    )

    # 保存审查产物
    await db.insert("artifacts", {
        "id": generate_id("ART"),
        "project_id": project_id,
        "requirement_id": requirement_id,
        "ticket_id": ticket_id,
        "type": "code_review",
        "name": f"代码审查 - {ticket['title']}",
        "path": None,
        "content": result_json,
        "metadata": json.dumps({"git": git_result, "score": score}) if git_result else json.dumps({"score": score}),
        "created_at": now_iso(),
    })

    return new_status
