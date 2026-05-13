"""
PermissionGate — 高风险操作的异步人工审批通道

流程：
  1. gate.check(tool_name, tool_input, context) 检测是否高风险
  2. 高风险 → 写 permission_requests 表 + 推送 SSE 通知前端
  3. 协程挂起，等待 future.set_result()（approve/deny）或超时
  4. approve → 正常继续；deny/timeout → 抛 PermissionDeniedError
"""
import asyncio
import logging
import re
import uuid
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("permissions.gate")

# 审批超时秒数（5 分钟）
APPROVAL_TIMEOUT_SECONDS = 300


class PermissionDeniedError(RuntimeError):
    """用户拒绝或审批超时时抛出"""


# ── 高风险规则定义 ─────────────────────────────────────────────────
# (tool_name, pattern, risk_label)
#   tool_name : Action 的 name 属性，支持 * 通配（匹配所有工具）
#   pattern   : 对 tool_input 的 JSON 化字符串做 re.search；None 表示工具本身即高风险
#   risk_label: 展示给用户的风险说明
_HIGH_RISK_RULES: list[Tuple[str, Optional[re.Pattern], str]] = [
    # Shell 危险命令
    ("shell", re.compile(r'\brm\s+-[rRfF]', re.I),             "删除文件（rm -rf）"),
    ("shell", re.compile(r'git\s+push\s+.*--force', re.I),     "强制推送（git push --force）"),
    ("shell", re.compile(r'DROP\s+TABLE|DROP\s+DATABASE', re.I), "删除数据库表"),
    ("shell", re.compile(r'\bformat\s+[a-zA-Z]:', re.I),       "磁盘格式化"),
    ("shell", re.compile(r'\b(shutdown|reboot|halt|poweroff)\b', re.I), "关机/重启"),
    # Git Merge 合入主干
    ("git_merge", re.compile(r'\b(main|master)\b', re.I),      "合入主干分支"),
]


def _build_input_str(tool_name: str, tool_input: dict) -> str:
    """把 tool_input 转成便于正则匹配的字符串"""
    import json
    try:
        return json.dumps(tool_input, ensure_ascii=False)
    except Exception:
        return str(tool_input)


def detect_risk(tool_name: str, tool_input: dict) -> Optional[str]:
    """
    检测是否高风险。
    返回风险说明字符串（非空 = 高风险）；返回 None 表示低风险，直接放行。
    """
    input_str = _build_input_str(tool_name, tool_input)
    for rule_tool, pattern, label in _HIGH_RISK_RULES:
        if rule_tool != tool_name:
            continue
        if pattern is None or pattern.search(input_str):
            return label
    return None


class PermissionGate:
    """
    全局单例。维护 pending_futures：{request_id -> asyncio.Future}
    """

    def __init__(self):
        # request_id -> asyncio.Future[bool]  (True=approve, False=deny)
        self._pending: Dict[str, asyncio.Future] = {}

    async def check(
        self,
        tool_name: str,
        tool_input: dict,
        context: dict,
    ) -> None:
        """
        检测工具是否高风险。
        低风险：直接返回（None）。
        高风险：挂起协程，等待用户审批或超时，拒绝时抛 PermissionDeniedError。
        """
        risk_label = detect_risk(tool_name, tool_input)
        if risk_label is None:
            return  # 低风险，直接放行

        project_id = context.get("project_id")
        ticket_id  = context.get("ticket_id")
        agent_type = context.get("agent_type")

        request_id = str(uuid.uuid4())
        logger.warning(
            "🔒 高风险操作需要审批 [%s]: tool=%s risk=%s project=%s ticket=%s",
            request_id[:8], tool_name, risk_label, project_id, ticket_id,
        )

        # 1. 写 permission_requests 表
        await self._persist_request(
            request_id, tool_name, tool_input, risk_label,
            project_id, ticket_id, agent_type,
        )

        # 2. 推 SSE 通知前端（publish_global + 项目频道）
        await self._notify_frontend(request_id, tool_name, risk_label, project_id)

        # 3. 挂起协程等待审批
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[request_id] = future

        try:
            approved = await asyncio.wait_for(
                asyncio.shield(future),
                timeout=APPROVAL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            approved = False
            logger.warning("🔒 审批超时，自动拒绝 [%s]", request_id[:8])
            await self._update_status(request_id, "timeout")
        finally:
            self._pending.pop(request_id, None)

        if not approved:
            raise PermissionDeniedError(
                f"高风险操作被拒绝：{risk_label}（工具：{tool_name}）"
            )

    def resolve(self, request_id: str, approved: bool) -> bool:
        """
        前端调用审批结果（通过 API 端点回调此方法）。
        返回 True 表示找到了 pending future，False 表示请求不存在（可能已超时）。
        """
        future = self._pending.get(request_id)
        if future is None or future.done():
            return False
        future.set_result(approved)
        return True

    # ── 内部辅助方法 ───────────────────────────────────────────────

    async def _persist_request(
        self,
        request_id: str,
        tool_name: str,
        tool_input: dict,
        risk_label: str,
        project_id: Optional[str],
        ticket_id: Optional[str],
        agent_type: Optional[str],
    ) -> None:
        import json
        from utils import now_iso
        try:
            from database import db
            await db.execute(
                "INSERT INTO permission_requests "
                "(id, tool_name, tool_input_json, risk_label, "
                " project_id, ticket_id, agent_type, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                (
                    request_id,
                    tool_name,
                    json.dumps(tool_input, ensure_ascii=False),
                    risk_label,
                    project_id,
                    ticket_id,
                    agent_type,
                    now_iso(),
                ),
            )
        except Exception as e:
            logger.warning("permission_gate 写库失败: %s", e)

    async def _update_status(self, request_id: str, status: str) -> None:
        from utils import now_iso
        try:
            from database import db
            await db.execute(
                "UPDATE permission_requests SET status=?, resolved_at=? WHERE id=?",
                (status, now_iso(), request_id),
            )
        except Exception as e:
            logger.warning("permission_gate 更新状态失败: %s", e)

    async def _notify_frontend(
        self,
        request_id: str,
        tool_name: str,
        risk_label: str,
        project_id: Optional[str],
    ) -> None:
        payload = {
            "request_id": request_id,
            "tool_name": tool_name,
            "risk_label": risk_label,
        }
        try:
            from events import event_manager
            # 全局频道 + 项目频道，确保前端能收到
            await event_manager.publish("global", "permission_request", payload)
            if project_id:
                await event_manager.publish_to_project(project_id, "permission_request", payload)
        except Exception as e:
            logger.warning("permission_gate 推 SSE 失败: %s", e)

    async def mark_resolved(self, request_id: str, approved: bool) -> None:
        """resolve() 后调用，更新数据库状态"""
        status = "approved" if approved else "denied"
        await self._update_status(request_id, status)


# 全局单例
permission_gate = PermissionGate()
