"""
AI 自动开发系统 - 工单验证接口
"""
import logging
from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import db
from models import TicketStatus
from utils import generate_id, now_iso
from events import event_manager

logger = logging.getLogger(__name__)

router = APIRouter()


# ==================== 数据模型 ====================

class TicketVerification(BaseModel):
    """工单验证请求"""
    approved: bool          # 是否通过
    verified_by: str        # 验证人
    notes: Optional[str] = None  # 验证备注


# ==================== 工单验证 API ====================

@router.get("/tickets/{ticket_id}/verification")
async def get_ticket_verification(ticket_id: str):
    """
    获取工单验证信息

    返回当前验证状态、验证历史等
    """
    ticket = await db.fetch_one(f"SELECT * FROM tickets WHERE id = ?", (ticket_id,))
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")

    # 获取验证历史
    history = await db.fetch_all("""
        SELECT * FROM ticket_logs
        WHERE ticket_id = ? AND log_action IN ('verification_approved', 'verification_rejected')
        ORDER BY created_at DESC
    """, (ticket_id,))

    return {
        "ticket_id": ticket_id,
        "verification_status": ticket.get("verification_status", "pending"),
        "current_status": ticket["status"],
        "verified_by": ticket.get("verified_by"),
        "verification_date": ticket.get("verification_date"),
        "verification_notes": ticket.get("verification_notes"),
        "history": history
    }


@router.post("/tickets/{ticket_id}/verify")
async def verify_ticket(ticket_id: str, verification: TicketVerification):
    """
    提交工单验证结果

    参数:
    - approved: 是否通过验证
    - verified_by: 验证人姓名/ID
    - notes: 验证备注（可选）
    """
    # 获取工单信息
    ticket = await db.fetch_one(f"SELECT * FROM tickets WHERE id = ?", (ticket_id,))
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")

    current_status = TicketStatus(ticket["status"])
    verification_status = ticket.get("verification_status", "pending")

    # 检查工单状态是否允许验证
    if verification_status == "pending":
        raise HTTPException(status_code=400, detail="工单当前无需验证")

    # 记录验证操作到日志表
    log_action = "verification_approved" if verification.approved else "verification_rejected"
    await db.insert("ticket_logs", {
        "id": generate_id(),
        "ticket_id": ticket_id,
        "log_action": log_action,
        "content": f"验证结果: {'通过' if verification.approved else '不通过'}",
        "operator": verification.verified_by,
        "created_at": now_iso()
    })

    # 更新工单验证状态
    if verification.approved:
        # 验证通过：更新验证状态为 approved
        await db.update(
            "tickets",
            {
                "verification_status": "approved",
                "verified_by": verification.verified_by,
                "verification_date": now_iso(),
                "verification_notes": verification.notes,
                "updated_at": now_iso()
            },
            f"id = '{ticket_id}'"
        )
        
        # 根据当前状态决定下一状态
        next_status = _get_next_status_after_approval(current_status)
        if next_status:
            await db.update(
                "tickets",
                {"status": next_status.value, "updated_at": now_iso()},
                f"id = '{ticket_id}'"
            )
            logger.info(f"工单 {ticket_id} 验证通过，状态变更为 {next_status.value}")
            
            # 发送事件通知
            await event_manager.publish_event("ticket_verified", {
                "ticket_id": ticket_id,
                "approved": True,
                "new_status": next_status.value,
                "verified_by": verification.verified_by
            })
    else:
        # 验证不通过：更新验证状态为 rejected
        await db.update(
            "tickets",
            {
                "verification_status": "rejected",
                "verified_by": verification.verified_by,
                "verification_date": now_iso(),
                "verification_notes": verification.notes,
                "updated_at": now_iso()
            },
            f"id = '{ticket_id}'"
        )
        
        # 根据当前状态决定回退状态
        rollback_status = _get_rollback_status_after_rejection(current_status)
        if rollback_status:
            await db.update(
                "tickets",
                {"status": rollback_status.value, "updated_at": now_iso()},
                f"id = '{ticket_id}'"
            )
            logger.info(f"工单 {ticket_id} 验证不通过，状态回退到 {rollback_status.value}")
            
            # 发送事件通知
            await event_manager.publish_event("ticket_verified", {
                "ticket_id": ticket_id,
                "approved": False,
                "new_status": rollback_status.value,
                "verified_by": verification.verified_by,
                "reason": verification.notes
            })
    
    return {
        "status": "success",
        "ticket_id": ticket_id,
        "approved": verification.approved,
        "new_status": ticket["status"]
    }


@router.get("/tickets/pending-verification")
async def get_pending_verification_tickets(project_id: str):
    """
    获取待验证工单列表
    """
    tickets = await db.fetch_all("""
        SELECT t.*, r.title as requirement_title
        FROM tickets t
        LEFT JOIN requirements r ON t.requirement_id = r.id
        WHERE t.project_id = ? 
        AND t.verification_status != 'pending'
        AND t.verification_status IS NOT NULL
        AND (t.verification_status != 'approved' 
             OR (t.verification_status = 'approved' AND t.updated_at > datetime('now', '-1 hour')))
        ORDER BY t.created_at ASC
    """, (project_id,))

    return {
        "tickets": tickets,
        "total": len(tickets)
    }


# ==================== 辅助函数 ====================

def _get_next_status_after_approval(current_status: TicketStatus) -> Optional[TicketStatus]:
    """根据当前状态获取验证通过后的下一状态"""
    status_map = {
        # 开发完成 → 验证通过 → 代码审查中
        TicketStatus.DEVELOPMENT_DONE: TicketStatus.REVIEW_IN_PROGRESS,
        # 代码审查中 → 验证通过 → 测试中
        TicketStatus.REVIEW_IN_PROGRESS: TicketStatus.TESTING_IN_PROGRESS,
        # 测试完成 → 验证通过 → 验收中
        TicketStatus.TESTING_DONE: TicketStatus.ACCEPTANCE_IN_PROGRESS,
        # 验收中 → 验证通过 → 部署中
        TicketStatus.ACCEPTANCE_IN_PROGRESS: TicketStatus.DEPLOYING,
        # 部署完成 → 验证通过 → 已完成
        TicketStatus.DEPLOY_DONE: TicketStatus.COMPLETED,
    }
    return status_map.get(current_status)


def _get_rollback_status_after_rejection(current_status: TicketStatus) -> Optional[TicketStatus]:
    """根据当前状态获取验证不通过后的回退状态"""
    status_map = {
        # 开发完成 → 验证不通过 → 开发中
        TicketStatus.DEVELOPMENT_DONE: TicketStatus.DEVELOPMENT_IN_PROGRESS,
        # 代码审查中 → 验证不通过 → 开发中
        TicketStatus.REVIEW_IN_PROGRESS: TicketStatus.DEVELOPMENT_IN_PROGRESS,
        # 测试完成 → 验证不通过 → 测试中
        TicketStatus.TESTING_DONE: TicketStatus.TESTING_IN_PROGRESS,
        # 验收中 → 验证不通过 → 开发中
        TicketStatus.ACCEPTANCE_IN_PROGRESS: TicketStatus.DEVELOPMENT_IN_PROGRESS,
    }
    return status_map.get(current_status)
