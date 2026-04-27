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
from llm_client import set_llm_context, clear_llm_context
from git_manager import git_manager

logger = logging.getLogger("orchestrator")

# Agent 注册中心（自动发现 + 自定义 Agent）
from agent_registry import instantiate_agents


class TicketOrchestrator:
    """工单编排器 — 管理需求拆单和工单在 Agent 之间的流转"""

    def __init__(self):
        # Agent 池（通过注册中心自动发现和实例化）
        self.agents = instantiate_agents()

        # 正在处理的工单（防止重复处理）
        self._processing: set = set()

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

    def _load_transition_rules(self) -> Dict:
        """从 SOP YAML 加载状态转换规则（默认 web 项目）"""
        try:
            from sop.loader import load_sop, sop_to_transition_rules
            self._sop_config = load_sop("default_sop")
            rules = sop_to_transition_rules(self._sop_config)
            if rules:
                logger.info("📋 SOP 配置已加载: %s (%d 条规则)",
                            self._sop_config.get("name", "?"), len(rules))
                return rules
        except Exception as e:
            logger.warning("SOP 配置加载失败，使用内置规则: %s", e)

        # 兜底：内置硬编码规则
        logger.info("📋 使用内置状态转换规则")
        return {
            TicketStatus.PENDING.value: {
                "agent": "ArchitectAgent",
                "action": "design_architecture",
                "next_status": TicketStatus.ARCHITECTURE_IN_PROGRESS.value,
            },
            TicketStatus.ARCHITECTURE_DONE.value: {
                "agent": "DevAgent",
                "action": "develop",
                "next_status": TicketStatus.DEVELOPMENT_IN_PROGRESS.value,
            },
            TicketStatus.DEVELOPMENT_DONE.value: {
                "agent": "ProductAgent",
                "action": "acceptance_review",
                "next_status": None,
            },
            TicketStatus.ACCEPTANCE_PASSED.value: {
                "agent": "TestAgent",
                "action": "run_tests",
                "next_status": TicketStatus.TESTING_IN_PROGRESS.value,
            },
            TicketStatus.ACCEPTANCE_REJECTED.value: {
                "agent": "DevAgent",
                "action": "rework",
                "next_status": TicketStatus.DEVELOPMENT_IN_PROGRESS.value,
            },
            TicketStatus.TESTING_FAILED.value: {
                "agent": "DevAgent",
                "action": "fix_issues",
                "next_status": TicketStatus.DEVELOPMENT_IN_PROGRESS.value,
            },
        }

    def reload_sop(self):
        """热重载 SOP 配置（供 API 调用）"""
        self.transition_rules = self._load_transition_rules()
        # v0.17 清掉项目级缓存，下次 dispatch 时按最新 default + traits 重算
        self._project_rules_cache.clear()
        return self._sop_config

    # ==================== v0.17 Phase C''：项目级 SOP 规则 ====================

    async def _get_rules_for_project(
        self,
        project_id: str,
        traits_json: Optional[str] = None,
    ) -> Dict:
        """按项目 traits 派生 transition_rules。

        无 traits（老 web 项目 / 未迁移）→ 用 default `self.transition_rules`。
        有 traits → 调 compose_sop + sop_to_transition_rules，cache 一份。

        cache key 是 (project_id, traits_tuple)；traits 变动自然 miss，
        旧条目不会被读到（内存占用可忽略）。
        """
        if traits_json is None:
            row = await db.fetch_one(
                "SELECT traits FROM projects WHERE id = ?", (project_id,)
            )
            traits_json = row["traits"] if row else "[]"

        try:
            import json as _json
            traits = _json.loads(traits_json) if traits_json else []
            if not isinstance(traits, list):
                traits = []
        except Exception:
            traits = []

        # 空 traits → 回退到 default（向后兼容所有老项目）
        if not traits:
            return self.transition_rules

        traits_tuple = tuple(sorted(traits))
        cache_key = (project_id, traits_tuple)

        if cache_key in self._project_rules_cache:
            return self._project_rules_cache[cache_key]

        try:
            from sop.loader import compose_sop, sop_to_transition_rules
            sop_config = compose_sop(traits=traits, ticket_type=None)
            rules = sop_to_transition_rules(sop_config)
            self._project_rules_cache[cache_key] = rules
            logger.info(
                "📋 项目 %s traits=%s → SOP %d 条规则",
                project_id[:12], traits, len(rules),
            )
            return rules
        except Exception as e:
            logger.warning(
                "为项目 %s compose SOP 失败，回退到 default: %s",
                project_id[:12], e,
            )
            return self.transition_rules

    def invalidate_project_rules(self, project_id: str):
        """清除指定项目的 rules 缓存（当 traits 变动时调用）"""
        to_remove = [k for k in self._project_rules_cache if k[0] == project_id]
        for k in to_remove:
            del self._project_rules_cache[k]
        if to_remove:
            logger.info("清除项目 %s 的 SOP 规则缓存（%d 条）", project_id[:12], len(to_remove))

    async def _get_all_actionable_statuses(self) -> List[str]:
        """轮询扫 ticket 用的 WHERE IN (...) 集合。

        = default rules keys ∪ 所有活跃项目按其 traits compose 出来的 rules keys
        （union，不重复）。
        """
        all_statuses = set(self.transition_rules.keys())

        try:
            projects = await db.fetch_all(
                "SELECT id, traits FROM projects WHERE status = 'active'"
            )
            for p in projects:
                rules = await self._get_rules_for_project(p["id"], p.get("traits"))
                all_statuses.update(rules.keys())
        except Exception as e:
            logger.warning("汇总 actionable_statuses 异常（只用 default）: %s", e)

        return list(all_statuses)

    def get_agent_status(self) -> Dict:
        """获取所有 Agent 的实时状态"""
        return {
            "agents": self._agent_status,
            "processing_tickets": list(self._processing),
            "processing_count": len(self._processing),
        }

    def _set_agent_busy(self, agent_name: str, ticket_id: str, ticket_title: str, action: str):
        """标记 Agent 为忙碌"""
        self._agent_status[agent_name] = {
            **self._agent_status.get(agent_name, {}),
            "status": "working",
            "ticket_id": ticket_id,
            "ticket_title": ticket_title,
            "action": action,
            "started_at": now_iso(),
        }

    def _set_agent_idle(self, agent_name: str, success: bool = True):
        """标记 Agent 为空闲"""
        prev = self._agent_status.get(agent_name, {})
        key = "completed_count" if success else "error_count"
        self._agent_status[agent_name] = {
            **prev,
            "status": "idle",
            "ticket_id": None,
            "ticket_title": None,
            "action": None,
            "started_at": None,
            key: prev.get(key, 0) + 1,
        }

    # ==================== 工单级"当前进度"字段（v0.19.x） ====================
    #
    # tickets.current_action / _started_at / _latest_log / _updated_at 四列驱动
    # 工单属性面板的「📍 当前进度」区。分派 action 前 set，完成/异常后清。
    # 中间的 log 心跳走 Phase ②：log_callback → 过滤关键字 → 5s throttle → 写 DB。

    async def _set_ticket_current_action(self, ticket_id: str, action_label: str):
        """Action 开始：写 current_action + started_at，清空 latest_log"""
        if not ticket_id:
            return
        try:
            await db.update("tickets", {
                "current_action": action_label,
                "current_action_started_at": now_iso(),
                "current_action_latest_log": None,
                "current_action_updated_at": None,
            }, "id = ?", (ticket_id,))
        except Exception as e:
            logger.debug("set_ticket_current_action 失败（忽略）: %s", e)

    async def _clear_ticket_current_action(self, ticket_id: str):
        """Action 结束（无论成败）：清 4 列"""
        if not ticket_id:
            return
        try:
            await db.update("tickets", {
                "current_action": None,
                "current_action_started_at": None,
                "current_action_latest_log": None,
                "current_action_updated_at": None,
            }, "id = ?", (ticket_id,))
        except Exception as e:
            logger.debug("clear_ticket_current_action 失败（忽略）: %s", e)

    async def _create_compile_bug(
        self,
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

    async def _resolve_compile_bug(self, ticket_id: str, project_id: str):
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

    def _make_ticket_progress_callback(self, project_id: str, ticket_id: str):
        """生产 log 心跳 callback：关键字过滤 + 5s throttle + 去重 + 写 DB + 推 SSE

        返回 async callable(line: str) → None；闭包维护 state（上次时间 / 上次 line）。
        UE actions 把它接入自己的 stdout 流式 pump 即可，不改变原有 log_callback 契约。
        """
        import re as _re
        import time as _time

        # 命中这些关键字才写进度（避免 UBT 200 行/秒打爆 SQLite）
        important_re = _re.compile(
            r"(error|warning|fatal|"
            r"\[ubt\]|\[playtest\]|\[package\]|\[engine\]|\[uat\]|"
            r"compiling|linking|cooking|staging|packaging|"
            r"running|completed|result=)",
            _re.IGNORECASE,
        )
        state = {"last_t": 0.0, "last_line": ""}
        THROTTLE_SEC = 5.0

        async def _cb(line: str):
            if not ticket_id or not line:
                return
            if not important_re.search(line):
                return
            line = line[:200]
            if line == state["last_line"]:
                return
            now = _time.time()
            if now - state["last_t"] < THROTTLE_SEC:
                return
            state["last_t"] = now
            state["last_line"] = line
            ts = now_iso()
            try:
                await db.update("tickets", {
                    "current_action_latest_log": line,
                    "current_action_updated_at": ts,
                }, "id = ?", (ticket_id,))
            except Exception:
                pass
            # 推 SSE 给前端 drawer 订阅
            try:
                from events import event_manager
                await event_manager.publish_to_project(
                    project_id, "ticket_action_progress", {
                        "ticket_id": ticket_id,
                        "latest_log": line,
                        "latest_log_at": ts,
                    },
                )
            except Exception:
                pass

        return _cb

    # ==================== 轮询调度 ====================

    async def start_event_bus(self):
        """启动内部事件总线"""
        from event_bus import internal_bus

        async def _on_event(event_type: str, data: dict):
            """事件处理：工单状态变更时直接触发处理"""
            if event_type == "ticket_ready":
                project_id = data.get("project_id")
                ticket_id = data.get("ticket_id")
                if project_id and ticket_id:
                    logger.info("⚡ 事件驱动: 立即处理工单 %s", ticket_id[:12])
                    asyncio.create_task(self._poll_process(project_id, ticket_id))

        internal_bus.set_handler(_on_event)
        await internal_bus.start()

    async def _publish_ticket_ready(self, project_id: str, ticket_id: str):
        """发布工单就绪事件（触发下一个 Agent 立即接手）"""
        try:
            from event_bus import internal_bus
            await internal_bus.publish("ticket_ready", {
                "project_id": project_id,
                "ticket_id": ticket_id,
            })
        except Exception as e:
            logger.debug("事件发布失败(非致命): %s", e)

    async def poll_loop(self, interval: int = 30):
        """后台轮询：兜底机制，扫描遗漏的工单（间隔已放宽到 30s）"""
        logger.info("🔄 工单轮询调度器已启动 (间隔 %ds, 事件总线为主)", interval)
        while True:
            try:
                await self._poll_once()
            except Exception as e:
                logger.error("轮询异常: %s", e, exc_info=True)
            await asyncio.sleep(interval)

    async def _poll_once(self):
        """单次轮询：扫描所有可流转状态的工单并处理"""
        # 1. v0.17: 找出所有状态在**任一项目 SOP** 中的工单（考虑 traits 派生的额外状态）
        actionable_statuses = await self._get_all_actionable_statuses()

        # 2. 也扫描"进行中"但可能是僵尸的工单（被打回后卡住的）
        in_progress_statuses = [
            TicketStatus.ARCHITECTURE_IN_PROGRESS.value,
            TicketStatus.DEVELOPMENT_IN_PROGRESS.value,
            TicketStatus.TESTING_IN_PROGRESS.value,
            TicketStatus.DEPLOYING.value,
        ]

        all_statuses = list(set(actionable_statuses + in_progress_statuses))
        if not all_statuses:
            return

        placeholders = ",".join(["?"] * len(all_statuses))
        sql = f"""
            SELECT t.*, r.status as req_status
            FROM tickets t
            LEFT JOIN requirements r ON t.requirement_id = r.id
            WHERE t.status IN ({placeholders})
            ORDER BY t.priority ASC, t.sort_order ASC
        """
        tickets = await db.fetch_all(sql, tuple(all_statuses))

        for t in tickets:
            ticket_id = t["id"]
            project_id = t["project_id"]

            # 跳过正在处理的
            if ticket_id in self._processing:
                continue

            # 跳过需求已暂停/取消的
            if t.get("req_status") in ("paused", "cancelled"):
                continue

            status = t["status"]

            # 对于"进行中"状态：检查是否僵尸（updated_at 超过 60 秒没更新）
            if status in in_progress_statuses:
                from datetime import datetime
                try:
                    updated_str = t["updated_at"]
                    # 去掉时区信息统一比较
                    if "+" in updated_str:
                        updated_str = updated_str.split("+")[0]
                    if "Z" in updated_str:
                        updated_str = updated_str.replace("Z", "")
                    updated = datetime.fromisoformat(updated_str)
                    now_dt = datetime.now()
                    age = (now_dt - updated).total_seconds()
                    if age < 60:
                        continue  # 还在正常处理中，跳过
                except Exception as e:
                    logger.warning("僵尸检测时间解析失败: %s (%s)", t["updated_at"], e)
                    continue
                logger.info("🧟 检测到僵尸工单: %s「%s」状态=%s (%.0fs 未更新)",
                            ticket_id[:12], t["title"][:20], status, age)
                # 僵尸工单：重置到对应的"完成"状态，让轮询器正常拾取
                reset_map = {
                    TicketStatus.ARCHITECTURE_IN_PROGRESS.value: TicketStatus.ARCHITECTURE_DONE.value,
                    TicketStatus.DEVELOPMENT_IN_PROGRESS.value: TicketStatus.DEVELOPMENT_DONE.value,
                    TicketStatus.TESTING_IN_PROGRESS.value: TicketStatus.TESTING_DONE.value,
                    TicketStatus.DEPLOYING.value: TicketStatus.DEPLOYED.value,
                }
                reset_to = reset_map.get(status)
                if reset_to:
                    await db.update("tickets", {
                        "status": reset_to, "updated_at": now_iso()
                    }, "id = ?", (ticket_id,))
                    logger.info("🔧 僵尸工单已重置: %s → %s", status, reset_to)
                    status = reset_to  # 用新状态继续判断

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

            # 标记为处理中，异步执行
            self._processing.add(ticket_id)
            logger.info("🔄 轮询拾取工单: %s「%s」状态=%s", ticket_id[:12], t["title"][:20], status)
            asyncio.create_task(self._poll_process(project_id, ticket_id))

        # ── 自动拾取 open BUG ──
        # 扫描所有项目中 status=open 且未关联 ticket 的 BUG，自动触发修复工作流
        await self._poll_open_bugs()

    async def _poll_open_bugs(self):
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
            if bug.get("ticket_id") and bug["ticket_id"] in self._processing:
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
            asyncio.create_task(self.run_bug_fix(project_id, bug_id))

    async def _poll_process(self, project_id: str, ticket_id: str):
        """轮询触发的工单处理（带锁保护）"""
        try:
            await self.process_ticket(project_id, ticket_id)
        finally:
            self._processing.discard(ticket_id)

    # ==================== BUG 修复工作流 ====================

    async def run_bug_fix(self, project_id: str, bug_id: str):
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

            docs_prefix = f"docs/bugs/{bug_id[-6:]}/"
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

        # ── 轮询器会自动拾取 architecture_done 状态的 ticket 并交给 DevAgent ──
        # 这里只需触发一次立即处理（不用等下一个轮询周期）
        self._processing.add(ticket_id)
        asyncio.create_task(self._run_bug_ticket(project_id, ticket_id, bug_id))

    async def _run_bug_ticket(self, project_id: str, ticket_id: str, bug_id: str):
        """执行 BUG ticket 流转，并在测试完成后同步更新 bugs 表状态"""
        try:
            await self.process_ticket(project_id, ticket_id)
            # process_ticket 完成后读取 ticket 最终状态
            ticket = await db.fetch_one("SELECT status FROM tickets WHERE id = ?", (ticket_id,))
            final_status = ticket["status"] if ticket else ""
            if final_status == TicketStatus.TESTING_DONE.value:
                version_id = await self._find_current_version(project_id)
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
            elif final_status in (TicketStatus.TESTING_FAILED.value, ""):
                await db.update("bugs", {
                    "status": "open", "updated_at": now_iso(),
                }, "id = ?", (bug_id,))
                await event_manager.publish_to_project(
                    project_id, "bug_status_changed",
                    {"bug_id": bug_id, "status": "open", "reason": "测试未通过"},
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
        finally:
            self._processing.discard(ticket_id)

    async def _find_current_version(self, project_id: str) -> Optional[str]:
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

    # ==================== 需求处理 ====================

    async def handle_requirement(self, project_id: str, requirement_id: str):
        """处理需求：分析 + 拆单"""
        try:
            requirement = await db.fetch_one(
                "SELECT * FROM requirements WHERE id = ?", (requirement_id,)
            )
            if not requirement:
                return

            logger.info("━" * 60)
            logger.info("📋 开始处理需求: %s「%s」", requirement_id[:12], requirement["title"])
            logger.info("━" * 60)

            agent = self.agents["ProductAgent"]

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

            # 读取已有代码上下文（避免盲拆单：让 ProductAgent 看到现有文件和关键代码
            # 之后再判断复杂度/拆出工单，防止与已有架构冲突或重复）
            from memory import AgentMemory
            try:
                code_ctx = await AgentMemory(project_id).get_code_context()
                existing_files = code_ctx.get("file_list", [])
                existing_code = code_ctx.get("code", {})
                if existing_files:
                    logger.info("📂 decompose 读到代码上下文: %d 文件, %d 片段",
                                len(existing_files), len(existing_code))
            except Exception as e:
                logger.warning("decompose 读代码上下文失败: %s", e)
                existing_files, existing_code = [], {}

            # Agent 执行拆单
            logger.info("🤖 ProductAgent.analyze_and_decompose 开始执行...")
            req_start = time.time()
            result = await agent.execute("analyze_and_decompose", {
                "title": requirement["title"],
                "description": requirement["description"],
                "priority": requirement["priority"],
                "project_id": project_id,
                "existing_files": existing_files,
                "existing_code": existing_code,
            })
            req_elapsed = int((time.time() - req_start) * 1000)
            logger.info("🤖 ProductAgent.analyze_and_decompose 完成 (%dms) → status=%s", req_elapsed, result.get("status"))

            clear_llm_context()

            if result.get("status") != "success":
                await self._log(
                    project_id, requirement_id, None, "ProductAgent",
                    "error", "analyzing", "analyzing",
                    f"需求分析失败: {result.get('message', '未知错误')}", "error"
                )
                # 回退状态允许重试
                await db.update("requirements", {
                    "status": RequirementStatus.SUBMITTED.value,
                    "updated_at": now_iso(),
                }, "id = ?", (requirement_id,))
                return

            # 记录是否走了降级路径
            prd_summary = result.get("prd_summary", "")
            is_fallback = prd_summary.startswith("[规则引擎]")
            if is_fallback:
                await self._log(
                    project_id, requirement_id, None, "ProductAgent",
                    "info", "analyzing", "analyzing",
                    "[WARNING] LLM 不可用，使用规则引擎降级拆单", "warning"
                )

            # Self-Consistency 投票留痕（如果开启）
            vote = result.get("_consistency_vote")
            if vote:
                await self._log(
                    project_id, requirement_id, None, "ProductAgent",
                    "consistency_vote", None, None,
                    f"🗳️ 拆单投票: {vote['n_candidates']} 候选 → 选 #{vote['best_index']}"
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
                git_result = await self._handle_git_files(
                    project_id, None, requirement_id,
                    "ProductAgent", "analyze_and_decompose", result
                )

            # 创建工单（两遍：先创建所有工单，再回填依赖 ID）
            tickets_data = result.get("tickets", [])
            created_tickets = []        # [ticket_id, ...]
            idx_to_id = {}              # 索引 → TK-ID 映射

            # === 第一遍：创建所有父工单 ===
            for idx, tk in enumerate(tickets_data):
                ticket_id = generate_id("TK")
                now = now_iso()
                idx_to_id[idx] = ticket_id

                # 简单需求跳过架构设计，直接进开发
                complexity = result.get("complexity", "medium")
                initial_status = TicketStatus.PENDING.value
                if complexity == "simple":
                    initial_status = TicketStatus.ARCHITECTURE_DONE.value

                ticket = {
                    "id": ticket_id,
                    "requirement_id": requirement_id,
                    "project_id": project_id,
                    "parent_ticket_id": None,
                    "title": tk["title"],
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
                        "title": ch["title"],
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
                    dep_titles = [tickets_data[d]["title"] for d in raw_deps if isinstance(d, int) and 0 <= d < len(tickets_data)]
                    if dep_titles:
                        dep_info = f"，依赖: {', '.join(dep_titles)}"
                children_info = f"，含 {len(children_data)} 个子工单" if children_data else ""
                await self._log(
                    project_id, requirement_id, ticket_id, "ProductAgent",
                    "create", None, "pending",
                    f"工单「{tk['title']}」已创建，模块: {tk.get('module', 'other')}{dep_info}{children_info}"
                )

            # === 第二遍：回填依赖 ID（索引 → 真实 TK-ID）===
            for idx, tk in enumerate(tickets_data):
                raw_deps = tk.get("dependencies", [])
                if raw_deps:
                    dep_ids = []
                    for d in raw_deps:
                        if isinstance(d, int) and d in idx_to_id:
                            dep_ids.append(idx_to_id[d])
                        elif isinstance(d, str) and d.startswith("TK-"):
                            dep_ids.append(d)  # 已经是 TK-ID
                    if dep_ids:
                        await db.update(
                            "tickets",
                            {"dependencies": json.dumps(dep_ids), "updated_at": now_iso()},
                            "id = ?",
                            (idx_to_id[idx],),
                        )

            # 更新需求状态为已拆单
            await db.update("requirements", {
                "status": RequirementStatus.DECOMPOSED.value,
                "updated_at": now_iso(),
            }, "id = ?", (requirement_id,))

            await self._log(
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

                    await self._log(
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

            # 自动启动所有工单的 Agent 流转
            # 更新需求状态为进行中
            await db.update("requirements", {
                "status": RequirementStatus.IN_PROGRESS.value,
                "updated_at": now_iso(),
            }, "id = ?", (requirement_id,))

            for ticket_id in created_tickets:
                await self.process_ticket(project_id, ticket_id)

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

    # ==================== 工单流转 ====================

    async def process_ticket(self, project_id: str, ticket_id: str):
        """根据当前状态自动分派到对应 Agent"""
        try:
            ticket = await db.fetch_one(
                "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
            )
            if not ticket:
                return

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
                return

            # === 检查重试次数（防止无限循环打回）===
            MAX_RETRIES = 5
            retry_count = await db.fetch_one(
                "SELECT COUNT(*) as cnt FROM ticket_logs WHERE ticket_id = ? AND action = 'reject'",
                (ticket_id,),
            )
            if retry_count and retry_count["cnt"] >= MAX_RETRIES:
                logger.warning("🛑 工单 %s 已被打回 %d 次，强制通过", ticket_id[:12], retry_count["cnt"])
                await db.update("tickets", {
                    "status": TicketStatus.TESTING_DONE.value,
                    "updated_at": now_iso(),
                }, "id = ?", (ticket_id,))
                await self._log(
                    project_id, ticket.get("requirement_id"), ticket_id, "Orchestrator",
                    "force_pass", ticket["status"], TicketStatus.TESTING_DONE.value,
                    f"工单已被打回 {retry_count['cnt']} 次，超过上限 {MAX_RETRIES} 次，强制标记完成",
                    "warning",
                )
                return

            # 检查前置依赖是否完成
            deps_json = ticket.get("dependencies", "[]")
            try:
                dep_ids = json.loads(deps_json) if deps_json else []
            except (json.JSONDecodeError, TypeError):
                dep_ids = []

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
                    await self._log(
                        project_id, ticket["requirement_id"], ticket_id, "Orchestrator",
                        "info", "pending", "pending",
                        f"等待前置依赖完成: {dep_names}", "info"
                    )
                    return  # 依赖未完成，跳过

            current_status = ticket["status"]
            # v0.17: 按项目 traits 派生 rules（无 traits → 回退 default，向后兼容）
            project_rules = await self._get_rules_for_project(project_id)
            rule = project_rules.get(current_status)

            if not rule:
                # 终态或无规则，不处理
                return

            agent_name = rule["agent"]
            action = rule["action"]
            next_status = rule.get("next_status")

            agent = self.agents.get(agent_name)
            if not agent:
                logger.error("Agent %s 不存在!", agent_name)
                await self._log(
                    project_id, ticket["requirement_id"], ticket_id, agent_name,
                    "error", current_status, current_status,
                    f"Agent {agent_name} 不存在", "error"
                )
                return

            logger.info("─" * 50)
            logger.info(
                "🎫 工单流转: %s「%s」 %s → %s.%s",
                ticket_id[:12], ticket["title"][:30],
                current_status, agent_name, action,
            )

            # 标记 Agent 忙碌
            self._set_agent_busy(agent_name, ticket_id, ticket["title"][:50], action)

            # 更新到进行中状态
            if next_status:
                await db.update("tickets", {
                    "status": next_status,
                    "assigned_agent": agent_name,
                    "current_owner": self._agent_to_owner(agent_name),
                    "started_at": ticket["started_at"] or now_iso(),
                    "updated_at": now_iso(),
                }, "id = ?", (ticket_id,))

                await self._log(
                    project_id, ticket["requirement_id"], ticket_id, agent_name,
                    "assign", current_status, next_status,
                    f"{agent_name} 接单开始处理"
                )

                await event_manager.publish_to_project(
                    project_id,
                    "ticket_status_changed",
                    {"ticket_id": ticket_id, "from": current_status, "to": next_status, "agent": agent_name},
                )

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
                                return
                            logger.warning("切换分支失败: %s, 当前: %s（非主分支，继续执行）", feat_branch, current_br2)
            except Exception as br_err:
                logger.warning("切换分支异常(非致命): %s", br_err)

            # 构建上下文
            context = await self._build_context(ticket)

            # 注入 SOP 阶段配置到 context
            sop_config = rule.get("config", {})
            if sop_config:
                context["sop_config"] = sop_config

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
            await self._set_ticket_current_action(ticket_id, f"{agent_name}.{action}")
            try:
                result = await agent.execute(action, context)
            finally:
                await self._clear_ticket_current_action(ticket_id)
            agent_elapsed = int((time.time() - agent_start) * 1000)
            logger.info(
                "🤖 %s.%s 完成 (%dms) → status=%s, files=%d",
                agent_name, action, agent_elapsed,
                result.get("status", "?"),
                len(result.get("files", {})),
            )

            clear_llm_context()

            # 标记 Agent 空闲
            self._set_agent_idle(agent_name, success=True)

            # Reflexion：rework / fix_issues 产出的反思写进 ticket_logs
            last_reflection = result.get("last_reflection") if isinstance(result, dict) else None
            if last_reflection and isinstance(last_reflection, dict):
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

                    await self._log(
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

            # 处理结果
            await self._handle_agent_result(project_id, ticket_id, ticket, agent_name, action, result)

            # === 事件驱动：触发后续工单立即处理 ===
            updated = await db.fetch_one("SELECT status FROM tickets WHERE id = ?", (ticket_id,))
            if updated:
                project_rules = await self._get_rules_for_project(project_id)
                if updated["status"] in project_rules:
                    await self._publish_ticket_ready(project_id, ticket_id)

        except Exception as e:
            logger.error("❌ 工单处理异常 [%s]: %s", ticket_id[:12] if ticket_id else "?", e, exc_info=True)
            # 标记 Agent 空闲（失败）
            if 'agent_name' in dir():
                self._set_agent_idle(agent_name, success=False)
            try:
                await self._log(
                    project_id, ticket.get("requirement_id") if ticket else None,
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

        # 保存执行结果（先 pop 二进制媒体文件，避免 JSON 序列化失败）
        media_files_temp = result.pop("_media_files", None)  # 暂存，稍后写入 Git
        result_json = json.dumps(result, ensure_ascii=False)
        if media_files_temp:
            result["_media_files"] = media_files_temp  # 写完 JSON 后放回，供 _handle_git_files 使用

        # === 通用：处理 Agent 返回的 files，写入 Git 仓库 ===
        git_result = await self._handle_git_files(
            project_id, ticket_id, requirement_id,
            agent_name, action, result
        )

        if agent_name == "ArchitectAgent":
            # 架构完成
            new_status = TicketStatus.ARCHITECTURE_DONE.value
            est_hours = result.get("estimated_hours", 4)
            est_completion = (datetime.now() + timedelta(hours=est_hours)).isoformat()

            await db.update("tickets", {
                "status": new_status,
                "result": result_json,
                "estimated_hours": est_hours,
                "estimated_completion": est_completion,
                "updated_at": now_iso(),
            }, "id = ?", (ticket_id,))

            # Self-Consistency 投票留痕（如果开启）
            vote = result.get("_consistency_vote")
            if vote:
                await self._log(
                    project_id, requirement_id, ticket_id, agent_name,
                    "consistency_vote", None, None,
                    f"🗳️ 架构投票: {vote['n_candidates']} 候选 → 选 #{vote['best_index']}"
                    f"{' (judge fallback)' if vote.get('fallback') else ''} | {vote.get('reasoning', '')[:150]}",
                    "info", detail_data={"consistency_vote": vote},
                )

            await self._log(
                project_id, requirement_id, ticket_id, agent_name,
                "complete", current_status, new_status,
                f"架构设计完成，预计开发 {est_hours} 小时",
                detail_data={
                    "estimated_hours": est_hours,
                    "result_summary": str(result.get("architecture", ""))[:500],
                    "git_commit": git_result.get("commit_hash") if git_result else None,
                    "git_files": git_result.get("files", []) if git_result else [],
                },
            )

            # 保存架构产物
            await db.insert("artifacts", {
                "id": generate_id("ART"),
                "project_id": project_id,
                "requirement_id": requirement_id,
                "ticket_id": ticket_id,
                "type": "architecture",
                "name": f"架构设计 - {ticket['title']}",
                "path": None,
                "content": result_json,
                "metadata": json.dumps({"git": git_result}) if git_result else None,
                "created_at": now_iso(),
            })

        elif agent_name == "DevAgent":
            # v0.18 Phase D：UE 引擎编译阶段（action=run_engine_compile）有自己的结果语义。
            # UECompileCheckAction 返回 status 可以是 success / compile_failed（早期 error
            # 已在开头的 BLOCKED 分支被捕获，此处只可能到 success 或 compile_failed）。
            if action == "run_engine_compile":
                r_status = result.get("status")
                errors_list = result.get("errors") or []
                if r_status == "success":
                    new_status = "engine_compile_passed"
                    await db.update("tickets", {
                        "status": new_status,
                        "result": result_json,
                        "updated_at": now_iso(),
                    }, "id = ?", (ticket_id,))
                    # v0.19.x：编译通过 → 把关联 Bug 标为 fixed
                    await self._resolve_compile_bug(ticket_id, project_id)
                    await self._log(
                        project_id, requirement_id, ticket_id, agent_name,
                        "complete", current_status, new_status,
                        f"UBT 编译通过（{result.get('duration_ms', 0) // 1000}s，"
                        f"target={result.get('target_name')}）",
                        detail_data={
                            "exit_code": result.get("exit_code"),
                            "duration_ms": result.get("duration_ms"),
                            "products": result.get("products"),
                            "command": result.get("command"),
                        },
                    )
                    # 通过不落 artifacts（产物列表已在 result 里有）
                else:
                    # compile_failed → 走 reject_goto: development 链路
                    new_status = "engine_compile_failed"
                    await db.update("tickets", {
                        "status": new_status,
                        "result": result_json,
                        "updated_at": now_iso(),
                    }, "id = ?", (ticket_id,))
                    err_brief = "; ".join(
                        f"{e.get('file', '?').split(chr(92))[-1]}:{e.get('line', '?')} {e.get('code', '')} {e.get('msg', '')[:80]}"
                        for e in errors_list[:3]
                    )
                    await self._log(
                        project_id, requirement_id, ticket_id, agent_name,
                        "reject", current_status, new_status,
                        f"UBT 编译失败 · {len(errors_list)} errors · 已创建 Bug 记录，DevAgent.fix_issues 将修复",
                        "warning",
                        detail_data={
                            "errors": errors_list[:10],
                            "warnings": (result.get("warnings") or [])[:5],
                            "exit_code": result.get("exit_code"),
                            "duration_ms": result.get("duration_ms"),
                            "command": result.get("command"),
                            "err_brief": err_brief,
                        },
                    )
                    # v0.19.x：编译失败自动创建 Bug 记录（走正式 Bug 流程）
                    await self._create_compile_bug(
                        project_id, requirement_id, ticket_id, errors_list, err_brief,
                    )
                return   # 不进入下面的产物落库

            # 常规 develop / rework / fix_issues → development_done
            # v0.19.x A 方案：若 self_test 失败（UE blocking 静态错）→ self_test_failed
            # → SOP 派生 self_test_failed → DevAgent.fix_issues 自动回跳
            self_test = result.get("self_test", {})
            test_summary = self_test.get("summary", "未自测")
            blocking_issues = self_test.get("ue_blocking_issues") or []

            if blocking_issues:
                new_status = "self_test_failed"
                await db.update("tickets", {
                    "status": new_status,
                    "result": result_json,
                    "updated_at": now_iso(),
                }, "id = ?", (ticket_id,))
                err_brief = "; ".join(
                    f"[{i.get('rule')}] {(i.get('file') or '?').split('/')[-1]}:{i.get('line') or '?'} "
                    f"{(i.get('msg') or '')[:80]}"
                    for i in blocking_issues[:3]
                )
                await self._log(
                    project_id, requirement_id, ticket_id, agent_name,
                    "reject", current_status, new_status,
                    f"UE 自测不通过 · {len(blocking_issues)} blocking · 将触发 fix_issues 修复",
                    "warning",
                    detail_data={
                        "issues": blocking_issues[:10],
                        "summary": self_test.get("ue_lint_summary"),
                        "err_brief": err_brief,
                    },
                )
                return   # 不落代码产物，等修好再落

            new_status = TicketStatus.DEVELOPMENT_DONE.value

            await db.update("tickets", {
                "status": new_status,
                "result": result_json,
                "updated_at": now_iso(),
            }, "id = ?", (ticket_id,))

            await self._log(
                project_id, requirement_id, ticket_id, agent_name,
                "complete", current_status, new_status,
                f"开发完成 | 自测: {test_summary}",
                detail_data={
                    "files_count": len(result.get("files", {})),
                    "result_summary": str(result.get("dev_result", {}).get("notes", ""))[:500],
                    "self_test": self_test,
                    "git_commit": git_result.get("commit_hash") if git_result else None,
                    "git_files": git_result.get("files", []) if git_result else [],
                },
            )

            # 保存代码产物
            await db.insert("artifacts", {
                "id": generate_id("ART"),
                "project_id": project_id,
                "requirement_id": requirement_id,
                "ticket_id": ticket_id,
                "type": "code",
                "name": f"代码 - {ticket['title']}",
                "path": None,
                "content": result_json,
                "metadata": json.dumps({"git": git_result}) if git_result else None,
                "created_at": now_iso(),
            })

        elif agent_name == "ReviewAgent":
            # 代码审查阶段结果（新增：独立于 TestAgent 的盲审修复）
            new_status = TicketStatus.REVIEW_PASSED.value
            score = result.get("score", 7)
            issues = result.get("issues", []) or []
            suggestions = result.get("suggestions", []) or []
            sop_cfg = ticket.get("_sop_config") or {}  # 可能为空
            pass_score = sop_cfg.get("pass_score", 7)

            await db.update("tickets", {
                "status": new_status,
                "result": result_json,
                "updated_at": now_iso(),
            }, "id = ?", (ticket_id,))

            # 低分只记 warning，不阻塞（block_on_low_score=false 默认）
            try:
                score_num = float(score)
            except (TypeError, ValueError):
                score_num = 7.0
            log_level = "warning" if score_num < pass_score else "info"
            issues_summary = ("; ".join(str(i) for i in issues[:3]) if issues else "无")[:300]
            await self._log(
                project_id, requirement_id, ticket_id, agent_name,
                "code_review", current_status, new_status,
                f"代码审查完成 {score}/10 → {'低于通过分 (warning)' if log_level == 'warning' else '通过'}"
                f" | 问题: {issues_summary}",
                log_level,
                detail_data={
                    "score": score,
                    "issues": issues[:5],
                    "suggestions": suggestions[:5],
                    "pass_score": pass_score,
                    "git_commit": git_result.get("commit_hash") if git_result else None,
                },
            )

            # 保存审查产物
            await db.insert("artifacts", {
                "id": generate_id("ART"),
                "project_id": project_id,
                "requirement_id": requirement_id,
                "ticket_id": ticket_id,
                "type": "code_review",
                "name": f"代码审查 - {ticket['title']}",
                "path": None,
                "content": result_json,
                "metadata": json.dumps({"git": git_result, "score": score}) if git_result else json.dumps({"score": score}),
                "created_at": now_iso(),
            })

        elif agent_name == "ProductAgent" and action == "acceptance_review":
            # 验收结果（只接受合法状态，防止 Agent 返回 "success" 等非标值）
            review_status = result.get("status", "acceptance_passed")
            if review_status not in (TicketStatus.ACCEPTANCE_PASSED.value, TicketStatus.ACCEPTANCE_REJECTED.value):
                review_status = TicketStatus.ACCEPTANCE_PASSED.value
            new_status = review_status

            await db.update("tickets", {
                "status": new_status,
                "result": result_json,
                "updated_at": now_iso(),
            }, "id = ?", (ticket_id,))

            if new_status == TicketStatus.ACCEPTANCE_PASSED.value:
                await self._log(
                    project_id, requirement_id, ticket_id, agent_name,
                    "accept", current_status, new_status,
                    "验收通过，转测试",
                    detail_data={"git_commit": git_result.get("commit_hash") if git_result else None},
                )
                # Failure Library：验收通过说明本工单的历次反思策略最终奏效
                try:
                    from failure_library import failure_library
                    await failure_library.mark_resolved(ticket_id)
                except Exception as fl_err:
                    logger.warning("FailureLibrary.mark_resolved 失败: %s", fl_err)
                # 知识蒸馏：验收通过后，后台尝试将修复经验沉淀到知识库（fire-and-forget）
                _fire_knowledge_distill(project_id, ticket_id)
            else:
                await self._log(
                    project_id, requirement_id, ticket_id, agent_name,
                    "reject", current_status, new_status,
                    f"验收不通过，打回开发。原因: {json.dumps(result.get('review', {}).get('issues', []), ensure_ascii=False)}"
                )

        elif agent_name == "TestAgent":
            # v0.19 Phase ②：UE playtest 阶段（action=run_playtest）有自己的结果语义
            # UEPlaytestAction 返回 status: success / playtest_failed / error
            if action == "run_playtest":
                r_status = result.get("status")
                summary = result.get("summary") or {}
                failed_tests = [t for t in (result.get("tests") or []) if t.get("result") == "failed"]
                if r_status == "success":
                    new_status = "play_test_passed"
                    await db.update("tickets", {
                        "status": new_status,
                        "result": result_json,
                        "updated_at": now_iso(),
                    }, "id = ?", (ticket_id,))
                    await self._log(
                        project_id, requirement_id, ticket_id, agent_name,
                        "complete", current_status, new_status,
                        f"Playtest 通过（{summary.get('passed', 0)}/{summary.get('total', 0)}，"
                        f"{result.get('duration_ms', 0) // 1000}s）",
                        detail_data={
                            "exit_code": result.get("exit_code"),
                            "duration_ms": result.get("duration_ms"),
                            "summary": summary,
                            "screenshots": (result.get("screenshots") or [])[:5],
                            "command": result.get("command"),
                        },
                    )
                else:
                    # playtest_failed → play_test_failed → SOP reject_goto development
                    new_status = "play_test_failed"
                    await db.update("tickets", {
                        "status": new_status,
                        "result": result_json,
                        "updated_at": now_iso(),
                    }, "id = ?", (ticket_id,))
                    fail_brief = "; ".join(
                        f"{t.get('name', '?')}: {'/'.join((t.get('errors') or ['?'])[:1])[:60]}"
                        for t in failed_tests[:3]
                    )
                    await self._log(
                        project_id, requirement_id, ticket_id, agent_name,
                        "reject", current_status, new_status,
                        f"Playtest 失败 · {summary.get('failed', len(failed_tests))}/{summary.get('total', 0)} failed · "
                        f"将触发 DevAgent.fix_issues 修复",
                        "warning",
                        detail_data={
                            "tests": failed_tests[:10],
                            "summary": summary,
                            "screenshots": (result.get("screenshots") or [])[:5],
                            "exit_code": result.get("exit_code"),
                            "duration_ms": result.get("duration_ms"),
                            "command": result.get("command"),
                            "fail_brief": fail_brief,
                        },
                    )
                return   # 不进入下面的常规 testing 分支

            # 测试结果（只接受合法状态）
            test_status = result.get("status", "testing_done")
            if test_status not in (TicketStatus.TESTING_DONE.value, TicketStatus.TESTING_FAILED.value):
                test_status = TicketStatus.TESTING_DONE.value
            new_status = test_status

            await db.update("tickets", {
                "status": new_status,
                "result": result_json,
                "updated_at": now_iso(),
            }, "id = ?", (ticket_id,))

            if new_status == TicketStatus.TESTING_DONE.value:
                await self._log(
                    project_id, requirement_id, ticket_id, agent_name,
                    "complete", current_status, new_status,
                    f"测试通过: {result.get('test_result', {}).get('summary', '')}",
                    detail_data={
                        "git_commit": git_result.get("commit_hash") if git_result else None,
                        "git_files": git_result.get("files", []) if git_result else [],
                    },
                )
                # Failure Library：测试通过也算历次反思策略奏效
                try:
                    from failure_library import failure_library
                    await failure_library.mark_resolved(ticket_id)
                except Exception as fl_err:
                    logger.warning("FailureLibrary.mark_resolved 失败: %s", fl_err)

                # 保存测试产物
                await db.insert("artifacts", {
                    "id": generate_id("ART"),
                    "project_id": project_id,
                    "requirement_id": requirement_id,
                    "ticket_id": ticket_id,
                    "type": "test",
                    "name": f"测试报告 - {ticket['title']}",
                    "path": None,
                    "content": result_json,
                    "metadata": json.dumps({"git": git_result}) if git_result else None,
                    "created_at": now_iso(),
                })

                # 保存截图 artifact
                for ss in result.get("test_result", {}).get("screenshots", []):
                    await db.insert("artifacts", {
                        "id": generate_id("ART"),
                        "project_id": project_id,
                        "requirement_id": requirement_id,
                        "ticket_id": ticket_id,
                        "type": "screenshot",
                        "name": ss["label"],
                        "path": ss["url"],
                        "content": None,
                        "metadata": json.dumps({"url": ss["url"]}),
                        "created_at": now_iso(),
                    })

                # 测试通过 → 触发后续依赖工单
                await self._trigger_dependents(project_id, ticket_id)

                # 检查需求下所有工单是否都测试通过（用于需求级统一部署）
                await self._check_requirement_completion(project_id, requirement_id)

                # 刷新里程碑进度
                try:
                    from api.milestones import refresh_all_milestones
                    await refresh_all_milestones(project_id)
                except Exception as ms_err:
                    logger.warning("刷新里程碑进度失败(非致命): %s", ms_err)
            else:
                # 测试不通过 → 保存测试产物 + 打回开发
                test_summary = result.get("test_result", {}).get("summary", {})
                pass_rate = test_summary.get("pass_rate", 0) if isinstance(test_summary, dict) else 0
                issues = test_summary.get("issues", []) if isinstance(test_summary, dict) else []

                await db.insert("artifacts", {
                    "id": generate_id("ART"),
                    "project_id": project_id,
                    "requirement_id": requirement_id,
                    "ticket_id": ticket_id,
                    "type": "test",
                    "name": f"测试报告(未通过) - {ticket['title']}",
                    "path": None,
                    "content": result_json,
                    "metadata": json.dumps({"git": git_result}) if git_result else None,
                    "created_at": now_iso(),
                })

                await self._log(
                    project_id, requirement_id, ticket_id, agent_name,
                    "reject", current_status, new_status,
                    f"测试未通过 (通过率 {pass_rate}%)，打回开发: {'; '.join(issues[:3]) if issues else '详见测试报告'}",
                    detail_data={
                        "pass_rate": pass_rate,
                        "issues": issues[:5],
                        "git_commit": git_result.get("commit_hash") if git_result else None,
                    },
                )

        elif agent_name == "DeployAgent":
            # 部署完成
            new_status = TicketStatus.DEPLOYED.value

            await db.update("tickets", {
                "status": new_status,
                "result": result_json,
                "completed_at": now_iso(),
                "updated_at": now_iso(),
            }, "id = ?", (ticket_id,))

            preview_url = result.get("deploy_result", {}).get("preview_url")
            deploy_msg = "部署完成"
            if preview_url:
                deploy_msg = f"部署完成，预览地址: {preview_url}"

            await self._log(
                project_id, requirement_id, ticket_id, agent_name,
                "complete", current_status, new_status,
                deploy_msg,
                detail_data={
                    "git_commit": git_result.get("commit_hash") if git_result else None,
                    "git_files": git_result.get("files", []) if git_result else [],
                    "preview_url": preview_url,
                },
            )

            # 保存部署产物
            await db.insert("artifacts", {
                "id": generate_id("ART"),
                "project_id": project_id,
                "requirement_id": requirement_id,
                "ticket_id": ticket_id,
                "type": "deploy_config",
                "name": f"部署配置 - {ticket['title']}",
                "path": None,
                "content": result_json,
                "metadata": json.dumps({"git": git_result}) if git_result else None,
                "created_at": now_iso(),
            })

            # 检查需求下所有工单是否都已完成
            await self._check_requirement_completion(project_id, requirement_id)

            # 刷新里程碑进度
            try:
                from api.milestones import refresh_all_milestones
                await refresh_all_milestones(project_id)
            except Exception as ms_err:
                logger.warning("刷新里程碑进度失败(非致命): %s", ms_err)

            # 触发依赖此工单的后续工单
            await self._trigger_dependents(project_id, ticket_id)

        else:
            new_status = current_status

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

        # === 强制将中文文件名转为英文 ===
        import re
        sanitized_files = {}
        for path, content in files.items():
            # 检测路径中是否有非 ASCII 字符
            if any(ord(c) > 127 for c in path):
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
        git_result = await git_manager.write_and_commit(
            project_id, files, commit_msg, agent=agent_name
        )

        # 写入二进制媒体文件（截图等），并追加 commit
        media_files: dict = result.pop("_media_files", {}) or {}
        if media_files:
            try:
                repo_dir = git_manager._repo_path(project_id)
                for media_path, img_bytes in media_files.items():
                    dest = repo_dir / media_path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(img_bytes)
                    logger.info("🖼️ 媒体文件写入: %s (%d bytes)", media_path, len(img_bytes))
                media_commit = await git_manager.commit(
                    project_id,
                    f"[{agent_name}] 测试截图: {ticket_title}",
                    author=agent_name,
                )
                await git_manager.push(project_id)
                logger.info("📸 测试截图已提交: %s", media_commit)
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
        tickets = await db.fetch_all(
            "SELECT status FROM tickets WHERE requirement_id = ? AND status != 'cancelled'",
            (requirement_id,),
        )

        DONE_STATUSES = {TicketStatus.TESTING_DONE.value, TicketStatus.DEPLOYED.value}
        all_done = all(t["status"] in DONE_STATUSES for t in tickets)

        if all_done and tickets:
            await db.update("requirements", {
                "status": RequirementStatus.COMPLETED.value,
                "completed_at": now_iso(),
                "updated_at": now_iso(),
            }, "id = ?", (requirement_id,))

            await self._log(
                project_id, requirement_id, None, "Orchestrator",
                "complete", "in_progress", "completed",
                f"需求已完成！所有 {len(tickets)} 个工单均已测试通过，可进行统一部署"
            )

            await event_manager.publish_to_project(
                project_id,
                "requirement_completed",
                {"requirement_id": requirement_id},
            )

            # 生成需求完成报告
            try:
                await self._generate_requirement_report(project_id, requirement_id)
            except Exception as rpt_err:
                logger.warning("生成需求报告失败(非致命): %s", rpt_err)

            # === 规范合并：先拉 develop 最新到 feat → 确认无冲突 → 再合入 develop ===
            try:
                req_data = await db.fetch_one("SELECT branch_name FROM requirements WHERE id = ?", (requirement_id,))
                branch_name = req_data.get("branch_name") if req_data else None
                if branch_name:
                    # 确保 develop 分支存在
                    primary_branch = await git_manager.get_primary_branch(project_id)
                    await git_manager.ensure_branch(project_id, "develop", from_branch=primary_branch)

                    # Step 1: 先把 develop 最新代码合入 feat（解决冲突在 feat 上）
                    logger.info("🔀 Step 1: merge develop → %s（拉最新）", branch_name)
                    pre_merge = await git_manager.merge_branch(
                        project_id, "develop", branch_name,
                        message=f"merge: develop → {branch_name} (合入最新代码)"
                    )
                    if not pre_merge["success"]:
                        logger.error("❌ develop → %s 合并冲突: %s", branch_name, pre_merge.get("error"))
                        await self._log(
                            project_id, requirement_id, None, "Orchestrator",
                            "error", "completed", "completed",
                            f"合并冲突: develop → {branch_name} 失败，需手动解决: {pre_merge.get('error', '')}"
                        )
                        # 不继续合入 develop，等手动解决
                        return

                    # Step 2: feat 合入 develop
                    logger.info("🔀 Step 2: merge %s → develop（合入功能）", branch_name)
                    merge_result = await git_manager.merge_branch(
                        project_id, branch_name, "develop",
                        message=f"merge: {branch_name} → develop (需求完成)"
                    )
                    if merge_result["success"]:
                        await self._log(
                            project_id, requirement_id, None, "Orchestrator",
                            "complete", "completed", "completed",
                            f"分支 {branch_name} 已合并到 develop (commit: {merge_result.get('commit', '?')})"
                        )
                        await event_manager.publish_to_project(
                            project_id,
                            "branch_merged",
                            {"source": branch_name, "target": "develop",
                             "commit": merge_result.get("commit"),
                             "requirement_id": requirement_id},
                        )
                        logger.info("🔀 分支合并完成: %s → develop", branch_name)

                        # === develop → 主分支：检查该项目所有需求是否都已完成，若是则合入主分支 ===
                        try:
                            all_reqs = await db.fetch_all(
                                "SELECT status FROM requirements WHERE project_id = ? AND status != 'cancelled'",
                                (project_id,),
                            )
                            all_reqs_done = all_reqs and all(
                                r["status"] == RequirementStatus.COMPLETED.value for r in all_reqs
                            )
                            if all_reqs_done:
                                primary_branch = await git_manager.get_primary_branch(project_id)
                                main_merge = await git_manager.merge_branch(
                                    project_id, "develop", primary_branch,
                                    message=f"merge: develop → {primary_branch} (所有需求已完成，发布版本)"
                                )
                                if main_merge["success"]:
                                    await self._log(
                                        project_id, requirement_id, None, "Orchestrator",
                                        "complete", "completed", "completed",
                                        f"develop 已合并到 {primary_branch} (commit: {main_merge.get('commit', '?')})"
                                    )
                                    await event_manager.publish_to_project(
                                        project_id,
                                        "branch_merged",
                                        {"source": "develop", "target": primary_branch,
                                         "commit": main_merge.get("commit"),
                                         "requirement_id": requirement_id},
                                    )
                                    logger.info("🚀 develop → %s 合并完成，项目版本已更新", primary_branch)
                                else:
                                    logger.warning("develop → %s 合并失败: %s", primary_branch, main_merge.get("error"))
                        except Exception as main_merge_err:
                            logger.warning("develop → 主分支合并失败(非致命): %s", main_merge_err)

                    else:
                        await self._log(
                            project_id, requirement_id, None, "Orchestrator",
                            "error", "completed", "completed",
                            f"分支合并失败: {merge_result.get('error', '未知错误')}", "warn"
                        )
                        logger.warning("分支合并失败: %s", merge_result.get("error"))
            except Exception as merge_err:
                logger.warning("分支合并失败(非致命): %s", merge_err)

    async def _generate_requirement_report(self, project_id: str, requirement_id: str):
        """需求完成后生成汇总报告 Markdown，保存到 Git 仓库 + artifacts 表"""
        req = await db.fetch_one("SELECT * FROM requirements WHERE id = ?", (requirement_id,))
        if not req:
            return

        project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
        req_short = requirement_id[-6:]

        # 获取所有工单
        tickets = await db.fetch_all(
            "SELECT * FROM tickets WHERE requirement_id = ? ORDER BY sort_order, created_at",
            (requirement_id,),
        )

        # 获取所有产物
        artifacts = await db.fetch_all(
            "SELECT * FROM artifacts WHERE requirement_id = ? ORDER BY created_at",
            (requirement_id,),
        )

        # 获取 LLM 会话统计
        llm_stats = await db.fetch_one(
            "SELECT COUNT(*) as count, SUM(input_tokens) as input_tokens, SUM(output_tokens) as output_tokens, SUM(duration_ms) as total_ms FROM llm_conversations WHERE requirement_id = ?",
            (requirement_id,),
        )

        # 获取日志
        logs = await db.fetch_all(
            "SELECT * FROM ticket_logs WHERE requirement_id = ? ORDER BY created_at",
            (requirement_id,),
        )

        # 获取 Git 提交记录
        git_commits = []
        try:
            git_commits = await git_manager.get_log(project_id, limit=50)
        except Exception:
            pass

        # === 构建报告 Markdown ===
        from datetime import datetime

        duration_str = ""
        if req.get("created_at") and req.get("completed_at"):
            try:
                t1 = datetime.fromisoformat(req["created_at"])
                t2 = datetime.fromisoformat(req["completed_at"])
                delta = t2 - t1
                hours = delta.total_seconds() / 3600
                duration_str = f"{hours:.1f} 小时"
            except Exception:
                pass

        md = f"# 📋 需求完成报告\n\n"
        md += f"## 基本信息\n\n"
        md += f"| 项目 | 内容 |\n|------|------|\n"
        md += f"| **需求ID** | {requirement_id} |\n"
        md += f"| **标题** | {req['title']} |\n"
        md += f"| **项目** | {project['name'] if project else '-'} |\n"
        md += f"| **优先级** | {req.get('priority', '-')} |\n"
        md += f"| **开发分支** | `{req.get('branch_name', '-')}` |\n"
        md += f"| **创建时间** | {req.get('created_at', '-')} |\n"
        md += f"| **完成时间** | {req.get('completed_at', '-')} |\n"
        md += f"| **总耗时** | {duration_str or '-'} |\n"
        md += f"| **工单数** | {len(tickets)} |\n\n"

        # 需求描述
        md += f"## 需求描述\n\n{req.get('description', '-')}\n\n"

        # PRD
        if req.get("prd_content"):
            md += f"## PRD 摘要\n\n{req['prd_content']}\n\n"

        # 工单清单
        md += f"## 工单清单 ({len(tickets)})\n\n"
        md += f"| # | 标题 | 状态 | 类型 | 模块 | Agent | 预估工时 |\n"
        md += f"|---|------|------|------|------|-------|----------|\n"
        for i, t in enumerate(tickets, 1):
            status_label = t.get("status", "")
            md += f"| {i} | {t['title']} | {status_label} | {t.get('type', '-')} | {t.get('module', '-')} | {t.get('assigned_agent', '-')} | {t.get('estimated_hours', '-')}h |\n"
        md += "\n"

        # 产出文件
        if artifacts:
            md += f"## 产出文件 ({len(artifacts)})\n\n"
            for a in artifacts:
                ticket_short = (a.get("ticket_id") or "")[-6:]
                md += f"- **{a.get('name', a['type'])}** ({a['type']}) — 工单 #{ticket_short} — {a.get('created_at', '')[:16]}\n"
            md += "\n"

        # 截图预览（收集各工单 Medias 目录下的图片）
        try:
            from git_manager import git_manager as _gm
            repo_dir = _gm._repo_path(project_id)
            req_short_path = req_short  # 需求短码
            screenshot_entries = []
            # 扫描 docs/<req_short>/<ticket_short>/Medias/ 目录
            docs_root = repo_dir / "docs" / req_short_path
            if docs_root.exists():
                for medias_dir in docs_root.glob("*/Medias"):
                    for img in sorted(medias_dir.glob("*.png")):
                        rel = img.relative_to(repo_dir / "docs" / req_short_path)
                        screenshot_entries.append(str(rel).replace("\\", "/"))
            if screenshot_entries:
                md += f"## 测试截图\n\n"
                for s in screenshot_entries:
                    md += f"![{s}](./{s})\n\n"
        except Exception:
            pass

        # AI 会话统计
        if llm_stats and llm_stats.get("count"):
            input_t = llm_stats.get("input_tokens") or 0
            output_t = llm_stats.get("output_tokens") or 0
            total_ms = llm_stats.get("total_ms") or 0
            md += f"## AI 会话统计\n\n"
            md += f"| 指标 | 数值 |\n|------|------|\n"
            md += f"| 会话次数 | {llm_stats['count']} |\n"
            md += f"| 输入 tokens | {input_t:,} |\n"
            md += f"| 输出 tokens | {output_t:,} |\n"
            md += f"| 总计 tokens | {input_t + output_t:,} |\n"
            md += f"| 总耗时 | {total_ms / 1000:.1f}s |\n\n"

        # 时间线（关键日志）
        key_actions = ["create", "decompose", "assign", "complete", "accept", "reject", "error"]
        key_logs = [l for l in logs if l.get("action") in key_actions][:30]
        if key_logs:
            md += f"## 关键时间线\n\n"
            md += f"| 时间 | Agent | 动作 | 说明 |\n|------|-------|------|------|\n"
            for l in key_logs:
                detail = ""
                try:
                    d = json.loads(l.get("detail", "{}"))
                    detail = d.get("message", "")[:60]
                except Exception:
                    detail = str(l.get("detail", ""))[:60]
                md += f"| {l.get('created_at', '')[:16]} | {l.get('agent_type', '-')} | {l.get('action', '-')} | {detail} |\n"
            md += "\n"

        # Git 提交记录
        if git_commits:
            md += f"## Git 提交记录 (最近 {len(git_commits)} 条)\n\n"
            for c in git_commits[:20]:
                md += f"- `{c.get('short_hash', '?')}` {c.get('message', '')} — {c.get('author', '')} {c.get('date', '')[:16]}\n"
            md += "\n"

        md += f"\n---\n*报告由 AI Dev System 自动生成 — {now_iso()[:16]}*\n"

        # === 保存报告 ===
        report_path = f"docs/{req_short}/REPORT.md"

        # 写入 Git 仓库
        try:
            await git_manager.write_file(project_id, report_path, md)
            commit_hash = await git_manager.commit(
                project_id,
                f"[Report] 需求完成报告: {req['title'][:30]}",
                author="AI Dev System",
            )
            await git_manager.push(project_id)
            logger.info("📊 需求报告已生成: %s (commit: %s)", report_path, commit_hash)
        except Exception as git_err:
            logger.warning("报告写入 Git 失败: %s", git_err)

        # 保存到 artifacts 表
        await db.insert("artifacts", {
            "id": generate_id("ART"),
            "project_id": project_id,
            "requirement_id": requirement_id,
            "ticket_id": None,
            "type": "report",
            "name": f"需求完成报告 - {req['title']}",
            "path": report_path,
            "content": md,
            "metadata": json.dumps({"ticket_count": len(tickets), "artifact_count": len(artifacts)}),
            "created_at": now_iso(),
        })

        await self._log(
            project_id, requirement_id, None, "Orchestrator",
            "complete", "completed", "completed",
            f"需求完成报告已生成: {report_path}"
        )

    async def _trigger_dependents(self, project_id: str, completed_ticket_id: str):
        """工单完成后，触发依赖它的后续工单流转"""
        # 查找同项目下所有 pending 且 dependencies 包含此工单 ID 的工单
        pending_tickets = await db.fetch_all(
            "SELECT * FROM tickets WHERE project_id = ? AND status = ? AND dependencies IS NOT NULL AND dependencies != '[]'",
            (project_id, TicketStatus.PENDING.value),
        )

        for pt in pending_tickets:
            try:
                deps = json.loads(pt["dependencies"]) if pt["dependencies"] else []
            except (json.JSONDecodeError, TypeError):
                continue

            if completed_ticket_id not in deps:
                continue

            # 检查该工单的所有依赖是否都已完成（testing_done 或 deployed）
            DONE_STATUSES = {TicketStatus.TESTING_DONE.value, TicketStatus.DEPLOYED.value}
            all_deps_done = True
            for dep_id in deps:
                dep_ticket = await db.fetch_one(
                    "SELECT status FROM tickets WHERE id = ?", (dep_id,)
                )
                if not dep_ticket or dep_ticket["status"] not in DONE_STATUSES:
                    all_deps_done = False
                    break

            if all_deps_done:
                logger.info(
                    "🔓 工单 %s 的所有前置依赖已完成，开始流转",
                    pt["id"][:12],
                )
                await self._log(
                    project_id, pt["requirement_id"], pt["id"], "Orchestrator",
                    "info", "pending", "pending",
                    f"前置依赖已全部完成（包括 #{completed_ticket_id[-6:]}），开始自动流转", "info"
                )
                # 异步触发后续工单流转
                import asyncio
                asyncio.create_task(self.process_ticket(project_id, pt["id"]))

    async def _build_context(self, ticket: Dict) -> Dict:
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
        context = {
            "ticket_id": ticket["id"],
            "ticket_title": ticket["title"],
            "ticket_description": ticket.get("description", ""),
            "ticket_type": ticket.get("type", "feature"),  # 'bug' or 'feature'
            "module": ticket.get("module", "other"),
            "project_id": project_id,
            "requirement_description": requirement["description"] if requirement else "",
            "requirement_title": requirement["title"] if requirement else "",
            # 文件路径前缀：docs/{需求短码}/{工单短码}/ — 避免不同需求/工单互相覆盖
            "docs_prefix": f"docs/{ticket['requirement_id'][-6:]}/{ticket['id'][-6:]}/",
            "src_prefix": f"src/{ticket.get('module', 'other')}/",
            "tests_prefix": f"tests/{ticket['requirement_id'][-6:]}/",
            # v0.19.x 工单面板进度区：让 UE 流式 actions 写心跳
            "_ticket_progress_cb": self._make_ticket_progress_callback(project_id, ticket["id"]),
        }

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

        # === 知识库上下文（全局 + 项目级）===
        try:
            context["knowledge_docs"] = self._load_knowledge_docs(project_id)
        except Exception as e:
            logger.warning("读取知识库失败: %s", e)
            context["knowledge_docs"] = ""

        return context

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

        # 读取关键文件内容（入口文件 + src/ 下的代码文件）
        code = {}
        ENTRY_FILES = {"index.html", "main.py", "app.py", "package.json"}
        CODE_EXTS = {".html", ".js", ".jsx", ".ts", ".tsx", ".py", ".css", ".json"}
        total_chars = 0
        MAX_TOTAL = 15000
        MAX_PER_FILE = 3000

        for fp in file_list:
            if total_chars >= MAX_TOTAL:
                break
            fname = fp.split("/")[-1]
            _, ext = (fname.rsplit(".", 1) if "." in fname else (fname, ""))
            ext = f".{ext}" if ext else ""

            # 优先读入口文件，其次 src/ 下的代码文件
            should_read = fname in ENTRY_FILES or (fp.startswith("src/") and ext in CODE_EXTS)
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

            from actions.diagnose_ticket import DiagnoseTicketAction
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


# 全局 Orchestrator
orchestrator = TicketOrchestrator()


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
