"""
AI 自动开发系统 - Orchestrator 工单编排器
核心调度引擎：管理工单在 Agent 之间的流转
"""
import json
import asyncio
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

            agent = self.agents["ProductAgent"]

            # 发 SSE：开始分析
            await event_manager.publish_to_project(
                project_id,
                "agent_working",
                {"agent": "ProductAgent", "action": "analyze_and_decompose", "requirement_id": requirement_id},
            )

            # Agent 执行拆单
            result = await agent.execute("analyze_and_decompose", {
                "title": requirement["title"],
                "description": requirement["description"],
                "priority": requirement["priority"],
            })

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

            # 创建工单
            tickets_data = result.get("tickets", [])
            created_tickets = []

            for idx, tk in enumerate(tickets_data):
                ticket_id = generate_id("TK")
                now = now_iso()

                # 创建工单
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
                    "dependencies": json.dumps(tk.get("dependencies", [])),
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

                # 日志
                await self._log(
                    project_id, requirement_id, ticket_id, "ProductAgent",
                    "create", None, "pending",
                    f"工单「{tk['title']}」已创建，模块: {tk.get('module', 'other')}"
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
            print(f"[Orchestrator] 需求处理异常: {e}")
            import traceback
            traceback.print_exc()

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
                print(f"[Orchestrator] 记录错误日志也失败了: {log_err}")

    # ==================== 工单流转 ====================

    async def process_ticket(self, project_id: str, ticket_id: str):
        """根据当前状态自动分派到对应 Agent"""
        try:
            ticket = await db.fetch_one(
                "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
            )
            if not ticket:
                return

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
                await self._log(
                    project_id, ticket["requirement_id"], ticket_id, agent_name,
                    "error", current_status, current_status,
                    f"Agent {agent_name} 不存在", "error"
                )
                return

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

            result = await agent.execute(action, context)

            # 处理结果
            await self._handle_agent_result(project_id, ticket_id, ticket, agent_name, action, result)

        except Exception as e:
            print(f"[Orchestrator] 工单处理异常: {e}")
            import traceback
            traceback.print_exc()
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
                print(f"[Orchestrator] 记录错误日志也失败了: {log_err}")

    async def _handle_agent_result(
        self,
        project_id: str,
        ticket_id: str,
        ticket: Dict,
        agent_name: str,
        action: str,
        result: Dict,
    ):
        """根据 Agent 执行结果更新工单状态"""
        requirement_id = ticket["requirement_id"]
        current_ticket = await db.fetch_one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        current_status = current_ticket["status"] if current_ticket else ticket["status"]

        # 保存执行结果
        result_json = json.dumps(result, ensure_ascii=False)

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
                f"架构设计完成，预计开发 {est_hours} 小时"
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
                "metadata": None,
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
                "开发完成，等待产品验收"
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
                "metadata": None,
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
                    "验收通过，转测试"
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
                    f"测试通过: {result.get('test_result', {}).get('summary', '')}"
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
                    "metadata": None,
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
                "部署完成"
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
                "metadata": None,
                "created_at": now_iso(),
            })

            # 检查需求下所有工单是否都已完成
            await self._check_requirement_completion(project_id, requirement_id)

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
    ):
        """记录日志并推送 SSE 实时事件"""
        log_id = generate_id("LOG")
        created_at = now_iso()
        detail_json = json.dumps({"message": message}, ensure_ascii=False)

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
