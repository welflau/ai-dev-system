"""工单的后台诊断：收集上下文，生成诊断，写回 `tickets.diagnosis` 并发事件。

工单转 blocked 后自动触发，也可以由诊断 API 手动触发，后者不限工单状态。

`diagnose_blocked_ticket` 是后台任务，整个函数体包在 `try/except` 里，任何异常只打日志，不往外抛。
它按顺序做这些事：

- 读 `projects.traits`、`ticket_logs` 最近 10 条、`artifacts` 最近 20 条的路径。
- 用 `sop.loader.compose_sop` 找出 `action` 和 `agent` 都匹配的第一个阶段。
- 把工单的 `result` 解析成字典，取出 `skill_id` 和 `skill_status`。
- 经 `runtime_facade.actions_diagnose_ticket()` 取诊断模块。`_is_timeout_block` 为真时调
  `synthesize_blocked_diagnosis` 合成诊断，否则跑一次 `DiagnoseTicketAction`。
- 把诊断写进 `tickets.diagnosis`，经 `orch._log` 记一条 `diagnose` 日志，再发 `ticket_diagnosed` 事件。

函数内的 `import json as _json`、`from sop.loader import compose_sop`、`import runtime_facade` 都保留，
诊断模块仍在调用时才解析。

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
from typing import Any, Dict, List

from events import event_manager
from utils import now_iso

logger = logging.getLogger("orchestrator")


async def diagnose_blocked_ticket(
    orch, db,
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

        import runtime_facade
        diag_mod = runtime_facade.actions_diagnose_ticket()
        if diag_mod._is_timeout_block(skill_status, error_msg):
            diagnosis = diag_mod.synthesize_blocked_diagnosis(
                skill_id=skill_id,
                skill_status=skill_status,
                error_msg=error_msg,
                action=action,
                outputs=parsed_result.get("outputs") or [],
                artifacts=parsed_result.get("artifacts") or [],
                extra_files=extra_files,
            )
        else:
            action_obj = diag_mod.DiagnoseTicketAction()
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
        await orch._log(
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
