"""工单停止必须杀掉登记中的 CLI 子进程，不能只改 tickets.status。"""
import asyncio

import llm_client as lc


class _FakeProc:
    def __init__(self):
        self.pid = 424242
        self.returncode = None
        self.killed = False

    def kill(self):
        self.killed = True
        self.returncode = -9


def setup_function():
    lc._LIVE_CLI_PROCS.clear()
    lc._ABORTED_TICKETS.clear()
    lc._ABORT_EVENTS.clear()
    lc._llm_ctx.ticket_id = None


def teardown_function():
    lc._LIVE_CLI_PROCS.clear()
    lc._ABORTED_TICKETS.clear()
    lc._ABORT_EVENTS.clear()
    lc._llm_ctx.ticket_id = None


def test_abort_ticket_cli_kills_registered(monkeypatch):
    killed = []

    async def fake_kill(proc):
        killed.append(proc)
        proc.returncode = -9

    monkeypatch.setattr(lc, "_kill_cli_proc_tree", fake_kill)
    lc._llm_ctx.ticket_id = "TK-stop-1"
    proc = _FakeProc()
    lc.register_cli_proc(proc)
    assert "TK-stop-1" in lc._LIVE_CLI_PROCS

    n = asyncio.run(lc.abort_ticket_cli("TK-stop-1"))
    assert n == 1
    assert killed == [proc]
    assert "TK-stop-1" not in lc._LIVE_CLI_PROCS
    assert lc.ticket_cli_was_aborted("TK-stop-1")


def test_clear_ticket_cli_abort_allows_next_run():
    lc._ABORTED_TICKETS.add("TK-stop-2")
    lc.clear_ticket_cli_abort("TK-stop-2")
    assert not lc.ticket_cli_was_aborted("TK-stop-2")


def test_await_cancelled_does_not_kill_parent():
    """首包到达时会 cancel 旁路 abort waiter；CancelledError 不能漏到工单协程。"""

    async def parent():
        blocker = asyncio.Event()
        waiter = asyncio.create_task(blocker.wait())
        await asyncio.sleep(0)
        await lc._await_cancelled(waiter)
        return "ok"

    assert asyncio.run(parent()) == "ok"
