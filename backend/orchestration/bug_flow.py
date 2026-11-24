"""BUG 修复流程：编译失败自动建 BUG，扫描待修的 BUG，建修复工单并把结果回写 bugs 表。

`run_bug_fix` 给一条 BUG 创建 type=bug 的真实工单，跳过 PM 和架构设计，直接从 DevAgent 开始，
复用 `orch.process_ticket` 流转到 TestAgent；`sync_bug_status_from_ticket` 按工单的最终状态回写
bugs 表。`poll_open_bugs` 由轮询调用，把 status=open 的 BUG 自动送进 `run_bug_fix`。

`create_compile_bug` 和 `resolve_compile_bug` 是 UBT 编译结果对 bugs 表的两处写入：编译失败建一条，
编译通过把关联的 in_dev BUG 标成 fixed。

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
import logging
from typing import Dict, List, Optional

from events import event_manager
from models import TicketStatus
from utils import generate_id, now_iso

logger = logging.getLogger("orchestrator")


async def create_compile_bug(
    orch, db,
    project_id: str,
    requirement_id: Optional[str],
    ticket_id: str,
    errors_list: List[Dict],
    err_brief: str,
):
    """UBT 编译失败时自动创建 Bug 记录（走正式 Bug 流程，在 BUG 列表可见）"""
    try:
        bug_id = generate_id("BUG")
        # 格式化错误描述
        err_lines = ["UBT 编译失败，以下为结构化错误列表：\n"]
        for i, e in enumerate(errors_list[:15], 1):
            fname = (e.get("file") or "?").replace("\\", "/").split("/")[-1]
            err_lines.append(
                f"{i}. `{fname}:{e.get('line', '?')}` "
                f"**{e.get('code', '')}**（{e.get('category', 'compile')}）: "
                f"{(e.get('msg') or '')[:200]}"
            )
        if len(errors_list) > 15:
            err_lines.append(f"… 还有 {len(errors_list) - 15} 个错误")

        description = "\n".join(err_lines)

        await db.insert("bugs", {
            "id": bug_id,
            "project_id": project_id,
            "requirement_id": requirement_id,
            "ticket_id": ticket_id,    # 关联触发此 Bug 的工单
            "title": f"UBT 编译失败: {err_brief[:120]}",
            "description": description,
            "priority": "high",
            "status": "in_dev",        # DevAgent 立即处理
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })
        logger.info("🐛 编译失败 Bug 已创建: %s (ticket=%s)", bug_id, ticket_id)
    except Exception as e:
        logger.warning("创建编译 Bug 失败（忽略）: %s", e)


async def resolve_compile_bug(orch, db, ticket_id: str, project_id: str):
    """编译通过时把关联的 in_dev Bug 标为 fixed"""
    try:
        rows = await db.fetch_all(
            "SELECT id FROM bugs WHERE ticket_id = ? AND project_id = ? AND status = 'in_dev'",
            (ticket_id, project_id),
        )
        for r in rows:
            await db.update("bugs", {
                "status": "fixed",
                "fix_notes": "UBT 编译通过，自动标记修复",
                "fixed_at": now_iso(),
                "updated_at": now_iso(),
            }, "id = ?", (r["id"],))
            logger.info("✅ 编译 Bug %s 已自动标为 fixed", r["id"])
    except Exception as e:
        logger.warning("自动 resolve Bug 失败（忽略）: %s", e)


async def poll_open_bugs(orch, db):
    """扫描所有 status=open 的 BUG，自动触发修复（无需手动点击）"""
    open_bugs = await db.fetch_all(
        """SELECT b.*, p.id as proj_id
               FROM bugs b
               JOIN projects p ON b.project_id = p.id
               WHERE b.status = 'open'
               ORDER BY
                 CASE b.priority WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END,
                 b.created_at ASC""",
    )
    for bug in open_bugs:
        bug_id = bug["id"]
        project_id = bug["project_id"]

        # 如果已关联 ticket 且 ticket 在处理中，跳过
        if bug.get("ticket_id") and bug["ticket_id"] in orch._processing:
            continue

        # 检查是否已有 in_dev/in_test 状态（避免重复触发）
        # （理论上 status=open 就是未触发，但做双重保险）
        if bug.get("ticket_id"):
            ticket = await db.fetch_one(
                "SELECT status FROM tickets WHERE id = ?", (bug["ticket_id"],)
            )
            if ticket and ticket["status"] not in (
                TicketStatus.TESTING_DONE.value, TicketStatus.DEPLOYED.value
            ):
                # ticket 还在流转中，不重复触发
                continue

        logger.info("🐛 轮询自动拾取 BUG: %s「%s」[%s]",
                    bug_id[:12], bug["title"][:30], bug.get("priority", "medium"))

        # 先更新 bugs 表状态为 in_dev，防止下次轮询重复触发
        await db.update("bugs", {
            "status": "in_dev",
            "updated_at": now_iso(),
        }, "id = ?", (bug_id,))

        # 异步触发修复工作流
        asyncio.create_task(orch.run_bug_fix(project_id, bug_id))


async def run_bug_fix(orch, db, project_id: str, bug_id: str):
    """BUG 修复工作流：创建真实 ticket（type=bug）直接从 DevAgent 开始，
    跳过 PM / 架构设计，复用 process_ticket() 正常流转到 TestAgent。
    """
    bug = await db.fetch_one("SELECT * FROM bugs WHERE id = ?", (bug_id,))
    if not bug:
        logger.error("BUG 不存在: %s", bug_id)
        return

    logger.info("━" * 60)
    logger.info("🐛 开始修复 BUG: %s「%s」", bug_id[:12], bug["title"])
    logger.info("━" * 60)

    # ── 如果已有关联 ticket，不重复创建 ──
    existing_ticket = await db.fetch_one(
        "SELECT id FROM tickets WHERE id = (SELECT ticket_id FROM bugs WHERE id = ?)",
        (bug_id,),
    ) if bug.get("ticket_id") else None

    if existing_ticket:
        ticket_id = existing_ticket["id"]
        logger.info("BUG 已关联 ticket: %s，直接触发流转", ticket_id)
    else:
        # ── 创建真实 ticket（type=bug，从 architecture_done 开始） ──
        ticket_id = generate_id("TK")
        now = now_iso()
        # BUG 需要一个 requirement_id；若无关联需求则创建一个"BUG 修复"虚拟需求
        req_id = bug.get("requirement_id")
        if not req_id:
            req_id = generate_id("REQ")
            await db.insert("requirements", {
                "id": req_id,
                "project_id": project_id,
                "title": f"[BUG修复] {bug['title']}",
                "description": bug["description"],
                "priority": bug.get("priority", "medium"),
                "status": "in_progress",
                "submitter": "system",
                "prd_content": None,
                "module": "other",
                "tags": "bug",
                "estimated_hours": None,
                "actual_hours": None,
                "milestone_id": None,
                "estimated_days": None,
                "created_at": now,
                "updated_at": now,
                "completed_at": None,
            })
            await db.update("bugs", {"requirement_id": req_id, "updated_at": now}, "id = ?", (bug_id,))

        docs_prefix = f"docs/Reqs/bugs/{bug_id[-6:]}/"
        await db.insert("tickets", {
            "id": ticket_id,
            "requirement_id": req_id,
            "project_id": project_id,
            "parent_ticket_id": None,
            "title": f"[BUG] {bug['title']}",
            "description": bug["description"],
            "type": "bug",
            "module": "other",
            "priority": 1 if bug.get("priority") == "critical" else 2 if bug.get("priority") == "high" else 3,
            "sort_order": 0,
            # 直接跳到 architecture_done，让轮询器从 DevAgent 开始
            "status": TicketStatus.ARCHITECTURE_DONE.value,
            "assigned_agent": None,
            "current_owner": "dev",
            "estimated_hours": 2,
            "actual_hours": None,
            "estimated_completion": None,
            "dependencies": "[]",
            "result": None,
            "created_at": now,
            "updated_at": now,
            "started_at": now,
            "completed_at": None,
        })

        # 把 ticket_id 写回 bugs 表（需要先做迁移列）
        try:
            await db.update("bugs", {"ticket_id": ticket_id, "updated_at": now}, "id = ?", (bug_id,))
        except Exception:
            pass  # 列可能还没迁移，不影响主流程

        logger.info("🎫 BUG ticket 已创建: %s → 从 architecture_done 开始流转", ticket_id)
        await event_manager.publish_to_project(
            project_id, "ticket_created",
            {"ticket_id": ticket_id, "title": f"[BUG] {bug['title']}", "type": "bug"},
        )

    # ── 立即触发处理（不等下一轮询周期）——项目槽限流；互斥由 process_ticket claim ──
    active_set = orch._project_active.setdefault(project_id, set())
    if len(active_set) < orch._MAX_CONCURRENT_PER_PROJECT:
        active_set.add(ticket_id)
        asyncio.create_task(orch._run_bug_ticket(project_id, ticket_id, bug_id))
    else:
        logger.info("🐛 BUG ticket 进入等待队列（项目并发已满）: %s", ticket_id[:12])


async def run_bug_ticket(orch, project_id: str, ticket_id: str, bug_id: str):
    """执行 BUG ticket 流转，并在测试完成后同步更新 bugs 表状态"""
    try:
        await orch.process_ticket(project_id, ticket_id)
        await orch._sync_bug_status_from_ticket(project_id, ticket_id, bug_id)
    finally:
        orch._project_active.get(project_id, set()).discard(ticket_id)


async def sync_bug_status_from_ticket(orch, db, project_id: str, ticket_id: str, bug_id: str):
    """按 ticket 最终状态回写 bugs 表。"""
    ticket = await db.fetch_one("SELECT status FROM tickets WHERE id = ?", (ticket_id,))
    final_status = ticket["status"] if ticket else ""
    if final_status == TicketStatus.TESTING_DONE.value:
        version_id = await orch._find_current_version(project_id)
        fixed_at = now_iso()
        await db.update("bugs", {
            "status": "fixed",
            "fixed_at": fixed_at,
            "version_id": version_id,
            "updated_at": fixed_at,
        }, "id = ?", (bug_id,))
        bug = await db.fetch_one("SELECT title FROM bugs WHERE id = ?", (bug_id,))
        await event_manager.publish_to_project(
            project_id, "bug_fixed",
            {"bug_id": bug_id, "title": bug["title"] if bug else "", "version_id": version_id},
        )
        await event_manager.publish_to_project(
            project_id, "bug_status_changed",
            {"bug_id": bug_id, "status": "fixed"},
        )
    elif final_status in (TicketStatus.TESTING_FAILED.value, TicketStatus.BLOCKED.value, ""):
        await db.update("bugs", {
            "status": "open", "updated_at": now_iso(),
        }, "id = ?", (bug_id,))
        await event_manager.publish_to_project(
            project_id, "bug_status_changed",
            {"bug_id": bug_id, "status": "open",
             "reason": "blocked" if final_status == TicketStatus.BLOCKED.value else "测试未通过"},
        )
    else:
        # 开发完成，等待测试
        await db.update("bugs", {
            "status": "in_test", "updated_at": now_iso(),
        }, "id = ?", (bug_id,))
        await event_manager.publish_to_project(
            project_id, "bug_status_changed",
            {"bug_id": bug_id, "status": "in_test"},
        )


async def find_current_version(orch, db, project_id: str) -> Optional[str]:
    """查找当前进行中的版本（milestone），用于 BUG 并入版本"""
    # 优先找 in_progress 里程碑
    milestone = await db.fetch_one(
        """SELECT id, title FROM milestones
               WHERE project_id = ? AND status = 'in_progress'
               ORDER BY planned_start ASC LIMIT 1""",
        (project_id,),
    )
    if milestone:
        return milestone["id"]
    # 没有进行中的，用最近的 planned 里程碑
    milestone = await db.fetch_one(
        """SELECT id, title FROM milestones
               WHERE project_id = ? AND status = 'planned'
               ORDER BY planned_start ASC LIMIT 1""",
        (project_id,),
    )
    return milestone["id"] if milestone else None
