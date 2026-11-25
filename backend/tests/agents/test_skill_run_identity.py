"""Skill 专属分支必须在最终 UPDATE 核对批次，尤其是连诊断一起落库的阻塞路径。"""
import json

import pytest

from .test_orchestrator_skill_branch import (
    SUCCESS_STATUS, TICKET_ID, _call_via_dispatcher, _logs, _run, skill_result,
)


@pytest.mark.parametrize("outcome,host", [
    ("waiting_human", "SkillAgent"),
    ("success", "DevAgent"),
    ("skipped", "PlannerAgent"),
    ("budget_exceeded", "SkillAgent"),
])
def test_redispatch_at_skill_write(tmp_path, monkeypatch, outcome, host):
    async def body(orch, db, events, dispatched):
        update = db.update
        await update("tickets", {"active_run_id": "A"}, "id = ?", (TICKET_ID,))
        writes = []

        async def redispatch_first(table, changes, where, params=()):
            if table == "tickets" and "result" in changes and not writes:
                # B 接单后的状态与 A 相同；在 A 的真实 SQL 执行前安排 B 赢得写入权。
                await update("tickets", {"active_run_id": "B", "result": "B 的进度",
                                         "diagnosis": "B 的诊断"}, "id = ?", (TICKET_ID,))
                writes.append(True)
            return await update(table, changes, where, params)
        monkeypatch.setattr(db, "update", redispatch_first)

        applied = await _call_via_dispatcher(orch, skill_result(outcome), agent_name=host, run_id="A")
        row = await db.fetch_one("SELECT status,result,diagnosis,active_run_id FROM tickets WHERE id=?",
                                 (TICKET_ID,))
        assert writes and row == {"status": "pending", "result": "B 的进度",
                                  "diagnosis": "B 的诊断", "active_run_id": "B"}
        assert applied is False
        comments = await db.fetch_all("SELECT id FROM ticket_comments WHERE ticket_id=?", (TICKET_ID,))
        assert await _logs(db) == comments == events == dispatched == []
        assert await _call_via_dispatcher(orch, skill_result("success"), agent_name=host, run_id="B")
        assert dispatched == [TICKET_ID]
    _run(body, tmp_path, monkeypatch)


def test_same_status_skill_result_applies_once(tmp_path, monkeypatch):
    async def body(orch, db, events, dispatched):
        await db.update("tickets", {"active_run_id": "A"}, "id = ?", (TICKET_ID,))
        first = skill_result("success", message="第一次")
        assert await _call_via_dispatcher(orch, first, run_id="A", current_status=SUCCESS_STATUS)
        duplicate = skill_result("success", message="重复")
        assert not await _call_via_dispatcher(orch, duplicate, run_id="A", current_status=SUCCESS_STATUS)
        row = await db.fetch_one("SELECT status,result,active_run_id FROM tickets WHERE id=?", (TICKET_ID,))
        assert (row["status"], json.loads(row["result"]), row["active_run_id"]) == (SUCCESS_STATUS, first, None)
        assert len(await _logs(db)) == 1
        assert len([event for event, _ in events if event == "ticket_status_changed"]) == 1
        assert dispatched == []
    _run(body, tmp_path, monkeypatch, initial_status=SUCCESS_STATUS)
