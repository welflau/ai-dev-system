"""轮询调度的周边：工单占用和入队，事件总线，僵尸工单回退，卡住的需求和父工单的恢复。

工单有两条被派出去的路。事件路径：上一个阶段收尾时 `publish_ticket_ready` 发事件，
`start_event_bus` 里订阅的回调直接调 `orch.process_ticket`。轮询路径：`poll_loop` 定时调
`orch._poll_once` 扫库兜底，扫到的工单经 `enqueue_ticket` 占项目槽后建任务跑 `poll_process`。

`ticket_held_by_this_process`、`zombie_rewind_status`、`repair_status_outside_sop` 给轮询判断
一张停在执行中状态的工单是还在跑、该回退重跑、还是状态不在当前 SOP 里需要修。

单次轮询与子工单完成检查在同包的 `poll_cycle`；轮询循环经 `orch._poll_once` 调用。

约定（`orchestration` 包里按职责拆出的模块都一样）：

- 函数体从 `TicketOrchestrator` 的同名方法原样搬来，函数名去掉了前导下划线。改动只有
  `self` 写成 `orch`，以及下面单独列出的几处。
- `TicketOrchestrator` 上保留同名方法，只做转发。这里的函数互相调用、调用别的模块里的
  逻辑都走 `orch.xxx`，测试给实例打的桩才会生效。
- `db` 由转发方法在调用时传入，这里不导入它。测试用
  `monkeypatch.setattr(orchestrator, "db", test_db)` 换库，函数必须拿到同一个对象。
- 状态都放在 `orch` 上，这个模块自己不存状态。
- 函数内的延迟导入保持原样，测试的打桩打在这些源模块上。
"""
import asyncio
import json
import logging
from typing import Optional

from events import event_manager
from models import TicketStatus
from utils import generate_id, now_iso

logger = logging.getLogger("orchestrator")


def try_claim_ticket(orch, ticket_id: str) -> bool:
    """无 await 地占用工单处理权。已占用则返回 False（asyncio 单线程下 check+add 原子）。"""
    if ticket_id in orch._processing:
        return False
    orch._processing.add(ticket_id)
    return True


def release_ticket(orch, ticket_id: str) -> None:
    orch._processing.discard(ticket_id)


def ticket_held_by_this_process(orch, ticket_id: str) -> bool:
    """本进程还在跑这张工单：禁止当成僵尸回退。

    实测：write_prd 等模型首包时 `_processing` 可能已被外部 `_release_ticket`
    清掉、CLI 也没登记上，但 process_ticket 协程和 Agent 状态仍是 working。
    只看集合会把活任务 78s 后打回 pending。
    """
    if not ticket_id:
        return False
    task = (orch._running_tasks or {}).get(ticket_id)
    if task is not None and not task.done():
        return True
    if ticket_id in orch._processing:
        return True
    for info in (orch._agent_status or {}).values():
        if info.get("status") == "working" and info.get("ticket_id") == ticket_id:
            return True
    for held in orch._project_active.values():
        if ticket_id in held:
            return True
    for held in orch._project_subtask_active.values():
        if ticket_id in held:
            return True
    try:
        from llm_client import ticket_has_live_cli
        if ticket_has_live_cli(ticket_id):
            return True
    except Exception:
        pass
    return False


async def ticket_heartbeat(orch, db, ticket_id: str, interval: float = 20.0):
    """等模型首包时可能几分钟没有 log。不刷新 updated_at，60s 僵尸门会误杀。"""
    while True:
        await asyncio.sleep(interval)
        try:
            await db.update(
                "tickets", {"updated_at": now_iso()}, "id = ?", (ticket_id,),
            )
        except Exception:
            pass


def enqueue_ticket(
    orch, project_id: str, ticket_id: str, *, is_subtask: bool = False, source: str = "",
) -> bool:
    """轮询侧调度：占项目槽 + create_task(_poll_process)。

    续跑走 ticket_ready → process_ticket，不经过这里。所以这里可以（也应该）
    拒绝已在处理 / 已占槽 / CLI 仍在跑的工单，否则 30s 一轮会叠出一串 write_prd。
    """
    if ticket_id in orch._processing:
        return False
    try:
        from llm_client import ticket_has_live_cli
        if ticket_has_live_cli(ticket_id):
            logger.info("⏭ 调度跳过 %s（CLI 仍在跑）", ticket_id[:12])
            return False
    except Exception:
        pass
    if is_subtask:
        subtask_set = orch._project_subtask_active.setdefault(project_id, set())
        if ticket_id in subtask_set:
            return False
        if len(subtask_set) >= orch._MAX_CONCURRENT_SUBTASKS:
            return False
        subtask_set.add(ticket_id)
    else:
        active_set = orch._project_active.setdefault(project_id, set())
        if ticket_id in active_set:
            return False
        if len(active_set) >= orch._MAX_CONCURRENT_PER_PROJECT:
            return False
        active_set.add(ticket_id)
    logger.info("⚡ 调度工单 %s（%s）", ticket_id[:12], source or "enqueue")
    asyncio.create_task(orch._poll_process(project_id, ticket_id, is_subtask=is_subtask))
    return True


