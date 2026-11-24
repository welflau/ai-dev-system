"""TestAgent 的结果处理器。

从 `TicketOrchestrator._handle_agent_result` 原样搬出（重构方案 R2 第 1 步），逻辑未改。
和原文的差别只有三处：`self` 写成 `orch`；共享的局部变量从 `ctx` 取；
`return` 写成 `return HANDLED`，落到函数尾部的路径写成 `return new_status`。
"""
import json
import logging
from typing import Optional

from models import TicketStatus
from orchestration.result_handlers.context import HANDLED, ResultContext
from utils import generate_id, now_iso

# 沿用拆分前的 logger 名，现有的日志过滤和采集规则不受影响。
logger = logging.getLogger("orchestrator")


async def handle_test(ctx: ResultContext) -> Optional[str]:
    """TestAgent：测试，以及 run_h5_playtest。

    run_h5_playtest 在处理器内收尾，其余返回新状态。
    """
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
    git_result = ctx.git_result

    if action == "run_h5_playtest":
        r_status = result.get("status")
        errors_list = result.get("errors") or []
        if r_status == "success":
            new_status = await orch._sop_success_status_for(
                project_id, action, default="h5_playtest_passed",
                ticket_type=ticket.get("type"),
            )
            await db.update("tickets", {
                "status": new_status,
                "result": result_json,
                "updated_at": now_iso(),
            }, "id = ?", (ticket_id,))
            skip = "（运行时跳过）" if result.get("runtime_skipped") else ""
            await orch._log(
                project_id, requirement_id, ticket_id, agent_name,
                "complete", current_status, new_status,
                f"H5 试玩通过{skip}（{result.get('duration_ms', 0)}ms）",
                detail_data={
                    "duration_ms": result.get("duration_ms"),
                    "warnings": (result.get("warnings") or [])[:5],
                    "screenshots": (result.get("screenshots") or [])[:5],
                    "preview_url": result.get("preview_url") or "",
                    "has_canvas": result.get("has_canvas", True),
                    "runtime_skipped": bool(result.get("runtime_skipped")),
                    "command": result.get("command"),
                    "task_id": result.get("task_id") or "",
                },
            )
            await orch._maybe_openspec_verify(
                project_id, ticket_id, stage_label="h5_playtest",
            )
        else:
            stage = await orch._sop_stage_for(project_id, action, ticket.get("type"))
            new_status = (stage or {}).get("reject_status") or "h5_playtest_failed"
            await db.update("tickets", {
                "status": new_status,
                "result": result_json,
                "updated_at": now_iso(),
            }, "id = ?", (ticket_id,))
            err_brief = "; ".join(
                f"{e.get('source', '?')}: {(e.get('msg') or '')[:80]}"
                for e in errors_list[:3]
            )
            await orch._log(
                project_id, requirement_id, ticket_id, agent_name,
                "reject", current_status, new_status,
                f"H5 试玩失败 · {len(errors_list)} errors · DevAgent.fix_issues 将修复",
                "warning",
                detail_data={
                    "errors": errors_list[:10],
                    "warnings": (result.get("warnings") or [])[:5],
                    "err_brief": err_brief,
                    "raw_tail": (result.get("raw_tail") or "")[-4000:],
                    "screenshots": (result.get("screenshots") or [])[:5],
                    "command": result.get("command"),
                    "task_id": result.get("task_id") or "",
                },
            )
        return HANDLED

    # 测试结果（只接受合法状态）
    test_status = result.get("status", "testing_done")
    if test_status not in (TicketStatus.TESTING_DONE.value, TicketStatus.TESTING_FAILED.value):
        test_status = TicketStatus.TESTING_DONE.value

    # run_tests 也被 smoke_test fragment 复用，但它的 success_status 是
    # smoke_test_passed（中间态，后面还有 code_review/acceptance），
    # 不是 testing_done（_HARD_TERMINAL）。写错会让工单提前终结。
    if test_status == TicketStatus.TESTING_DONE.value:
        test_status = await orch._sop_success_status_for(
            project_id, action, default=TicketStatus.TESTING_DONE.value,
            ticket_type=ticket.get("type"),
        )
    new_status = test_status

    await db.update("tickets", {
        "status": new_status,
        "result": result_json,
        "updated_at": now_iso(),
    }, "id = ?", (ticket_id,))

    # 成功分支要认所有"非失败"状态 —— smoke_test 阶段成功时是
    # smoke_test_passed 而非 testing_done，用 == 判会被误当成失败打回。
    if new_status != TicketStatus.TESTING_FAILED.value:
        _tr_shots = [
            (s.get("url") if isinstance(s, dict) else str(s))
            for s in (result.get("test_result", {}).get("screenshots") or [])
            if s
        ]
        await orch._log(
            project_id, requirement_id, ticket_id, agent_name,
            "complete", current_status, new_status,
            f"测试通过: {result.get('test_result', {}).get('summary', '')}",
            detail_data={
                "git_commit": git_result.get("commit_hash") if git_result else None,
                "git_files": git_result.get("files", []) if git_result else [],
                "screenshots": _tr_shots[:10],
            },
        )
        # Failure Library：测试通过也算历次反思策略奏效
        try:
            from failure_library import failure_library
            await failure_library.mark_resolved(ticket_id)
        except Exception as fl_err:
            logger.warning("FailureLibrary.mark_resolved 失败: %s", fl_err)

        # 保存测试产物
        await db.insert("artifacts", {
            "id": generate_id("ART"),
            "project_id": project_id,
            "requirement_id": requirement_id,
            "ticket_id": ticket_id,
            "type": "test",
            "name": f"测试报告 - {ticket['title']}",
            "path": None,
            "content": result_json,
            "metadata": json.dumps({"git": git_result}) if git_result else None,
            "created_at": now_iso(),
        })

        # 保存截图 artifact
        for ss in result.get("test_result", {}).get("screenshots", []):
            await db.insert("artifacts", {
                "id": generate_id("ART"),
                "project_id": project_id,
                "requirement_id": requirement_id,
                "ticket_id": ticket_id,
                "type": "screenshot",
                "name": ss["label"],
                "path": ss["url"],
                "content": None,
                "metadata": json.dumps({"url": ss["url"]}),
                "created_at": now_iso(),
            })

        # 测试通过 → 触发后续依赖工单
        await orch._trigger_dependents(project_id, ticket_id)

        # 检查需求下所有工单是否都测试通过（用于需求级统一部署）
        await orch._check_requirement_completion(project_id, requirement_id)

        # 刷新里程碑进度
        try:
            from api.milestones import refresh_all_milestones
            await refresh_all_milestones(project_id)
        except Exception as ms_err:
            logger.warning("刷新里程碑进度失败(非致命): %s", ms_err)
    else:
        # 测试不通过 → 保存测试产物 + 打回开发
        test_summary = result.get("test_result", {}).get("summary", {})
        pass_rate = test_summary.get("pass_rate", 0) if isinstance(test_summary, dict) else 0
        issues = test_summary.get("issues", []) if isinstance(test_summary, dict) else []

        await db.insert("artifacts", {
            "id": generate_id("ART"),
            "project_id": project_id,
            "requirement_id": requirement_id,
            "ticket_id": ticket_id,
            "type": "test",
            "name": f"测试报告(未通过) - {ticket['title']}",
            "path": None,
            "content": result_json,
            "metadata": json.dumps({"git": git_result}) if git_result else None,
            "created_at": now_iso(),
        })

        await orch._log(
            project_id, requirement_id, ticket_id, agent_name,
            "reject", current_status, new_status,
            f"测试未通过 (通过率 {pass_rate}%)，打回开发: {'; '.join(issues[:3]) if issues else '详见测试报告'}",
            detail_data={
                "pass_rate": pass_rate,
                "issues": issues[:5],
                "git_commit": git_result.get("commit_hash") if git_result else None,
            },
        )

    return new_status
