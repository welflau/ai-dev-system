"""工单阶段重置和状态回退。

评论触发返工、变更影响分析、人工重置都走 `reset_phases`：先清掉指定阶段之后的产出标记，
再把工单状态退回该阶段的入口状态，由轮询或事件重新派单。工单正在执行时不直接改状态，
目标状态记在 `orch._pending_restart` 里，等在途的 Agent 收尾后由 `process_ticket` 改写。

`is_forward_jump` 用 SOP 的状态线性序判断一次改写是不是跳过了中间阶段，回退路径上
遇到前跳一律拒绝。

约定（`orchestration` 包里按职责拆出的模块都一样）：

- 函数体从 `TicketOrchestrator` 的同名方法原样搬来，函数名去掉了前导下划线。改动只有
  `self` 写成 `orch`，以及下面单独列出的几处。
- `TicketOrchestrator` 上保留同名方法，只做转发。这里的函数互相调用、调用别的模块里的
  逻辑都走 `orch.xxx`，测试给实例打的桩才会生效。
- `db` 由转发方法在调用时传入，这里不导入它。测试用
  `monkeypatch.setattr(orchestrator, "db", test_db)` 换库，函数必须拿到同一个对象。
- 状态都放在 `orch` 上，这个模块自己不存状态。
- 函数内的延迟导入保持原样，测试的打桩打在这些源模块上。

这个模块多出的一处改动：`seq_index` 原来读 `TicketOrchestrator._STATUS_SUFFIXES`，
这里不能导入 `orchestrator`，改成读本模块的 `STATUS_SUFFIXES`。类上的同名属性指向同一个对象。
"""
import json
import logging
from typing import List, Optional

from events import event_manager
from models import TicketStatus
from utils import now_iso

logger = logging.getLogger("orchestrator")

PHASE_ORDER = [
    "propose", "architecture", "development",
    "testing", "verify", "review", "deploy",
]
MAX_RESET_COUNT = 3  # 超过此次数自动 blocked

# 阶段 → 「重跑该阶段所需的入口状态」。
# 写的是 *触发* 状态而不是阶段自身状态：orchestrator 靠 SOP 的 trigger_on 派单，
# 把 status 退回上一阶段的 success_status，下一轮轮询/事件才会重新派发该阶段。
# 例：development 要重跑 → status 退到 architecture_done（development 的 trigger_on）。
PHASE_ENTRY_STATUS = {
    "propose": TicketStatus.PLANNING_DONE.value,
    "architecture": TicketStatus.PLANNING_DONE.value,
    "development": TicketStatus.ARCHITECTURE_DONE.value,
    "testing": TicketStatus.ACCEPTANCE_PASSED.value,
    "verify": TicketStatus.ACCEPTANCE_PASSED.value,
    "review": TicketStatus.DEVELOPMENT_DONE.value,
    "deploy": TicketStatus.ACCEPTANCE_PASSED.value,
}


async def resolve_phase_entry_status(
    orch, db, project_id: str, from_phase: str, ticket_type: Optional[str] = None,
) -> Optional[str]:
    """查该项目 SOP 里重跑 `from_phase` 应该退回的状态。

    优先读 SOP（trait-first 项目插了 fragment 后，development 的 trigger_on 可能
    不是 architecture_done），SOP 里查不到再用 `_PHASE_ENTRY_STATUS` 兜底。
    """
    # SOP 的 stage id 与 PHASE_ORDER 命名并不完全一致
    stage_aliases = {
        "development": ("development",),
        "architecture": ("architecture",),
        "testing": ("testing", "smoke_test", "play_test", "h5_typecheck", "h5_playtest"),
        "review": ("code_review",),
        "deploy": ("deploy",),
        "verify": ("testing",),
        "propose": ("planning", "architecture"),
    }.get(from_phase, (from_phase,))

    try:
        row = await db.fetch_one(
            "SELECT traits FROM projects WHERE id = ?", (project_id,)
        )
        traits = json.loads((row or {}).get("traits") or "[]")
        if isinstance(traits, list) and traits:
            from sop.loader import compose_sop
            stages = compose_sop(traits=traits, ticket_type=ticket_type).get("stages", [])
        else:
            stages = (orch._sop_config or {}).get("stages", [])

        for sid in stage_aliases:
            for stage in stages:
                if stage.get("id") == sid and stage.get("trigger_on"):
                    return stage["trigger_on"]
    except Exception as e:
        logger.debug("_resolve_phase_entry_status 读 SOP 失败，用兜底表: %s", e)

    return orch._PHASE_ENTRY_STATUS.get(from_phase)