async def start_event_bus(orch):
    """启动内部事件总线"""
    from event_bus import internal_bus

    async def _on_event(event_type: str, data: dict):
        """事件处理：工单状态变更时直接触发处理"""
        if event_type == "ticket_ready":
            project_id = data.get("project_id")
            ticket_id = data.get("ticket_id")
            if project_id and ticket_id:
                # 不经项目槽：续跑时槽位常仍被当前 _poll_process 占用。
                # 互斥只靠 process_ticket claim（发布时若仍持锁，新任务会跳过，
                # 等 release 后由轮询兜底；为减少窗口，发布前会先 release）。
                logger.info("⚡ 事件驱动: 续跑工单 %s", ticket_id[:12])
                asyncio.create_task(orch.process_ticket(project_id, ticket_id))

    internal_bus.set_handler(_on_event)
    await internal_bus.start()


async def publish_ticket_ready(orch, project_id: str, ticket_id: str):
    """发布工单就绪事件（触发下一个 Agent 立即接手）"""
    try:
        from event_bus import internal_bus
        await internal_bus.publish("ticket_ready", {
            "project_id": project_id,
            "ticket_id": ticket_id,
        })
    except Exception as e:
        logger.debug("事件发布失败(非致命): %s", e)


async def poll_loop(orch, interval: int = 30):
    """后台轮询：兜底机制，扫描遗漏的工单（间隔已放宽到 30s）"""
    logger.info("🔄 工单轮询调度器已启动 (间隔 %ds, 事件总线为主)", interval)
    while True:
        try:
            await orch._poll_once()
        except Exception as e:
            logger.error("轮询异常: %s", e, exc_info=True)
        await asyncio.sleep(interval)


async def repair_status_outside_sop(
    orch, db, project_id: str, ticket: dict, current_status: str,
) -> Optional[str]:
    """status 不在当前项目 SOP 里时（视频工单被 unblock 到 architecture_done），
    回退到第一条可派单 trigger，避免看板永久停在「审核中」。"""
    try:
        from sop.loader import compose_sop
        from sop.status_repair import next_status_if_outside_sop
        row = await db.fetch_one(
            "SELECT traits FROM projects WHERE id = ?", (project_id,),
        )
        traits = json.loads((row or {}).get("traits") or "[]")
        if not isinstance(traits, list):
            traits = []
        stages = compose_sop(
            traits=traits, ticket_type=ticket.get("type"),
        ).get("stages", [])
        new_status = next_status_if_outside_sop(current_status, stages)
        if not new_status:
            return None
        ticket_id = ticket["id"]
        await db.update("tickets", {
            "status": new_status, "updated_at": now_iso(),
        }, "id = ?", (ticket_id,))
        await orch._log(
            project_id, ticket.get("requirement_id"), ticket_id, "Orchestrator",
            "sop_repair", current_status, new_status,
            f"工单状态「{current_status}」不在当前 SOP 中"
            f"（对应软件阶段已被裁掉），已回退到「{new_status}」继续派单。",
            "warning",
            detail_data={"from": current_status, "to": new_status},
        )
        logger.info(
            "🔧 SOP 状态修复: %s %s → %s", ticket_id, current_status, new_status,
        )
        return new_status
    except Exception as e:
        logger.warning("_repair_status_outside_sop 失败: %s", e)
        return None


