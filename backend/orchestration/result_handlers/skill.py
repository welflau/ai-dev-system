"""Skill 阶段的结果处理器：选择工单状态、记录分支结果、通知并决定是否派单。

调用方通过 is_skill_run_result 识别 skill 结果，宿主 Role 可以是任何 Agent。
本处理器已自行收尾，始终返回 HANDLED，避免调用方重复通知和派单。
"""
import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from events import event_manager
from models import TicketStatus
from orchestration.result_handlers.context import HANDLED, ResultContext
from utils import now_iso

# 沿用拆分前的 logger 名，现有的日志过滤和采集规则不受影响。
logger = logging.getLogger("orchestrator")


@dataclass(frozen=True)
class _SkillRun:
    skill_id: str
    status: str
    outputs: List
    artifacts: List[Dict]
    rounds: int


async def handle_skill(ctx: ResultContext) -> Optional[str]:
    """按 skill 结果收尾；日志、评论和事件均归属 SOP 指定的宿主 Role。"""
    result = ctx.result
    cfg = result.get("sop_config") or {}
    skill_id = result.get("skill_id") or cfg.get("skill_id") or "?"
    status = result.get("skill_status") or result.get("status") or ""
    outputs = result.get("outputs") or []
    artifacts = result.get("artifacts") or []
    rounds = result.get("rounds") or 0
    success_status = await _resolve_skill_success_status(
        ctx.orch, ctx.project_id, ctx.action, result, cfg, ctx.ticket.get("type"),
    )
    status = _classify_status(status, skill_id, cfg, artifacts, result)
    run = _SkillRun(skill_id, status, outputs, artifacts, rounds)

    if run.status == "waiting_human":
        new_status = (cfg.get("_ready_status") or result.get("success_status")
                      or f"{cfg.get('_stage_id') or skill_id}_ready")
        await _record_waiting(ctx, run, new_status)
    elif run.status in ("success", "partial"):
        new_status = success_status
        await _record_completion(ctx, run, new_status)
    elif run.status == "skipped":
        new_status = success_status
        await _record_skip(ctx, run, new_status)
    else:
        new_status = TicketStatus.BLOCKED.value
        await _record_blocked(ctx, run, new_status)

    await _publish_and_continue(ctx, new_status)
    return HANDLED


def _classify_status(status: str, skill_id: str, cfg: Dict, artifacts: List[Dict], result: Dict) -> str:
    """预算豁免要求全部声明产物；人审只需至少一种可审产物。"""
    if status == "budget_exceeded" and skill_produces_satisfied(cfg, artifacts):
        # 工具可能在预算耗尽前已写完产物，按 partial 收尾，避免重跑。
        logger.info("⏱ skill %s 超预算但产出齐全（%d 个），按成功处理", skill_id, len(artifacts))
        return "partial"
    if status == "waiting_human" and cfg.get("_produces"):
        declared = _declared_kinds(cfg)
        got = {a.get("kind") for a in artifacts if a.get("kind")}
        if declared and not (declared & got):
            result["message"] = (
                f"skill {skill_id} 进入人审但必产出未齐"
                f"（需要 {sorted(declared)}，"
                f"实际 {sorted(k for k in got if k)}）"
            )
            return "error"
    return status


async def _save_status(ctx: ResultContext, new_status: str, **fields) -> None:
    # 保留收到时的 JSON 快照；人审缺产物时，诊断会使用后来补写的错误原因。
    await ctx.db.update("tickets", {
        "status": new_status, "result": ctx.result_json, **fields, "updated_at": now_iso(),
    }, "id = ?", (ctx.ticket_id,))


async def _record_waiting(ctx: ResultContext, run: _SkillRun, new_status: str) -> None:
    gate_files = skill_gate_file_paths(ctx.result)
    waiting = ctx.result.get("waiting_human") or {}
    if not isinstance(waiting, dict):
        waiting = {}
    await _save_status(ctx, new_status)
    await ctx.orch._log(
        ctx.project_id, ctx.requirement_id, ctx.ticket_id, ctx.agent_name,
        "complete", ctx.current_status, new_status,
        f"skill {run.skill_id} 等待人工确认（{run.rounds} 轮）", "info",
        detail_data={
            "skill_id": run.skill_id, "skill_status": run.status,
            "outputs": run.outputs[:20], "rounds": run.rounds, "run_as_agent": ctx.agent_name,
            "files": gate_files[:20], "file_paths": gate_files[:20],
            "gate_message_id": waiting.get("_message_id") or "",
            "gate_session_id": waiting.get("session_id") or "",
        },
    )
    lines = [f"⏸ skill `{run.skill_id}` 已产出，等待确认。"]
    if gate_files:
        lines.append("产物：" + "、".join(f"`{p}`" for p in gate_files[:8]))
    if waiting.get("_message_id"):
        lines.append("确认卡已发到对话，也可在工单里直接确认。")
    await ctx.orch._write_phase_comment(
        ctx.project_id, ctx.ticket_id, ctx.agent_name, "\n".join(lines), phase=new_status,
    )