async def reset_phases(
    orch, db,
    ticket_id: str,
    project_id: str,
    from_phase: str,
    reason: str,
) -> bool:
    """
    将指定阶段及后续所有阶段重置为 pending，并把工单退回该阶段入口状态重新跑。
    保留历史日志（可追溯），返回是否成功。
    reset_count >= MAX_RESET_COUNT 时自动 blocked 并通知人工介入。
    """
    try:
        idx = orch.PHASE_ORDER.index(from_phase)
    except ValueError:
        logger.warning("reset_phases: 未知 phase '%s'", from_phase)
        return False

    phases_to_reset = orch.PHASE_ORDER[idx:]
    ts = now_iso()

    # 检查重置次数（取 from_phase 的 reset_count）
    row = await db.fetch_one(
        "SELECT reset_count FROM ticket_phase_status WHERE ticket_id=? AND phase=?",
        (ticket_id, from_phase),
    )
    current_count = (row or {}).get("reset_count", 0)
    new_count = current_count + 1

    if new_count > orch.MAX_RESET_COUNT:
        # 超过阈值 → blocked，等待人工
        await db.execute(
            "UPDATE tickets SET status='blocked', updated_at=? WHERE id=?",
            (ts, ticket_id),
        )
        orch._pending_restart.pop(ticket_id, None)
        await orch.post_milestone_comment(
            ticket_id, project_id,
            f"⚠️ 阶段 `{from_phase}` 已重置 {new_count} 次，超过上限（{orch.MAX_RESET_COUNT}次），"
            f"工单已暂停，请人工介入确认方向。\n原因：{reason}",
            level="error",
        )
        logger.warning("reset_phases: ticket %s 超过重置上限，自动 blocked", ticket_id)
        return False

    # 更新/插入阶段状态
    for phase in phases_to_reset:
        existing = await db.fetch_one(
            "SELECT reset_count FROM ticket_phase_status WHERE ticket_id=? AND phase=?",
            (ticket_id, phase),
        )
        if existing:
            await db.execute(
                """UPDATE ticket_phase_status
                       SET status='pending', reset_count=reset_count+1,
                           last_reset_reason=?, last_reset_at=?, completed_at=NULL
                       WHERE ticket_id=? AND phase=?""",
                (reason, ts, ticket_id, phase),
            )
        else:
            await db.insert("ticket_phase_status", {
                "ticket_id": ticket_id, "phase": phase,
                "status": "pending", "reset_count": 1,
                "last_reset_reason": reason, "last_reset_at": ts,
            })

    # 写时间轴日志
    await orch._add_layer_log(
        ticket_id, project_id,
        action="phase_reset", layer="harness",
        detail={
            "from_phase": from_phase,
            "phases": phases_to_reset,
            "reason": reason,
            "reset_count": new_count,
        },
    )

    # === 真正把工单退回去重跑 ===
    # ticket_phase_status 只是审计记录，orchestrator 派单看的是 tickets.status，
    # 光写上面那张表工单会原地不动（用户却看到「已重置」）。
    restarted = await orch._rewind_ticket_status(
        ticket_id, project_id, from_phase, reason,
    )

    logger.info(
        "reset_phases: ticket %s from=%s reason=%s restarted=%s",
        ticket_id, from_phase, reason, restarted,
    )
    return True


async def sop_status_sequence(
    orch, db, project_id: str, ticket_type: Optional[str] = None,
) -> List[str]:
    """该项目 SOP 线性主链上的状态顺序。

    用于判断「回退」是否真的在往后退 —— 工单还没跑到 development 时把 status
    改成 architecture_done 是**前跳**，会把架构阶段整段跳过。

    复用 loader 的 `_statuses_for_sop_stage`：它每个 stage 收 [in_progress,
    success_status, reject_status]，**带上了执行中态**。只收 trigger_on /
    success_status 是不够的 —— 那样 architecture_in_progress 之类的执行中态
    根本不在序列里，防前跳判断会静默失效。
    branch_only 的 stage（rework 等）不在主链上，不参与排序。
    """
    seq: List[str] = ["pending"]
    try:
        from sop.loader import _statuses_for_sop_stage, _TERMINAL_STATUSES

        row = await db.fetch_one(
            "SELECT traits FROM projects WHERE id = ?", (project_id,)
        )
        traits = json.loads((row or {}).get("traits") or "[]")
        if isinstance(traits, list) and traits:
            from sop.loader import compose_sop
            stages = compose_sop(traits=traits, ticket_type=ticket_type).get("stages", [])
        else:
            stages = (orch._sop_config or {}).get("stages", [])

        for stage in stages:
            if stage.get("branch_only"):
                continue
            for val in _statuses_for_sop_stage(stage):
                if val not in seq:
                    seq.append(val)
        for val in _TERMINAL_STATUSES:
            if val not in seq:
                seq.append(val)
    except Exception as e:
        logger.debug("_sop_status_sequence 失败: %s", e)
    return seq


# 状态后缀 → 去掉后得到「阶段词根」，用于把序列里没显式出现的状态定位到
# 它所属阶段。loader._get_next_status 是张硬编码表（只覆盖 Architect/Dev/Test），
# review_in_progress / acceptance_in_progress 这些不在表里，缺了它们防前跳
# 判断会漏。按词根归位比继续堆表可靠。
STATUS_SUFFIXES = ("_in_progress", "_done", "_passed", "_failed", "_rejected")


