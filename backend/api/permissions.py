"""
权限审批 API 端点

GET  /api/permissions/pending          — 查询所有待审批请求
POST /api/permissions/{id}/resolve     — 批准或拒绝
GET  /api/permissions/history          — 最近 50 条审批记录（调试用）
"""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from database import db

logger = logging.getLogger("api.permissions")

router = APIRouter(prefix="/api/permissions", tags=["permissions"])


class ResolveRequest(BaseModel):
    approved: bool
    reason: Optional[str] = None   # 拒绝时可附原因（可选）


@router.get("/pending")
async def get_pending_permissions():
    """返回所有 status='pending' 的审批请求（含内存里正在等待的）"""
    rows = await db.fetch_all(
        "SELECT id, tool_name, tool_input_json, risk_label, "
        "       project_id, ticket_id, agent_type, status, created_at "
        "FROM permission_requests WHERE status='pending' "
        "ORDER BY created_at DESC"
    )
    return {"items": [dict(r) for r in rows]}


@router.post("/{request_id}/resolve")
async def resolve_permission(request_id: str, body: ResolveRequest):
    """批准或拒绝一个审批请求"""
    from permissions.gate import permission_gate
    from utils import now_iso

    # 检查请求是否存在
    row = await db.fetch_one(
        "SELECT id, status FROM permission_requests WHERE id=?", (request_id,)
    )
    if not row:
        raise HTTPException(status_code=404, detail="审批请求不存在")
    if row["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"该请求已处理（status={row['status']}）")

    # 通知协程
    found = permission_gate.resolve(request_id, body.approved)

    # 更新数据库状态
    status = "approved" if body.approved else "denied"
    await db.execute(
        "UPDATE permission_requests SET status=?, resolved_at=? WHERE id=?",
        (status, now_iso(), request_id),
    )

    action_str = "批准" if body.approved else "拒绝"
    logger.info("权限审批 %s: %s [%s]", action_str, request_id[:8], status)

    return {
        "success": True,
        "request_id": request_id,
        "approved": body.approved,
        "future_found": found,   # False 表示协程可能已超时
    }


@router.get("/history")
async def get_permission_history(limit: int = 50):
    """最近审批记录（供调试/审计查看）"""
    rows = await db.fetch_all(
        "SELECT id, tool_name, risk_label, project_id, ticket_id, "
        "       status, created_at, resolved_at "
        "FROM permission_requests "
        "ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    return {"items": [dict(r) for r in rows]}