async def _record_completion(ctx: ResultContext, run: _SkillRun, new_status: str) -> None:
    await _save_status(ctx, new_status)
    kinds = [a.get("kind") for a in run.artifacts if a.get("kind")]
    partial = run.status == "partial"
    await ctx.orch._log(
        ctx.project_id, ctx.requirement_id, ctx.ticket_id, ctx.agent_name,
        "complete", ctx.current_status, new_status,
        f"skill {run.skill_id} {'部分完成' if partial else '完成'}"
        f"（{run.rounds} 轮，{len(run.outputs)} 个产出）",
        "warning" if partial else "info",
        detail_data={
            "skill_id": run.skill_id, "skill_status": run.status,
            "outputs": run.outputs[:20], "artifact_kinds": kinds,
            "rounds": run.rounds, "run_as_agent": ctx.agent_name,
        },
    )
    await ctx.orch._write_phase_comment(
        ctx.project_id, ctx.ticket_id, ctx.agent_name,
        f"{'⚠️' if partial else '✅'} skill `{run.skill_id}` 执行完成"
        + (f"，产出：{', '.join(kinds)}" if kinds else "")
        + (f"\n{str(ctx.result.get('message') or '')[:200]}" if partial else ""),
        phase=new_status,
    )


async def _record_skip(ctx: ResultContext, run: _SkillRun, new_status: str) -> None:
    # 跳到成功态，避免同一条规则反复命中不可用的 skill。
    await _save_status(ctx, new_status)
    await ctx.orch._log(
        ctx.project_id, ctx.requirement_id, ctx.ticket_id, ctx.agent_name,
        "skip", ctx.current_status, new_status,
        f"skill {run.skill_id} 不可用，已跳过 | {str(ctx.result.get('message') or '')[:200]}",
        "warning",
        detail_data={
            "skill_id": run.skill_id, "reason": ctx.result.get("message"), "run_as_agent": ctx.agent_name,
        },
    )


async def _record_blocked(ctx: ResultContext, run: _SkillRun, new_status: str) -> None:
    """失败不自动重试；用本地诊断同时更新工单和通知。"""
    fail_msg = str(ctx.result.get("message") or f"skill {run.skill_id} 未成功")
    try:
        rows = await ctx.db.fetch_all(
            "SELECT path FROM artifacts WHERE ticket_id = ? ORDER BY created_at DESC LIMIT 20",
            (ctx.ticket_id,),
        )
        extra_files = [r.get("path") for r in (rows or []) if r.get("path")]
    except Exception:
        extra_files = []
    diagnosis = ctx.synthesize_blocked_diagnosis(
        skill_id=str(run.skill_id or ""), skill_status=str(run.status or ""),
        error_msg=fail_msg, action=ctx.action, outputs=run.outputs,
        artifacts=run.artifacts, extra_files=extra_files,
    )
    await _save_status(ctx, new_status, diagnosis=json.dumps(diagnosis, ensure_ascii=False))
    await ctx.orch._log(
        ctx.project_id, ctx.requirement_id, ctx.ticket_id, ctx.agent_name,
        "blocked", ctx.current_status, new_status,
        f"skill {run.skill_id} 执行失败（{run.status}），已标记 blocked "
        f"等待人工介入 | {fail_msg[:300]}", "error",
        detail_data={
            "skill_id": run.skill_id, "skill_status": run.status,
            "error": fail_msg, "outputs": run.outputs[:20], "rounds": run.rounds,
            "run_as_agent": ctx.agent_name,
        },
    )
    await ctx.orch._write_phase_comment(
        ctx.project_id, ctx.ticket_id, ctx.agent_name,
        f"❌ skill `{run.skill_id}` 执行失败（{run.status}），需人工介入。\n{fail_msg[:300]}",
        phase=new_status,
    )
    await event_manager.publish_to_project(
        ctx.project_id, "ticket_blocked",
        {"ticket_id": ctx.ticket_id, "from": ctx.current_status, "to": new_status,
         "agent": ctx.agent_name, "action": ctx.action, "error": fail_msg[:300], "diagnosis": diagnosis},
    )
    await event_manager.publish_to_project(
        ctx.project_id, "ticket_diagnosed", {"ticket_id": ctx.ticket_id, "diagnosis": diagnosis},
    )


