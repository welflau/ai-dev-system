"""DeployAgent 的结果处理器。

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


async def handle_deploy(ctx: ResultContext) -> Optional[str]:
    """DeployAgent：部署。

    SOP 声明的成功状态不是 deployed 时（如 UE 的 packaged）在处理器内收尾，
    真正部署完成才返回 deployed。
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

    # deploy_ue / deploy_web fragment 都用 action=run_ci_deploy，但 success_status
    # 不同：deploy_ue 是 packaged（后面还有 code_review → acceptance → deploy），
    # deploy_web 是 deployed（终态）。必须读 SOP 声明，不能硬编码成 deployed ——
    # 否则 UE 项目会提前撞进 _HARD_TERMINAL，审查和验收整段被跳过。
    if action == "run_ci_deploy":
        new_status = await orch._sop_success_status_for(
            project_id, action, default=TicketStatus.DEPLOYED.value,
            ticket_type=ticket.get("type"),
        )
        if new_status != TicketStatus.DEPLOYED.value:
            await db.update("tickets", {
                "status": new_status,
                "result": result_json,
                "updated_at": now_iso(),
            }, "id = ?", (ticket_id,))
            deploy_info = result.get("deploy_result", {}) or {}
            await orch._log(
                project_id, requirement_id, ticket_id, agent_name,
                "complete", current_status, new_status,
                f"打包已触发（strategy={deploy_info.get('strategy')}，"
                f"build_type={deploy_info.get('build_type')}）",
                detail_data={
                    "strategy": deploy_info.get("strategy"),
                    "build_type": deploy_info.get("build_type"),
                    "build_id": deploy_info.get("build_id"),
                    "git_commit": git_result.get("commit_hash") if git_result else None,
                },
            )
            # 不落 deploy_config 产物、不做需求完成检查 —— 留给真正的 deploy 阶段。
            # 状态已推进，交由 process_ticket 末尾的事件驱动继续流转。
            return HANDLED

    # 部署完成
    new_status = TicketStatus.DEPLOYED.value

    await db.update("tickets", {
        "status": new_status,
        "result": result_json,
        "completed_at": now_iso(),
        "updated_at": now_iso(),
    }, "id = ?", (ticket_id,))

    preview_url = result.get("deploy_result", {}).get("preview_url")
    deploy_msg = "部署完成"
    if preview_url:
        deploy_msg = f"部署完成，预览地址: {preview_url}"

    await orch._log(
        project_id, requirement_id, ticket_id, agent_name,
        "complete", current_status, new_status,
        deploy_msg,
        detail_data={
            "git_commit": git_result.get("commit_hash") if git_result else None,
            "git_files": git_result.get("files", []) if git_result else [],
            "preview_url": preview_url,
        },
    )

    # 保存部署产物
    await db.insert("artifacts", {
        "id": generate_id("ART"),
        "project_id": project_id,
        "requirement_id": requirement_id,
        "ticket_id": ticket_id,
        "type": "deploy_config",
        "name": f"部署配置 - {ticket['title']}",
        "path": None,
        "content": result_json,
        "metadata": json.dumps({"git": git_result}) if git_result else None,
        "created_at": now_iso(),
    })

    # 检查需求下所有工单是否都已完成
    await orch._check_requirement_completion(project_id, requirement_id)

    # 刷新里程碑进度
    try:
        from api.milestones import refresh_all_milestones
        await refresh_all_milestones(project_id)
    except Exception as ms_err:
        logger.warning("刷新里程碑进度失败(非致命): %s", ms_err)

    # 触发依赖此工单的后续工单
    await orch._trigger_dependents(project_id, ticket_id)

    return new_status
