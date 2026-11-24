"""DevAgent 的结果处理器。

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
    await db.update("tickets", {
        "status": new_status, "result": result_json, "updated_at": now_iso(),
    }, "id = ?", (ticket_id,))
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
    """DevAgent：开发、返工、修复，以及 run_h5_typecheck。

    只有正常写入 development_done 才返回新状态。类型检查、代码生成失败、
    自测不通过、迟到结果这四种情况在处理器内收尾。
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

    if action == "run_h5_typecheck":
        r_status = result.get("status")
        errors_list = result.get("errors") or []
        if r_status == "success":
            new_status = await orch._sop_success_status_for(
                project_id, action, default="h5_typecheck_passed",
                ticket_type=ticket.get("type"),
            )
            await db.update("tickets", {
                "status": new_status,
                "result": result_json,
                "updated_at": now_iso(),
            }, "id = ?", (ticket_id,))
            await orch._log(
                project_id, requirement_id, ticket_id, agent_name,
                "complete", current_status, new_status,
                f"tsc 通过（{result.get('duration_ms', 0)}ms）",
                detail_data={
                    "exit_code": result.get("exit_code"),
                    "duration_ms": result.get("duration_ms"),
                    "command": result.get("command"),
                    "task_id": result.get("task_id") or "",
                },
            )
        else:
            stage = await orch._sop_stage_for(project_id, action, ticket.get("type"))
            new_status = (stage or {}).get("reject_status") or "h5_typecheck_failed"
            await db.update("tickets", {
                "status": new_status,
                "result": result_json,
                "updated_at": now_iso(),
            }, "id = ?", (ticket_id,))
            err_brief = "; ".join(
                f"{e.get('file', '?')}:{e.get('line', '?')} {e.get('code', '')} {(e.get('msg') or '')[:80]}"
                for e in errors_list[:3]
            )
            await orch._log(
                project_id, requirement_id, ticket_id, agent_name,
                "reject", current_status, new_status,
                f"tsc 失败 · {len(errors_list)} errors · DevAgent.fix_issues 将修复",
                "warning",
                detail_data={
                    "errors": errors_list[:10],
                    "hints": (result.get("hints") or [])[:5],
                    "err_brief": err_brief,
                    "raw_tail": (result.get("raw_tail") or "")[-4000:],
                    "command": result.get("command"),
                    "exit_code": result.get("exit_code"),
                    "task_id": result.get("task_id") or "",
                },
            )
        return HANDLED

    # 常规 develop / rework / fix_issues → development_done
    # v0.19.x A 方案：若 self_test 失败（UE blocking 静态错）→ self_test_failed
    # → SOP 派生 self_test_failed → DevAgent.fix_issues 自动回跳
    # 代码生成未产出有效代码（零文件 / 只有降级模板 / Action 失败）。
    # DevAgent 用独立 status=development_failed 表达，而不是 status=error ——
    # error 在函数开头就被转成 blocked（硬终态要人工），可 LLM 一次超时
    # 完全值得自动重试。这里记 reject（进 _reject_count_since_reset 计数），
    # SOP 的 development_failed → DevAgent.fix_issues 会带反思重开发，
    # 累计超过 MAX_RETRIES 才 blocked 止损。
    # 背景：TK-20260920-ce79a9 —— 降级产出 console.log 空壳，一路走到 deployed。
    if result.get("status") == "development_failed":
        new_status = "development_failed"
        cg = result.get("code_gen_failure") or {}
        fail_msg = str(result.get("message") or "代码生成未产出有效代码")
        await db.update("tickets", {
            "status": new_status,
            "result": result_json,
            "updated_at": now_iso(),
        }, "id = ?", (ticket_id,))
        await orch._log(
            project_id, requirement_id, ticket_id, agent_name,
            "reject", current_status, new_status,
            f"代码生成未产出有效代码 · {fail_msg[:200]} · 将触发 fix_issues 反思重开发",
            "error",
            detail_data={
                "reason": fail_msg,
                "file_count": cg.get("file_count", 0),
                "files": cg.get("files", []),
                "notes": cg.get("notes", ""),
            },
        )
        return HANDLED   # 不落代码产物：这一轮没有值得留存的产出

    self_test = result.get("self_test", {})
    test_summary = self_test.get("summary", "未自测")
    blocking_issues = self_test.get("ue_blocking_issues") or []

    if blocking_issues:
        new_status = "self_test_failed"
        await db.update("tickets", {
            "status": new_status,
            "result": result_json,
            "updated_at": now_iso(),
        }, "id = ?", (ticket_id,))
        err_brief = "; ".join(
            f"[{i.get('rule')}] {(i.get('file') or '?').split('/')[-1]}:{i.get('line') or '?'} "
            f"{(i.get('msg') or '')[:80]}"
            for i in blocking_issues[:3]
        )
        await orch._log(
            project_id, requirement_id, ticket_id, agent_name,
            "reject", current_status, new_status,
            f"UE 自测不通过 · {len(blocking_issues)} blocking · 将触发 fix_issues 修复",
            "warning",
            detail_data={
                "issues": blocking_issues[:10],
                "summary": self_test.get("ue_lint_summary"),
                "err_brief": err_brief,
            },
        )
        return HANDLED   # 不落代码产物，等修好再落

    new_status = TicketStatus.DEVELOPMENT_DONE.value

    # 写入前再读一次：终态 / 已越过 development_done 则丢弃迟到结果
    latest = await db.fetch_one("SELECT status FROM tickets WHERE id = ?", (ticket_id,))
    latest_status = (latest or {}).get("status", current_status)
    if latest_status in orch._HARD_TERMINAL or latest_status in {
        TicketStatus.TESTING_DONE.value,
        TicketStatus.DEPLOYED.value,
    }:
        logger.info(
            "⏭ 工单 %s 当前状态 %s，跳过写入 development_done（终态/已越过开发）",
            ticket_id[:12], latest_status,
        )
        return HANDLED

    await db.update("tickets", {
        "status": new_status,
        "result": result_json,
        "updated_at": now_iso(),
    }, "id = ?", (ticket_id,))

    # develop/rework 产出文件列表（供时间轴/会话文件链接渲染）
    _dev_files = list((result.get("files") or {}).keys())
    _dev_media = list(result.get("media_paths") or [])
    for mp in _dev_media:
        if mp not in _dev_files:
            _dev_files.append(mp)
    _st_shots = [
        (s.get("url") if isinstance(s, dict) else str(s))
        for s in (self_test.get("screenshots") or [])
        if s
    ]
    _dev_file_names = [p.replace("\\", "/").split("/")[-1] for p in _dev_files]
    await orch._log(
        project_id, requirement_id, ticket_id, agent_name,
        "complete", current_status, new_status,
        f"开发完成 | 自测: {test_summary}",
        detail_data={
            "files_count": len(_dev_files),
            "files": _dev_file_names[:50],       # 文件名（chip 显示）
            "file_paths": _dev_files[:50],        # 完整相对路径（点击定位）
            "screenshots": _st_shots[:10],        # 自测截图（时间轴缩略图预览）
            "result_summary": str(result.get("dev_result", {}).get("notes", ""))[:500],
            "self_test": self_test,
            "git_commit": git_result.get("commit_hash") if git_result else None,
            "git_files": git_result.get("files", []) if git_result else [],
        },
    )
    # 阶段完成评论：供时间轴展示和下游 Agent 感知
    files_count = len(result.get("files", {}))
    notes_brief = str(result.get("dev_result", {}).get("notes", ""))[:120]
    await orch._write_phase_comment(
        project_id, ticket_id, agent_name,
        f"✅ 开发完成，共提交 {files_count} 个文件。自测：{test_summary}"
        + (f"\n备注：{notes_brief}" if notes_brief else ""),
        phase=new_status,
    )

    # 保存代码产物
    await db.insert("artifacts", {
        "id": generate_id("ART"),
        "project_id": project_id,
        "requirement_id": requirement_id,
        "ticket_id": ticket_id,
        "type": "code",
        "name": f"代码 - {ticket['title']}",
        "path": None,
        "content": result_json,
        "metadata": json.dumps({"git": git_result}) if git_result else None,
        "created_at": now_iso(),
    })

    return new_status
