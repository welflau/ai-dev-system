"""派单门禁：同一张工单不能被 30s 轮询叠着派。

write_prd 漏了 in_progress 时，工单一直停在 pending，轮询当成新单，
界面上就只剩「调用模型」占位。claim 集合拦不住「已占槽又 create_task」这条路。
"""
from types import SimpleNamespace

from orchestrator import TicketOrchestrator


def _orch():
    o = TicketOrchestrator.__new__(TicketOrchestrator)
    o._processing = set()
    o._running_tasks = {}
    o._agent_status = {}
    o._project_active = {}
    o._project_subtask_active = {}
    o._MAX_CONCURRENT_PER_PROJECT = 1
    o._MAX_CONCURRENT_SUBTASKS = 3
    return o


def _capture_tasks(monkeypatch, bucket):
    def _create(coro):
        bucket.append(coro)
        try:
            coro.close()
        except Exception:
            pass
        return SimpleNamespace()
    monkeypatch.setattr("orchestrator.asyncio.create_task", _create)


def test_enqueue_skips_second_dispatch_on_same_ticket(monkeypatch):
    created = []
    _capture_tasks(monkeypatch, created)
    o = _orch()
    assert o._enqueue_ticket("proj", "TK-1", source="poll") is True
    assert o._enqueue_ticket("proj", "TK-1", source="poll") is False
    assert len(created) == 1


def test_enqueue_skips_when_process_ticket_already_claimed(monkeypatch):
    created = []
    _capture_tasks(monkeypatch, created)
    o = _orch()
    o._processing.add("TK-2")
    assert o._enqueue_ticket("proj", "TK-2", source="poll") is False
    assert created == []


def test_enqueue_skips_when_cli_still_running(monkeypatch):
    created = []
    _capture_tasks(monkeypatch, created)
    monkeypatch.setattr("llm_client.ticket_has_live_cli", lambda tid: tid == "TK-3")
    o = _orch()
    assert o._enqueue_ticket("proj", "TK-3", source="poll") is False
    assert created == []


def test_held_by_processing_is_not_zombie():
    o = _orch()
    o._processing.add("TK-live")
    assert o._ticket_held_by_this_process("TK-live") is True
    assert o._ticket_held_by_this_process("TK-other") is False


def test_held_by_project_slot_is_not_zombie():
    """enqueue 已占槽、process_ticket 还没 claim 时，也不能当僵尸打回。"""
    o = _orch()
    o._project_active["proj"] = {"TK-slot"}
    assert o._ticket_held_by_this_process("TK-slot") is True


def test_held_by_live_cli_is_not_zombie(monkeypatch):
    monkeypatch.setattr("llm_client.ticket_has_live_cli", lambda tid: tid == "TK-cli")
    o = _orch()
    assert o._ticket_held_by_this_process("TK-cli") is True
    assert o._ticket_held_by_this_process("TK-idle") is False


def test_held_by_running_task_even_if_processing_released():
    """实测：_processing 被外部 _release_ticket 清掉时，协程还在等模型。"""
    o = _orch()
    o._running_tasks["TK-run"] = SimpleNamespace(done=lambda: False)
    o._processing.clear()
    assert o._ticket_held_by_this_process("TK-run") is True
    o._running_tasks["TK-run"] = SimpleNamespace(done=lambda: True)
    assert o._ticket_held_by_this_process("TK-run") is False


def test_held_by_agent_working_status():
    o = _orch()
    o._agent_status["PlannerAgent"] = {
        "status": "working", "ticket_id": "TK-work", "action": "write_prd",
    }
    assert o._ticket_held_by_this_process("TK-work") is True
    assert o._ticket_held_by_this_process("TK-other") is False


def test_zombie_idle_threshold_is_not_sixty_seconds():
    import inspect
    src = inspect.getsource(TicketOrchestrator._poll_once)
    assert "age < 300" in src
    assert "age < 60" not in src


def test_poll_once_skips_held_tickets_before_zombie():
    """活 write_prd 等首包时 updated_at 可能 89s 不动，门禁必须先看占槽/CLI。"""
    import inspect
    src = inspect.getsource(TicketOrchestrator._poll_once)
    assert "_ticket_held_by_this_process" in src
    assert "本轮不再立刻派单" in src
    hb = inspect.getsource(TicketOrchestrator.process_ticket)
    assert "_ticket_heartbeat" in hb


def test_director_visual_in_progress_is_zombie_candidate():
    assert TicketOrchestrator._status_is_executing("director_visual_in_progress")
    assert TicketOrchestrator._status_is_executing("director_brief_in_progress")
    assert TicketOrchestrator._status_is_executing("planning_in_progress")
    assert TicketOrchestrator._status_is_executing("deploying")
    assert not TicketOrchestrator._status_is_executing("director_visual_ready")
    assert not TicketOrchestrator._status_is_executing("director_script_done")
    assert not TicketOrchestrator._status_is_executing("pending")


def test_poll_once_scans_dynamic_in_progress_statuses():
    """视频 SOP 的 *_in_progress 不在 trigger 集合里，必须靠 GLOB 扫到才能僵尸回收。"""
    import inspect
    src = inspect.getsource(TicketOrchestrator._poll_once)
    assert "GLOB '*_in_progress'" in src
    assert "_status_is_executing" in src
    assert "僵尸工单无法回退" in src
