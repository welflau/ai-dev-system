"""Agent 忙闲状态和工单「当前进度」字段。

`orch._agent_status` 记每个 Agent 是否在忙、在处理哪张工单，`get_agent_status` 给接口读。
tickets 表的 current_action 等四列驱动工单面板的「当前进度」区：分派动作前
`set_ticket_current_action` 写入，结束后 `clear_ticket_current_action` 清掉，中间的日志心跳由
`make_ticket_progress_callback` 生成的回调按关键字过滤、限频、去重后写库并推 SSE。

约定（`orchestration` 包里按职责拆出的模块都一样）：

- 函数体从 `TicketOrchestrator` 的同名方法原样搬来，函数名去掉了前导下划线。改动只有
  `self` 写成 `orch`，以及下面单独列出的几处。
- `TicketOrchestrator` 上保留同名方法，只做转发。这里的函数互相调用、调用别的模块里的
  逻辑都走 `orch.xxx`，测试给实例打的桩才会生效。
- `db` 由转发方法在调用时传入，这里不导入它。测试用
  `monkeypatch.setattr(orchestrator, "db", test_db)` 换库，函数必须拿到同一个对象。
- 状态都放在 `orch` 上，这个模块自己不存状态。
- 函数内的延迟导入保持原样，测试的打桩打在这些源模块上。
"""
import logging
from typing import Dict

from utils import now_iso

logger = logging.getLogger("orchestrator")


def get_agent_status(orch) -> Dict:
    """获取所有 Agent 的实时状态"""
    return {
        "agents": orch._agent_status,
        "processing_tickets": list(orch._processing),
        "processing_count": len(orch._processing),
    }


def set_agent_busy(orch, agent_name: str, ticket_id: str, ticket_title: str, action: str):
    """标记 Agent 为忙碌"""
    orch._agent_status[agent_name] = {
        **orch._agent_status.get(agent_name, {}),
        "status": "working",
        "ticket_id": ticket_id,
        "ticket_title": ticket_title,
        "action": action,
        "started_at": now_iso(),
    }


def set_agent_idle(orch, agent_name: str, success: bool = True):
    """标记 Agent 为空闲"""
    prev = orch._agent_status.get(agent_name, {})
    key = "completed_count" if success else "error_count"
    orch._agent_status[agent_name] = {
        **prev,
        "status": "idle",
        "ticket_id": None,
        "ticket_title": None,
        "action": None,
        "started_at": None,
        key: prev.get(key, 0) + 1,
    }


async def set_ticket_current_action(orch, db, ticket_id: str, action_label: str):
    """Action 开始：写 current_action + started_at，清空 latest_log"""
    if not ticket_id:
        return
    try:
        ts = now_iso()
        await db.update("tickets", {
            "current_action": action_label,
            "current_action_started_at": ts,
            "current_action_latest_log": None,
            "current_action_updated_at": ts,
            "updated_at": ts,
        }, "id = ?", (ticket_id,))
    except Exception as e:
        logger.debug("set_ticket_current_action 失败（忽略）: %s", e)


async def clear_ticket_current_action(orch, db, ticket_id: str):
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


def make_ticket_progress_callback(orch, db, project_id: str, ticket_id: str):
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
                "updated_at": ts,
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