async def _publish_and_continue(ctx: ResultContext, new_status: str) -> None:
    await event_manager.publish_to_project(
        ctx.project_id, "ticket_status_changed",
        {"ticket_id": ctx.ticket_id, "from": ctx.current_status,
         "to": new_status, "agent": ctx.agent_name},
    )
    if (new_status == ctx.current_status or new_status == TicketStatus.BLOCKED.value
            or str(new_status).endswith("_ready")):
        return
    await asyncio.sleep(0.5)
    updated = await ctx.db.fetch_one("SELECT status FROM tickets WHERE id = ?", (ctx.ticket_id,))
    if updated:
        rules = await ctx.orch._get_rules_for_project(ctx.project_id, ticket_type=ctx.ticket.get("type"))
        if updated["status"] in rules:
            await ctx.orch.process_ticket(ctx.project_id, ctx.ticket_id)


async def _resolve_skill_success_status(
    orch: Any,
    project_id: str,
    action: str,
    result: Dict,
    sop_cfg: Dict,
    ticket_type: Optional[str],
) -> str:
    """skill stage 的成功态。三级回退，优先用零成本的来源。"""
    direct = result.get("success_status") or sop_cfg.get("_success_status")
    if direct:
        return str(direct)

    stage = await orch._sop_stage_for(project_id, action, ticket_type)
    if stage and stage.get("success_status"):
        return str(stage["success_status"])

    # action 形如 `skill_demo_draft`（见 workflow_composer._stage_action）
    stage_id = sop_cfg.get("_stage_id") or action.removeprefix("skill_")
    fallback = f"{stage_id}_done"
    logger.warning(
        "SkillAgent 结果缺 success_status，按约定推导为 '%s'（action=%s）",
        fallback, action,
    )
    return fallback


def _declared_kinds(sop_cfg: Dict) -> set:
    return {
        p.get("kind") for p in (sop_cfg.get("_produces") or [])
        if isinstance(p, dict) and p.get("kind")
    }


def skill_produces_satisfied(sop_cfg: Dict, artifacts: List[Dict]) -> bool:
    """x-workflow.produces 声明的 kind 是否都已登记。

    用于 budget_exceeded 的豁免判断。没有 produces 声明（老 skill）时
    返回 False —— 无从判断是否齐全，宁可按失败处理交人工。
    """
    declared = _declared_kinds(sop_cfg)
    if not declared:
        return False
    got = {a.get("kind") for a in artifacts if a.get("kind")}
    return declared.issubset(got)


def skill_gate_file_paths(result: Dict) -> List[str]:
    """人审节点给工单看的产物路径：优先确认卡 preview，其次产物总线，再补 skill 相对路径。"""
    paths: List[str] = []
    seen = set()

    def add(raw: Any) -> None:
        s = str(raw or "").replace("\\", "/").strip().lstrip("./")
        if not s or s.endswith(".ads-waiting-human.json") or s in seen:
            return
        seen.add(s)
        paths.append(s)

    waiting = result.get("waiting_human") if isinstance(result.get("waiting_human"), dict) else {}
    for p in (waiting or {}).get("preview_paths") or []:
        add(p)
    for item in (waiting or {}).get("preview_urls") or []:
        if isinstance(item, dict):
            add(item.get("path"))
    for art in result.get("artifacts") or []:
        if isinstance(art, dict):
            add(art.get("path"))
    for out in result.get("outputs") or []:
        s = str(out or "").replace("\\", "/").strip().lstrip("./")
        if not s:
            continue
        if s.startswith(("works/", "artifacts/", "docs/")):
            add(s)
        elif "/" in s:
            add("works/" + s)
        else:
            add(s)
    return paths[:20]
