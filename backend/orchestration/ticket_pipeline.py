"""`process_ticket` 的分步管线：一次派单按顺序走完 `STEPS` 里的每一步。

从 `TicketOrchestrator.process_ticket` 拆出（重构方案 R2 第 2 步）。`process_ticket`
保留外层骨架：入口 claim、登记运行中的协程、异常处理、`finally` 里的释放和清理。

约定：

- 每一步是 `async def step(run) -> Optional[str]`。返回 `CONTINUE` 进入下一步；
  返回原因字符串表示本轮到此为止，对应拆分前函数体里的一次 `return`。
- 步骤之间共享的值放在 `TicketRun` 上，字段和拆分前的局部变量同名。
- 步骤体从原函数按顺序原样搬出。改动有五处：`self` 写成 `orch`；共享的局部变量
  从 `run` 取、往 `run` 存；`return` 带上停止原因；反思记录拆成三个小函数；
  `load_ticket` 里去掉一个没用到的 `clear_checkpoint_context` 导入。
- `db` 由调用方传入，这里不导入。测试用
  `monkeypatch.setattr(orchestrator, "db", test_db)` 换库，步骤必须拿到同一个对象。
- 函数内的延迟导入（`llm_client`、`checkpoint`、`capability_check`、`api.knowledge`、
  `failure_library`）保持原样，测试的打桩打在这些源模块上。
- 步骤都在 `process_ticket` 所在的协程里直接 `await`，不另起任务。检查点上下文和
  LLM 上下文是 contextvar，另起任务会让它们对后续步骤失效。

新增步骤时接到 `STEPS` 里，元组的顺序就是执行顺序。
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from events import event_manager
from git_manager import git_manager
from llm_client import clear_llm_context, set_llm_context
from models import TicketStatus
from utils import now_iso

logger = logging.getLogger("orchestrator")

# 步骤返回 CONTINUE 表示继续下一步；返回原因字符串表示停止。
CONTINUE = None


@dataclass
class TicketRun:
    """一次 `process_ticket` 调用里各步骤共享的状态。

    `ticket` 是派单前读到的那一行，后面的步骤改了数据库也不刷新它：
    `trigger_status` 和结果处理都依赖派单前的状态。

    `agent_chosen` 在 `select_agent` 取到 Agent 名时置真。`process_ticket` 的异常
    处理靠它判断要不要给 Agent 记一次失败，语义和拆分前的
    `if 'agent_name' in dir()` 相同。
    """

    orch: Any                               # TicketOrchestrator
    db: Any
    project_id: str
    ticket_id: str
    ticket: Optional[Dict[str, Any]] = None
    current_status: str = ""
    rule: Optional[Dict[str, Any]] = None
    agent_name: Optional[str] = None
    agent_chosen: bool = False
    action: Optional[str] = None
    next_status: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    result: Any = None
    stopped_at: str = ""                    # 停在哪一步（函数名），走完全程时为空
    stop_reason: Optional[str] = None


async def load_ticket(run: TicketRun) -> Optional[str]:
    """取工单并打检查点起点。上一轮 CLI 还在跑、或工单不存在时停止。"""
    db = run.db
    project_id = run.project_id
    ticket_id = run.ticket_id
    try:
        from llm_client import ticket_has_live_cli
        if ticket_has_live_cli(ticket_id):
            logger.info("⏭ 跳过工单 %s（上一轮 CLI 仍在跑，不重复派单）", ticket_id[:12])
            return "live_cli"
    except Exception:
        pass
    # 取到就登记到 run：process_ticket 的 except / finally 要读它。
    ticket = run.ticket = await db.fetch_one(
        "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
    )
    if not ticket:
        return "ticket_not_found"

    # Checkpoint：工单处理起点锚点 + 写上下文（供 git_manager 钩子）
    try:
        from checkpoint import set_checkpoint_context
        from checkpoint.service import checkpoint_service
        from capability_check import _get_repo_path
        _repo = await _get_repo_path(project_id)
        set_checkpoint_context(
            project_id=project_id, ticket_id=ticket_id,
            requirement_id=ticket.get("requirement_id") or "",
            agent_type="Orchestrator", action="process_ticket",
            repo_path=_repo or "",
        )
        await checkpoint_service.ensure_ticket_start(project_id, ticket_id)
    except Exception as _cpe:
        logger.debug("ticket_start checkpoint 跳过: %s", _cpe)
    return CONTINUE


async def check_entry_gates(run: TicketRun) -> Optional[str]:
    """入口门闩：硬终态工单、需求已暂停或取消时不派单。"""
    orch = run.orch
    db = run.db
    ticket_id = run.ticket_id
    ticket = run.ticket
    # 硬终态：不再派单（含 blocked——需人工 unblock）
    if ticket["status"] in orch._HARD_TERMINAL:
        logger.info(
            "⏭ 工单 %s 已终态 %s，跳过自动流转",
            ticket_id[:12], ticket["status"],
        )
        return "hard_terminal"

    # 新一轮执行：清掉上一轮「停止」留下的 CLI aborted 标记
    try:
        from llm_client import clear_ticket_cli_abort
        clear_ticket_cli_abort(ticket_id)
    except Exception:
        pass

    # 检查需求是否被暂停或取消
    requirement = await db.fetch_one(
        "SELECT status FROM requirements WHERE id = ?",
        (ticket["requirement_id"],),
    )
    if requirement and requirement["status"] in ("paused", "cancelled"):
        logger.info(
            "⏸️ 需求 %s 处于 %s 状态，跳过工单 %s 的流转",
            ticket["requirement_id"][:12], requirement["status"], ticket_id[:12],
        )
        return "requirement_inactive"
    return CONTINUE


async def check_global_circuit_breaker(run: TicketRun) -> Optional[str]:
    """全局止损：累计打回次数或同因连续失败达到上限，改 blocked 并起诊断。"""
    orch = run.orch
    db = run.db
    project_id = run.project_id
    ticket_id = run.ticket_id
    ticket = run.ticket
    # === 全局 reject 上限 + 同因连续失败熔断：硬停 blocked ===
    # 旧 force_pass→testing_done 会把「编译环空转」标成已完成，跳过 Test/Deploy，
    # 前端显示「已完成」但 OpenSpec/验收实际未跑。正确语义：转人工介入。
    # 追加：同一失败原因连续出现即确定性失败，不必陪跑满 5 次烧 token ——
    # TK-20261110-48b6af 实测连续 10+ 次同一句「LLM 输出无效…」仍每轮重派。
    MAX_RETRIES = 5
    CONSECUTIVE_FAILURE_LIMIT = 3
    reject_cnt_global = await orch._reject_count_since_reset(ticket_id)
    same_cnt, fingerprint = await orch._consecutive_same_failure(ticket_id)
    hit_global = reject_cnt_global >= MAX_RETRIES
    hit_repeated = same_cnt >= CONSECUTIVE_FAILURE_LIMIT
    if hit_global or hit_repeated:
        block_reason = "repeated_failure_fingerprint" if hit_repeated else "global_reject_limit"
        if hit_repeated:
            block_msg = (
                f"同一失败原因连续出现 {same_cnt} 次（≥{CONSECUTIVE_FAILURE_LIMIT}），"
                f"判定为确定性失败，停止自动重试并标记 blocked。"
                f"原因：{fingerprint[:80]}"
            )
        else:
            block_msg = (
                f"工单已被打回 {reject_cnt_global} 次，超过上限 {MAX_RETRIES} 次，"
                f"停止自动流转并标记 blocked（不再强制标记完成）。"
                f"请人工排查环境/编译/需求后解除阻塞。"
            )
        from_status = ticket["status"]
        logger.warning("🛑 工单 %s 止损 blocked：%s", ticket_id[:12], block_msg[:120])
        await db.update("tickets", {
            "status": TicketStatus.BLOCKED.value,
            "updated_at": now_iso(),
        }, "id = ?", (ticket_id,))
        await orch._log(
            project_id, ticket.get("requirement_id"), ticket_id, "Orchestrator",
            "blocked", from_status, TicketStatus.BLOCKED.value,
            block_msg,
            "warning",
            detail_data={
                "reject_count": reject_cnt_global,
                "max_retries": MAX_RETRIES,
                "consecutive_same_failure": same_cnt,
                "consecutive_failure_limit": CONSECUTIVE_FAILURE_LIMIT,
                "failure_fingerprint": fingerprint[:120],
                "reason": block_reason,
                "legacy_action": "force_pass",
            },
        )
        await event_manager.publish_to_project(
            project_id, "ticket_blocked",
            {
                "ticket_id": ticket_id,
                "from": from_status,
                "to": TicketStatus.BLOCKED.value,
                "reason": block_reason,
            },
        )
        asyncio.create_task(orch._diagnose_blocked_ticket(
            project_id=project_id,
            ticket_id=ticket_id,
            current_ticket=dict(ticket),
            agent_name="Orchestrator",
            action=block_reason,
            error_msg=f"{block_msg}（最后状态: {from_status}）",
            blocked_from_status=from_status,
        ))
        return "global_circuit_breaker"
    return CONTINUE


async def check_dependencies(run: TicketRun) -> Optional[str]:
    """前置依赖：pending 工单的依赖未完成时等待。"""
    orch = run.orch
    db = run.db
    project_id = run.project_id
    ticket_id = run.ticket_id
    ticket = run.ticket
    # 检查前置依赖是否完成
    deps_json = ticket.get("dependencies", "[]")
    try:
        dep_ids = json.loads(deps_json) if deps_json else []
    except (json.JSONDecodeError, TypeError):
        dep_ids = []

    # 过滤自引用（工单依赖自身会导致死循环）
    dep_ids = [d for d in dep_ids if d != ticket_id]

    if dep_ids and ticket["status"] == TicketStatus.PENDING.value:
        # 查询所有依赖工单的状态（testing_done 或 deployed 都算完成）
        DONE_STATUSES = {TicketStatus.TESTING_DONE.value, TicketStatus.DEPLOYED.value}
        pending_deps = []
        for dep_id in dep_ids:
            dep_ticket = await db.fetch_one(
                "SELECT id, title, status FROM tickets WHERE id = ?", (dep_id,)
            )
            if dep_ticket and dep_ticket["status"] not in DONE_STATUSES:
                pending_deps.append(dep_ticket)

        if pending_deps:
            dep_names = ", ".join(f"#{d['id'][-6:]}({d['title'][:20]})" for d in pending_deps)
            logger.info(
                "⏳ 工单 %s 等待前置依赖完成: %s",
                ticket_id[:12], dep_names,
            )
            await orch._log(
                project_id, ticket["requirement_id"], ticket_id, "Orchestrator",
                "info", "pending", "pending",
                f"等待前置依赖完成: {dep_names}", "info"
            )
            return "waiting_dependencies"  # 依赖未完成，跳过
    return CONTINUE


async def match_rule(run: TicketRun) -> Optional[str]:
    """按当前状态匹配 SOP 规则。状态不在 SOP 内时先尝试修复，仍无规则就停止。"""
    orch = run.orch
    project_id = run.project_id
    ticket = run.ticket
    current_status = ticket["status"]
    # v0.17: 按项目 traits + 工单 type 派生 rules（无 traits → 回退 default）
    project_rules = await orch._get_rules_for_project(
        project_id, ticket_type=ticket.get("type"),
    )
    rule = project_rules.get(current_status)

    if not rule:
        repaired = await orch._repair_status_outside_sop(
            project_id, ticket, current_status,
        )
        if repaired and repaired != current_status:
            current_status = repaired
            rule = project_rules.get(current_status)
    if not rule:
        # 终态或无规则，不处理
        return "no_rule"
    run.current_status = current_status
    run.rule = rule
    return CONTINUE


async def check_stage_retry_limit(run: TicketRun) -> Optional[str]:
    """阶段级止损：返工规则的连续失败次数达到 max_retries，改 blocked 并起诊断。"""
    orch = run.orch
    db = run.db
    project_id = run.project_id
    ticket_id = run.ticket_id
    ticket = run.ticket
    current_status = run.current_status
    rule = run.rule
    # ── P0：max_retries 止损 ──────────────────────────────────
    # reject 回跳规则（如 engine_compile_failed → fix_issues）带 _rework_source_stage
    # 和 config.max_retries。若该失败状态已连续触发超过上限，直接 blocked，
    # 停止 develop↔compile_failed 无限循环烧 token（实测踩过 4 轮空转坑）。
    rework_source = rule.get("_rework_source_stage")
    max_retries = int((rule.get("config") or {}).get("max_retries") or 0)
    if rework_source and max_retries > 0:
        reject_cnt = await orch._reject_count_since_reset(
            ticket_id, to_status=current_status,
        )
        if reject_cnt >= max_retries:
            logger.warning(
                "🛑 工单 %s 在 %s 已 reject %d 次（≥max_retries=%d），blocked 止损",
                ticket_id[:12], current_status, reject_cnt, max_retries,
            )
            await db.update("tickets", {
                "status": TicketStatus.BLOCKED.value,
                "updated_at": now_iso(),
            }, "id = ?", (ticket_id,))
            await orch._log(
                project_id, ticket["requirement_id"], ticket_id, "Orchestrator",
                "blocked", current_status, TicketStatus.BLOCKED.value,
                f"「{current_status}」已连续失败 {reject_cnt} 次（上限 {max_retries}），"
                f"停止自动重试，转人工介入。反复重试同一失败通常是环境/需求问题，"
                f"继续重试只会空转烧 token。",
                "warning",
                detail_data={"reject_count": reject_cnt, "max_retries": max_retries,
                             "source_stage": rework_source, "failed_status": current_status},
            )
            await event_manager.publish_to_project(
                project_id, "ticket_blocked",
                {"ticket_id": ticket_id, "from": current_status,
                 "to": TicketStatus.BLOCKED.value, "reason": "max_retries_exceeded"},
            )
            asyncio.create_task(orch._diagnose_blocked_ticket(
                project_id=project_id,
                ticket_id=ticket_id,
                current_ticket=dict(ticket),
                agent_name=rule.get("agent") or "Orchestrator",
                action=rework_source,
                error_msg=f"阶段「{rework_source}」（{current_status}）连续失败 {reject_cnt} 次（上限 {max_retries}）",
                blocked_from_status=current_status,
            ))
            return "stage_retry_limit"
    return CONTINUE


async def select_agent(run: TicketRun) -> Optional[str]:
    """从规则取 Agent、动作和进行中状态。"""
    current_status = run.current_status
    rule = run.rule
    agent_name = rule["agent"]
    # 取到 Agent 名就立刻登记：之后任何一步出错，process_ticket 都给它记一次失败。
    run.agent_name = agent_name
    run.agent_chosen = True
    action = rule["action"]
    run.action = action
    next_status = rule.get("next_status")
    if not next_status:
        # 门禁：没有 in_progress 就会在 trigger 状态上空转，30s 轮询再派一发。
        next_status = f"{action}_in_progress" if action else None
        logger.error(
            "🛑 SOP 门禁：%s.%s 在状态 %s 上没有 in_progress，"
            "已兜底改写为 %s。请把该 stage 补进 _get_next_status。",
            agent_name, action, current_status, next_status,
        )
    run.next_status = next_status
    return CONTINUE


async def skip_inapplicable_stage(run: TicketRun) -> Optional[str]:
    """跳过不适用的阶段：非代码工单的编译类阶段，无界面工单的 UX 和美术设计。"""
    orch = run.orch
    db = run.db
    project_id = run.project_id
    ticket_id = run.ticket_id
    ticket = run.ticket
    current_status = run.current_status
    agent_name = run.agent_name
    action = run.action
    # ── P1：片段声明 skip_when: noncode_ticket 的阶段 ──────────
    # 非代码工单（验证流程、跑通某流程）没有可编译的源码，硬跑只会空转。
    # 跳到该阶段自己的 success_status，不在这里写死 action 名或目标状态。
    #
    # ── P2：无界面工单跳过 UX / 美术设计 ───────────────────────
    # 同理，ux_design / art_design 的 trait 条件（platform:* / category:game）
    # 对桌面和游戏项目必然命中，纯后端/纯 C++ 逻辑工单也会被拉去做
    # 交互设计和视觉规范，实测空转 153s 且产出无人使用。
    _skip_reason = None
    _skip_stage = await orch._sop_stage_for(
        project_id, action, ticket.get("type"),
    )
    if (
        (_skip_stage or {}).get("skip_when") == "noncode_ticket"
        and orch._is_noncode_ticket(ticket)
    ):
        _skip_to = (_skip_stage or {}).get("success_status") or ""
        if _skip_to:
            _skip_reason = (
                "noncode_ticket", _skip_to,
                "检测到非代码工单（验证/流程类，无可编译源码），"
                f"跳过{_skip_stage.get('name') or action}，直接进入后续阶段。",
            )
    elif (action in ("write_ux_design", "write_art_design")
            and not orch._needs_design_stage(ticket)):
        # 跳到该阶段的 success_status，让流水线接着往下走
        _skip_to = await orch._sop_success_status_for(
            project_id, action,
            default=("ux_design_done" if action == "write_ux_design"
                     else "art_design_done"),
            ticket_type=ticket.get("type"),
        )
        _label = "UX 交互设计" if action == "write_ux_design" else "美术视觉设计"
        _skip_reason = ("no_ui_ticket", _skip_to,
                        f"工单不涉及界面/视觉（module={ticket.get('module')}，"
                        f"标题描述无 UI 相关信号），跳过{_label}阶段。")

    if _skip_reason:
        reason_code, skip_to, skip_msg = _skip_reason
        await db.update("tickets", {
            "status": skip_to,
            "assigned_agent": agent_name,
            "updated_at": now_iso(),
        }, "id = ?", (ticket_id,))
        await orch._log(
            project_id, ticket["requirement_id"], ticket_id, "Orchestrator",
            "skip", current_status, skip_to, skip_msg, "info",
            detail_data={"skipped_action": action,
                         "reason": reason_code,
                         "module": ticket.get("module"),
                         "title": ticket.get("title", "")[:80]},
        )
        await event_manager.publish_to_project(
            project_id, "ticket_status_changed",
            {"ticket_id": ticket_id, "from": current_status, "to": skip_to,
             "agent": "Orchestrator"},
        )
        logger.info("⏭ 工单 %s 跳过 %s（%s）→ %s",
                    ticket_id[:12], action, reason_code, skip_to)
        # 先释放再续跑，避免事件侧撞 claim
        orch._release_ticket(ticket_id)
        await orch._publish_ticket_ready(project_id, ticket_id)
        return "stage_skipped"
    return CONTINUE


async def ensure_agent_registered(run: TicketRun) -> Optional[str]:
    """SOP 点名的 Agent 没有注册时改 blocked。"""
    orch = run.orch
    db = run.db
    project_id = run.project_id
    ticket_id = run.ticket_id
    ticket = run.ticket
    current_status = run.current_status
    agent_name = run.agent_name
    action = run.action
    agent = orch.agents.get(agent_name)
    if not agent:
        # 不能只 return —— 状态没变，下一轮轮询会再命中同一条 rule，
        # 无限重试刷错误日志。SOP 引用了未注册的 Agent 属于配置错误，
        # 只能转人工，标 blocked 止损。
        logger.error(
            "Agent %s 不存在（SOP 配置错误），工单 %s 标记 blocked",
            agent_name, ticket_id[:12],
        )
        await db.update("tickets", {
            "status": TicketStatus.BLOCKED.value,
            "updated_at": now_iso(),
        }, "id = ?", (ticket_id,))
        await orch._log(
            project_id, ticket["requirement_id"], ticket_id, agent_name,
            "blocked", current_status, TicketStatus.BLOCKED.value,
            f"SOP 声明的 Agent「{agent_name}」未在 agent_registry 注册，"
            f"无法派单。请修正 SOP fragment 或实现该 Agent 后解除阻塞。",
            "error",
            detail_data={"missing_agent": agent_name, "action": action},
        )
        await event_manager.publish_to_project(
            project_id, "ticket_blocked",
            {"ticket_id": ticket_id, "from": current_status,
             "to": TicketStatus.BLOCKED.value, "reason": "agent_not_registered",
             "agent": agent_name},
        )
        return "agent_not_registered"
    return CONTINUE


async def assign_ticket(run: TicketRun) -> Optional[str]:
    """派单：标记 Agent 忙碌，工单改成进行中状态。"""
    orch = run.orch
    db = run.db
    project_id = run.project_id
    ticket_id = run.ticket_id
    ticket = run.ticket
    current_status = run.current_status
    agent_name = run.agent_name
    action = run.action
    next_status = run.next_status
    logger.info("─" * 50)
    logger.info(
        "🎫 工单流转: %s「%s」 %s → %s.%s",
        ticket_id[:12], ticket["title"][:30],
        current_status, agent_name, action,
    )

    # 标记 Agent 忙碌
    orch._set_agent_busy(agent_name, ticket_id, ticket["title"][:50], action)

    # 更新到进行中状态
    if next_status:
        await db.update("tickets", {
            "status": next_status,
            "assigned_agent": agent_name,
            "current_owner": orch._agent_to_owner(agent_name),
            "started_at": ticket["started_at"] or now_iso(),
            "updated_at": now_iso(),
        }, "id = ?", (ticket_id,))

        await orch._log(
            project_id, ticket["requirement_id"], ticket_id, agent_name,
            "assign", current_status, next_status,
            f"{agent_name} 接单开始处理"
        )

        await event_manager.publish_to_project(
            project_id,
            "ticket_status_changed",
            {"ticket_id": ticket_id, "from": current_status, "to": next_status, "agent": agent_name},
        )
    return CONTINUE


async def switch_to_feature_branch(run: TicketRun) -> Optional[str]:
    """切到需求的 feat 分支。切换失败且停在主分支时停止，防止直接提交到主分支。"""
    db = run.db
    project_id = run.project_id
    ticket = run.ticket
    # 切换到需求对应的 feat 分支（确保文件提交到正确分支）
    try:
        req = await db.fetch_one(
            "SELECT branch_name FROM requirements WHERE id = ?",
            (ticket["requirement_id"],),
        )
        feat_branch = req.get("branch_name") if req else None
        if feat_branch and git_manager.repo_exists(project_id):
            current_br = await git_manager.get_current_branch(project_id)
            if current_br != feat_branch:
                ok = await git_manager.switch_branch(project_id, feat_branch)
                if ok:
                    logger.info("🌿 已切换到分支: %s", feat_branch)
                else:
                    # 切换失败 → 验证当前分支，如果在 main/master 上则阻止执行
                    current_br2 = await git_manager.get_current_branch(project_id)
                    if current_br2 in ("main", "master"):
                        logger.error("🛑 切换分支失败且当前在 %s，阻止 Agent 执行（防止直接提交到主分支）", current_br2)
                        return "branch_switch_failed_on_main"
                    logger.warning("切换分支失败: %s, 当前: %s（非主分支，继续执行）", feat_branch, current_br2)
    except Exception as br_err:
        logger.warning("切换分支异常(非致命): %s", br_err)
    return CONTINUE


async def build_agent_context(run: TicketRun) -> Optional[str]:
    """构建 Agent 上下文，写入触发状态、SOP 阶段配置和人工评论。"""
    orch = run.orch
    db = run.db
    ticket_id = run.ticket_id
    ticket = run.ticket
    current_status = run.current_status
    rule = run.rule
    agent_name = run.agent_name
    # 构建上下文（传入当前 Agent 名，供 KnowledgeLoader 差异化加载知识）
    # 注意：此时数据库里的 tickets.status 已被上面的 `if next_status` 改写为
    # `development_in_progress`，而 ticket["status"] 仍保留着触发态（如 `h5_typecheck_failed`、
    # `engine_compile_failed`）。必须把 `trigger_status` 透传进 context，否则
    # DevAgent._do_fix_issues 去查数据库只会读到 `development_in_progress`，永远走兜底 `testing_failed`！
    context = await orch._build_context(ticket, agent_name=agent_name)
    context["trigger_status"] = current_status

    # 注入 SOP 阶段配置到 context
    sop_config = rule.get("config", {})
    if sop_config:
        context["sop_config"] = sop_config

    # ===== 注入人工评论（最高优先级指令）=====
    human_comments = await db.fetch_all(
        "SELECT author, content, created_at FROM ticket_comments "
        "WHERE ticket_id = ? AND author_type = 'human' ORDER BY created_at ASC",
        (ticket_id,),
    )
    if human_comments:
        lines = "\n".join(
            f"- [{c['created_at'][:16]}] {c['content']}"
            for c in human_comments
        )
        context["human_instructions"] = (
            "## ⚠️ 人工指令（最高优先级，必须严格遵循）\n"
            "以下是人工在工单中留下的评论和指令，执行时必须优先遵循，不得偏离：\n"
            + lines
        )
        logger.info(
            "📌 工单 %s 注入 %d 条人工评论到 Agent prompt",
            ticket_id[:12], len(human_comments),
        )
    run.context = context
    return CONTINUE


async def run_agent(run: TicketRun) -> Optional[str]:
    """执行 Agent：发事件、设 LLM 上下文、起心跳，结束后标记空闲。"""
    orch = run.orch
    project_id = run.project_id
    ticket_id = run.ticket_id
    ticket = run.ticket
    agent_name = run.agent_name
    action = run.action
    context = run.context
    # Agent 执行
    await event_manager.publish_to_project(
        project_id,
        "agent_working",
        {"agent": agent_name, "action": action, "ticket_id": ticket_id},
    )

    # 模拟处理延迟（让前端能看到状态变化）
    await asyncio.sleep(1)

    # 设置 LLM 上下文
    set_llm_context(
        ticket_id=ticket_id,
        requirement_id=ticket["requirement_id"],
        project_id=project_id,
        agent_type=agent_name,
        action=action,
    )

    logger.info("🤖 %s.%s 开始执行...", agent_name, action)
    agent_start = time.time()
    # v0.19.x 工单面板进度区：写 current_action 字段
    await orch._set_ticket_current_action(ticket_id, f"{agent_name}.{action}")

    # 方案A：写 agent_start 思考日志
    await orch._log_agent_thought(
        project_id, ticket.get("requirement_id"), ticket_id,
        agent_name, action, "start",
        title=ticket.get("title", ""),
    )

    hb_task = asyncio.create_task(orch._ticket_heartbeat(ticket_id))
    try:
        # skill stage 必须经 SkillRunner。SOP 上的 agent 只是宿主 Role
        # （时间轴 / LLM agent_type / inject_to），不能直接调
        # PlannerAgent.execute("skill_xxx")——那会落到「未知任务」。
        result = await orch._execute_assigned_agent(
            agent_name, action, context,
        )
    finally:
        hb_task.cancel()
        try:
            await hb_task
        except (asyncio.CancelledError, Exception):
            pass
        await orch._clear_ticket_current_action(ticket_id)
    agent_elapsed = int((time.time() - agent_start) * 1000)
    logger.info(
        "🤖 %s.%s 完成 (%dms) → status=%s, files=%d",
        agent_name, action, agent_elapsed,
        result.get("status", "?"),
        len(result.get("files", {})),
    )

    # 方案A：写 agent_done 思考日志（含产出摘要）
    await orch._log_agent_thought(
        project_id, ticket.get("requirement_id"), ticket_id,
        agent_name, action, "done",
        result=result, elapsed_ms=agent_elapsed,
    )

    clear_llm_context()

    # 标记 Agent 空闲
    orch._set_agent_idle(agent_name, success=True)
    run.result = result
    return CONTINUE


async def _log_reflection(run: TicketRun, last_reflection: Dict[str, Any]) -> None:
    """把反思摘要写进 ticket_logs。失败只记 warning。"""
    orch = run.orch
    project_id = run.project_id
    ticket_id = run.ticket_id
    ticket = run.ticket
    agent_name = run.agent_name
    try:
        retry_count = last_reflection.get("retry_count", "?")
        root_cause = (last_reflection.get("root_cause") or "").strip()
        strategy = (last_reflection.get("strategy_change") or "").strip()
        changes = last_reflection.get("specific_changes") or []
        confidence = last_reflection.get("confidence", 0.0)

        # 组合一个人类可读的摘要（不截断，让前端展开看）
        parts = [f"[反思 #{retry_count}]"]
        if root_cause:
            parts.append(f"根因: {root_cause}")
        if strategy:
            parts.append(f"策略: {strategy}")
        if changes:
            changes_text = "; ".join(str(c) for c in changes[:3])
            parts.append(f"修改: {changes_text}")
        if isinstance(confidence, (int, float)):
            parts.append(f"(confidence={confidence:.2f})")

        message = " | ".join(parts)

        await orch._log(
            project_id,
            ticket.get("requirement_id"),
            ticket_id,
            agent_name,
            "reflection",
            None,
            None,
            message,
            "info",
            detail_data={"reflection": last_reflection},
        )
    except Exception as log_err:
        logger.warning("写 reflection 日志失败: %s", log_err)


async def _index_reflection(run: TicketRun, last_reflection: Dict[str, Any]) -> None:
    """把反思根因写进 tickets_fts 搜索索引。失败只记 warning。"""
    db = run.db
    project_id = run.project_id
    ticket_id = run.ticket_id
    # tickets_fts：reflection 后将根因加入搜索索引（让历史检索能找到错误类型）
    try:
        ticket_base = await db.fetch_one(
            "SELECT title, description FROM tickets WHERE id = ?", (ticket_id,)
        )
        if ticket_base:
            root_cause = (last_reflection.get("root_cause") or "").strip()
            errors_str = " ".join(
                str(e) for e in (last_reflection.get("specific_changes") or [])[:3]
            )
            search_text = (
                f"{ticket_base['title']} "
                f"{ticket_base['description'] or ''} "
                f"{root_cause} {errors_str}"
            ).strip()
            from api.knowledge import _upsert_tickets_fts
            await _upsert_tickets_fts(ticket_id, project_id, search_text)
    except Exception as fts_err:
        logger.warning("tickets_fts 更新失败（忽略）: %s", fts_err)


async def _record_failure_case(run: TicketRun, last_reflection: Dict[str, Any]) -> None:
    """往 Failure Library 写一条案例。失败只记 warning。"""
    project_id = run.project_id
    ticket_id = run.ticket_id
    ticket = run.ticket
    agent_name = run.agent_name
    action = run.action
    # Failure Library：同步写一条案例，供未来跨工单检索
    try:
        from failure_library import failure_library
        failure_type = ("testing_failed" if action == "fix_issues"
                        else "acceptance_rejected")
        await failure_library.record(
            agent_type=agent_name,
            failure_type=failure_type,
            reflection=last_reflection,
            project_id=project_id,
            requirement_id=ticket.get("requirement_id"),
            ticket_id=ticket_id,
            module=ticket.get("module"),
            ticket_title=ticket.get("title", "") or "",
            ticket_description=ticket.get("description", "") or "",
        )
    except Exception as fl_err:
        logger.warning("FailureLibrary.record 失败（已降级）: %s", fl_err)


async def record_reflection(run: TicketRun) -> Optional[str]:
    """结果里带反思时写三处：ticket_logs、tickets_fts、Failure Library。三处互不影响。"""
    result = run.result
    # Reflexion：rework / fix_issues 产出的反思写进 ticket_logs
    last_reflection = result.get("last_reflection") if isinstance(result, dict) else None
    if last_reflection and isinstance(last_reflection, dict):
        await _log_reflection(run, last_reflection)
        await _index_reflection(run, last_reflection)
        await _record_failure_case(run, last_reflection)
    return CONTINUE


async def handle_result(run: TicketRun) -> Optional[str]:
    """处理 Agent 结果；结果不是 error 时打阶段边界检查点。"""
    orch = run.orch
    project_id = run.project_id
    ticket_id = run.ticket_id
    ticket = run.ticket
    agent_name = run.agent_name
    action = run.action
    result = run.result
    # 处理结果
    await orch._handle_agent_result(project_id, ticket_id, ticket, agent_name, action, result)

    # Checkpoint：成功跑完一轮后打阶段边界（可供时间轴「还原到此」）
    try:
        if isinstance(result, dict) and result.get("status") != "error":
            from checkpoint.service import checkpoint_service
            await checkpoint_service.create_phase_boundary(
                project_id, ticket_id,
                agent_type=agent_name, action=action,
                note=f"{agent_name}.{action} 完成",
            )
    except Exception as _pbe:
        logger.debug("phase_boundary checkpoint 跳过: %s", _pbe)
    return CONTINUE


async def apply_pending_restart(run: TicketRun) -> Optional[str]:
    """应用执行期间排队的阶段回退。回退生效时停止，由回退自己触发后续流转。"""
    orch = run.orch
    db = run.db
    project_id = run.project_id
    ticket_id = run.ticket_id
    ticket = run.ticket
    # === 阶段重置排队：在途 run 已收尾，此刻应用回退（优先于正常流转）===
    # 评论触发的 tweak/partial 在工单执行中登记到 _pending_restart，
    # 这里应用才不会被刚写完的 Agent 结果覆盖。
    pending = orch._pending_restart.pop(ticket_id, None)
    if pending:
        cur = await db.fetch_one("SELECT status FROM tickets WHERE id = ?", (ticket_id,))
        cur_status = (cur or {}).get("status") or ""
        if cur_status in orch._HARD_TERMINAL:
            logger.info(
                "⏭ 工单 %s 已终态 %s，放弃排队中的阶段回退",
                ticket_id[:12], cur_status,
            )
        elif await orch._is_forward_jump(
            project_id, cur_status, pending["status"], ticket.get("type"),
        ):
            # 刚收尾的这一跑可能已经把工单退得比回退目标更靠前（如 rework
            # 把状态打回 development_done，而排队目标是 acceptance_passed），
            # 此时应用回退反而会跳过中间阶段。评论已注入，让它自然往下跑。
            logger.info(
                "⏭ 工单 %s 收尾后已在 %s，排队的回退目标 %s 会前跳，放弃改写",
                ticket_id[:12], cur_status, pending["status"],
            )
        else:
            orch._release_ticket(ticket_id)
            await orch._apply_status_rewind(
                ticket_id, project_id, cur_status,
                pending["status"], pending["reason"],
            )
            return "status_rewound"
    return CONTINUE


async def publish_next_stage(run: TicketRun) -> Optional[str]:
    """新状态命中规则时，先释放处理权，再发 ticket_ready 触发下一阶段。"""
    orch = run.orch
    db = run.db
    project_id = run.project_id
    ticket_id = run.ticket_id
    ticket = run.ticket
    # === 事件驱动：触发后续阶段立即处理 ===
    updated = await db.fetch_one("SELECT status FROM tickets WHERE id = ?", (ticket_id,))
    if updated:
        project_rules = await orch._get_rules_for_project(
            project_id, ticket_type=ticket.get("type"),
        )
        if updated["status"] in project_rules:
            # 先释放互斥，再发布；否则事件侧 process_ticket 会撞 claim 被跳过
            orch._release_ticket(ticket_id)
            await orch._publish_ticket_ready(project_id, ticket_id)
    return CONTINUE


# 执行顺序。从 `assign_ticket` 起，工单已改成进行中、Agent 已标忙碌。
STEPS = (
    load_ticket,
    check_entry_gates,
    check_global_circuit_breaker,
    check_dependencies,
    match_rule,
    check_stage_retry_limit,
    select_agent,
    skip_inapplicable_stage,
    ensure_agent_registered,
    assign_ticket,
    switch_to_feature_branch,
    build_agent_context,
    run_agent,
    record_reflection,
    handle_result,
    apply_pending_restart,
    publish_next_stage,
)


async def run_pipeline(run: TicketRun) -> Optional[str]:
    """按 `STEPS` 的顺序执行。有步骤停止时返回它给的原因，走完全程返回 `CONTINUE`。

    停在哪一步、为什么停，记在 `run.stopped_at` 和 `run.stop_reason` 上。
    异常不在这里处理，原样抛给 `process_ticket`。
    """
    for step in STEPS:
        reason = await step(run)
        if reason is not CONTINUE:
            run.stopped_at = step.__name__
            run.stop_reason = reason
            logger.debug(
                "工单 %s 本轮停在 %s（%s）", run.ticket_id[:12], run.stopped_at, reason,
            )
            return reason
    return CONTINUE
