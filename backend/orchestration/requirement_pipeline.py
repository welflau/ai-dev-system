"""`handle_requirement` 的分步管线：一次需求分析按顺序走完 `STEPS` 里的每一步。

从 `TicketOrchestrator.handle_requirement` 拆出（重构方案 R2 第 2 步的延续）。
`handle_requirement` 保留外层骨架：分析占用标记、异常兜底、`finally` 里的释放。

约定和 `ticket_pipeline` 相同：

- 每一步是 `async def step(run) -> Optional[str]`。返回 `CONTINUE` 进入下一步；
  返回原因字符串表示本轮到此为止，对应拆分前函数体里的一次 `return`。
- 步骤之间共享的值放在 `RequirementRun` 上，字段和拆分前的局部变量同名。
- 步骤体从原函数按顺序原样搬出。改动有三处：`self` 写成 `orch`；共享的局部变量
  从 `run` 取、往 `run` 存；两处 `return` 带上停止原因。
- `db` 和 `llm_client` 由调用方传入，这里不导入这两个对象。测试用
  `monkeypatch.setattr(orchestrator, ...)` 换掉它们，步骤必须拿到同一个对象。
- 函数内的延迟导入（`memory`、`api.milestones`）保持原样，测试的打桩打在这些源模块上。
- 步骤都在 `handle_requirement` 所在的协程里直接 `await`，不另起任务，和拆分前的执行方式一致。
- 步骤里出的异常不在这里处理，原样抛给 `handle_requirement` 的兜底。

从 `create_tickets` 到 `mark_decomposed` 的落库不在事务里，中途出错时已建的工单会留下。
这是拆分前就有的行为，`tests/agents/test_orchestrator_handle_requirement.py` 里标了
「现状」的用例记着这一类情况。

新增步骤时接到 `STEPS` 里，元组的顺序就是执行顺序。
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from events import event_manager
from git_manager import git_manager
from llm_client import clear_llm_context, set_llm_context
from models import RequirementStatus, TicketStatus
from utils import generate_id, now_iso

logger = logging.getLogger("orchestrator")

# 步骤返回 CONTINUE 表示继续下一步；返回原因字符串表示停止。
CONTINUE = None


def analysis_progress_message(elapsed_s: int, step: str, timeout_s: int) -> str:
    """PRD 分析心跳文案。看板实时日志靠它判断还活着。"""
    step = (step or "等待 LLM").strip()
    return f"PRD 分析仍在进行（已 {int(elapsed_s)}s / 超时 {int(timeout_s)}s）：{step}"


@dataclass
class RequirementRun:
    """一次 `handle_requirement` 调用里各步骤共享的状态。

    `requirement` 是分析开始前读到的那一行，后面的步骤改了数据库也不刷新它。

    `current_step` 是只有一个键 `name` 的字典，`on_step` 每次被调用都改写它，
    心跳日志从这里取「现在做到哪一步」。
    """

    orch: Any                               # TicketOrchestrator
    db: Any
    llm_client: Any                         # 只读它的几个属性拼开场文案和超时
    project_id: str
    requirement_id: str
    requirement: Optional[Dict[str, Any]] = None
    agent: Any = None                       # ProductAgent
    timeout_s: int = 0
    current_step: Optional[Dict[str, str]] = None
    on_step: Optional[Callable[[str], Any]] = None
    existing_files: Optional[List[Any]] = None
    existing_code: Optional[Dict[str, Any]] = None
    result: Any = None                      # ProductAgent 的回传
    prd_summary: str = ""
    tickets_data: Optional[List[Dict[str, Any]]] = None
    created_tickets: Optional[List[str]] = None     # 父工单号，按创建顺序
    idx_to_id: Optional[Dict[int, str]] = None      # 回传里的下标 → 工单号
    stopped_at: str = ""                    # 停在哪一步（函数名），走完全程时为空
    stop_reason: Optional[str] = None


async def load_requirement(run: RequirementRun) -> Optional[str]:
    """取需求。查不到时停止。"""
    db = run.db
    requirement_id = run.requirement_id

    requirement = await db.fetch_one(
        "SELECT * FROM requirements WHERE id = ?", (requirement_id,)
    )
    if not requirement:
        return "requirement_not_found"

    logger.info("━" * 60)
    logger.info("📋 开始处理需求: %s「%s」", requirement_id[:12], requirement["title"])
    logger.info("━" * 60)

    run.requirement = requirement
    return CONTINUE


async def announce_start(run: RequirementRun) -> Optional[str]:
    """写开场进度、发 `agent_working`、设 LLM 上下文。`on_step` 和超时留给后面的步骤用。"""
    orch = run.orch
    llm_client = run.llm_client
    project_id = run.project_id
    requirement_id = run.requirement_id
    requirement = run.requirement

    agent = orch.agents["ProductAgent"]
    llm_fmt = getattr(llm_client, "api_format", "") or "unknown"
    llm_name = (
        f"CLI {getattr(llm_client, 'cli_type', '') or getattr(llm_client, 'cli_model', '')}"
        if llm_fmt == "cli"
        else f"{llm_fmt} {getattr(llm_client, 'model', '')}"
    ).strip()
    timeout_s = int(
        getattr(llm_client, "cli_timeout", 0) or getattr(llm_client, "timeout", 0) or 1800
    )
    current_step = {"name": "准备分析"}

    async def on_step(msg: str):
        current_step["name"] = msg
        await orch._log(
            project_id, requirement_id, None, "ProductAgent",
            "progress", "analyzing", "analyzing", msg,
        )

    await on_step(
        f"开始 PRD 分析「{requirement['title']}」：{llm_name}，超时 {timeout_s}s。"
        f"分析期间会写进度，不会一直空白。"
    )
    await orch._log_agent_thought(
        project_id, requirement_id, None,
        "ProductAgent", "analyze_and_decompose", "start",
        title=requirement.get("title") or "",
    )

    # 发 SSE：开始分析
    await event_manager.publish_to_project(
        project_id,
        "agent_working",
        {"agent": "ProductAgent", "action": "analyze_and_decompose", "requirement_id": requirement_id},
    )

    # 设置 LLM 上下文（用于记录会话）
    set_llm_context(
        ticket_id=None,
        requirement_id=requirement_id,
        project_id=project_id,
        agent_type="ProductAgent",
        action="analyze_and_decompose",
    )

    run.agent = agent
    run.timeout_s = timeout_s
    run.current_step = current_step
    run.on_step = on_step
    return CONTINUE


async def read_code_context(run: RequirementRun) -> Optional[str]:
    """读项目已有代码，供 ProductAgent 拆单时参考。读不到就按需求原文拆。"""
    project_id = run.project_id
    on_step = run.on_step

    # 读取已有代码上下文（避免盲拆单：让 ProductAgent 看到现有文件和关键代码
    # 之后再判断复杂度/拆出工单，防止与已有架构冲突或重复）
    from memory import AgentMemory
    try:
        await on_step("正在读取项目代码上下文…")
        code_ctx = await AgentMemory(project_id).get_code_context()
        existing_files = code_ctx.get("file_list", [])
        existing_code = code_ctx.get("code", {})
        if existing_files:
            logger.info("📂 decompose 读到代码上下文: %d 文件, %d 片段",
                        len(existing_files), len(existing_code))
            await on_step(f"已读取 {len(existing_files)} 个文件、{len(existing_code)} 段代码，开始理解项目。")
        else:
            await on_step("项目还没有代码，直接按需求拆单。")
    except Exception as e:
        logger.warning("decompose 读代码上下文失败: %s", e)
        existing_files, existing_code = [], {}
        await on_step(f"读取代码上下文失败（{e}），将按需求原文拆单。")

    run.existing_files = existing_files
    run.existing_code = existing_code
    return CONTINUE


async def run_analysis(run: RequirementRun) -> Optional[str]:
    """调 ProductAgent 拆单，期间每 20 秒写一条心跳。结束后清 LLM 上下文。"""
    orch = run.orch
    db = run.db
    project_id = run.project_id
    requirement_id = run.requirement_id
    requirement = run.requirement
    agent = run.agent
    timeout_s = run.timeout_s
    current_step = run.current_step
    on_step = run.on_step
    existing_files = run.existing_files
    existing_code = run.existing_code

    # Agent 执行拆单
    logger.info("🤖 ProductAgent.analyze_and_decompose 开始执行...")
    req_start = time.time()

    async def _heartbeat():
        elapsed = 0
        while True:
            await asyncio.sleep(20)
            elapsed += 20
            try:
                await orch._log(
                    project_id, requirement_id, None, "ProductAgent",
                    "heartbeat", "analyzing", "analyzing",
                    analysis_progress_message(elapsed, current_step["name"], timeout_s),
                )
            except Exception as hb_err:
                logger.debug("需求分析心跳失败: %s", hb_err)

    hb_task = asyncio.create_task(_heartbeat())
    try:
        project_traits: list = []
        try:
            prow = await db.fetch_one("SELECT traits FROM projects WHERE id = ?", (project_id,))
            if prow and prow.get("traits"):
                raw = prow["traits"]
                project_traits = json.loads(raw) if isinstance(raw, str) else list(raw)
        except Exception:
            project_traits = []
        result = await agent.execute("analyze_and_decompose", {
            "title": requirement["title"],
            "description": requirement["description"],
            "priority": requirement["priority"],
            "project_id": project_id,
            "existing_files": existing_files,
            "existing_code": existing_code,
            "project_traits": project_traits,
            "on_step": on_step,
        })
    finally:
        hb_task.cancel()
        try:
            await hb_task
        except asyncio.CancelledError:
            pass
    req_elapsed = int((time.time() - req_start) * 1000)
    logger.info("🤖 ProductAgent.analyze_and_decompose 完成 (%dms) → status=%s", req_elapsed, result.get("status"))
    await orch._log_agent_thought(
        project_id, requirement_id, None,
        "ProductAgent", "analyze_and_decompose", "done",
        result=result, elapsed_ms=req_elapsed,
    )

    clear_llm_context()

    run.result = result
    return CONTINUE


async def check_analysis_result(run: RequirementRun) -> Optional[str]:
    """Agent 回传不是 success 时，需求退回已提交并停止。"""
    orch = run.orch
    db = run.db
    project_id = run.project_id
    requirement_id = run.requirement_id
    result = run.result

    if result.get("status") != "success":
        await orch._log(
            project_id, requirement_id, None, "ProductAgent",
            "error", "analyzing", "analyzing",
            f"需求分析失败: {result.get('message', '未知错误')}", "error"
        )
        # 回退状态允许重试
        await db.update("requirements", {
            "status": RequirementStatus.SUBMITTED.value,
            "updated_at": now_iso(),
        }, "id = ?", (requirement_id,))
        return "analysis_failed"

    return CONTINUE


async def record_analysis(run: RequirementRun) -> Optional[str]:
    """记录分析结果：规则引擎降级告警、投票留痕、PRD 摘要入库、PRD 文件走 Git。"""
    orch = run.orch
    db = run.db
    project_id = run.project_id
    requirement_id = run.requirement_id
    result = run.result

    # 记录是否走了降级路径
    prd_summary = result.get("prd_summary", "")
    is_fallback = prd_summary.startswith("[规则引擎]")
    if is_fallback:
        await orch._log(
            project_id, requirement_id, None, "ProductAgent",
            "info", "analyzing", "analyzing",
            "[WARNING] LLM 不可用，使用规则引擎降级拆单", "warning"
        )

    # Self-Consistency 投票留痕（如果开启）
    vote = result.get("_consistency_vote")
    if vote:
        await orch._log(
            project_id, requirement_id, None, "ProductAgent",
            "consistency_vote", None, None,
            f"🗳️ 拆单投票: {vote.get('n_candidates')} 候选 → 选 #{vote.get('best_index')}"
            f"{' (judge fallback)' if vote.get('fallback') else ''} | {vote.get('reasoning', '')[:150]}",
            "info", detail_data={"consistency_vote": vote},
        )
    await db.update("requirements", {
        "prd_content": prd_summary,
        "updated_at": now_iso(),
    }, "id = ?", (requirement_id,))

    # === 写入 PRD 文件到 Git 仓库 ===
    prd_files = result.get("files", {})
    git_result = None
    if prd_files:
        git_result = await orch._handle_git_files(
            project_id, None, requirement_id,
            "ProductAgent", "analyze_and_decompose", result
        )

    run.prd_summary = prd_summary
    return CONTINUE


async def create_tickets(run: RequirementRun) -> Optional[str]:
    """第一遍：建父工单、子任务、子工单。依赖先占位，下一步回填。"""
    orch = run.orch
    db = run.db
    project_id = run.project_id
    requirement_id = run.requirement_id
    result = run.result

    # 创建工单（两遍：先创建所有工单，再回填依赖 ID）
    tickets_data = [tk for tk in (result.get("tickets") or []) if isinstance(tk, dict)]
    created_tickets = []        # [ticket_id, ...]
    idx_to_id = {}              # 索引 → TK-ID 映射

    # 需求级 AI 生图开关：拆出的工单统一继承
    req_use_aigc = 0
    try:
        _req_row = await db.fetch_one(
            "SELECT use_aigc FROM requirements WHERE id = ?", (requirement_id,)
        )
        req_use_aigc = int((_req_row or {}).get("use_aigc") or 0)
    except Exception:
        pass

    # === 第一遍：创建所有父工单 ===
    for idx, tk in enumerate(tickets_data):
        ticket_id = generate_id("TK")
        now = now_iso()
        idx_to_id[idx] = ticket_id

        # 需求规模自适应：按复杂度跳过不必要的阶段
        complexity = result.get("complexity", "medium")
        ticket_count = len(result.get("tickets") or [])
        initial_status = TicketStatus.PENDING.value

        if complexity == "simple" or ticket_count <= 1:
            # XS：改颜色/改文案/小 Bug 修复 → 跳过 Planner + Architect，直接开发
            initial_status = TicketStatus.ARCHITECTURE_DONE.value
            logger.info("规模 XS：跳过策划+架构阶段 → 直接开发 (%s)", (tk.get("title") or "")[:20])
        elif complexity == "medium" and ticket_count <= 2:
            # S：小功能 → 跳过 Planner（策划已在需求层面做），直接架构
            initial_status = TicketStatus.PLANNING_DONE.value
            logger.info("规模 S：跳过策划阶段 → 直接架构 (%s)", (tk.get("title") or "")[:20])

        ticket = {
            "id": ticket_id,
            "requirement_id": requirement_id,
            "project_id": project_id,
            "parent_ticket_id": None,
            "title": tk.get("title") or f"工单 {idx + 1}",
            "description": tk.get("description", ""),
            "type": tk.get("type", "feature"),
            "module": tk.get("module", "other"),
            "priority": tk.get("priority", 3),
            "sort_order": idx,
            "status": initial_status,
            "assigned_agent": None,
            "current_owner": "product",
            "estimated_hours": tk.get("estimated_hours"),
            "actual_hours": None,
            "use_aigc": req_use_aigc,  # 继承需求级开关
            "estimated_completion": None,
            "dependencies": "[]",  # 占位，第二遍回填
            "result": None,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "completed_at": None,
        }
        await db.insert("tickets", ticket)
        created_tickets.append(ticket_id)

        # 创建子任务
        for st_idx, st in enumerate(tk.get("subtasks", [])):
            st_id = generate_id("ST")
            # 兼容字符串和 dict 两种格式
            if isinstance(st, str):
                st_title = st
                st_desc = ""
            else:
                st_title = st.get("title", str(st))
                st_desc = st.get("description", "")
            await db.insert("subtasks", {
                "id": st_id,
                "ticket_id": ticket_id,
                "title": st_title,
                "description": st_desc,
                "status": "pending",
                "assigned_agent": None,
                "sort_order": st_idx,
                "result": None,
                "created_at": now,
                "updated_at": now,
                "completed_at": None,
            })

        # 创建子工单（children）
        children_data = tk.get("children", [])
        for ch_idx, ch in enumerate(children_data):
            child_id = generate_id("TK")
            child_now = now_iso()
            child_ticket = {
                "id": child_id,
                "requirement_id": requirement_id,
                "project_id": project_id,
                "parent_ticket_id": ticket_id,
                "title": ch.get("title") or f"子工单 {ch_idx + 1}",
                "description": ch.get("description", ""),
                "type": ch.get("type", tk.get("type", "feature")),
                "module": ch.get("module", tk.get("module", "other")),
                "priority": ch.get("priority", tk.get("priority", 3)),
                "sort_order": ch_idx,
                "status": TicketStatus.PENDING.value,
                "assigned_agent": None,
                "current_owner": "product",
                "estimated_hours": ch.get("estimated_hours"),
                "actual_hours": None,
                "estimated_completion": None,
                "dependencies": "[]",
                "result": None,
                "created_at": child_now,
                "updated_at": child_now,
                "started_at": None,
                "completed_at": None,
            }
            await db.insert("tickets", child_ticket)

        # 日志
        dep_info = ""
        raw_deps = tk.get("dependencies", [])
        if raw_deps:
            dep_titles = [tickets_data[d].get("title") or f"工单{d}" for d in raw_deps if isinstance(d, int) and 0 <= d < len(tickets_data)]
            if dep_titles:
                dep_info = f"，依赖: {', '.join(dep_titles)}"
        children_info = f"，含 {len(children_data)} 个子工单" if children_data else ""
        await orch._log(
            project_id, requirement_id, ticket_id, "ProductAgent",
            "create", None, "pending",
            f"工单「{tk.get('title') or ticket_id}」已创建，模块: {tk.get('module', 'other')}{dep_info}{children_info}"
        )

    run.tickets_data = tickets_data
    run.created_tickets = created_tickets
    run.idx_to_id = idx_to_id
    return CONTINUE


async def backfill_dependencies(run: RequirementRun) -> Optional[str]:
    """第二遍：把依赖里的下标换成真实工单号。"""
    db = run.db
    tickets_data = run.tickets_data
    idx_to_id = run.idx_to_id

    # === 第二遍：回填依赖 ID（索引 → 真实 TK-ID）===
    for idx, tk in enumerate(tickets_data):
        raw_deps = tk.get("dependencies", [])
        if raw_deps:
            current_tk_id = idx_to_id[idx]
            dep_ids = []
            for d in raw_deps:
                if isinstance(d, int) and d in idx_to_id:
                    dep_id = idx_to_id[d]
                    if dep_id != current_tk_id:  # 过滤自引用
                        dep_ids.append(dep_id)
                elif isinstance(d, str) and d.startswith("TK-"):
                    if d != current_tk_id:  # 过滤自引用
                        dep_ids.append(d)
            if dep_ids:
                await db.update(
                    "tickets",
                    {"dependencies": json.dumps(dep_ids), "updated_at": now_iso()},
                    "id = ?",
                    (current_tk_id,),
                )

    return CONTINUE


async def mark_decomposed(run: RequirementRun) -> Optional[str]:
    """需求改成已拆单，写日志、发 `requirement_decomposed`、存 PRD 产物。"""
    orch = run.orch
    db = run.db
    project_id = run.project_id
    requirement_id = run.requirement_id
    requirement = run.requirement
    prd_summary = run.prd_summary
    created_tickets = run.created_tickets

    # 更新需求状态为已拆单
    await db.update("requirements", {
        "status": RequirementStatus.DECOMPOSED.value,
        "updated_at": now_iso(),
    }, "id = ?", (requirement_id,))

    await orch._log(
        project_id, requirement_id, None, "ProductAgent",
        "decompose", "analyzing", "decomposed",
        f"需求已拆分为 {len(created_tickets)} 个工单"
    )

    await event_manager.publish_to_project(
        project_id,
        "requirement_decomposed",
        {
            "requirement_id": requirement_id,
            "ticket_count": len(created_tickets),
            "ticket_ids": created_tickets,
        },
    )

    # 保存 PRD 产物
    await db.insert("artifacts", {
        "id": generate_id("ART"),
        "project_id": project_id,
        "requirement_id": requirement_id,
        "ticket_id": None,
        "type": "prd",
        "name": f"PRD - {requirement['title']}",
        "path": None,
        "content": prd_summary,
        "metadata": json.dumps({"ticket_count": len(created_tickets)}),
        "created_at": now_iso(),
    })

    return CONTINUE


async def associate_milestone(run: RequirementRun) -> Optional[str]:
    """自动关联里程碑。失败不影响后续。"""
    project_id = run.project_id
    requirement_id = run.requirement_id
    requirement = run.requirement
    created_tickets = run.created_tickets

    # === 自动关联里程碑 + 修正 Roadmap ===
    try:
        from api.milestones import auto_associate_requirement
        await auto_associate_requirement(
            project_id, requirement_id,
            requirement["title"], requirement["description"],
            ticket_count=len(created_tickets),
        )
    except Exception as ms_err:
        logger.warning("自动关联里程碑失败(非致命): %s", ms_err)

    return CONTINUE


async def create_feature_branch(run: RequirementRun) -> Optional[str]:
    """从 develop 拉需求的开发分支，分支名记到需求上。失败不影响后续。"""
    orch = run.orch
    db = run.db
    project_id = run.project_id
    requirement_id = run.requirement_id

    # === 自动创建 Git 分支 ===
    branch_name = None
    try:
        import re
        from datetime import datetime
        date_str = datetime.now().strftime("%Y%m%d")
        # 分支名只用英文数字：feat/{日期}-req-{需求短码}
        req_short = requirement_id[-6:]
        branch_name = f"feat/{date_str}-req-{req_short}"

        # 确保 develop 存在，从主分支（main 或 master）拉取新分支
        primary_branch = await git_manager.get_primary_branch(project_id)
        await git_manager.ensure_branch(project_id, "develop", from_branch=primary_branch)
        ok = await git_manager.switch_branch(project_id, "develop")
        if not ok:
            logger.warning("切换到 develop 失败，将在默认分支上开发")

        ok = await git_manager.create_branch(project_id, branch_name)
        if ok:
            # 保存分支名到需求
            await db.update("requirements", {
                "branch_name": branch_name,
                "updated_at": now_iso(),
            }, "id = ?", (requirement_id,))

            await orch._log(
                project_id, requirement_id, None, "Orchestrator",
                "info", "decomposed", "decomposed",
                f"已创建开发分支: {branch_name}"
            )
            logger.info("🌿 开发分支已创建: %s", branch_name)
        else:
            branch_name = None
            logger.warning("创建分支失败，将在默认分支上开发")
    except Exception as br_err:
        branch_name = None
        logger.warning("创建分支失败(非致命): %s", br_err)

    return CONTINUE


async def dispatch_tickets(run: RequirementRun) -> Optional[str]:
    """需求改成进行中，按创建顺序逐张派单。"""
    orch = run.orch
    db = run.db
    project_id = run.project_id
    requirement_id = run.requirement_id
    created_tickets = run.created_tickets

    # 自动启动所有工单的 Agent 流转
    # 更新需求状态为进行中
    await db.update("requirements", {
        "status": RequirementStatus.IN_PROGRESS.value,
        "updated_at": now_iso(),
    }, "id = ?", (requirement_id,))

    for ticket_id in created_tickets:
        await orch.process_ticket(project_id, ticket_id)

    return CONTINUE

# 执行顺序。`create_tickets` 起开始写工单表；`dispatch_tickets` 之前需求已改成进行中。
STEPS = (
    load_requirement,
    announce_start,
    read_code_context,
    run_analysis,
    check_analysis_result,
    record_analysis,
    create_tickets,
    backfill_dependencies,
    mark_decomposed,
    associate_milestone,
    create_feature_branch,
    dispatch_tickets,
)


async def run_pipeline(run: RequirementRun) -> Optional[str]:
    """按 `STEPS` 的顺序执行。有步骤停止时返回它给的原因，走完全程返回 `CONTINUE`。

    停在哪一步、为什么停，记在 `run.stopped_at` 和 `run.stop_reason` 上。
    异常不在这里处理，原样抛给 `handle_requirement`。
    """
    for step in STEPS:
        reason = await step(run)
        if reason is not CONTINUE:
            run.stopped_at = step.__name__
            run.stop_reason = reason
            logger.debug(
                "需求 %s 本轮停在 %s（%s）", run.requirement_id[:12], run.stopped_at, reason,
            )
            return reason
    return CONTINUE
