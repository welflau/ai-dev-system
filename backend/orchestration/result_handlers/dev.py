"""DevAgent 的结果处理：HTML 原型、H5 类型检查和开发工单。"""
import json
from typing import Optional

from models import TicketStatus
from orchestration.result_flow import update_current_ticket
from orchestration.result_handlers.context import HANDLED, ResultContext
from utils import generate_id, now_iso


async def handle_html_prototype(ctx: ResultContext) -> Optional[str]:
    """DevAgent.write_html_prototype：落 html_prototype 产物，状态写成 html_prototype_done。

    在处理器内收尾。
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

    new_status = TicketStatus.HTML_PROTOTYPE_DONE.value
    await _save_result(ctx, new_status)
    await db.insert("artifacts", {
        "id": generate_id("ART"),
        "project_id": project_id, "requirement_id": requirement_id,
        "ticket_id": ticket_id, "type": "html_prototype",
        "name": f"HTML原型 - {ticket['title']}",
        "path": None, "content": result.get("html_content", result_json)[:2000],
        "metadata": None, "created_at": now_iso(),
    })
    await orch._log(
        project_id, requirement_id, ticket_id, agent_name,
        action, current_status, new_status,
        f"HTML 原型已生成，核心循环：{result.get('core_mechanics','')[:80]}",
    )
    await orch._write_phase_comment(
        project_id, ticket_id, agent_name,
        f"✅ HTML 原型已生成。核心机制：{result.get('core_mechanics','无')[:120]}",
        phase=new_status,
    )
    return HANDLED


async def handle_dev(ctx: ResultContext) -> Optional[str]:
    """仅成功开发返回新状态给公共收尾；其他分支不触发即时派单。"""
    if ctx.action == "run_h5_typecheck":
        await _record_typecheck(ctx)
        return HANDLED
    if ctx.result.get("status") == "development_failed":
        await _reject_code_generation(ctx)
        return HANDLED

    self_test = ctx.result.get("self_test", {})
    summary = self_test.get("summary", "未自测")
    blocking = self_test.get("ue_blocking_issues") or []
    if blocking:
        await _reject_self_test(ctx, self_test, blocking)
        return HANDLED

    new_status = TicketStatus.DEVELOPMENT_DONE.value
    await _save_result(ctx, new_status)
    await _log_completion(ctx, new_status, self_test, summary)
    await _comment_completion(ctx, new_status, summary)
    await _save_code_artifact(ctx)
    return new_status


async def _save_result(ctx: ResultContext, status: str) -> None:
    await update_current_ticket(ctx.db, ctx.ticket_id, ctx.current_status, {
        "status": status, "result": ctx.result_json, "updated_at": now_iso(),
    })


async def _record_typecheck(ctx: ResultContext) -> None:
    result = ctx.result
    errors = result.get("errors") or []
    ticket_type = ctx.ticket.get("type")
    if result.get("status") == "success":
        status = await ctx.orch._sop_success_status_for(
            ctx.project_id, ctx.action, default="h5_typecheck_passed", ticket_type=ticket_type,
        )
        await _save_result(ctx, status)
        await ctx.orch._log(
            ctx.project_id, ctx.requirement_id, ctx.ticket_id, ctx.agent_name,
            "complete", ctx.current_status, status, f"tsc 通过（{result.get('duration_ms', 0)}ms）",
            detail_data={
                "exit_code": result.get("exit_code"), "duration_ms": result.get("duration_ms"),
                "command": result.get("command"), "task_id": result.get("task_id") or "",
            },
        )
        return

    stage = await ctx.orch._sop_stage_for(ctx.project_id, ctx.action, ticket_type)
    status = (stage or {}).get("reject_status") or "h5_typecheck_failed"
    await _save_result(ctx, status)
    err_brief = "; ".join(
        f"{e.get('file', '?')}:{e.get('line', '?')} {e.get('code', '')} {(e.get('msg') or '')[:80]}"
        for e in errors[:3]
    )
    await ctx.orch._log(
        ctx.project_id, ctx.requirement_id, ctx.ticket_id, ctx.agent_name,
        "reject", ctx.current_status, status,
        f"tsc 失败 · {len(errors)} errors · DevAgent.fix_issues 将修复", "warning",
        detail_data={
            "errors": errors[:10], "hints": (result.get("hints") or [])[:5],
            "err_brief": err_brief, "raw_tail": (result.get("raw_tail") or "")[-4000:],
            "command": result.get("command"), "exit_code": result.get("exit_code"),
            "task_id": result.get("task_id") or "",
        },
    )


async def _reject_code_generation(ctx: ResultContext) -> None:
    """无有效代码时只记 reject，供重试计数使用，不保存代码产物。"""
    status = "development_failed"
    failure = ctx.result.get("code_gen_failure") or {}
    reason = str(ctx.result.get("message") or "代码生成未产出有效代码")
    await _save_result(ctx, status)
    await ctx.orch._log(
        ctx.project_id, ctx.requirement_id, ctx.ticket_id, ctx.agent_name,
        "reject", ctx.current_status, status,
        f"代码生成未产出有效代码 · {reason[:200]} · 将触发 fix_issues 反思重开发", "error",
        detail_data={
            "reason": reason, "file_count": failure.get("file_count", 0),
            "files": failure.get("files", []), "notes": failure.get("notes", ""),
        },
    )


async def _reject_self_test(ctx: ResultContext, self_test: dict, blocking: list) -> None:
    status = "self_test_failed"
    await _save_result(ctx, status)
    err_brief = "; ".join(
        f"[{i.get('rule')}] {(i.get('file') or '?').split('/')[-1]}:{i.get('line') or '?'} "
        f"{(i.get('msg') or '')[:80]}"
        for i in blocking[:3]
    )
    await ctx.orch._log(
        ctx.project_id, ctx.requirement_id, ctx.ticket_id, ctx.agent_name,
        "reject", ctx.current_status, status,
        f"UE 自测不通过 · {len(blocking)} blocking · 将触发 fix_issues 修复", "warning",
        detail_data={
            "issues": blocking[:10], "summary": self_test.get("ue_lint_summary"), "err_brief": err_brief,
        },
    )


async def _log_completion(ctx: ResultContext, status: str, self_test: dict, summary: str) -> None:
    result = ctx.result
    paths = list((result.get("files") or {}).keys())
    for path in list(result.get("media_paths") or []):
        if path not in paths:
            paths.append(path)
    screenshots = [
        (s.get("url") if isinstance(s, dict) else str(s))
        for s in (self_test.get("screenshots") or []) if s
    ]
    names = [p.replace("\\", "/").split("/")[-1] for p in paths]
    git = ctx.git_result
    await ctx.orch._log(
        ctx.project_id, ctx.requirement_id, ctx.ticket_id, ctx.agent_name,
        "complete", ctx.current_status, status, f"开发完成 | 自测: {summary}",
        detail_data={
            "files_count": len(paths), "files": names[:50], "file_paths": paths[:50],
            "screenshots": screenshots[:10],
            "result_summary": str(result.get("dev_result", {}).get("notes", ""))[:500],
            "self_test": self_test,
            "git_commit": git.get("commit_hash") if git else None,
            "git_files": git.get("files", []) if git else [],
        },
    )


async def _comment_completion(ctx: ResultContext, status: str, summary: str) -> None:
    # 评论只数代码文件；时间轴还展示媒体路径。
    files_count = len(ctx.result.get("files", {}))
    notes = str(ctx.result.get("dev_result", {}).get("notes", ""))[:120]
    await ctx.orch._write_phase_comment(
        ctx.project_id, ctx.ticket_id, ctx.agent_name,
        f"✅ 开发完成，共提交 {files_count} 个文件。自测：{summary}"
        + (f"\n备注：{notes}" if notes else ""),
        phase=status,
    )


async def _save_code_artifact(ctx: ResultContext) -> None:
    await ctx.db.insert("artifacts", {
        "id": generate_id("ART"),
        "project_id": ctx.project_id, "requirement_id": ctx.requirement_id,
        "ticket_id": ctx.ticket_id, "type": "code", "name": f"代码 - {ctx.ticket['title']}",
        "path": None, "content": ctx.result_json,
        "metadata": json.dumps({"git": ctx.git_result}) if ctx.git_result else None,
        "created_at": now_iso(),
    })
