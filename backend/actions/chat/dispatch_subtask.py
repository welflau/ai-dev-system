"""
DispatchSubtaskAction — Agent 在执行中动态创建子 Ticket

使用场景：
  DevAgent 在开发过程中发现需要专项测试，主动派发子 Ticket 给 TestAgent；
  PlannerAgent 发现某模块需要深度 UX 设计，派发子 Ticket 给 UXAgent。

设计原则：
  1. 子 Ticket 创建后进入 PENDING 状态，Orchestrator 下一轮 poll 自动拾取
  2. 父 Ticket 状态置为 WAITING_SUBTASKS，等待子 Ticket 全部完成
  3. 循环检测：子 Ticket 不能再派发给自己的父/祖先 Ticket
  4. 子 Ticket 深度上限：3 层（防止失控嵌套）
"""
import json
import logging
from typing import Any, Dict, List, Optional

from actions.base import ActionBase, ActionResult
from database import db
from utils import generate_id, now_iso

logger = logging.getLogger("actions.dispatch_subtask")

# 子 Ticket 最大嵌套深度
MAX_SUBTASK_DEPTH = 3

# 父 Ticket 等待子 Ticket 的中间状态（写入 tickets.status）
WAITING_SUBTASKS_STATUS = "waiting_subtasks"


async def _get_ancestor_ids(ticket_id: str) -> List[str]:
    """递归获取所有祖先 Ticket 的 ID，用于循环检测"""
    ancestors = []
    current = ticket_id
    for _ in range(MAX_SUBTASK_DEPTH + 2):
        row = await db.fetch_one(
            "SELECT parent_ticket_id FROM tickets WHERE id = ?", (current,)
        )
        if not row or not row["parent_ticket_id"]:
            break
        parent = row["parent_ticket_id"]
        ancestors.append(parent)
        current = parent
    return ancestors


async def _get_subtask_depth(ticket_id: str) -> int:
    """计算当前 Ticket 的嵌套深度（0 = 顶层）"""
    depth = 0
    current = ticket_id
    for _ in range(MAX_SUBTASK_DEPTH + 2):
        row = await db.fetch_one(
            "SELECT parent_ticket_id FROM tickets WHERE id = ?", (current,)
        )
        if not row or not row["parent_ticket_id"]:
            break
        depth += 1
        current = row["parent_ticket_id"]
    return depth


class DispatchSubtaskAction(ActionBase):
    """创建子 Ticket 并将父 Ticket 置为等待状态"""

    @property
    def name(self) -> str:
        return "dispatch_subtask"

    @property
    def description(self) -> str:
        return "派发子任务：创建一个子 Ticket 并等待它完成后再继续父任务"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "在当前任务执行过程中，派发一个子任务给指定 Agent 处理。\n"
                "子任务完成后，父任务会自动恢复执行。\n"
                "适用场景：需要专项测试、深度 UX 设计、独立模块开发等。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "子任务标题，简短描述要做什么",
                    },
                    "description": {
                        "type": "string",
                        "description": "子任务详细说明（背景、要求、验收条件）",
                    },
                    "start_status": {
                        "type": "string",
                        "description": (
                            "子任务从哪个状态开始（决定由哪个 Agent 接手）。"
                            "常用：pending（从头开始）/ architecture_done（直接到开发）/ "
                            "development_done（直接到测试）"
                        ),
                        "enum": ["pending", "architecture_done", "development_done"],
                    },
                    "priority": {
                        "type": "integer",
                        "description": "优先级：1=紧急, 2=高, 3=普通（默认 2）",
                        "enum": [1, 2, 3],
                    },
                },
                "required": ["title", "description"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        parent_ticket_id = context.get("ticket_id") or context.get("parent_ticket_id")
        project_id       = context.get("project_id")
        title            = (context.get("title") or "").strip()
        description      = (context.get("description") or "").strip()
        start_status     = context.get("start_status", "pending")
        priority         = int(context.get("priority") or 2)

        if not title:
            return ActionResult(success=False, error="子任务标题不能为空")
        if not parent_ticket_id:
            return ActionResult(success=False, error="缺少 parent_ticket_id（当前 Agent 的 ticket_id）")
        if not project_id:
            return ActionResult(success=False, error="缺少 project_id")

        # ── 循环检测 ──────────────────────────────────────────────────────────
        ancestors = await _get_ancestor_ids(parent_ticket_id)
        depth = len(ancestors)
        if depth >= MAX_SUBTASK_DEPTH:
            return ActionResult(
                success=False,
                error=f"子任务嵌套深度已达上限 {MAX_SUBTASK_DEPTH} 层，不能再派发"
            )

        # ── 获取父 Ticket 信息（继承 requirement_id）────────────────────────
        parent = await db.fetch_one(
            "SELECT * FROM tickets WHERE id = ? AND project_id = ?",
            (parent_ticket_id, project_id),
        )
        if not parent:
            return ActionResult(success=False, error=f"父 Ticket 不存在: {parent_ticket_id}")

        requirement_id = parent["requirement_id"]

        # ── 创建子 Ticket ────────────────────────────────────────────────────
        now = now_iso()
        sub_ticket_id = generate_id("TK")

        from models import TicketStatus
        valid_statuses = {s.value for s in TicketStatus}
        if start_status not in valid_statuses:
            start_status = TicketStatus.PENDING.value

        await db.insert("tickets", {
            "id":               sub_ticket_id,
            "requirement_id":   requirement_id,
            "project_id":       project_id,
            "parent_ticket_id": parent_ticket_id,
            "title":            f"[子任务] {title}",
            "description":      description,
            "type":             "subtask",
            "module":           parent.get("module") or "other",
            "priority":         priority,
            "sort_order":       0,
            "status":           start_status,
            "assigned_agent":   None,
            "result":           None,
            "created_at":       now,
            "updated_at":       now,
        })

        # ── 父 Ticket 置为等待状态 ────────────────────────────────────────────
        prev_status = parent["status"]
        await db.update("tickets", {
            "status":     WAITING_SUBTASKS_STATUS,
            "updated_at": now,
        }, "id = ?", (parent_ticket_id,))

        # 写日志
        from utils import generate_id as _gid
        await db.insert("ticket_logs", {
            "id":             _gid("LOG"),
            "ticket_id":      parent_ticket_id,
            "project_id":     project_id,
            "requirement_id": requirement_id,
            "agent_type":     context.get("agent_type") or "Agent",
            "action":         "dispatch_subtask",
            "from_status":    prev_status,
            "to_status":      WAITING_SUBTASKS_STATUS,
            "detail":         json.dumps({
                "sub_ticket_id":  sub_ticket_id,
                "sub_title":      title,
                "start_status":   start_status,
            }, ensure_ascii=False),
            "level":          "info",
            "created_at":     now,
        })

        # SSE 通知
        try:
            from events import event_manager
            await event_manager.publish_to_project(project_id, "ticket_status_changed", {
                "ticket_id": parent_ticket_id,
                "from":      prev_status,
                "to":        WAITING_SUBTASKS_STATUS,
            })
        except Exception:
            pass

        logger.info(
            "📦 子任务已派发: 父=%s 子=%s「%s」起始状态=%s",
            parent_ticket_id[:12], sub_ticket_id[:12], title[:30], start_status,
        )

        return ActionResult(
            success=True,
            message=f"子任务「{title}」已创建（ID: {sub_ticket_id}），父任务进入等待状态",
            data={
                "sub_ticket_id":    sub_ticket_id,
                "parent_ticket_id": parent_ticket_id,
                "start_status":     start_status,
            },
        )