async def zombie_rewind_status(orch, db, ticket_id: str, status: str) -> Optional[str]:
    """僵尸工单该回退到哪个状态重跑。

    僵尸的语义是「这个阶段半路死了」，不是「这个阶段做完了」。所以要退回
    **派单前的那个状态**，让 SOP 重新触发同一个 stage，而不是跳到它的成功态。
    （旧实现直接 fast-forward 到 xxx_done，等于替没跑完的阶段宣布成功，
    下游拿着空仓库继续跑完整条流水线 —— TK-20260920-ce79a9。）

    来源优先级：
      1. 本次进入该 in_progress 状态时那条 `assign` 日志的 from_status —— 最准
      2. SOP 里 success_status == 本状态的那个 stage 的 trigger_on —— 兜底
      3. 都拿不到 → 返回 None（宁可让它继续挂着等人看，也不谎报完成）

    连续在同一状态僵尸超过 MAX_ZOMBIE_REWIND 次 → 返回 blocked 止损，
    避免「死 → 回退 → 再死」的无限重跑。
    """
    MAX_ZOMBIE_REWIND = 3
    rewind_cnt = 0
    try:
        reset_row = await db.fetch_one(
            """SELECT created_at FROM ticket_logs
                   WHERE ticket_id = ? AND action IN ('unblock', 'reject_reset')
                   ORDER BY created_at DESC LIMIT 1""",
            (ticket_id,),
        )
        since = (reset_row or {}).get("created_at")
        sql = """SELECT COUNT(*) AS c FROM ticket_logs
                     WHERE ticket_id = ? AND action = 'zombie_reset' AND from_status = ?"""
        params: list = [ticket_id, status]
        if since:
            sql += " AND created_at > ?"
            params.append(since)
        row = await db.fetch_one(sql, tuple(params))
        rewind_cnt = (row or {}).get("c", 0) or 0
    except Exception as e:
        logger.debug("zombie_reset 计数失败: %s", e)
    if rewind_cnt >= MAX_ZOMBIE_REWIND:
        logger.warning(
            "🛑 工单 %s 在 %s 已僵尸重跑 %d 次，转 blocked 等人工",
            ticket_id[:12], status, rewind_cnt,
        )
        return TicketStatus.BLOCKED.value

    # 1. 最近一条把工单推进到本状态的 assign 日志
    try:
        row = await db.fetch_one(
            """SELECT from_status FROM ticket_logs
                   WHERE ticket_id = ? AND action = 'assign' AND to_status = ?
                   ORDER BY created_at DESC LIMIT 1""",
            (ticket_id, status),
        )
        prev = (row or {}).get("from_status")
        if prev and prev != status:
            return prev
    except Exception as e:
        logger.debug("僵尸回退读 assign 日志失败: %s", e)

    # 2. 从 SOP 反查：哪个 stage 的 success_status 是本状态 → 退回它的 trigger_on
    try:
        ticket = await db.fetch_one(
            "SELECT project_id, type FROM tickets WHERE id = ?", (ticket_id,)
        )
        rules = await orch._get_rules_for_project(
            (ticket or {}).get("project_id") or "", ticket_type=(ticket or {}).get("type"),
        )
        for trigger, rule in (rules or {}).items():
            if rule.get("next_status") == status and trigger != status:
                return trigger
    except Exception as e:
        logger.debug("僵尸回退查 SOP 失败: %s", e)

    return None


async def resume_stuck_analyses(orch, db):
    """status=analyzing 但本进程没在跑 → 上次进程死了，重新拆单。"""
    rows = await db.fetch_all(
        "SELECT id, project_id, title FROM requirements WHERE status = 'analyzing'"
    )
    for row in rows or []:
        rid = row["id"]
        if rid in orch._analyzing_reqs:
            continue
        logger.warning("🧟 需求分析中断，重新开始: %s「%s」", rid[:12], (row.get("title") or "")[:40])
        try:
            await orch._log(
                row["project_id"], rid, None, "Orchestrator",
                "zombie_reset", "analyzing", "analyzing",
                "需求分析在进程重启后中断，正在重新开始 PRD 分析。",
                "warning",
            )
        except Exception as e:
            logger.debug("写需求分析续跑日志失败: %s", e)
        asyncio.create_task(orch.handle_requirement(row["project_id"], rid))


async def resume_parent_ticket(orch, db, parent_ticket_id: str, project_id: str, parent_row: dict):
    """恢复父 Ticket：从 waiting_subtasks 恢复到 PENDING，让轮询器正常拾取"""
    now = now_iso()
    requirement_id = parent_row.get("requirement_id")

    await db.update("tickets", {
        "status":     TicketStatus.PENDING.value,
        "updated_at": now,
    }, "id = ?", (parent_ticket_id,))

    await db.insert("ticket_logs", {
        "id":             generate_id("LOG"),
        "ticket_id":      parent_ticket_id,
        "project_id":     project_id,
        "requirement_id": requirement_id,
        "agent_type":     "Orchestrator",
        "action":         "subtasks_complete",
        "from_status":    "waiting_subtasks",
        "to_status":      TicketStatus.PENDING.value,
        "detail":         json.dumps({"message": "所有子任务完成，父任务恢复执行"}, ensure_ascii=False),
        "level":          "info",
        "created_at":     now,
    })

    try:
        await event_manager.publish_to_project(project_id, "ticket_status_changed", {
            "ticket_id": parent_ticket_id,
            "from":      "waiting_subtasks",
            "to":        TicketStatus.PENDING.value,
        })
    except Exception:
        pass


async def poll_process(orch, project_id: str, ticket_id: str, is_subtask: bool = False):
    """调度触发的工单处理。_processing 由 process_ticket claim/release；此处只清项目槽。"""
    try:
        await orch.process_ticket(project_id, ticket_id)
    finally:
        if is_subtask:
            orch._project_subtask_active.get(project_id, set()).discard(ticket_id)
        else:
            orch._project_active.get(project_id, set()).discard(ticket_id)
