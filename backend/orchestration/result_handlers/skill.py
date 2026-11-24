"""skill 阶段的结果处理器。

从 `TicketOrchestrator._handle_skill_agent_result` 和它的三个辅助方法原样搬出
（重构方案 R2 第 1 步的收尾），逻辑未改。和原文的差别只有四处：

- `self` 写成 `orch`，共享的局部变量从 `ctx` 取；
- 三个辅助方法改成本模块的函数，其中两个原来是静态方法，去掉了下划线前缀；
- 本地诊断说明由 `ctx.synthesize_blocked_diagnosis` 提供，本模块不导入 `actions`；
- 函数末尾补了 `return HANDLED`。

这个处理器自己发 `ticket_status_changed`，自己决定要不要继续派单，所以总是返回 HANDLED。
它不在按 Agent 名查的注册表里：skill 结果由调用方用 `is_skill_run_result` 识别，
宿主 Role 可以是任何 Agent。
"""
import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from events import event_manager
from models import TicketStatus
from orchestration.result_handlers.context import HANDLED, ResultContext
from utils import now_iso

# 沿用拆分前的 logger 名，现有的日志过滤和采集规则不受影响。
logger = logging.getLogger("orchestrator")


async def handle_skill(ctx: ResultContext) -> Optional[str]:
    """Skill 阶段的结果 → 推进状态 + 登记产物。

    为什么必须有这个分支：缺了它结果会落到 `_handle_agent_result` 末尾的
    `else: new_status = current_status` —— 状态不推进，同一条 rule 反复命中，
    skill 被无限重跑烧 token。ArtistAgent 和 UEEditorAgent 的注释都
    记着同一个坑，它们都是踩了才补的分支。

    `agent_name` 是 SOP 上的宿主 Role（可能是 PlannerAgent 等），不是
    执行引擎 SkillAgent。时间轴 / 评论 / SSE 记宿主。

    状态来源优先级：
      1. `result["success_status"]` —— SkillAgent 从 sop_config 回传，最可靠
         且零 DB 查询（compose_sop 单次 53ms）
      2. `_sop_stage_for` 反查 —— 兼容手工构造的 context
      3. `skill_{action}_done` 约定推导 —— 最后兜底

    Agent 返回 status=error 已在函数开头统一转 blocked，这里只处理
    success / partial / skipped / budget_exceeded。
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

    sop_cfg = result.get("sop_config") or {}
    skill_id = result.get("skill_id") or sop_cfg.get("skill_id") or "?"
    skill_status = result.get("skill_status") or result.get("status") or ""
    outputs = result.get("outputs") or []
    artifacts = result.get("artifacts") or []
    rounds = result.get("rounds") or 0

    success_status = await _resolve_skill_success_status(
        orch, project_id, action, result, sop_cfg, ticket.get("type"),
    )

    # budget_exceeded 但 produces 声明的 kind 全部拿到了 → 按成功处理。
    # 理由：query_engine/engine.py:391 的 Budget.check() 只在**轮与轮之间**
    # 生效。像 gen_image 这种阻塞几十秒的工具，跑完回来下一轮开头就可能
    # 触发超时 —— 此时图已经落盘了，判 blocked 等于白烧一次钱。
    if skill_status == "budget_exceeded" and skill_produces_satisfied(
        sop_cfg, artifacts
    ):
        logger.info(
            "⏱ skill %s 超预算但产出齐全（%d 个），按成功处理",
            skill_id, len(artifacts),
        )
        skill_status = "partial"

    if skill_status == "waiting_human" and (sop_cfg.get("_produces") or []):
        declared = {
            p.get("kind") for p in (sop_cfg.get("_produces") or [])
            if isinstance(p, dict) and p.get("kind")
        }
        got = {a.get("kind") for a in artifacts if a.get("kind")}
        # 人审看的是「这次有没有做出要审的东西」。clip-trial 还会声明
        # voice_anchor，visual 还会声明 scene_bible，Mode 不同并不都会落盘，
        # 不能按「声明的 kind 一个不漏」卡死。空产出才是上次那种假确认卡。
        if declared and not (declared & got):
            fail_msg = (
                f"skill {skill_id} 进入人审但必产出未齐"
                f"（需要 {sorted(declared)}，"
                f"实际 {sorted(k for k in got if k)}）"
            )
            skill_status = "error"
            result["message"] = fail_msg

    if skill_status == "waiting_human":
        new_status = (
            sop_cfg.get("_ready_status")
            or result.get("success_status")
            or f"{sop_cfg.get('_stage_id') or skill_id}_ready"
        )
        gate_files = skill_gate_file_paths(result)
        waiting_human = result.get("waiting_human") or {}
        if not isinstance(waiting_human, dict):
            waiting_human = {}
        await db.update("tickets", {
            "status": new_status, "result": result_json, "updated_at": now_iso(),
        }, "id = ?", (ticket_id,))
        await orch._log(
            project_id, requirement_id, ticket_id, agent_name,
            "complete", current_status, new_status,
            f"skill {skill_id} 等待人工确认（{rounds} 轮）",
            "info",
            detail_data={
                "skill_id": skill_id, "skill_status": skill_status,
                "outputs": outputs[:20], "rounds": rounds,
                "run_as_agent": agent_name,
                "files": gate_files[:20],
                "file_paths": gate_files[:20],
                "gate_message_id": waiting_human.get("_message_id") or "",
                "gate_session_id": waiting_human.get("session_id") or "",
            },
        )
        comment_lines = [f"⏸ skill `{skill_id}` 已产出，等待确认。"]
        if gate_files:
            comment_lines.append(
                "产物：" + "、".join(f"`{p}`" for p in gate_files[:8])
            )
        if waiting_human.get("_message_id"):
            comment_lines.append("确认卡已发到对话，也可在工单里直接确认。")
        await orch._write_phase_comment(
            project_id, ticket_id, agent_name,
            "\n".join(comment_lines),
            phase=new_status,
        )
    elif skill_status in ("success", "partial"):
        new_status = success_status
        await db.update("tickets", {
            "status": new_status, "result": result_json, "updated_at": now_iso(),
        }, "id = ?", (ticket_id,))
        kinds = [a.get("kind") for a in artifacts if a.get("kind")]
        await orch._log(
            project_id, requirement_id, ticket_id, agent_name,
            "complete", current_status, new_status,
            f"skill {skill_id} {'部分完成' if skill_status == 'partial' else '完成'}"
            f"（{rounds} 轮，{len(outputs)} 个产出）",
            "warning" if skill_status == "partial" else "info",
            detail_data={
                "skill_id": skill_id, "skill_status": skill_status,
                "outputs": outputs[:20], "artifact_kinds": kinds,
                "rounds": rounds, "run_as_agent": agent_name,
            },
        )
        await orch._write_phase_comment(
            project_id, ticket_id, agent_name,
            f"{'⚠️' if skill_status == 'partial' else '✅'} "
            f"skill `{skill_id}` 执行完成"
            + (f"，产出：{', '.join(kinds)}" if kinds else "")
            + (f"\n{str(result.get('message') or '')[:200]}"
               if skill_status == "partial" else ""),
            phase=new_status,
        )

    elif skill_status == "skipped":
        # availability 不满足（如 skill 依赖的 CLI 没装）→ 跳到成功态。
        # 不能停在原状态：那条 rule 会反复命中同一个不可用的 skill。
        new_status = success_status
        await db.update("tickets", {
            "status": new_status, "result": result_json, "updated_at": now_iso(),
        }, "id = ?", (ticket_id,))
        await orch._log(
            project_id, requirement_id, ticket_id, agent_name,
            "skip", current_status, new_status,
            f"skill {skill_id} 不可用，已跳过 | "
            f"{str(result.get('message') or '')[:200]}",
            "warning",
            detail_data={
                "skill_id": skill_id, "reason": result.get("message"),
                "run_as_agent": agent_name,
            },
        )

    else:
        # budget_exceeded（产出不全）/ 未知状态 → blocked 等人工。
        # **刻意不自动重试**：skill 是 LLM 自由发挥的，重跑一次就再烧一轮
        # token，而失败原因（prompt 不清楚 / 工具不可用 / 预算太紧）
        # 重跑都解决不了。workflow_composer 也因此不给 skill stage 配
        # reject_goto（否则 sop_to_transition_rules 会派生无限重试规则）。
        new_status = TicketStatus.BLOCKED.value
        fail_msg = str(result.get("message") or f"skill {skill_id} 未成功")
        extra_files = []
        try:
            art_rows = await db.fetch_all(
                "SELECT path FROM artifacts WHERE ticket_id = ? "
                "ORDER BY created_at DESC LIMIT 20",
                (ticket_id,),
            )
            extra_files = [r.get("path") for r in (art_rows or []) if r.get("path")]
        except Exception:
            extra_files = []
        diagnosis = ctx.synthesize_blocked_diagnosis(
            skill_id=str(skill_id or ""),
            skill_status=str(skill_status or ""),
            error_msg=fail_msg,
            action=action,
            outputs=outputs,
            artifacts=artifacts,
            extra_files=extra_files,
        )
        await db.update("tickets", {
            "status": new_status,
            "result": result_json,
            "diagnosis": json.dumps(diagnosis, ensure_ascii=False),
            "updated_at": now_iso(),
        }, "id = ?", (ticket_id,))
        await orch._log(
            project_id, requirement_id, ticket_id, agent_name,
            "blocked", current_status, new_status,
            f"skill {skill_id} 执行失败（{skill_status}），已标记 blocked "
            f"等待人工介入 | {fail_msg[:300]}",
            "error",
            detail_data={
                "skill_id": skill_id, "skill_status": skill_status,
                "error": fail_msg, "outputs": outputs[:20], "rounds": rounds,
                "run_as_agent": agent_name,
            },
        )
        await orch._write_phase_comment(
            project_id, ticket_id, agent_name,
            f"❌ skill `{skill_id}` 执行失败（{skill_status}），需人工介入。"
            f"\n{fail_msg[:300]}",
            phase=new_status,
        )
        await event_manager.publish_to_project(
            project_id, "ticket_blocked",
            {
                "ticket_id": ticket_id,
                "from": current_status,
                "to": new_status,
                "agent": agent_name,
                "action": action,
                "error": fail_msg[:300],
                "diagnosis": diagnosis,
            },
        )
        # CLI 刚超时再调 LLM 诊断会再卡一轮。skill 失败用本地说明即可。
        await event_manager.publish_to_project(
            project_id, "ticket_diagnosed",
            {"ticket_id": ticket_id, "diagnosis": diagnosis},
        )

    await event_manager.publish_to_project(
        project_id, "ticket_status_changed",
        {"ticket_id": ticket_id, "from": current_status,
         "to": new_status, "agent": agent_name},
    )

    # 推进到下一阶段。和函数末尾的通用收尾逻辑一致 —— 这里 early-return
    # 了所以必须自己做，否则 skill 链会在第一个 stage 之后停住，
    # 只能等 30s 的 poll_loop 兜底（poll 间隔见 poll_loop 的默认参数）。
    if (
        new_status != current_status
        and new_status != TicketStatus.BLOCKED.value
        and not str(new_status).endswith("_ready")
    ):
        await asyncio.sleep(0.5)
        updated = await db.fetch_one(
            "SELECT status FROM tickets WHERE id = ?", (ticket_id,)
        )
        if updated:
            rules = await orch._get_rules_for_project(
                project_id, ticket_type=ticket.get("type"),
            )
            if updated["status"] in rules:
                await orch.process_ticket(project_id, ticket_id)

    return HANDLED


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


def skill_produces_satisfied(sop_cfg: Dict, artifacts: List[Dict]) -> bool:
    """x-workflow.produces 声明的 kind 是否都已登记。

    用于 budget_exceeded 的豁免判断。没有 produces 声明（老 skill）时
    返回 False —— 无从判断是否齐全，宁可按失败处理交人工。
    """
    declared = {
        p.get("kind") for p in (sop_cfg.get("_produces") or [])
        if isinstance(p, dict) and p.get("kind")
    }
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