async def is_forward_jump(
    orch,
    project_id: str,
    current_status: str,
    target_status: str,
    ticket_type: Optional[str] = None,
) -> bool:
    """把 status 从 current 改成 target 是否属于「前跳」（跳过中间阶段）。

    无法定位其中任一状态（如 blocked / fragment 派生态）时返回 False —— 宁可
    放行也不要静默拦掉正常回退。
    """
    seq = await orch._sop_status_sequence(project_id, ticket_type)
    cur_idx = orch._seq_index(seq, current_status)
    tgt_idx = orch._seq_index(seq, target_status)
    return cur_idx is not None and tgt_idx is not None and tgt_idx > cur_idx


def seq_index(seq: List[str], status: str) -> Optional[int]:
    """status 在线性序中的位置；不在序列里则按阶段词根归到同阶段最早的位置。"""
    if not status:
        return None
    if status in seq:
        return seq.index(status)

    root = status
    for suffix in STATUS_SUFFIXES:
        if status.endswith(suffix):
            root = status[: -len(suffix)]
            break
    if root == status:
        return None  # 无法识别词根（如 deploying），不参与判断

    prefix = root + "_"
    for i, s in enumerate(seq):
        if s == root or s.startswith(prefix):
            return i
    return None


async def rewind_ticket_status(
    orch, db,
    ticket_id: str,
    project_id: str,
    from_phase: str,
    reason: str,
) -> bool:
    """把 tickets.status 退回 from_phase 的入口状态并触发重新派单。

    工单正在执行时不能直接改 —— 在途 Agent 收尾会用旧上下文覆盖 status。
    这种情况登记 `_pending_restart`，由 process_ticket 的 finally 收口时应用。
    """
    ticket = await db.fetch_one(
        "SELECT status, type FROM tickets WHERE id = ?", (ticket_id,)
    )
    if not ticket:
        return False

    current_status = ticket.get("status") or ""
    if current_status in orch._HARD_TERMINAL:
        logger.info(
            "⏭ 工单 %s 已终态 %s，不做阶段回退", ticket_id[:12], current_status,
        )
        return False

    ticket_type = ticket.get("type")
    target = await orch._resolve_phase_entry_status(
        project_id, from_phase, ticket_type,
    )
    if not target:
        logger.warning(
            "reset_phases: 无法确定 phase '%s' 的入口状态，工单 %s 未回退",
            from_phase, ticket_id[:12],
        )
        return False

    if target == current_status:
        # 已经站在入口状态上（如刚被打回），无需改写，直接催一脚重跑
        await orch._publish_ticket_ready(project_id, ticket_id)
        return True

    # 防前跳：工单还没跑到该阶段时，回退目标可能在当前状态之后，
    # 直接改写会把中间阶段整段跳过。此时不动 status，评论已作为
    # human_instructions 注入，工单跑到该阶段自然会读到。
    if await orch._is_forward_jump(project_id, current_status, target, ticket_type):
        logger.info(
            "⏭ 工单 %s 尚未跑到 %s 阶段（当前 %s），跳过回退，评论已作为指令注入",
            ticket_id[:12], from_phase, current_status,
        )
        return False

    # 在途执行：延后应用，避免被 Agent 结果覆盖
    if ticket_id in orch._processing:
        orch._pending_restart[ticket_id] = {
            "status": target,
            "reason": reason,
            "from_phase": from_phase,
        }
        logger.info(
            "⏳ 工单 %s 正在执行，阶段回退 → %s 已排队（等在途 run 收尾）",
            ticket_id[:12], target,
        )
        return True

    await orch._apply_status_rewind(ticket_id, project_id, current_status, target, reason)
    return True


async def apply_status_rewind(
    orch, db,
    ticket_id: str,
    project_id: str,
    from_status: str,
    target_status: str,
    reason: str,
) -> None:
    """写回退状态 + 记日志 + 发 ticket_ready 让 orchestrator 立刻重新派单。"""
    await db.update("tickets", {
        "status": target_status,
        "updated_at": now_iso(),
    }, "id = ?", (ticket_id,))

    requirement_id = None
    try:
        row = await db.fetch_one(
            "SELECT requirement_id FROM tickets WHERE id = ?", (ticket_id,)
        )
        requirement_id = (row or {}).get("requirement_id")
    except Exception:
        pass

    await orch._log(
        project_id, requirement_id, ticket_id, "Orchestrator",
        "phase_rewind", from_status, target_status,
        f"阶段重置：工单退回 {target_status} 重新执行 | {reason}"[:500],
        detail_data={"reason": reason},
    )
    await event_manager.publish_to_project(project_id, "ticket_status_changed", {
        "ticket_id": ticket_id,
        "from_status": from_status,
        "to_status": target_status,
    })
    await orch._publish_ticket_ready(project_id, ticket_id)
