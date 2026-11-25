"""
AI 自动开发系统 - Orchestrator 工单编排器
核心调度引擎：管理工单在 Agent 之间的流转
"""
import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

from database import db
from models import (
    TicketStatus,
    RequirementStatus,
    AgentType,
    validate_ticket_transition,
    STATUS_LABELS,
)
from utils import generate_id, now_iso
from events import event_manager
from llm_client import llm_client
from git_manager import git_manager
from orchestration import (
    agent_state,
    blocked_diagnosis,
    bug_flow,
    change_flows,
    context_assembly,
    context_builder,
    failure_counters,
    git_persist,
    openspec_closeout,
    poll_cycle,
    polling,
    reporting,
    requirement_pipeline,
    result_flow,
    result_handlers,
    rewind,
    sop_rules,
    ticket_log,
    ticket_pipeline,
)
from orchestration.result_handlers import HANDLED, ResultContext
# 保留旧导入路径；skill 归属和处理器优先级由同一张注册表所在模块决定。
from orchestration.result_handlers import is_skill_run_result  # noqa: F401
# 心跳文案跟着需求分析的步骤搬到了 requirement_pipeline，原来的导入路径继续可用。
from orchestration.requirement_pipeline import analysis_progress_message  # noqa: F401
# 片段收尾用的纯函数搬到了 orchestration/sop_rules，tests/plugins/test_ue5_closeout.py 从这里导入
from orchestration.sop_rules import (  # noqa: F401
    stage_hook_names,
    rewind_trigger,
    closeout_log_level,
    closeout_message,
    closeout_detail,
)


logger = logging.getLogger("orchestrator")

# Agent 注册中心（自动发现 + 自定义 Agent）
from agent_registry import instantiate_agents


