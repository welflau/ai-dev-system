"""ProductAgent 的结果处理器。

从 `TicketOrchestrator._handle_agent_result` 原样搬出（重构方案 R2 第 1 步），逻辑未改。
和原文的差别只有三处：`self` 写成 `orch`；共享的局部变量从 `ctx` 取；
`return` 写成 `return HANDLED`，落到函数尾部的路径写成 `return new_status`。
"""
import json
import logging
from typing import Optional

from models import TicketStatus
from orchestration.result_handlers.context import HANDLED, ResultContext
from utils import now_iso

# 沿用拆分前的 logger 名，现有的日志过滤和采集规则不受影响。
logger = logging.getLogger("orchestrator")


async def handle_acceptance_review(ctx: ResultContext) -> Optional[str]:
    """ProductAgent.acceptance_review：验收。

    通过和不通过都返回新状态。LLM 降级时重派验收或转 blocked，在处理器内收尾。
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
    git_result = ctx.git_result

    # LLM 降级 ≠ 代码有问题：验收根本没执行，不该当成「验收不通过」打回开发。
    # 保持「降级 ≠ 通过」（永不产生 acceptance_passed）：有限次直接重派验收，
    # 耗尽后 blocked 转人工；全程不记 reject，不占全局 MAX_RETRIES / 同因熔断额度，
    # 也不触发 DevAgent.fix_issues 反思重开发（TK-20261110-48b6af 实测
    # result.degraded=true 且 reject 原因恒为 []，白打回 8 次）。
    if result.get("degraded"):
        degrade_reason = str(result.get("degrade_reason") or "LLM 降级")
        retry_cnt = await orch._acceptance_retry_count(ticket_id)
        if retry_cnt >= 2:
            new_status = TicketStatus.BLOCKED.value
            log_action, level = "blocked", "warning"
            msg = (f"验收连续降级 {retry_cnt + 1} 次，停止自动重派，转人工排查 LLM/CLI 环境。"
                   f"原因: {degrade_reason[:120]}")
        else:
            stage = await orch._sop_stage_for(
                project_id, "acceptance_review", ticket.get("type")
            )
            new_status = (stage or {}).get("trigger_on") or "review_passed"
            log_action, level = "acceptance_retry", "warning"
            msg = (f"验收未执行（LLM 降级），不打回开发，直接重派验收（第 {retry_cnt + 1} 次）。"
                   f"原因: {degrade_reason[:120]}")
        await db.update("tickets", {
            "status": new_status,
            "result": result_json,
            "updated_at": now_iso(),
        }, "id = ?", (ticket_id,))
        await orch._log(
            project_id, requirement_id, ticket_id, agent_name,
            log_action, current_status, new_status, msg, level,
            detail_data={"degraded": True, "degrade_reason": degrade_reason,
                         "issues": result.get("issues") or []},
        )
        return HANDLED

    # 验收结果（只接受合法状态，防止 Agent 返回 "success" 等非标值）
    review_status = result.get("status", "acceptance_passed")
    if review_status not in (TicketStatus.ACCEPTANCE_PASSED.value, TicketStatus.ACCEPTANCE_REJECTED.value):
        review_status = TicketStatus.ACCEPTANCE_PASSED.value
    new_status = review_status

    await db.update("tickets", {
        "status": new_status,
        "result": result_json,
        "updated_at": now_iso(),
    }, "id = ?", (ticket_id,))

    _acc_shots = [result["screenshot_path"]] if result.get("screenshot_path") else []
    if new_status == TicketStatus.ACCEPTANCE_PASSED.value:
        await orch._log(
            project_id, requirement_id, ticket_id, agent_name,
            "accept", current_status, new_status,
            "验收通过，转测试",
            detail_data={
                "git_commit": git_result.get("commit_hash") if git_result else None,
                "screenshots": _acc_shots,
            },
        )
        # Failure Library：验收通过说明本工单的历次反思策略最终奏效
        try:
            from failure_library import failure_library
            await failure_library.mark_resolved(ticket_id)
        except Exception as fl_err:
            logger.warning("FailureLibrary.mark_resolved 失败: %s", fl_err)
        # 知识蒸馏：验收通过后，后台尝试将修复经验沉淀到知识库（fire-and-forget）
        ctx.fire_knowledge_distill(project_id, ticket_id)
    else:
        await orch._log(
            project_id, requirement_id, ticket_id, agent_name,
            "reject", current_status, new_status,
            f"验收不通过，打回开发。原因: {json.dumps(result.get('review', {}).get('issues') or result.get('issues') or [], ensure_ascii=False)}"
        )

    return new_status
