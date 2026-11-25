"""单次轮询：扫描可流转和执行中的工单，检查子工单是否完成。

跳过本进程持有的工单以及已暂停或取消的需求。执行态超过或达到 300 秒时，按
`orch._zombie_rewind_status` 给出的状态回退，回退成功后本轮不再派单。
可流转工单通过依赖检查才入队；普通工单的 source 是 poll，子工单是 poll-sub。
等待子工单的父工单在没有子项或子项全部完成时恢复。

保留函数内对 contracts、datetime 和 llm_client.abort_ticket_cli 的导入。
check_subtasks_complete 中原有的 WAITING_SUBTASKS_STATUS 导入未使用，搬移时保留。

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
import json
import logging

from models import TicketStatus
from utils import now_iso

logger = logging.getLogger("orchestrator")


async def poll_once(orch, db):
    """单次轮询：扫描所有可流转状态的工单并处理"""
    # 1. v0.17: 找出所有状态在**任一项目 SOP** 中的工单（考虑 traits 派生的额外状态）
    actionable_statuses = await orch._get_all_actionable_statuses()

    # 2. 执行中状态：SOP trigger 里没有 *_in_progress（那是 next_status）。
    #    硬编码软件阶段会漏掉 director_visual_in_progress，重启后轮询看不见，
    #    界面一直「正在干什么」其实进程已经死了。用 GLOB 扫全部 *_in_progress。
    # 3. Phase 4: 也扫 waiting_subtasks，用于检测子 Ticket 是否全部完成
    from contracts import WAITING_SUBTASKS_STATUS
    waiting_statuses = [WAITING_SUBTASKS_STATUS]

    all_statuses = list(set(actionable_statuses + waiting_statuses))
    if all_statuses:
        placeholders = ",".join(["?"] * len(all_statuses))
        where = (
            f"t.status IN ({placeholders}) "
            f"OR t.status GLOB '*_in_progress' "
            f"OR t.status = 'deploying'"
        )
        params = tuple(all_statuses)
    else:
        where = "t.status GLOB '*_in_progress' OR t.status = 'deploying'"
        params = ()
    sql = f"""
            SELECT t.*, r.status as req_status
            FROM tickets t
            LEFT JOIN requirements r ON t.requirement_id = r.id
            WHERE {where}
            ORDER BY t.priority ASC, t.sort_order ASC
        """
    tickets = await db.fetch_all(sql, params)

    for t in tickets:
        ticket_id = t["id"]
        project_id = t["project_id"]

        # 跳过本进程还在跑的（含项目槽 / 活 CLI）。否则等模型首包时
        # updated_at 不动，60s 僵尸门会把活 write_prd 打回 pending 再派。
        if orch._ticket_held_by_this_process(ticket_id):
            continue

        # 跳过需求已暂停/取消的
        if t.get("req_status") in ("paused", "cancelled"):
            continue

        status = t["status"]

        # Phase 4：waiting_subtasks 状态 — 检测子 Ticket 是否全部完成
        if status == WAITING_SUBTASKS_STATUS:
            await orch._check_subtasks_complete(ticket_id, project_id, t)
            continue

        # 对于"进行中"状态：本进程没在跑，且 updated_at 超过 300 秒没更新
        # → 才是僵尸（进程重启 / Agent 崩溃）。活任务等首包也会 89s 无 log，
        # 不能在这里打回 pending，否则同一轮 poll 立刻再派，assign→zombie 循环。
        if orch._status_is_executing(status):
            from datetime import datetime
            try:
                updated_str = t["updated_at"] or ""
                # 去掉时区信息统一比较
                if "+" in updated_str:
                    updated_str = updated_str.split("+")[0]
                if "Z" in updated_str:
                    updated_str = updated_str.replace("Z", "")
                updated = datetime.fromisoformat(updated_str)
                now_dt = datetime.now()
                age = (now_dt - updated).total_seconds()
                # 等模型首包 78–90s 无 log 是正常的，60s 会误杀活 write_prd。
                if age < 300:
                    continue  # 还在正常处理中，跳过
            except Exception as e:
                logger.warning("僵尸检测时间解析失败: %s (%s)", t["updated_at"], e)
                continue
            logger.info("🧟 检测到僵尸工单: %s「%s」状态=%s (%.0fs 未更新)",
                        ticket_id[:12], t["title"][:20], status, age)
            # 僵尸 = 这个阶段**半路死了**（进程重启 / Agent 崩溃 / 任务被吞）。
            # 原先这里 reset 到对应的「完成」状态（development_in_progress →
            # development_done），等于替一个从没跑完的阶段宣布成功：
            # TK-20260920-ce79a9 的开发阶段在后端重启时死掉，40 秒后被这张表
            # 标成 development_done，下游 code_review / acceptance 就在一个
            # 只有 console.log 空壳的仓库上继续跑，最后 deployed。
            # 正确语义是**回退重跑**：退回该阶段的触发态，让 SOP 重新派单。
            reset_to = await orch._zombie_rewind_status(ticket_id, status)
            if reset_to and reset_to != status:
                try:
                    from llm_client import abort_ticket_cli
                    await abort_ticket_cli(ticket_id)
                except Exception:
                    pass
                await db.update("tickets", {
                    "status": reset_to, "updated_at": now_iso()
                }, "id = ?", (ticket_id,))
                await orch._log(
                    project_id, t.get("requirement_id"), ticket_id, "Orchestrator",
                    "zombie_reset", status, reset_to,
                    f"工单在「{status}」卡死 {age:.0f}s（进程重启/Agent 崩溃），"
                    f"回退到「{reset_to}」重跑该阶段。"
                    f"注意：不再直接标记为完成——半路死掉的阶段没有产出可言。",
                    "warning",
                    detail_data={"stale_seconds": int(age), "from": status, "to": reset_to},
                )
                logger.info("🔧 僵尸工单已回退重跑: %s → %s", status, reset_to)
                # 本轮不再立刻派单：否则 rewind→pending 后同一拍 assign，
                # 界面上就是 assign → thought_start → zombie_reset 循环。
                continue
            logger.warning(
                "🧟 僵尸工单无法回退，保持挂起: %s status=%s (%.0fs)",
                ticket_id[:12], status, age,
            )
            continue

        # 检查依赖（仅对 pending 和有依赖的状态检查）
        if status in actionable_statuses:
            deps_json = t.get("dependencies", "[]")
            try:
                dep_ids = json.loads(deps_json) if deps_json else []
            except (json.JSONDecodeError, TypeError):
                dep_ids = []

            if dep_ids:
                DONE_STATUSES = {TicketStatus.TESTING_DONE.value, TicketStatus.DEPLOYED.value}
                all_deps_done = True
                for dep_id in dep_ids:
                    dep = await db.fetch_one("SELECT status FROM tickets WHERE id = ?", (dep_id,))
                    if not dep or dep["status"] not in DONE_STATUSES:
                        all_deps_done = False
                        break
                if not all_deps_done:
                    continue

        # L8: 区分子任务 / 顶层任务；互斥与槽位统一走 _enqueue_ticket
        is_subtask = bool(t.get("parent_ticket_id"))
        if is_subtask:
            orch._enqueue_ticket(project_id, ticket_id, is_subtask=True, source="poll-sub")
        else:
            orch._enqueue_ticket(project_id, ticket_id, is_subtask=False, source="poll")

    # ── 自动拾取 open BUG ──
    # 扫描所有项目中 status=open 且未关联 ticket 的 BUG，自动触发修复工作流
    await orch._poll_open_bugs()
    await orch._resume_stuck_analyses()


async def check_subtasks_complete(orch, db, parent_ticket_id: str, project_id: str, parent_row: dict):
    """Phase 4：检查父 Ticket 的所有子 Ticket 是否全部完成。
    全部完成 → 父 Ticket 恢复到 PENDING（让轮询器继续执行下一阶段）。
    """
    from contracts import WAITING_SUBTASKS_STATUS
    DONE_STATUSES = {TicketStatus.TESTING_DONE.value, TicketStatus.DEPLOYED.value}

    sub_tickets = await db.fetch_all(
        "SELECT id, title, status FROM tickets WHERE parent_ticket_id = ?",
        (parent_ticket_id,),
    )
    if not sub_tickets:
        # 没有子 Ticket（可能被删除），直接恢复
        logger.warning("父 Ticket %s 无子任务记录，自动恢复到 pending", parent_ticket_id[:12])
        await orch._resume_parent_ticket(parent_ticket_id, project_id, parent_row)
        return

    pending = [s for s in sub_tickets if s["status"] not in DONE_STATUSES]
    if pending:
        names = ", ".join(f"#{s['id'][-6:]}({s['title'][:15]})" for s in pending[:3])
        logger.debug("⏳ 父 Ticket %s 等待子任务完成: %s", parent_ticket_id[:12], names)
        return

    # 所有子 Ticket 完成 → 恢复父 Ticket
    logger.info("✅ 所有子任务完成，恢复父 Ticket: %s", parent_ticket_id[:12])
    await orch._resume_parent_ticket(parent_ticket_id, project_id, parent_row)