class TicketOrchestrator:
    """工单编排器 — 管理需求拆单和工单在 Agent 之间的流转"""

    def __init__(self):
        # Agent 池（通过注册中心自动发现和实例化）
        self.agents = instantiate_agents()

        # 正在处理的工单（防止重复处理）。claim 必须在 process_ticket 入口、且在任何 await 之前完成。
        self._processing: set = set()
        # process_ticket 协程本身。_processing 曾被外部 _release_ticket 清掉，
        # 但任务还在等模型；僵尸检测必须看这个，不能只看集合。
        self._running_tasks: Dict[str, asyncio.Task] = {}
        # 正在跑的需求分析。进程重启后面会丢，靠轮询把 status=analyzing 且不在此集合里的需求续跑。
        self._analyzing_reqs: set = set()

        # 每个项目的并发限制，防止大批需求同时涌入耗尽 LLM 配额
        self._MAX_CONCURRENT_PER_PROJECT = 1   # 顶层工单：每项目同时处理 1 个（DB 稳定）
        # L8: 子任务独立并发槽，最多 3 个子任务并行（不占顶层槽位）
        self._MAX_CONCURRENT_SUBTASKS = 3
        # 每个项目当前活跃的工单集合（顶层）— 仅用于项目级限流，不替代 _processing
        self._project_active: Dict[str, set] = {}
        # L8: 每个项目当前活跃的子任务集合（独立于顶层槽位）
        self._project_subtask_active: Dict[str, set] = {}

        # 硬终态：不再自动派单；迟到的 Agent 结果一律丢弃
        self._HARD_TERMINAL = {
            TicketStatus.BLOCKED.value,
            TicketStatus.CANCELLED.value,
            TicketStatus.TESTING_DONE.value,
            TicketStatus.DEPLOYED.value,
            TicketStatus.DONE.value,
            "completed",
        }

        # Agent 实时状态追踪
        self._agent_status: Dict[str, Dict] = {
            name: {"status": "idle", "ticket_id": None, "ticket_title": None,
                   "action": None, "started_at": None, "completed_count": 0, "error_count": 0}
            for name in self.agents.keys()
        }

        # === 从 SOP 配置加载状态转换规则 ===
        self._sop_config = None
        self.transition_rules = self._load_transition_rules()

        # v0.17 Phase C''：项目级 SOP rules 缓存
        # key = (project_id, traits_tuple)
        # value = dict of transition_rules
        self._project_rules_cache: Dict = {}

        # 阶段重置时工单正在执行 → 记下目标状态，等在途 run 收尾后再改写并续跑。
        # 直接改 status 会被在途 Agent 的结果覆盖（_handle_agent_result 只防终态回写）。
        # key = ticket_id, value = {"status", "reason", "from_phase"}
        self._pending_restart: Dict[str, Dict] = {}

    def _load_transition_rules(self) -> Dict:
        """从 SOP YAML 加载状态转换规则（默认 web 项目）"""
        return sop_rules.load_transition_rules(self)

    def reload_sop(self):
        """热重载 SOP 配置（供 API 调用）"""
        return sop_rules.reload_sop(self)

    # ==================== v0.17 Phase C''：项目级 SOP 规则 ====================

    _NONCODE_TICKET_KEYWORDS = sop_rules.NONCODE_TICKET_KEYWORDS

    def _is_noncode_ticket(self, ticket: Dict) -> bool:
        """启发式判断工单是否为"非代码验证/流程类"（无可编译产物）。"""
        return sop_rules.is_noncode_ticket(self, ticket)

    _UI_KEYWORDS_CN = sop_rules.UI_KEYWORDS_CN
    _UI_KEYWORDS_EN = sop_rules.UI_KEYWORDS_EN
    _WORD_RE = sop_rules.WORD_RE

    _NON_UI_MODULES = sop_rules.NON_UI_MODULES

    def _needs_design_stage(self, ticket: Dict) -> bool:
        """工单是否真的需要 UX / 美术设计阶段。"""
        return sop_rules.needs_design_stage(self, ticket)

    async def _get_rules_for_project(
        self,
        project_id: str,
        traits_json: Optional[str] = None,
        ticket_type: Optional[str] = None,
    ) -> Dict:
        """按项目 traits + 工单 type 派生 transition_rules。"""
        return await sop_rules.get_rules_for_project(self, db, project_id, traits_json, ticket_type)

    async def _sop_stage_for(
        self, project_id: str, action: str, ticket_type: Optional[str] = None,
    ) -> Optional[Dict]:
        """查该项目 SOP 里执行 `action` 的 stage 定义。"""
        return await sop_rules.sop_stage_for(self, project_id, action, ticket_type)

    async def _sop_stages_for(
        self, project_id: str, ticket_type: Optional[str] = None,
    ) -> List[Dict]:
        return await sop_rules.sop_stages_for(self, db, project_id, ticket_type)

    async def _sop_success_status_for(
        self, project_id: str, action: str, *, default: str,
        ticket_type: Optional[str] = None,
    ) -> str:
        """该项目 SOP 里 `action` 阶段声明的 success_status，找不到返回 default。"""
        return await sop_rules.sop_success_status_for(
            self, project_id, action, default=default, ticket_type=ticket_type,
        )

    async def _invoke_stage_hook(self, name: str, ctx: Dict) -> Optional[Dict]:
        return await sop_rules.invoke_stage_hook(self, name, ctx)

    async def _apply_fragment_closeout(
        self,
        project_id: str,
        ticket_id: str,
        ticket: Dict,
        agent_name: str,
        action: str,
        result: Dict,
        result_json: str,
        current_status: str,
        requirement_id: Optional[str],
    ) -> bool:
        """阶段声明了 closeout: status 时，按片段写状态并跑钩子。"""
        return await sop_rules.apply_fragment_closeout(
            self, db, project_id, ticket_id, ticket, agent_name, action, result, result_json,
            current_status, requirement_id,
        )

    def invalidate_project_rules(self, project_id: str):
        """清除指定项目的 rules 缓存（当 traits 变动时调用）"""
        return sop_rules.invalidate_project_rules(self, project_id)

    _TERMINAL_STATUSES = sop_rules.TERMINAL_STATUSES

    _MEDIA_COMMIT_LABELS = git_persist.MEDIA_COMMIT_LABELS

    async def _get_all_actionable_statuses(self) -> List[str]:
        """轮询扫 ticket 用的 WHERE IN (...) 集合。"""
        return await sop_rules.get_all_actionable_statuses(self, db)

    _status_is_executing = staticmethod(sop_rules.status_is_executing)

    def get_agent_status(self) -> Dict:
        """获取所有 Agent 的实时状态"""
        return agent_state.get_agent_status(self)

    def _set_agent_busy(self, agent_name: str, ticket_id: str, ticket_title: str, action: str):
        """标记 Agent 为忙碌"""
        return agent_state.set_agent_busy(self, agent_name, ticket_id, ticket_title, action)

    def _set_agent_idle(self, agent_name: str, success: bool = True):
        """标记 Agent 为空闲"""
        return agent_state.set_agent_idle(self, agent_name, success)

    # ==================== 工单级"当前进度"字段（v0.19.x） ====================
    #
    # tickets.current_action / _started_at / _latest_log / _updated_at 四列驱动
    # 工单属性面板的「📍 当前进度」区。分派 action 前 set，完成/异常后清。
    # 中间的 log 心跳走 Phase ②：log_callback → 过滤关键字 → 5s throttle → 写 DB。

    async def _set_ticket_current_action(self, ticket_id: str, action_label: str):
        """Action 开始：写 current_action + started_at，清空 latest_log"""
        return await agent_state.set_ticket_current_action(self, db, ticket_id, action_label)

    async def _clear_ticket_current_action(self, ticket_id: str):
        """Action 结束（无论成败）：清 4 列"""
        return await agent_state.clear_ticket_current_action(self, db, ticket_id)

    async def _create_compile_bug(
        self,
        project_id: str,
        requirement_id: Optional[str],
        ticket_id: str,
        errors_list: List[Dict],
        err_brief: str,
    ):
        """UBT 编译失败时自动创建 Bug 记录（走正式 Bug 流程，在 BUG 列表可见）"""
        return await bug_flow.create_compile_bug(
            self, db, project_id, requirement_id, ticket_id, errors_list, err_brief,
        )

    async def _resolve_compile_bug(self, ticket_id: str, project_id: str):
        """编译通过时把关联的 in_dev Bug 标为 fixed"""
        return await bug_flow.resolve_compile_bug(self, db, ticket_id, project_id)

    def _make_ticket_progress_callback(self, project_id: str, ticket_id: str):
        """生产 log 心跳 callback：关键字过滤 + 5s throttle + 去重 + 写 DB + 推 SSE"""
        return agent_state.make_ticket_progress_callback(self, db, project_id, ticket_id)

    # ==================== 轮询调度 ====================

    def _try_claim_ticket(self, ticket_id: str) -> bool:
        """无 await 地占用工单处理权。已占用则返回 False（asyncio 单线程下 check+add 原子）。"""
        return polling.try_claim_ticket(self, ticket_id)

    def _release_ticket(self, ticket_id: str) -> None:
        return polling.release_ticket(self, ticket_id)

    def _ticket_held_by_this_process(self, ticket_id: str) -> bool:
        """本进程还在跑这张工单：禁止当成僵尸回退。"""
        return polling.ticket_held_by_this_process(self, ticket_id)

    async def _ticket_heartbeat(self, ticket_id: str, interval: float = 20.0):
        """等模型首包时可能几分钟没有 log。不刷新 updated_at，60s 僵尸门会误杀。"""
        return await polling.ticket_heartbeat(self, db, ticket_id, interval)

    def _enqueue_ticket(
        self, project_id: str, ticket_id: str, *, is_subtask: bool = False, source: str = "",
    ) -> bool:
        """轮询侧调度：占项目槽 + create_task(_poll_process)。"""
        return polling.enqueue_ticket(
            self, project_id, ticket_id, is_subtask=is_subtask, source=source,
        )

    async def start_event_bus(self):
        """启动内部事件总线"""
        return await polling.start_event_bus(self)

    async def _publish_ticket_ready(self, project_id: str, ticket_id: str):
        """发布工单就绪事件（触发下一个 Agent 立即接手）"""
        return await polling.publish_ticket_ready(self, project_id, ticket_id)

    async def poll_loop(self, interval: int = 30):
        """后台轮询：兜底机制，扫描遗漏的工单（间隔已放宽到 30s）"""
        return await polling.poll_loop(self, interval)

    async def _repair_status_outside_sop(
        self, project_id: str, ticket: dict, current_status: str,
    ) -> Optional[str]:
        """status 不在当前项目 SOP 里时（视频工单被 unblock 到 architecture_done），"""
        return await polling.repair_status_outside_sop(self, db, project_id, ticket, current_status)

    async def _zombie_rewind_status(self, ticket_id: str, status: str) -> Optional[str]:
        """僵尸工单该回退到哪个状态重跑。"""
        return await polling.zombie_rewind_status(self, db, ticket_id, status)

    async def _poll_once(self):
        """单次轮询：扫描所有可流转状态的工单并处理"""
        return await poll_cycle.poll_once(self, db)

    async def _resume_stuck_analyses(self):
        """status=analyzing 但本进程没在跑 → 上次进程死了，重新拆单。"""
        return await polling.resume_stuck_analyses(self, db)

    async def _poll_open_bugs(self):
        """扫描所有 status=open 的 BUG，自动触发修复（无需手动点击）"""
        return await bug_flow.poll_open_bugs(self, db)

    async def _check_subtasks_complete(self, parent_ticket_id: str, project_id: str, parent_row: dict):
        """Phase 4：检查父 Ticket 的所有子 Ticket 是否全部完成。"""
        return await poll_cycle.check_subtasks_complete(
            self, db, parent_ticket_id, project_id, parent_row,
        )

    async def _resume_parent_ticket(self, parent_ticket_id: str, project_id: str, parent_row: dict):
        """恢复父 Ticket：从 waiting_subtasks 恢复到 PENDING，让轮询器正常拾取"""
        return await polling.resume_parent_ticket(
            self, db, parent_ticket_id, project_id, parent_row,
        )

    async def _poll_process(self, project_id: str, ticket_id: str, is_subtask: bool = False):
        """调度触发的工单处理。_processing 由 process_ticket claim/release；此处只清项目槽。"""
        return await polling.poll_process(self, project_id, ticket_id, is_subtask)

    # ==================== BUG 修复工作流 ====================

    async def run_bug_fix(self, project_id: str, bug_id: str):
        """BUG 修复工作流：创建真实 ticket（type=bug）直接从 DevAgent 开始，"""
        return await bug_flow.run_bug_fix(self, db, project_id, bug_id)

    async def _run_bug_ticket(self, project_id: str, ticket_id: str, bug_id: str):
        """执行 BUG ticket 流转，并在测试完成后同步更新 bugs 表状态"""
        return await bug_flow.run_bug_ticket(self, project_id, ticket_id, bug_id)

    async def _sync_bug_status_from_ticket(self, project_id: str, ticket_id: str, bug_id: str):
        """按 ticket 最终状态回写 bugs 表。"""
        return await bug_flow.sync_bug_status_from_ticket(self, db, project_id, ticket_id, bug_id)

    async def _find_current_version(self, project_id: str) -> Optional[str]:
        """查找当前进行中的版本（milestone），用于 BUG 并入版本"""
        return await bug_flow.find_current_version(self, db, project_id)

    # ==================== 需求处理 ====================

    async def handle_requirement(self, project_id: str, requirement_id: str):
        """处理需求：分析 + 拆单。

        同一条需求同时只跑一次分析，靠 `_analyzing_reqs` 互斥。

        具体步骤在 `orchestration.requirement_pipeline`（`STEPS`），这里只保留外层骨架：
        占用标记、异常兜底、释放。
        """
        if requirement_id in self._analyzing_reqs:
            logger.info("需求分析已在进行，跳过重复调度: %s", requirement_id[:12])
            return
        self._analyzing_reqs.add(requirement_id)
        try:
            # 步骤之间共享的状态。db 和 llm_client 取调用时的模块全局，测试会换掉它们。
            run = requirement_pipeline.RequirementRun(
                orch=self, db=db, llm_client=llm_client,
                project_id=project_id, requirement_id=requirement_id,
            )
            await requirement_pipeline.run_pipeline(run)

        except Exception as e:
            logger.error("❌ 需求处理异常: %s", e, exc_info=True)

            # 记录错误日志
            try:
                await self._log(
                    project_id, requirement_id, None, "ProductAgent",
                    "error", "analyzing", "submitted",
                    f"需求处理异常: {str(e)}", "error"
                )
                # 将需求状态回退为已提交，允许用户重试
                await db.update("requirements", {
                    "status": RequirementStatus.SUBMITTED.value,
                    "updated_at": now_iso(),
                }, "id = ?", (requirement_id,))

                await event_manager.publish_to_project(
                    project_id,
                    "requirement_error",
                    {"requirement_id": requirement_id, "error": str(e)},
                )
            except Exception as log_err:
                logger.error("记录需求错误日志也失败了: %s", log_err)
        finally:
            self._analyzing_reqs.discard(requirement_id)

    # ==================== 工单流转 ====================

    async def _last_reset_at(self, ticket_id: str) -> Optional[str]:
        """最近一次人工解除 blocked / 重置计数的时间点，作为所有止损计数的共同起点。"""
        return await failure_counters.last_reset_at(self, db, ticket_id)

    async def _reject_count_since_reset(
        self, ticket_id: str, to_status: Optional[str] = None,
    ) -> int:
        """工单被打回的次数，**只数最近一次人工解除 blocked 之后的**。"""
        return await failure_counters.reject_count_since_reset(self, db, ticket_id, to_status)

    _failure_fingerprint = staticmethod(failure_counters.failure_fingerprint)

    async def _consecutive_same_failure(self, ticket_id: str) -> tuple:
        """最近连续出现同一失败原因的 reject 次数（跳过无原因的验收打回）。"""
        return await failure_counters.consecutive_same_failure(self, db, ticket_id)

    async def _acceptance_retry_count(self, ticket_id: str) -> int:
        """本工单因「验收 LLM 降级」已重派验收的次数（自最近一次 unblock 起）。"""
        return await failure_counters.acceptance_retry_count(self, db, ticket_id)

    async def process_ticket(self, project_id: str, ticket_id: str):
        """根据当前状态自动分派到对应 Agent。

        单工单互斥：入口 claim，退出 release。事件/轮询/create_task 共用此门闩，
        避免并发重复 assign / 重复止损。

        具体步骤在 `orchestration.ticket_pipeline`（`STEPS`），这里只保留外层骨架：
        claim、登记运行中的协程、异常处理、释放和清理。
        """
        if not self._try_claim_ticket(ticket_id):
            logger.info("⏭ 跳过工单 %s（已有处理中任务）", ticket_id[:12])
            return
        _cur_task = asyncio.current_task()
        if _cur_task is not None:
            self._running_tasks[ticket_id] = _cur_task
        # 步骤之间共享的状态。except / finally 会读 run.ticket，取工单失败时它是 None。
        run = ticket_pipeline.TicketRun(
            orch=self, db=db, project_id=project_id, ticket_id=ticket_id,
        )
        try:
            await ticket_pipeline.run_pipeline(run)

        except asyncio.CancelledError:
            logger.warning(
                "⚠️ 工单处理被取消 [%s]，CLI 可能仍在跑；不应当成僵尸回退",
                ticket_id[:12] if ticket_id else "?",
            )
            raise
        except Exception as e:
            logger.error("❌ 工单处理异常 [%s]: %s", ticket_id[:12] if ticket_id else "?", e, exc_info=True)
            # 标记 Agent 空闲（失败）。选出 Agent 之后出的错才记到它头上。
            if run.agent_chosen:
                self._set_agent_idle(run.agent_name, success=False)
            try:
                await self._log(
                    project_id, run.ticket.get("requirement_id") if run.ticket else None,
                    ticket_id, "Orchestrator",
                    "error", None, None,
                    f"工单处理异常: {str(e)}", "error"
                )
                await event_manager.publish_to_project(
                    project_id,
                    "ticket_error",
                    {"ticket_id": ticket_id, "error": str(e)},
                )
            except Exception as log_err:
                logger.error("记录工单错误日志也失败了: %s", log_err)
        finally:
            self._running_tasks.pop(ticket_id, None)
            self._release_ticket(ticket_id)
            # 兜底：异常路径下排队的阶段回退也要生效，否则用户看到「已重置」但工单不动
            try:
                leftover = self._pending_restart.pop(ticket_id, None)
                if leftover:
                    cur = await db.fetch_one(
                        "SELECT status FROM tickets WHERE id = ?", (ticket_id,)
                    )
                    cur_status = (cur or {}).get("status") or ""
                    if (
                        cur_status
                        and cur_status not in self._HARD_TERMINAL
                        and not await self._is_forward_jump(
                            project_id, cur_status, leftover["status"],
                            (run.ticket or {}).get("type"),
                        )
                    ):
                        await self._apply_status_rewind(
                            ticket_id, project_id, cur_status,
                            leftover["status"], leftover["reason"],
                        )
            except Exception as _pre:
                logger.warning("应用排队的阶段回退失败: %s", _pre)
            try:
                from checkpoint import clear_checkpoint_context
                clear_checkpoint_context()
            except Exception:
                pass

    async def _execute_assigned_agent(
        self,
        agent_name: str,
        action: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """真正调用 Agent.execute。

        skill stage（`sop_config.skill_id`）一律交给 SkillAgent / SkillRunner。
        SOP 上的 `agent` 只决定：时间轴归属、LLM `agent_type`、inject_to 知识。
        若直接调 `PlannerAgent.execute("skill_xxx")`，会落到「未知任务」error
        再被 `_handle_agent_result` 的 error→blocked 吃掉，skill 永远跑不起来。
        """
        sop = context.get("sop_config") or {}
        executor_name = "SkillAgent" if sop.get("skill_id") else agent_name
        executor = self.agents.get(executor_name)
        if executor is None:
            need = (
                f"（skill_id={sop.get('skill_id')} 需要 SkillAgent 作为执行引擎）"
                if sop.get("skill_id") else ""
            )
            return {
                "status": "error",
                "message": f"SOP 声明的 Agent「{executor_name}」未注册{need}",
            }
        return await executor.execute(action, context)

    async def _handle_agent_result(
        self,
        project_id: str,
        ticket_id: str,
        ticket: Dict,
        agent_name: str,
        action: str,
        result: Dict,
        *, assigned_status: Optional[str] = None,
    ) -> bool:
        """返回 False 表示工单已删除或结果已过期，管线应跳过本轮收尾。"""
        requirement_id = ticket["requirement_id"]
        current_ticket = await db.fetch_one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        if current_ticket is None:
            return False
        current_status = current_ticket["status"]

        # === 终态门闩：丢弃迟到的在途结果（blocked 后仍跑完的 fix_issues 等）===
        if current_status in self._HARD_TERMINAL:
            logger.warning(
                "⏭ 工单 %s 已终态 %s，忽略迟到的 %s.%s 结果",
                ticket_id[:12], current_status, agent_name, action,
            )
            await self._log(
                project_id, requirement_id, ticket_id, "Orchestrator",
                "stale_ignored", current_status, current_status,
                f"工单已终态 {current_status}，忽略迟到的 {agent_name}.{action} 结果，不改写状态",
                "warning",
                detail_data={
                    "ignored_agent": agent_name,
                    "ignored_action": action,
                    "result_status": (result or {}).get("status") if isinstance(result, dict) else None,
                },
            )
            return False

        if (assigned_status is not None and current_status != assigned_status
                and result_handlers.requires_assigned_status(agent_name, action, result)):
            logger.info("忽略迟到的 %s.%s：工单 %s 已离开派单状态 %s（当前 %s）",
                        agent_name, action, ticket_id, assigned_status, current_status)
            return False

        try:
            if isinstance(result, dict) and result.get("status") == "error":
                await result_flow.block_agent_error(
                    self, db, project_id=project_id, ticket_id=ticket_id, requirement_id=requirement_id,
                    ticket_snapshot=current_ticket, agent_name=agent_name, action=action,
                    result=result, current_status=current_status,
                )
            else:
                await self._route_agent_result(
                    project_id, ticket_id, ticket, agent_name, action, result, current_status,
                )
        except result_flow.StaleAgentResult:
            logger.info("忽略迟到的 %s.%s：工单 %s 已删除或已离开 %s",
                        agent_name, action, ticket_id, current_status)
            return False
        return True

    async def _route_agent_result(self, project_id, ticket_id, ticket, agent_name, action,
                                  result, current_status):
        requirement_id = ticket["requirement_id"]
        result_json = result_flow.serialize_result(result)

        # === 通用：处理 Agent 返回的 files，写入 Git 仓库 ===
        git_result = await self._handle_git_files(
            project_id, ticket_id, requirement_id,
            agent_name, action, result
        )

        # 片段声明 closeout: status 的阶段在这里收尾并 return。
        # 不能落到后面的 develop 产物落库，否则测试生成会把状态写回 development_done。
        if await self._apply_fragment_closeout(
            project_id, ticket_id, ticket, agent_name, action,
            result, result_json, current_status, requirement_id,
        ):
            return

        ctx = ResultContext(
            orch=self, db=db,
            project_id=project_id, ticket_id=ticket_id, ticket=ticket,
            agent_name=agent_name, action=action,
            result=result, result_json=result_json,
            current_status=current_status, requirement_id=requirement_id,
            git_result=git_result,
            fire_knowledge_distill=_fire_knowledge_distill,
            synthesize_blocked_diagnosis=_synthesize_blocked_diagnosis,
        )

        handler = result_handlers.select_handler(agent_name, action, result)
        if handler is None:
            # 没有专属处理器：状态不变，照常走尾部。
            new_status = current_status
        else:
            new_status = await handler(ctx)
            if new_status is HANDLED:
                # 处理器已收尾：不发状态事件，也不在这里继续派单。
                return

        await self._publish_result_and_continue(project_id, ticket_id, agent_name, current_status, new_status)

    async def _publish_result_and_continue(self, project_id, ticket_id, agent_name, current_status, new_status):
        """发布状态事件；等待之后重新读库，只对仍匹配规则的工单派单。"""
        # 发 SSE 事件
        await event_manager.publish_to_project(
            project_id,
            "ticket_status_changed",
            {"ticket_id": ticket_id, "from": current_status, "to": new_status, "agent": agent_name},
        )

        # 继续流转到下一个阶段
        await asyncio.sleep(0.5)
        updated_ticket = await db.fetch_one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        if updated_ticket:
            project_rules = await self._get_rules_for_project(project_id)
            if updated_ticket["status"] in project_rules:
                await self.process_ticket(project_id, ticket_id)

    # ==================== Git 文件处理 ====================

    async def _handle_git_files(
        self,
        project_id: str,
        ticket_id: str,
        requirement_id: str,
        agent_name: str,
        action: str,
        result: Dict,
    ) -> Optional[Dict]:
        """从 Agent 结果中提取 files，写入 Git 仓库并提交"""
        return await git_persist.handle_git_files(
            self, db, project_id, ticket_id, requirement_id, agent_name, action, result,
        )

    async def _record_command(
        self,
        project_id: str,
        ticket_id: Optional[str],
        requirement_id: Optional[str],
        agent_type: str,
        action: str,
        step_order: int,
        command_type: str,
        command: str,
        status: str = "success",
        duration_ms: int = None,
    ):
        """记录执行命令到 ticket_commands 表"""
        return await ticket_log.record_command(
            self, db, project_id, ticket_id, requirement_id, agent_type, action, step_order,
            command_type, command, status, duration_ms,
        )

    async def _check_requirement_completion(self, project_id: str, requirement_id: str):
        """检查需求下所有工单是否都已测试通过或部署完成"""
        return await reporting.check_requirement_completion(self, db, project_id, requirement_id)

    async def _generate_requirement_report(self, project_id: str, requirement_id: str):
        """需求完成后生成汇总报告 Markdown，保存到 Git 仓库 + artifacts 表"""
        return await reporting.generate_requirement_report(self, db, project_id, requirement_id)

    async def _trigger_dependents(self, project_id: str, completed_ticket_id: str):
        """工单完成后，触发依赖它的后续工单流转"""
        return await reporting.trigger_dependents(self, db, project_id, completed_ticket_id)

    async def _inject_rejection_context(self, context: Dict, ticket: Dict) -> None:
        """把「本轮被打回的真实原因」注入 context，供 ReflectionAction 使用。"""
        return await context_builder.inject_rejection_context(self, db, context, ticket)

    async def _build_context(self, ticket: Dict, agent_name: str = "") -> Dict:
        """构建 Agent 执行上下文"""
        return await context_assembly.build_context(self, db, ticket, agent_name)

    async def _fetch_prior_insights(self, ticket_title: str, project_id: str) -> str:
        """编码前主动检索相关历史经验，注入 prior_insights 供 DevAgent 参考。"""
        return await context_builder.fetch_prior_insights(self, db, ticket_title, project_id)

    def _load_knowledge_docs(self, project_id: str, global_limit: int = 2000, project_limit: int = 3000) -> str:
        """读取全局知识库 + 项目知识库文档，返回拼接文本"""
        return context_builder.load_knowledge_docs(self, project_id, global_limit, project_limit)

    async def _collect_existing_code(self, project_id: str) -> Dict:
        """收集仓库中已有的代码文件（用于增量开发上下文）"""
        return await context_builder.collect_existing_code(self, project_id)

    def _agent_to_owner(self, agent_name: str) -> str:
        """Agent 名称转持有者角色"""
        return context_builder.agent_to_owner(self, agent_name)

    async def _diagnose_blocked_ticket(
        self,
        project_id: str,
        ticket_id: str,
        current_ticket: Dict,
        agent_name: str,
        action: str,
        error_msg: str,
        blocked_from_status: str,
    ):
        """后台跑一次 LLM 诊断，写回 tickets.diagnosis 并发 SSE 事件。"""
        return await blocked_diagnosis.diagnose_blocked_ticket(
            self, db, project_id, ticket_id, current_ticket, agent_name, action, error_msg,
            blocked_from_status,
        )

    async def _write_memory(
        self,
        project_id: str,
        mem_type: str,
        title: str,
        content: str,
        agent_type: str = "",
        requirement_id: str = None,
        ticket_id: str = None,
        tags: list = None,
    ) -> None:
        """写入 Agent Memory（决策/交接/项目状态/经验）"""
        return await ticket_log.write_memory(
            self, db, project_id, mem_type, title, content, agent_type, requirement_id, ticket_id,
            tags,
        )

    LOCAL_TOOL_ACTIONS = ticket_log.LOCAL_TOOL_ACTIONS

    async def _log_agent_thought(
        self,
        project_id: str,
        requirement_id: Optional[str],
        ticket_id: Optional[str],
        agent_name: str,
        action: str,
        phase: str,  # "start" | "done"
        title: str = "",
        result: Optional[Dict] = None,
        elapsed_ms: int = 0,
    ):
        """把 Agent 执行的开始/完成写入 ticket_logs，让操作日志可见思考过程。"""
        return await ticket_log.log_agent_thought(
            self, project_id, requirement_id, ticket_id, agent_name, action, phase, title, result,
            elapsed_ms,
        )

    async def _log(
        self,
        project_id: str,
        requirement_id: Optional[str],
        ticket_id: Optional[str],
        agent_type: str,
        action: str,
        from_status: Optional[str],
        to_status: Optional[str],
        message: str,
        level: str = "info",
        detail_data: Optional[Dict] = None,
    ):
        """记录日志并推送 SSE 实时事件"""
        return await ticket_log.log(
            self, db, project_id, requirement_id, ticket_id, agent_type, action, from_status,
            to_status, message, level, detail_data,
        )


    async def _write_phase_comment(
        self,
        project_id: str,
        ticket_id: str,
        agent_type: str,
        summary: str,
        phase: Optional[str] = None,
        reply_to_comment_id: Optional[str] = None,
    ):
        """Agent 阶段完成后写一条 agent 类型评论，供时间轴展示和下游 Agent 感知"""
        return await ticket_log.write_phase_comment(
            self, db, project_id, ticket_id, agent_type, summary, phase, reply_to_comment_id,
        )

    # ──────────────────────────────────────────────────────────────
    # 三层融合：阶段重置 + 里程碑通知
    # ──────────────────────────────────────────────────────────────

    PHASE_ORDER = rewind.PHASE_ORDER
    MAX_RESET_COUNT = rewind.MAX_RESET_COUNT

    _PHASE_ENTRY_STATUS = rewind.PHASE_ENTRY_STATUS

    async def _resolve_phase_entry_status(
        self, project_id: str, from_phase: str, ticket_type: Optional[str] = None,
    ) -> Optional[str]:
        """查该项目 SOP 里重跑 `from_phase` 应该退回的状态。"""
        return await rewind.resolve_phase_entry_status(
            self, db, project_id, from_phase, ticket_type,
        )

    async def reset_phases(
        self,
        ticket_id: str,
        project_id: str,
        from_phase: str,
        reason: str,
    ) -> bool:
        """将指定阶段及后续所有阶段重置为 pending，并把工单退回该阶段入口状态重新跑。"""
        return await rewind.reset_phases(self, db, ticket_id, project_id, from_phase, reason)

    async def _sop_status_sequence(
        self, project_id: str, ticket_type: Optional[str] = None,
    ) -> List[str]:
        """该项目 SOP 线性主链上的状态顺序。"""
        return await rewind.sop_status_sequence(self, db, project_id, ticket_type)

    _STATUS_SUFFIXES = rewind.STATUS_SUFFIXES

    async def _is_forward_jump(
        self,
        project_id: str,
        current_status: str,
        target_status: str,
        ticket_type: Optional[str] = None,
    ) -> bool:
        """把 status 从 current 改成 target 是否属于「前跳」（跳过中间阶段）。"""
        return await rewind.is_forward_jump(
            self, project_id, current_status, target_status, ticket_type,
        )

    _seq_index = staticmethod(rewind.seq_index)

    async def _rewind_ticket_status(
        self,
        ticket_id: str,
        project_id: str,
        from_phase: str,
        reason: str,
    ) -> bool:
        """把 tickets.status 退回 from_phase 的入口状态并触发重新派单。"""
        return await rewind.rewind_ticket_status(
            self, db, ticket_id, project_id, from_phase, reason,
        )

    async def _apply_status_rewind(
        self,
        ticket_id: str,
        project_id: str,
        from_status: str,
        target_status: str,
        reason: str,
    ) -> None:
        """写回退状态 + 记日志 + 发 ticket_ready 让 orchestrator 立刻重新派单。"""
        return await rewind.apply_status_rewind(
            self, db, ticket_id, project_id, from_status, target_status, reason,
        )

    async def _maybe_openspec_verify(
        self, project_id: str, ticket_id: str, *, stage_label: str = "",
    ) -> bool:
        """测试阶段通过后触发 OpenSpec Verify（规范层，可选增强）。"""
        return await openspec_closeout.maybe_openspec_verify(
            self, db, project_id, ticket_id, stage_label=stage_label,
        )

    async def _finalize_openspec_after_done(
        self, project_id: str, ticket_id: str,
    ) -> None:
        """工单已到 testing_done/deployed 但 OpenSpec 停在 applied 时，软收尾 Verify→Archive。"""
        return await openspec_closeout.finalize_openspec_after_done(self, db, project_id, ticket_id)

    async def post_milestone_comment(
        self,
        ticket_id: str,
        project_id: str,
        message: str,
        level: str = "info",
    ):
        """发送里程碑系统通知到工单评论区（SSE 实时推送 + DB 持久化）"""
        return await ticket_log.post_milestone_comment(
            self, db, ticket_id, project_id, message, level,
        )

    async def _add_layer_log(
        self,
        ticket_id: str,
        project_id: str,
        action: str,
        layer: str,
        detail: dict,
        level: str = "info",
    ):
        """写带 layer 标注的 ticket_log（三层时间轴显示用）"""
        return await ticket_log.add_layer_log(
            self, db, ticket_id, project_id, action, layer, detail, level,
        )


    async def reply_to_comment(
        self,
        ticket_id: str,
        project_id: str,
        comment_content: str,
        comment_id: str = None,
    ):
        """用户发评论后，由当前负责 Agent（或 ChatAssistant）立刻异步回复。"""
        return await change_flows.reply_to_comment(
            self, db, ticket_id, project_id, comment_content, comment_id,
        )

    # ──────────────────────────────────────────────────────────────
    # 三层融合：变更分析中间件 + Tweak Flow
    # ──────────────────────────────────────────────────────────────

    async def _handle_change_impact(
        self,
        ticket_id: str,
        project_id: str,
        comment: str,
        comment_id: Optional[str],
        ticket: dict,
    ) -> bool:
        """变更分析中间件：检测评论是否含需求变更，路由到对应 Flow。"""
        return await change_flows.handle_change_impact(
            self, db, ticket_id, project_id, comment, comment_id, ticket,
        )

    async def _tweak_flow(
        self,
        ticket_id: str,
        project_id: str,
        comment: str,
        impact,
        comment_id: Optional[str] = None,
    ) -> None:
        """Tweak Flow：细节调整，specs 不变，重置开发阶段重新执行。"""
        return await change_flows.tweak_flow(
            self, db, ticket_id, project_id, comment, impact, comment_id,
        )

    async def _partial_flow(
        self,
        ticket_id: str,
        project_id: str,
        comment: str,
        impact,
        comment_id: Optional[str],
        ticket: dict,
    ) -> None:
        """Partial Flow：局部需求变化，更新 OpenSpec specs 后重新执行受影响阶段。"""
        return await change_flows.partial_flow(
            self, db, ticket_id, project_id, comment, impact, comment_id, ticket,
        )

    async def _breaking_flow(
        self,
        ticket_id: str,
        project_id: str,
        comment: str,
        impact,
        comment_id: Optional[str],
        ticket: dict,
    ) -> None:
        """Breaking Flow：需求根本变更，关闭当前工单，创建衍生新工单。"""
        return await change_flows.breaking_flow(
            self, db, ticket_id, project_id, comment, impact, comment_id, ticket,
        )

    async def _extract_title_from_comment(self, comment: str, original_title: str) -> str:
        """从评论中提取新需求标题，失败返回截断评论。"""
        return await change_flows.extract_title_from_comment(self, comment, original_title)


    # ── TODO G：uproject 自愈 ───────────────────────────────────────────────

    async def _try_uproject_heal(
        self,
        project_id: str,
        ticket_id: str,
        playtest_result: Dict,
    ) -> Dict:
        """尝试 uproject 自愈，返回 heal_result dict。"""
        try:
            from plugins.registry import require_action
            action = require_action("ue_uproject_heal")
            log_text = (playtest_result.get("raw_head") or "") + (playtest_result.get("raw_tail") or "")
            result = await action.run({
                "project_id": project_id,
                "playtest_log": log_text,
            })
            return result.data or {}
        except Exception as e:
            logger.warning("uproject 自愈失败（忽略）: %s", e)
            return {"healed": False, "reason": str(e)}


# 全局 Orchestrator
orchestrator = TicketOrchestrator()

# P2 拆主环：把自己注册到 L0 叶子门面。agents/actions 不再
# `from orchestrator import orchestrator`，改从 runtime_facade 按名字取，
# 消除 7 条反向回边；注册发生在模块加载末尾，运行时取用时序不变。
import runtime_facade as _runtime_facade
_runtime_facade.register("orchestrator", orchestrator)


def _synthesize_blocked_diagnosis(**kwargs) -> Dict[str, Any]:
    """skill 失败时的本地诊断说明，不调 LLM。

    留在这里是因为测试按模块全局名给它打桩，构造 `ResultContext` 时也按模块全局名取。
    L3 的 `actions.diagnose_ticket` 经 `runtime_facade` 在调用时才解析，只在真的要诊断时才加载。
    """
    return _runtime_facade.actions_diagnose_ticket().synthesize_blocked_diagnosis(**kwargs)


def _fire_knowledge_distill(project_id: str, ticket_id: str):
    """验收通过后，后台尝试将修复经验蒸馏到知识库（fire-and-forget）"""
    import asyncio as _asyncio

    async def _run():
        try:
            cycle_count = await db.fetch_one(
                "SELECT count(*) as n FROM ticket_logs "
                "WHERE ticket_id = ? AND action IN ('reject', 'error', 'reflection')",
                (ticket_id,),
            )
            if not cycle_count or cycle_count["n"] == 0:
                return  # 无失败-修复循环，无需蒸馏
            distill_mod = _runtime_facade.actions_knowledge_distill()
            await distill_mod.KnowledgeDistillAction().run({"ticket_id": ticket_id, "project_id": project_id})
        except Exception as e:
            logger.warning("[知识蒸馏] 失败（忽略）: %s", e)

    try:
        loop = _asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_run())
    except Exception:
        pass
