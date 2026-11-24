"""
AI 自动开发系统 - Orchestrator 工单编排器
核心调度引擎：管理工单在 Agent 之间的流转
"""
import json
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
    bug_flow,
    change_flows,
    failure_counters,
    polling,
    reporting,
    requirement_pipeline,
    result_handlers,
    rewind,
    sop_rules,
    ticket_pipeline,
)
from orchestration.result_handlers import HANDLED, ResultContext
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

# 二进制媒体文件的 commit 消息标签。key 可以是 (agent, action) 或仅 agent。
# 这条通道被多个 Agent 复用（TestAgent 截图 / ArtistAgent 占位图），
# 不按来源区分会产出「[ArtistAgent] 测试截图」这种自相矛盾的提交记录。
_MEDIA_COMMIT_LABELS = {
    ("TestAgent", "run_tests"):          "测试截图",
    ("TestAgent", "run_playtest"):       "Playtest 截图",
    ("ArtistAgent", "generate_assets"):  "资产占位图",
    "TestAgent":    "测试截图",
    "ArtistAgent":  "美术资产",
    "UEEditorAgent": "UE 编辑器截图",
}

# Agent 注册中心（自动发现 + 自定义 Agent）
from agent_registry import instantiate_agents


def is_skill_run_result(agent_name: str, result: Any) -> bool:
    """skill 阶段的结果必须走 `result_handlers.handle_skill`。

    不能只看 `agent_name == "SkillAgent"`：`x-workflow.agent` 可以点名
    PlannerAgent 等宿主 Role，执行引擎仍是 SkillRunner。只认名字的话，
    那些结果会落到 `_handle_agent_result` 末尾的 `else` —— 状态不推进，
    同一条 rule 反复命中，skill 被无限重跑烧 token。
    """
    if agent_name == "SkillAgent":
        return True
    if not isinstance(result, dict):
        return False
    return bool(result.get("skill_id") or result.get("skill_status"))


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
        # 1. v0.17: 找出所有状态在**任一项目 SOP** 中的工单（考虑 traits 派生的额外状态）
        actionable_statuses = await self._get_all_actionable_statuses()

        # 2. 执行中状态：SOP trigger 里没有 *_in_progress（那是 next_status）。
        #    硬编码软件阶段会漏掉 director_visual_in_progress，重启后轮询看不见，
        #    界面一直「正在干什么」其实进程已经死了。用 GLOB 扫全部 *_in_progress。
        # 3. Phase 4: 也扫 waiting_subtasks，用于检测子 Ticket 是否全部完成
        from actions.chat.dispatch_subtask import WAITING_SUBTASKS_STATUS
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
            if self._ticket_held_by_this_process(ticket_id):
                continue

            # 跳过需求已暂停/取消的
            if t.get("req_status") in ("paused", "cancelled"):
                continue

            status = t["status"]

            # Phase 4：waiting_subtasks 状态 — 检测子 Ticket 是否全部完成
            if status == WAITING_SUBTASKS_STATUS:
                await self._check_subtasks_complete(ticket_id, project_id, t)
                continue

            # 对于"进行中"状态：本进程没在跑，且 updated_at 超过 300 秒没更新
            # → 才是僵尸（进程重启 / Agent 崩溃）。活任务等首包也会 89s 无 log，
            # 不能在这里打回 pending，否则同一轮 poll 立刻再派，assign→zombie 循环。
            if self._status_is_executing(status):
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
                reset_to = await self._zombie_rewind_status(ticket_id, status)
                if reset_to and reset_to != status:
                    try:
                        from llm_client import abort_ticket_cli
                        await abort_ticket_cli(ticket_id)
                    except Exception:
                        pass
                    await db.update("tickets", {
                        "status": reset_to, "updated_at": now_iso()
                    }, "id = ?", (ticket_id,))
                    await self._log(
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
                self._enqueue_ticket(project_id, ticket_id, is_subtask=True, source="poll-sub")
            else:
                self._enqueue_ticket(project_id, ticket_id, is_subtask=False, source="poll")

        # ── 自动拾取 open BUG ──
        # 扫描所有项目中 status=open 且未关联 ticket 的 BUG，自动触发修复工作流
        await self._poll_open_bugs()
        await self._resume_stuck_analyses()

    async def _resume_stuck_analyses(self):
        """status=analyzing 但本进程没在跑 → 上次进程死了，重新拆单。"""
        return await polling.resume_stuck_analyses(self, db)

    async def _poll_open_bugs(self):
        """扫描所有 status=open 的 BUG，自动触发修复（无需手动点击）"""
        return await bug_flow.poll_open_bugs(self, db)

    async def _check_subtasks_complete(self, parent_ticket_id: str, project_id: str, parent_row: dict):
        """Phase 4：检查父 Ticket 的所有子 Ticket 是否全部完成。
        全部完成 → 父 Ticket 恢复到 PENDING（让轮询器继续执行下一阶段）。
        """
        from actions.chat.dispatch_subtask import WAITING_SUBTASKS_STATUS
        DONE_STATUSES = {TicketStatus.TESTING_DONE.value, TicketStatus.DEPLOYED.value}

        sub_tickets = await db.fetch_all(
            "SELECT id, title, status FROM tickets WHERE parent_ticket_id = ?",
            (parent_ticket_id,),
        )
        if not sub_tickets:
            # 没有子 Ticket（可能被删除），直接恢复
            logger.warning("父 Ticket %s 无子任务记录，自动恢复到 pending", parent_ticket_id[:12])
            await self._resume_parent_ticket(parent_ticket_id, project_id, parent_row)
            return

        pending = [s for s in sub_tickets if s["status"] not in DONE_STATUSES]
        if pending:
            names = ", ".join(f"#{s['id'][-6:]}({s['title'][:15]})" for s in pending[:3])
            logger.debug("⏳ 父 Ticket %s 等待子任务完成: %s", parent_ticket_id[:12], names)
            return

        # 所有子 Ticket 完成 → 恢复父 Ticket
        logger.info("✅ 所有子任务完成，恢复父 Ticket: %s", parent_ticket_id[:12])
        await self._resume_parent_ticket(parent_ticket_id, project_id, parent_row)

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
    ):
        """根据 Agent 执行结果更新工单状态 + 写入 Git 仓库"""
        requirement_id = ticket["requirement_id"]
        current_ticket = await db.fetch_one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        current_status = current_ticket["status"] if current_ticket else ticket["status"]

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
            return

        # === 止血：Agent 返回 error 直接标记 blocked，阻止 orchestrator 再次分派 ===
        # 典型场景：fragment 声明的 action（如 run_engine_compile）未在 Agent 中实现，
        # execute() 走 fallthrough 返回 {"status": "error", "message": "未知任务: xxx"}。
        # 之前 orchestrator 无视此 error，按 agent_name 分支强写下一状态（如 DevAgent 一律
        # 写成 development_done），导致 ticket 在同一状态反复触发同一规则，死循环 + 烧 token。
        if isinstance(result, dict) and result.get("status") == "error":
            err_msg = str(result.get("message") or result.get("error") or "Agent 返回 error")
            blocked_status = TicketStatus.BLOCKED.value
            await db.update("tickets", {
                "status": blocked_status,
                "result": json.dumps(result, ensure_ascii=False),
                "updated_at": now_iso(),
            }, "id = ?", (ticket_id,))
            await self._log(
                project_id, requirement_id, ticket_id, agent_name,
                "blocked", current_status, blocked_status,
                f"{agent_name}.{action} 返回 error，工单已标记 blocked 等待人工介入 | {err_msg[:300]}",
                "error",
                detail_data={"action": action, "error": err_msg, "raw_result": result},
            )
            await event_manager.publish_to_project(
                project_id,
                "ticket_blocked",
                {
                    "ticket_id": ticket_id,
                    "from": current_status,
                    "to": blocked_status,
                    "agent": agent_name,
                    "action": action,
                    "error": err_msg[:300],
                },
            )
            logger.warning(
                "🚧 工单 blocked: %s %s.%s → %s",
                ticket_id[:12], agent_name, action, err_msg[:120],
            )

            # Hook emit：让 chat_alert_hook 把错误推到 AI 聊天面板
            try:
                from hooks.registry import hook_registry
                from hooks.types import HookEvent, ToolHookContext
                await hook_registry.emit(ToolHookContext(
                    event=HookEvent.TOOL_ERROR,
                    tool_name=f"agent:{agent_name}.{action}",
                    input={},
                    error=RuntimeError(err_msg[:300]),
                    project_id=project_id,
                    ticket_id=ticket_id,
                    agent_type=agent_name,
                ))
            except Exception:
                pass

            # fire-and-forget：后台跑 LLM 诊断，不阻塞主 poll 循环
            # 结果写回 tickets.diagnosis，SSE 推前端
            asyncio.create_task(self._diagnose_blocked_ticket(
                project_id=project_id,
                ticket_id=ticket_id,
                current_ticket=dict(current_ticket) if current_ticket else dict(ticket),
                agent_name=agent_name,
                action=action,
                error_msg=err_msg,
                blocked_from_status=current_status,
            ))
            return

        # 保存执行结果（先 pop 二进制媒体文件，避免 JSON 序列化失败；但把图片路径记入 result["media_paths"] 供时间轴展示缩略图与打开 Tab）
        media_files_temp = result.pop("_media_files", None)  # 暂存，稍后写入 Git
        if isinstance(media_files_temp, dict) and media_files_temp:
            result["media_paths"] = list(media_files_temp.keys())
        result_json = json.dumps(result, ensure_ascii=False)
        if media_files_temp:
            result["_media_files"] = media_files_temp  # 写完 JSON 后放回，供 _handle_git_files 使用

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

        # 各 Agent 的分支在 orchestration/result_handlers/。分发顺序和拆分前一致：
        # (Agent, action) 精确匹配 → skill → 按 Agent 名。
        handler = result_handlers.pre_skill_handler(agent_name, action)

        if handler is None and is_skill_run_result(agent_name, result):
            # 自己发状态事件、自己决定要不要继续派单，总是返回 HANDLED。
            handler = result_handlers.handle_skill

        if handler is None:
            handler = result_handlers.agent_handler(agent_name, action)

        if handler is None:
            # 没有专属处理器：状态不变，照常走尾部。
            new_status = current_status
        else:
            new_status = await handler(ctx)
            if new_status is HANDLED:
                # 处理器已收尾：不发状态事件，也不在这里继续派单。
                return

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
        files = result.get("files", {})
        if not files or not isinstance(files, dict):
            return None

        # === 强制将中文文件名转为英文（仅对非 docs/ 目录的代码文件）===
        # docs/ 下的 Markdown 文档保留中文名，方便人工阅读和知识库索引
        import re
        sanitized_files = {}
        for path, content in files.items():
            is_doc = path.startswith("docs/") and path.endswith(".md")
            if not is_doc and any(ord(c) > 127 for c in path):
                # 提取目录和扩展名
                parts = path.rsplit("/", 1)
                dir_part = parts[0] + "/" if len(parts) > 1 else ""
                filename = parts[-1]
                name, ext = (filename.rsplit(".", 1) if "." in filename else (filename, ""))
                # 去掉非 ASCII，保留英文数字下划线横线
                safe_name = re.sub(r'[^\x00-\x7f]', '', name).strip("_- ")
                if not safe_name:
                    # 全是中文，用哈希替代
                    safe_name = f"module_{abs(hash(name)) % 100000}"
                sanitized_files[f"{dir_part}{safe_name}.{ext}" if ext else f"{dir_part}{safe_name}"] = content
                logger.info("📝 文件名修正: %s → %s", path, list(sanitized_files.keys())[-1])
            else:
                sanitized_files[path] = content
        files = sanitized_files
        result["files"] = files  # 回写，确保后续产物记录也用修正后的路径

        start_time = time.time()

        # 确保仓库已初始化
        project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
        if project:
            # 恢复自定义仓库路径映射（防止重启后丢失）
            repo_path = project.get("git_repo_path")
            if repo_path and project_id not in git_manager._custom_paths:
                from git_manager import PROJECTS_DIR
                default_path = str(PROJECTS_DIR / project_id)
                if repo_path != default_path:
                    git_manager.set_project_path(project_id, repo_path)

        if not git_manager.repo_exists(project_id):
            if project:
                await git_manager.init_repo(project_id, project["name"], project.get("description", ""))

        # 记录命令：写入文件
        step = 0
        for file_path in files.keys():
            await self._record_command(
                project_id, ticket_id, requirement_id, agent_name, action,
                step, "write_file", f"写入文件: {file_path}", "success"
            )
            step += 1

        # 构建有意义的 commit message
        ticket = await db.fetch_one("SELECT title FROM tickets WHERE id = ?", (ticket_id,))
        ticket_title = ticket["title"] if ticket else ticket_id
        file_names = ", ".join(f.split("/")[-1] for f in list(files.keys())[:3])
        if len(files) > 3:
            file_names += f" +{len(files)-3}"
        action_labels = {
            "design_architecture": "架构设计",
            "develop": "开发",
            "rework": "返工",
            "fix_issues": "修复",
            "acceptance_review": "验收",
            "run_tests": "测试",
        }
        action_label = action_labels.get(action, action)
        commit_msg = f"[{agent_name}] {action_label}: {ticket_title} ({file_names})"

        # 手动挡：只写文件，不自动 git commit
        project_mode = (project or {}).get("mode", "auto") if project else "auto"
        if project_mode == "manual":
            logger.info("🔧 手动挡：跳过 git commit，直接写入文件 (%d 个)", len(files))
            git_result = await git_manager.write_files_only(project_id, files)
        else:
            git_result = await git_manager.write_and_commit(
                project_id, files, commit_msg, agent=agent_name
            )

        # 写入二进制媒体文件（截图 / 占位图等），手动挡也只写不 commit
        media_files: dict = result.pop("_media_files", {}) or {}
        if media_files:
            try:
                repo_dir = git_manager._repo_path(project_id)
                for media_path, img_bytes in media_files.items():
                    dest = repo_dir / media_path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(img_bytes)
                    logger.info("🖼️ 媒体文件写入: %s (%d bytes)", media_path, len(img_bytes))
                if project_mode != "manual":
                    # 这条通道最早只给 TestAgent 的截图用，消息写死了「测试截图」。
                    # 现在 ArtistAgent 的占位图也走这里，硬编码会产出
                    # 「[ArtistAgent] 测试截图: ...」这种驴唇不对马嘴的 commit。
                    media_label = _MEDIA_COMMIT_LABELS.get(
                        (agent_name, action), _MEDIA_COMMIT_LABELS.get(agent_name, "媒体文件"),
                    )
                    media_commit = await git_manager.commit(
                        project_id,
                        f"[{agent_name}] {media_label}: {ticket_title}",
                        author=agent_name,
                    )
                    await git_manager.push(project_id)
                    logger.info("🖼️ %s已提交: %s", media_label, media_commit)
            except Exception as me:
                logger.warning("媒体文件提交失败（不影响主流程）: %s", me)
        # 记录当前分支名到 git_result
        if git_result:
            try:
                current_branch = await git_manager.get_current_branch(project_id)
                git_result["branch"] = current_branch
            except Exception:
                pass

        elapsed = int((time.time() - start_time) * 1000)

        # 记录命令：git commit
        if git_result and git_result.get("commit_hash"):
            await self._record_command(
                project_id, ticket_id, requirement_id, agent_name, action,
                step, "git_commit",
                f"git commit -m \"{commit_msg}\" → {git_result['commit_hash']}",
                "success", elapsed
            )
            step += 1

            # 记录命令：git push
            if git_result.get("pushed"):
                await self._record_command(
                    project_id, ticket_id, requirement_id, agent_name, action,
                    step, "git_push", "git push origin main", "success"
                )
            else:
                # push 失败：git_manager 已按原因分类并推送可执行的修复卡
                status = git_manager.get_last_push_status(project_id) or {}
                push_err_msg = (
                    f"{agent_name}.{action} {status.get('title') or 'git push 失败'}。"
                    f"{status.get('summary') or '代码已 commit 但未推送到远端。'}"
                    f" 工单: {(ticket_id or '')[-8:] or '(需求级)'}。"
                    f"{status.get('next_step') or ''}"
                )
                logger.warning("⚠️ %s", push_err_msg)
                await self._log(
                    project_id, requirement_id, ticket_id, agent_name,
                    "git_push_failed", None, None, push_err_msg, "warn",
                )

            # 自动部署 dev 环境（Agent 完成文件提交后）
            if agent_name in ("DevAgent", "ArchitectAgent"):
                try:
                    from agents.deploy import DeployAgent
                    await DeployAgent.deploy_env(project_id, "dev")
                except Exception as de:
                    logger.warning("Dev 环境自动部署失败: %s", de)

        return git_result

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
        await db.insert("ticket_commands", {
            "id": generate_id("CMD"),
            "ticket_id": ticket_id,
            "requirement_id": requirement_id,
            "project_id": project_id,
            "agent_type": agent_type,
            "action": action,
            "step_order": step_order,
            "command_type": command_type,
            "command": command,
            "result": None,
            "status": status,
            "duration_ms": duration_ms,
            "created_at": now_iso(),
        })

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
        """把「本轮被打回的真实原因」注入 context，供 ReflectionAction 使用。

        断链背景：actions/reflection.py:170-171 与 agents/dev.py:696,711,809 都读
        context["rejection_reason"] / ["test_issues"]，但此前全仓库没有任何运行时
        代码给这两个键赋值（只在 _test_reflection*.py 里手工塞过）。结果验收打回的
        真实原因（tickets.result.review.issues / reject 日志 message）进不了反思
        prompt，反思只看到空信号，下一轮重复同样的错误（TK-20261110-48b6af
        20:30:00 的 reject 里明明写着「package.json 未声明 three 依赖」，
        却因断链始终没传给 DevAgent）。

        双源提取，兼容新旧数据结构：
        - tickets.result：review.issues / issues / degrade_reason
        - 最近一条 reject 日志 detail：issues / reason / message
        仅在本轮结果确实是「被打回」类状态时注入，避免把历史成功结果带进新工单。
        """
        try:
            raw_result = ticket.get("result")
            result_obj = (json.loads(raw_result) if isinstance(raw_result, str) and raw_result
                          else (raw_result or {}))
            if not isinstance(result_obj, dict):
                result_obj = {}
            result_status = str(result_obj.get("status") or "")

            review = result_obj.get("review") or {}
            issues = [str(i) for i in (review.get("issues") or result_obj.get("issues") or []) if i]
            reason = str(result_obj.get("degrade_reason") or "")

            reject_row = await db.fetch_one(
                """SELECT detail FROM ticket_logs
                   WHERE ticket_id = ? AND action = 'reject'
                   ORDER BY created_at DESC LIMIT 1""",
                (ticket["id"],),
            )
            if reject_row and reject_row.get("detail"):
                try:
                    det = json.loads(reject_row["detail"])
                except (ValueError, TypeError):
                    det = {}
                if not isinstance(det, dict):
                    det = {}
                if not issues:
                    issues = [str(i) for i in (det.get("issues") or []) if i]
                if not reason:
                    reason = str(det.get("reason") or det.get("message") or "")

            if result_status in ("acceptance_rejected", "testing_failed",
                                 "development_failed", "error"):
                context["rejection_reason"] = "; ".join(issues[:10]) or reason[:500]
                context["test_issues"] = issues[:10]
            else:
                context["rejection_reason"] = ""
                context["test_issues"] = []
        except Exception as e:
            logger.debug("注入返工失败信号失败（非致命）: %s", e)
            context.setdefault("rejection_reason", "")
            context.setdefault("test_issues", [])

    async def _build_context(self, ticket: Dict, agent_name: str = "") -> Dict:
        """构建 Agent 执行上下文"""
        requirement = await db.fetch_one(
            "SELECT * FROM requirements WHERE id = ?", (ticket["requirement_id"],)
        )

        # 获取之前的执行结果
        prev_results = await db.fetch_all(
            "SELECT * FROM artifacts WHERE ticket_id = ? ORDER BY created_at",
            (ticket["id"],),
        )

        project_id = ticket.get("project_id", "")
        req_short = (ticket["requirement_id"] or "standalone")[-6:]

        # 获取项目 repo_path，注入 context 供 Agent 直接使用（无需再查 DB）
        _repo_path = ""
        try:
            from git_manager import git_manager as _gm
            _rp = _gm._repo_path(project_id)
            if _rp:
                _repo_path = str(_rp)
        except Exception:
            pass

        context = {
            "ticket_id": ticket["id"],
            "ticket_title": ticket["title"],
            "ticket_description": ticket.get("description", ""),
            "ticket_type": ticket.get("type", "feature"),
            "module": ticket.get("module", "other"),
            "project_id": project_id,
            "requirement_id": ticket.get("requirement_id") or "",
            "agent_type": agent_name or "",
            "repo_path": _repo_path,          # ← 注入 repo_path
            "requirement_description": requirement["description"] if requirement else "",
            "requirement_title": requirement["title"] if requirement else "",
            "docs_prefix": f"docs/Reqs/{req_short}/{ticket['id'][-6:]}/",
            "src_prefix": f"src/{ticket.get('module', 'other')}/",
            "tests_prefix": f"tests/{req_short}/",
            "_ticket_progress_cb": self._make_ticket_progress_callback(project_id, ticket["id"]),
        }

        # 返工失败信号（rejection_reason / test_issues）注入，供反思 Action 读取
        await self._inject_rejection_context(context, ticket)

        # 若为 BUG ticket，附加 BUG 原始信息
        if ticket.get("type") == "bug":
            bug = await db.fetch_one(
                "SELECT * FROM bugs WHERE ticket_id = ?", (ticket["id"],)
            )
            if bug:
                context["bug_id"] = bug["id"]
                context["bug_priority"] = bug.get("priority", "medium")
                context["bug_description"] = bug.get("description", "")
                context["bug_fix_notes"] = bug.get("fix_notes") or ""

        # 添加之前阶段的产物
        for art in prev_results:
            if art["type"] == "architecture":
                try:
                    context["architecture"] = json.loads(art["content"]) if art["content"] else {}
                except json.JSONDecodeError:
                    context["architecture"] = {}
            elif art["type"] == "code":
                try:
                    context["dev_result"] = json.loads(art["content"]) if art["content"] else {}
                except json.JSONDecodeError:
                    context["dev_result"] = {}
            elif art["type"] == "test":
                try:
                    context["test_result"] = json.loads(art["content"]) if art["content"] else {}
                except json.JSONDecodeError:
                    context["test_result"] = {}

        # v0.18 Phase B：注入项目级 UE 配置（引擎/uproject/target 等），供
        # UECompileCheckAction / InstantiateUETemplateAction 等 UE 相关 action 透传使用。
        # 这样 DevAgent.run_engine_compile 不再需要每次从前端卡片 context 里取。
        #
        # v0.19.x A 方案：同时注入 traits，让 SelfTestAction 按 trait 分 UE / web 分支
        try:
            traits_row = await db.fetch_one(
                "SELECT traits FROM projects WHERE id = ?", (project_id,),
            )
            raw = (traits_row or {}).get("traits") or "[]"
            try:
                traits_list = json.loads(raw) if isinstance(raw, str) else list(raw)
            except Exception:
                traits_list = []
            if isinstance(traits_list, list):
                context["traits"] = [str(t) for t in traits_list if t]
        except Exception as e:
            logger.debug("读 traits 失败（忽略）: %s", e)

        try:
            proj_row = await db.fetch_one(
                """SELECT ue_engine_path, ue_engine_version, ue_engine_type,
                          uproject_path, ue_target_name, ue_target_platform, ue_target_config
                   FROM projects WHERE id = ?""",
                (project_id,),
            )
            if proj_row:
                for k, v in proj_row.items():
                    if v is not None and v != "":
                        context[k] = v
                # uproject_path 若是相对路径，拼成绝对
                up = context.get("uproject_path")
                if up and not Path(up).is_absolute():
                    from git_manager import git_manager
                    rp = git_manager._repo_path(project_id)
                    if rp:
                        context["uproject_path"] = str(Path(rp) / up)
        except Exception as e:
            logger.warning("读取项目 UE 配置失败（非致命）: %s", e)

        # === 增量开发上下文：读取仓库中已有文件 ===
        try:
            from memory import AgentMemory
            mem = AgentMemory(project_id)
            code_ctx = await mem.get_code_context()
            context["existing_files"] = code_ctx.get("file_list", [])
            context["existing_code"] = code_ctx.get("code", {})
            logger.info("📂 已有代码上下文: %d 文件, %d 个代码片段",
                        len(context["existing_files"]), len(context["existing_code"]))
        except Exception as e:
            logger.warning("读取已有代码失败: %s", e)
            context["existing_files"] = []
            context["existing_code"] = {}

        # 获取同需求下已完成工单的摘要
        try:
            context["sibling_tickets"] = await mem.get_sibling_tickets(
                ticket["requirement_id"], exclude_ticket_id=ticket["id"]
            )
        except Exception:
            context["sibling_tickets"] = []

        # === 知识库上下文（按 Agent 类型差异化加载）===
        try:
            from knowledge_loader import KnowledgeLoader
            loader = KnowledgeLoader(agent_name, project_id, context.get("traits", []))
            knowledge = await loader.load()
            context["project_knowledge"]  = knowledge.get("project_knowledge", "")
            context["domain_knowledge"]   = knowledge.get("domain_knowledge", "")
            context["agent_spec"]         = knowledge.get("agent_spec", "")
            # 向后兼容：合并到旧字段，防止使用旧字段的 Agent 读不到
            context["knowledge_docs"] = "\n\n".join(
                filter(None, [context["project_knowledge"], context["domain_knowledge"]])
            ) or self._load_knowledge_docs(project_id)
        except Exception as e:
            logger.warning("KnowledgeLoader 失败，降级到旧逻辑: %s", e)
            context["knowledge_docs"] = self._load_knowledge_docs(project_id)
            context["project_knowledge"] = context["domain_knowledge"] = context["agent_spec"] = ""

        # === Insight 主动注入：编码前自动检索相关历史经验 ===
        try:
            context["prior_insights"] = await self._fetch_prior_insights(
                ticket["title"], project_id
            )
        except Exception as e:
            logger.warning("Insight 注入失败（非致命）: %s", e)
            context["prior_insights"] = ""

        # === v0.20 UCP：探测 Editor 是否可用，注入到 context ===
        traits = context.get("project_traits") or []
        is_ue_project = any(t in traits for t in ("engine:ue5", "engine:ue4"))
        if is_ue_project:
            try:
                from actions.ue_editor_control import probe_ucp
                context["ucp_available"] = await probe_ucp(timeout=1.0)
            except Exception:
                context["ucp_available"] = False
        else:
            context["ucp_available"] = False

        return context

    async def _fetch_prior_insights(self, ticket_title: str, project_id: str) -> str:
        """编码前主动检索相关历史经验，注入 prior_insights 供 DevAgent 参考。

        来源1：knowledge_fts（知识库文档 + dev-notes）
        来源2：tickets_fts（已完成工单的 Reflexion 根因分析）
        """
        if not ticket_title or not ticket_title.strip():
            return ""

        # FTS5 安全化：去掉特殊字符，整体用双引号包裹短语搜索
        clean = ticket_title.replace('"', ' ').strip()
        import re as _re
        fts_query = f'"{clean}"' if _re.search(r'[.\-+*():!]', clean) else clean

        parts = []

        # --- 1. 知识库命中（含置信度标注）---
        try:
            rows = await db.fetch_all("""
                SELECT ki.filename, ki.confidence, ki.used_count,
                       snippet(knowledge_fts, 0, '', '', '...', 40) AS snippet
                FROM knowledge_fts
                JOIN knowledge_index ki ON knowledge_fts.rowid = ki.id
                WHERE knowledge_fts MATCH ?
                  AND (ki.project_id = ? OR ki.project_id IS NULL)
                ORDER BY rank
                LIMIT 5
            """, (fts_query, project_id))
            if rows:
                high_conf, others = [], []
                for r in rows:
                    conf = r.get("confidence") or "medium"
                    label = "⭐ [高置信，建议直接应用]" if conf == "high" else ""
                    line = f"- [{r['filename']}] {r['snippet']} {label}"
                    if conf == "high":
                        high_conf.append(line)
                    else:
                        others.append(line)
                # 高置信度排前面，自动应用
                all_lines = high_conf + others
                parts.append("## 相关知识库条目\n" + "\n".join(all_lines[:4]))
                # 更新 used_count
                for r in rows[:4]:
                    await db.execute(
                        "UPDATE knowledge_index SET used_count = used_count + 1 WHERE id = ?",
                        (r["id"],)
                    )
        except Exception as e:
            logger.debug("prior_insights 知识库查询失败: %s", e)

        # --- 2. 历史工单 Reflexion 根因 ---
        try:
            rows = await db.fetch_all("""
                SELECT t.title,
                       snippet(tickets_fts, 0, '', '', '...', 30) AS snippet,
                       (SELECT tl.detail FROM ticket_logs tl
                        WHERE tl.ticket_id = tf.ticket_id AND tl.action = 'reflection'
                        ORDER BY tl.created_at DESC LIMIT 1) AS reflection_detail
                FROM tickets_fts tf
                JOIN tickets t ON tf.ticket_id = t.id
                WHERE tickets_fts MATCH ?
                  AND tf.project_id = ?
                  AND t.status IN ('acceptance_passed','testing_done','deployed')
                ORDER BY rank
                LIMIT 3
            """, (fts_query, project_id))
            if rows:
                lines = []
                for r in rows:
                    entry = f"- [{r['title']}] {r['snippet']}"
                    if r["reflection_detail"]:
                        try:
                            rd = json.loads(r["reflection_detail"])
                            if rd.get("root_cause"):
                                entry += f"\n  曾经根因: {rd['root_cause']}"
                            if rd.get("strategy_change"):
                                entry += f"\n  修复策略: {rd['strategy_change']}"
                        except Exception:
                            pass
                    lines.append(entry)
                parts.append("## 相关历史工单经验\n" + "\n".join(lines))
        except Exception as e:
            logger.debug("prior_insights 历史工单查询失败: %s", e)

        if not parts:
            return ""

        return (
            "# 历史经验（编码前参考，避免重复踩坑）\n\n"
            + "\n\n".join(parts)
        )

    def _load_knowledge_docs(self, project_id: str, global_limit: int = 2000, project_limit: int = 3000) -> str:
        """读取全局知识库 + 项目知识库文档，返回拼接文本"""
        from config import BASE_DIR
        parts = []

        def _read_docs(docs_dir: Path, label: str, char_limit: int):
            if not docs_dir.exists():
                return
            files = sorted(docs_dir.glob("*.md"), key=lambda f: f.name)
            total = 0
            section_parts = []
            for f in files:
                if total >= char_limit:
                    break
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                    remaining = char_limit - total
                    if len(text) > remaining:
                        text = text[:remaining] + "\n...(truncated)"
                    section_parts.append(f"### {f.name}\n{text}")
                    total += len(text)
                except Exception:
                    pass
            if section_parts:
                parts.append(f"## {label}\n" + "\n\n".join(section_parts))

        _read_docs(BASE_DIR / "docs", "全局规范", global_limit)
        _read_docs(BASE_DIR / "projects" / project_id / "docs", "项目文档", project_limit)

        return "\n\n".join(parts)

    async def _collect_existing_code(self, project_id: str) -> Dict:
        """收集仓库中已有的代码文件（用于增量开发上下文）"""
        if not git_manager.repo_exists(project_id):
            return {"file_list": [], "code": {}}

        tree = await git_manager.get_file_tree(project_id)
        children = tree.get("children", [])

        # 扁平化文件列表
        file_list = []
        def _flatten(nodes, prefix=""):
            for n in nodes:
                path = f"{prefix}{n['name']}" if not prefix else f"{prefix}/{n['name']}"
                if n["type"] == "file":
                    file_list.append(path)
                elif n.get("children"):
                    _flatten(n["children"], path)
        _flatten(children)

        # 读取关键文件内容（入口/配置文件 + src/ 与 scripts/ 下的代码文件）
        code = {}
        ENTRY_FILES = {"index.html", "main.py", "app.py", "package.json", "tsconfig.json", "vite.config.ts", "vite.config.js"}
        CODE_EXTS = {".html", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".py", ".css", ".json"}
        total_chars = 0
        MAX_TOTAL = 15000
        MAX_PER_FILE = 3000

        for fp in file_list:
            if total_chars >= MAX_TOTAL:
                break
            fname = fp.split("/")[-1]
            _, ext = (fname.rsplit(".", 1) if "." in fname else (fname, ""))
            ext = f".{ext}" if ext else ""

            # 优先读入口/配置文件，其次 src/ 或 scripts/ 下的代码文件
            should_read = fname in ENTRY_FILES or (fp.startswith(("src/", "scripts/")) and ext in CODE_EXTS)
            if not should_read:
                continue

            content = await git_manager.get_file_content(project_id, fp)
            if content:
                truncated = content[:MAX_PER_FILE]
                if len(content) > MAX_PER_FILE:
                    truncated += f"\n... (truncated, total {len(content)} chars)"
                code[fp] = truncated
                total_chars += len(truncated)

        return {"file_list": file_list, "code": code}

    def _agent_to_owner(self, agent_name: str) -> str:
        """Agent 名称转持有者角色"""
        mapping = {
            "ProductAgent": "product",
            "ArchitectAgent": "architect",
            "DevAgent": "developer",
            "TestAgent": "tester",
            "ReviewAgent": "reviewer",
            "DeployAgent": "deployer",
        }
        return mapping.get(agent_name, "unknown")

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
        """后台跑一次 LLM 诊断，写回 tickets.diagnosis 并发 SSE 事件。
        fire-and-forget：任何异常都只打日志，绝不冒泡到 poll 循环。
        """
        try:
            # 收集上下文
            import json as _json
            proj_row = await db.fetch_one(
                "SELECT traits FROM projects WHERE id = ?", (project_id,)
            )
            traits: List[str] = []
            if proj_row:
                try:
                    raw = proj_row.get("traits") or "[]"
                    parsed = _json.loads(raw) if isinstance(raw, str) else raw
                    if isinstance(parsed, list):
                        traits = [str(t) for t in parsed]
                except Exception:
                    pass

            # 最近 10 条日志（最新在前）
            recent_logs = await db.fetch_all(
                "SELECT agent_type, action, from_status, to_status, detail, created_at "
                "FROM ticket_logs WHERE ticket_id = ? "
                "ORDER BY created_at DESC LIMIT 10",
                (ticket_id,),
            )

            # 定位该 action 对应的 SOP 阶段定义（若能 compose）
            sop_stage: Dict[str, Any] = {}
            try:
                from sop.loader import compose_sop
                cfg = compose_sop(traits=traits, ticket_type=None)
                for s in (cfg.get("stages") or []):
                    if s.get("action") == action and s.get("agent") == agent_name:
                        sop_stage = dict(s)
                        break
            except Exception:
                pass

            context = {
                "ticket_id": ticket_id,
                "ticket_title": current_ticket.get("title", ""),
                "ticket_description": current_ticket.get("description", ""),
                "project_id": project_id,
                "project_traits": traits,
                "current_status": blocked_from_status,
                "failed_agent": agent_name,
                "failed_action": action,
                "failed_error_message": error_msg,
                "recent_logs": recent_logs,
                "sop_stage": sop_stage,
            }

            parsed_result: Dict[str, Any] = {}
            try:
                raw_result = current_ticket.get("result")
                parsed_result = (
                    _json.loads(raw_result) if isinstance(raw_result, str)
                    else (raw_result or {})
                )
                if not isinstance(parsed_result, dict):
                    parsed_result = {}
            except Exception:
                parsed_result = {}
            skill_id = str(parsed_result.get("skill_id") or "")
            skill_status = str(parsed_result.get("skill_status") or "")
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

            from actions.diagnose_ticket import (
                DiagnoseTicketAction,
                _is_timeout_block,
                synthesize_blocked_diagnosis,
            )
            if _is_timeout_block(skill_status, error_msg):
                diagnosis = synthesize_blocked_diagnosis(
                    skill_id=skill_id,
                    skill_status=skill_status,
                    error_msg=error_msg,
                    action=action,
                    outputs=parsed_result.get("outputs") or [],
                    artifacts=parsed_result.get("artifacts") or [],
                    extra_files=extra_files,
                )
            else:
                action_obj = DiagnoseTicketAction()
                result = await action_obj.run(context)
                diagnosis = (result.data or {}).get("diagnosis") or {}

            # 写回 ticket
            await db.update(
                "tickets",
                {
                    "diagnosis": _json.dumps(diagnosis, ensure_ascii=False),
                    "updated_at": now_iso(),
                },
                "id = ?",
                (ticket_id,),
            )

            # 日志 + SSE
            await self._log(
                project_id,
                current_ticket.get("requirement_id"),
                ticket_id,
                "System",
                "diagnose",
                None,
                None,
                f"🩺 诊断完成: {(diagnosis.get('symptom') or '')[:80]} | "
                f"根因: {(diagnosis.get('root_cause') or '')[:100]} | "
                f"置信度={diagnosis.get('confidence', 0):.2f}",
                "info",
                detail_data={"diagnosis": diagnosis},
            )

            await event_manager.publish_to_project(
                project_id,
                "ticket_diagnosed",
                {
                    "ticket_id": ticket_id,
                    "diagnosis": diagnosis,
                },
            )

            logger.info(
                "🩺 工单 %s 诊断完成 | %s",
                ticket_id[:12],
                (diagnosis.get("root_cause") or "")[:120],
            )
        except Exception as e:
            logger.error(
                "🩺 诊断后台任务失败 ticket=%s: %s",
                ticket_id[:12], e, exc_info=True,
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
        try:
            mem_id = generate_id("MEM")
            await db.insert("agent_memory", {
                "id": mem_id,
                "project_id": project_id,
                "type": mem_type,
                "agent_type": agent_type,
                "title": title[:200],
                "content": content,
                "tags": json.dumps(tags or [], ensure_ascii=False),
                "requirement_id": requirement_id,
                "ticket_id": ticket_id,
                "created_at": now_iso(),
            })
        except Exception as e:
            logger.debug("_write_memory 失败（忽略）: %s", e)

    # 本地工具动作（不走 LLM，直接执行 shell/CLI）
    LOCAL_TOOL_ACTIONS = frozenset({
        "run_engine_compile", "run_engine_compile_check",
        "run_uat", "run_ci_deploy", "playtest",
        "write_html_prototype",  # 轻量本地生成，不走 ReAct LLM
        "run_h5_typecheck",
        "run_h5_playtest",
    })

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
        """把 Agent 执行的开始/完成写入 ticket_logs，让操作日志可见思考过程。

        LLM 推理类动作 → thought_start / thought_done
        本地工具类动作 → tool_start  / tool_done
        """
        try:
            # 区分 LLM 推理 vs 本地工具
            is_local = action in self.LOCAL_TOOL_ACTIONS
            log_prefix = "tool" if is_local else "thought"

            detail_data: Optional[Dict] = None
            if phase == "start":
                msg = f"[{agent_name}] 开始 {action}"
                if title:
                    msg += f"：{title[:60]}"
            else:
                # 从 result 提取产出摘要
                status = (result or {}).get("status", "?")
                files = (result or {}).get("files") or {}
                file_names = [f.split("/")[-1] for f in list(files.keys())]
                file_summary = ", ".join(file_names[:4])
                if len(files) > 4:
                    file_summary += f" 等 {len(files)} 个文件"

                notes = ""
                dev_r = (result or {}).get("dev_result") or {}
                if isinstance(dev_r, dict):
                    notes = str(dev_r.get("notes") or "")[:60]
                elif isinstance(result, dict):
                    notes = str(result.get("notes") or "")[:60]

                parts = [f"[{agent_name}] 完成 {action} ({elapsed_ms}ms) status={status}"]
                if file_summary:
                    parts.append(f"产出: {file_summary}")
                if notes:
                    parts.append(f"备注: {notes}")
                msg = " | ".join(parts)

                # 结构化文件列表，供前端渲染文件标签与图片缩略图
                detail_data = {}
                media_dict = (result or {}).get("_media_files") or {}
                media_paths = list(media_dict.keys()) if isinstance(media_dict, dict) else list((result or {}).get("media_paths") or [])
                all_paths = list(files.keys()) + [p for p in media_paths if p not in files]
                all_names = [p.replace("\\", "/").split("/")[-1] for p in all_paths]
                shots = list((result or {}).get("screenshots") or [])
                st_shots = ((result or {}).get("self_test") or {}).get("screenshots") or []
                tr_shots = ((result or {}).get("test_result") or {}).get("screenshots") or []
                for s in (st_shots + tr_shots):
                    u = s.get("url") if isinstance(s, dict) else s
                    if u and u not in shots:
                        shots.append(u)
                if all_paths or shots:
                    detail_data = {
                        "files": all_names[:16],
                        "file_paths": all_paths[:16],
                        "file_count": len(all_paths),
                        "screenshots": shots[:10],
                        "media_paths": media_paths[:16],
                        "elapsed_ms": elapsed_ms,
                        "status": status,
                    }

                # 本地工具类：把关键输出也存入 detail，供展开查看 + AI 上下文
                if is_local and isinstance(result, dict):
                    # UBT 编译：errors / raw_tail
                    errors = result.get("errors") or []
                    raw_tail = (result.get("raw_tail") or "")[:4000]
                    command = result.get("command", "")
                    if errors or raw_tail:
                        detail_data["output_summary"] = raw_tail[-2000:] if raw_tail else ""
                        detail_data["errors_summary"] = json.dumps(
                            [{"msg": e.get("message", ""), "file": e.get("file", ""), "line": e.get("line", "")}
                             for e in errors[:10]],
                            ensure_ascii=False,
                        )
                        detail_data["command"] = command[:300]
                    # Playtest：直接用 message（已含 pass/fail 信息）
                    playtest_msg = result.get("message") or result.get("msg", "")
                    if playtest_msg and not detail_data.get("output_summary"):
                        detail_data["output_summary"] = str(playtest_msg)[:2000]

            await self._log(
                project_id, requirement_id, ticket_id,
                agent_name, f"{log_prefix}_{phase}",
                None, None,
                msg, "info",
                detail_data=detail_data,
            )
        except Exception as e:
            logger.debug("_log_agent_thought 失败（忽略）: %s", e)

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
        log_id = generate_id("LOG")
        created_at = now_iso()

        # 构建丰富的 detail JSON
        detail_obj = {"message": message}
        if detail_data:
            detail_obj.update(detail_data)
        detail_json = json.dumps(detail_obj, ensure_ascii=False)

        await db.insert("ticket_logs", {
            "id": log_id,
            "ticket_id": ticket_id,
            "subtask_id": None,
            "requirement_id": requirement_id,
            "project_id": project_id,
            "agent_type": agent_type,
            "action": action,
            "from_status": from_status,
            "to_status": to_status,
            "detail": detail_json,
            "level": level,
            "created_at": created_at,
        })

        # 实时推送日志到前端底部面板
        await event_manager.publish_to_project(
            project_id,
            "log_added",
            {
                "id": log_id,
                "ticket_id": ticket_id,
                "requirement_id": requirement_id,
                "agent_type": agent_type,
                "action": action,
                "from_status": from_status,
                "to_status": to_status,
                "detail": detail_json,
                "level": level,
                "created_at": created_at,
            },
        )

        # Session Transcript 镜像（backend/logs/session_<req_id>/）
        try:
            from session_logger import session_logger
            await session_logger.log_event(
                requirement_id=requirement_id,
                kind="log",
                agent=agent_type,
                action=action,
                ticket_id=ticket_id,
                from_status=from_status,
                to_status=to_status,
                message=message,
                detail=detail_data,
            )
        except Exception as e:
            logger.warning("SessionLogger.log_event 失败: %s", e)


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
        try:
            comment_id = "CMT-" + generate_id()
            await db.insert("ticket_comments", {
                "id": comment_id,
                "ticket_id": ticket_id,
                "project_id": project_id,
                "author": agent_type,
                "author_type": "agent",
                "content": summary,
                "phase": phase,
                "reply_to_comment_id": reply_to_comment_id,
                "created_at": now_iso(),
            })
            await event_manager.publish_to_project(project_id, "comment_added", {
                "ticket_id": ticket_id,
                "comment_id": comment_id,
                "author_type": "agent",
                "author": agent_type,
                "content": summary,
                "phase": phase,
            })
        except Exception as e:
            logger.debug("_write_phase_comment 失败（忽略）: %s", e)

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
        """测试阶段通过后触发 OpenSpec Verify（规范层，可选增强）。

        为什么放 orchestrator 而不是 Agent 里：Verify 失败要把工单打成 blocked，
        而 orchestrator 在 Agent 返回之后才写状态 —— Agent 内部写的 blocked 会被
        随后的 play_test_passed 覆盖掉。run_tests 那条路径侥幸没踩到是因为它写
        状态的时机恰好在后面，但同一件事分两处实现迟早走样，所以统一收口到这里。

        幂等：openspec_stage 已经是 verified / archived 就不重跑。
        """
        try:
            row = await db.fetch_one(
                "SELECT openspec_stage FROM tickets WHERE id = ?", (ticket_id,),
            )
            stage = ((row or {}).get("openspec_stage") or "").strip()
            # 没有 OpenSpec（空）→ _run_openspec_verify 自己会静默跳过；
            # 已 verified/archived → 重复 validate 没意义，还会多发一条里程碑评论
            if stage in ("verified", "archived"):
                return True

            from agents.test import TestAgent
            ctx = {"project_id": project_id, "ticket_id": ticket_id}
            ok = await TestAgent()._run_openspec_verify(ctx)
            if ok and stage_label:
                logger.info(
                    "📐 OpenSpec Verify 由 %s 阶段触发并通过（ticket=%s）",
                    stage_label, ticket_id[:12],
                )
            return ok
        except Exception as e:
            logger.debug("_maybe_openspec_verify 失败（忽略）: %s", e)
            return False

    async def _finalize_openspec_after_done(
        self, project_id: str, ticket_id: str,
    ) -> None:
        """工单已到 testing_done/deployed 但 OpenSpec 停在 applied 时，软收尾 Verify→Archive。

        用于历史单（含旧 force_pass）打开详情时补跑；新路径 reject 上限改为 blocked，不再走此收尾。
        Verify 失败不回 blocked（block_on_fail=False）。
        """
        row = await db.fetch_one(
            "SELECT openspec_stage, status FROM tickets WHERE id = ?", (ticket_id,),
        )
        if not row:
            return
        stage = (row.get("openspec_stage") or "").strip()
        if stage in ("", "archived"):
            return
        if stage not in ("proposed", "applied", "verified"):
            return

        ctx = {"project_id": project_id, "ticket_id": ticket_id}
        if stage in ("proposed", "applied"):
            from agents.test import TestAgent
            ok = await TestAgent()._run_openspec_verify(ctx, block_on_fail=False)
            if not ok:
                logger.info(
                    "📐 OpenSpec 终态收尾：Verify 未通过，跳过 Archive（ticket=%s）",
                    ticket_id[:12],
                )
                return
            row = await db.fetch_one(
                "SELECT openspec_stage FROM tickets WHERE id = ?", (ticket_id,),
            )
            stage = ((row or {}).get("openspec_stage") or "").strip()

        if stage == "verified":
            from agents.deploy import DeployAgent
            await DeployAgent()._run_openspec_archive(ctx)
            # archive 成功时 DeployAgent 会写 openspec_stage=archived；补一条 layer 日志便于时间轴跳转
            row2 = await db.fetch_one(
                "SELECT openspec_stage FROM tickets WHERE id = ?", (ticket_id,),
            )
            if (row2 or {}).get("openspec_stage") == "archived":
                await self._add_layer_log(
                    ticket_id, project_id, action="openspec_archive",
                    layer="spec", detail={"message": "终态收尾 Archive 完成"},
                )

    async def post_milestone_comment(
        self,
        ticket_id: str,
        project_id: str,
        message: str,
        level: str = "info",
    ):
        """发送里程碑系统通知到工单评论区（SSE 实时推送 + DB 持久化）"""
        try:
            comment_id = "CMT-" + generate_id()
            await db.insert("ticket_comments", {
                "id": comment_id,
                "ticket_id": ticket_id,
                "project_id": project_id,
                "author": "System",
                "author_type": "system",
                "content": message,
                "phase": "milestone",
                "created_at": now_iso(),
            })
            await event_manager.publish_to_project(project_id, "comment_added", {
                "ticket_id": ticket_id,
                "comment_id": comment_id,
                "author_type": "system",
                "author": "System",
                "content": message,
                "level": level,
            })
        except Exception as e:
            logger.debug("post_milestone_comment 失败（忽略）: %s", e)

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
        try:
            import json as _json
            log_id = generate_id("LOG")
            await db.insert("ticket_logs", {
                "id": log_id,
                "ticket_id": ticket_id,
                "project_id": project_id,
                "agent_type": layer,
                "action": action,
                "detail": _json.dumps(detail, ensure_ascii=False),
                "level": level,
                "layer": layer,
                "created_at": now_iso(),
            })
        except Exception as e:
            logger.debug("_add_layer_log 失败（忽略）: %s", e)


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

    留在这里是因为它要导入 L3 模块；结果处理器经 `ResultContext` 拿到它。
    导入放在函数里，和搬出去之前一样只在真的要诊断时才发生。
    """
    from actions.diagnose_ticket import synthesize_blocked_diagnosis
    return synthesize_blocked_diagnosis(**kwargs)


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
            from actions.knowledge_distill import KnowledgeDistillAction
            await KnowledgeDistillAction().run({"ticket_id": ticket_id, "project_id": project_id})
        except Exception as e:
            logger.warning("[知识蒸馏] 失败（忽略）: %s", e)

    try:
        loop = _asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_run())
    except Exception:
        pass
