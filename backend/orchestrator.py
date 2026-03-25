"""
AI 自动开发系统 - Orchestrator 工单编排器
核心调度引擎：管理工单在 Agent 之间的流转
"""
import json
import asyncio
import logging
import time
from typing import Any, Dict, Optional
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

# Agent 导入
from agents.product import ProductAgent
from agents.architect import ArchitectAgent
from agents.dev import DevAgent
from agents.test import TestAgent
from agents.review import ReviewAgent
from agents.deploy import DeployAgent


class TicketOrchestrator:
    """工单编排器 — 管理需求拆单和工单在 Agent 之间的流转"""

    def __init__(self):
        # Agent 池
        self.agents = {
            "ProductAgent": ProductAgent(),
            "ArchitectAgent": ArchitectAgent(),
            "DevAgent": DevAgent(),
            "TestAgent": TestAgent(),
            "ReviewAgent": ReviewAgent(),
            "DeployAgent": DeployAgent(),
        }

        # 状态转换规则表：当前状态 → 下一步由哪个 Agent 处理
        self.transition_rules = {
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
                "next_status": None,  # 根据验收结果决定
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
            TicketStatus.TESTING_DONE.value: {
                "agent": "DeployAgent",
                "action": "deploy",
                "next_status": TicketStatus.DEPLOYING.value,
            },
            TicketStatus.TESTING_FAILED.value: {
                "agent": "DevAgent",
                "action": "fix_issues",
                "next_status": TicketStatus.DEVELOPMENT_IN_PROGRESS.value,
            },
        }

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

            # Agent 执行拆单
            logger.info("🤖 ProductAgent.analyze_and_decompose 开始执行...")
            req_start = time.time()
            result = await agent.execute("analyze_and_decompose", {
                "title": requirement["title"],
                "description": requirement["description"],
                "priority": requirement["priority"],
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
                    "status": TicketStatus.PENDING.value,
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
                    await db.insert("subtasks", {
                        "id": st_id,
                        "ticket_id": ticket_id,
                        "title": st["title"],
                        "description": st.get("description", ""),
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

            # 检查前置依赖是否完成
            deps_json = ticket.get("dependencies", "[]")
            try:
                dep_ids = json.loads(deps_json) if deps_json else []
            except (json.JSONDecodeError, TypeError):
                dep_ids = []

            if dep_ids and ticket["status"] == TicketStatus.PENDING.value:
                # 查询所有依赖工单的状态
                pending_deps = []
                for dep_id in dep_ids:
                    dep_ticket = await db.fetch_one(
                        "SELECT id, title, status FROM tickets WHERE id = ?", (dep_id,)
                    )
                    if dep_ticket and dep_ticket["status"] != TicketStatus.DEPLOYED.value:
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
            rule = self.transition_rules.get(current_status)

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

            # 构建上下文
            context = await self._build_context(ticket)

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
            result = await agent.execute(action, context)
            agent_elapsed = int((time.time() - agent_start) * 1000)
            logger.info(
                "🤖 %s.%s 完成 (%dms) → status=%s, files=%d",
                agent_name, action, agent_elapsed,
                result.get("status", "?"),
                len(result.get("files", {})),
            )

            clear_llm_context()

            # 处理结果
            await self._handle_agent_result(project_id, ticket_id, ticket, agent_name, action, result)

        except Exception as e:
            logger.error("❌ 工单处理异常 [%s]: %s", ticket_id[:12] if ticket_id else "?", e, exc_info=True)
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

        # 保存执行结果
        result_json = json.dumps(result, ensure_ascii=False)

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
            # 开发完成
            new_status = TicketStatus.DEVELOPMENT_DONE.value

            await db.update("tickets", {
                "status": new_status,
                "result": result_json,
                "updated_at": now_iso(),
            }, "id = ?", (ticket_id,))

            await self._log(
                project_id, requirement_id, ticket_id, agent_name,
                "complete", current_status, new_status,
                "开发完成，等待产品验收",
                detail_data={
                    "files_count": len(result.get("files", {})),
                    "result_summary": str(result.get("dev_result", {}).get("notes", ""))[:500],
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

        elif agent_name == "ProductAgent" and action == "acceptance_review":
            # 验收结果
            review_status = result.get("status", "acceptance_passed")
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
            else:
                await self._log(
                    project_id, requirement_id, ticket_id, agent_name,
                    "reject", current_status, new_status,
                    f"验收不通过，打回开发。原因: {json.dumps(result.get('review', {}).get('issues', []), ensure_ascii=False)}"
                )

        elif agent_name == "TestAgent":
            # 测试结果
            test_status = result.get("status", "testing_done")
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
            else:
                await self._log(
                    project_id, requirement_id, ticket_id, agent_name,
                    "reject", current_status, new_status,
                    f"测试不通过，打回开发"
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

            await self._log(
                project_id, requirement_id, ticket_id, agent_name,
                "complete", current_status, new_status,
                "部署完成",
                detail_data={
                    "git_commit": git_result.get("commit_hash") if git_result else None,
                    "git_files": git_result.get("files", []) if git_result else [],
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
        if updated_ticket and updated_ticket["status"] in self.transition_rules:
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

        # 写入文件 + 提交
        commit_msg = f"[{agent_name}] {action}: {len(files)} files"
        git_result = await git_manager.write_and_commit(
            project_id, files, commit_msg, agent=agent_name
        )

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
        """检查需求下所有工单是否都已完成"""
        tickets = await db.fetch_all(
            "SELECT status FROM tickets WHERE requirement_id = ? AND status != 'cancelled'",
            (requirement_id,),
        )

        all_deployed = all(t["status"] == TicketStatus.DEPLOYED.value for t in tickets)

        if all_deployed and tickets:
            await db.update("requirements", {
                "status": RequirementStatus.COMPLETED.value,
                "completed_at": now_iso(),
                "updated_at": now_iso(),
            }, "id = ?", (requirement_id,))

            await self._log(
                project_id, requirement_id, None, "Orchestrator",
                "complete", "in_progress", "completed",
                f"需求已完成！所有 {len(tickets)} 个工单均已部署"
            )

            await event_manager.publish_to_project(
                project_id,
                "requirement_completed",
                {"requirement_id": requirement_id},
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

            # 检查该工单的所有依赖是否都已完成
            all_deps_done = True
            for dep_id in deps:
                dep_ticket = await db.fetch_one(
                    "SELECT status FROM tickets WHERE id = ?", (dep_id,)
                )
                if not dep_ticket or dep_ticket["status"] != TicketStatus.DEPLOYED.value:
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

        context = {
            "ticket_id": ticket["id"],
            "ticket_title": ticket["title"],
            "ticket_description": ticket.get("description", ""),
            "module": ticket.get("module", "other"),
            "requirement_description": requirement["description"] if requirement else "",
            "requirement_title": requirement["title"] if requirement else "",
        }

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

        return context

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


# 全局 Orchestrator
orchestrator = TicketOrchestrator()
