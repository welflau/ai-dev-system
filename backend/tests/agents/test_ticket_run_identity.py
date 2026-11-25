"""用真实派单/收尾和临时 SQLite 控制两次执行的回传顺序。"""
import asyncio
import json
import sqlite3

import pytest

from database import Database, SCHEMA_SQL
from orchestration.ticket_pipeline import TicketRun, assign_ticket, handle_result
from .test_orchestrator_process_ticket import PROJECT_ID, TICKET_ID, _run, _ticket


async def dispatch(env, label, next_status="building"):
    ticket = await _ticket(env)
    run = TicketRun(env.orch, env.db, PROJECT_ID, TICKET_ID, ticket=ticket,
                    current_status=ticket["status"], next_status=next_status,
                    agent_name="DevAgent", action="develop",
                    result={"status": "success", "message": label})
    assert await assign_ticket(run) is None
    return run


def real_results(env):
    del env.orch._handle_agent_result
    env.rules = {}

    async def git(pid, tid, rid, agent, action, result):
        env.calls["git"].append(result["message"])
    env.orch._handle_git_files = git


@pytest.mark.parametrize("timing", ["before-git", "during-git", "before-update", "error-update"])
def test_new_dispatch_owns_same_status(tmp_path, monkeypatch, timing):
    async def body(env):
        real_results(env)
        a = await dispatch(env, "A")
        b = None

        async def redispatch():
            nonlocal b
            await env.db.update("tickets", {"status": "pending", "result": "keep"},
                                "id = ?", (TICKET_ID,))
            b = await dispatch(env, "B")

        if timing == "before-git":
            await redispatch()
        elif timing == "during-git":
            async def git(*args):
                env.calls["git"].append(args[-1]["message"])
                if b is None:
                    await redispatch()
            env.orch._handle_git_files = git
        else:
            update = env.db.update

            async def concurrent_update(table, changes, where, params=()):
                if table == "tickets" and "result" in changes and changes["result"] != "keep" and b is None:
                    await redispatch()
                return await update(table, changes, where, params)
            monkeypatch.setattr(env.db, "update", concurrent_update)
            if timing == "error-update":
                a.result["status"] = "error"

        assert await handle_result(a) == "stale_result"
        row = await _ticket(env)
        assert (row["status"], row["result"]) == ("building", "keep")
        assert env.calls["git"] == ([] if timing in ("before-git", "error-update") else ["A"])
        assert env.calls["cp_boundary"] == env.calls["diagnose"] == []
        assert await handle_result(b) is None
        assert json.loads((await _ticket(env))["result"])["message"] == "B"
        assert len(env.calls["cp_boundary"]) == 1
    _run(body, tmp_path, monkeypatch)


def test_legacy_ticket_survives_migration_and_restart(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.execute("ALTER TABLE tickets DROP COLUMN active_run_id")
        conn.executescript("""
            INSERT INTO projects (id,name,created_at,updated_at) VALUES ('p','project','t','t');
            INSERT INTO requirements (id,project_id,title,description,created_at,updated_at)
            VALUES ('r','p','req','','t','t');
            INSERT INTO tickets (id,requirement_id,project_id,title,status,result,created_at,updated_at)
            VALUES ('x','r','p','ticket','building','saved','t','t');
        """)
    conn.close()

    async def boot(restart):
        db = Database(str(path))
        await db.connect()
        try:
            await db.init_tables()
            row = await db.fetch_one("SELECT status,result,active_run_id FROM tickets WHERE id='x'")
            assert row == {"status": "building", "result": "saved", "active_run_id": "A" if restart else None}
            if restart:
                await db.update("tickets", {"status": "pending"}, "id = ?", ("x",))
                row = await db.fetch_one("SELECT active_run_id FROM tickets WHERE id='x'")
                assert row["active_run_id"] is None
            else:
                await db.update("tickets", {"active_run_id": "A"}, "id = ?", ("x",))
        finally:
            await db.disconnect()

    asyncio.run(boot(False))
    asyncio.run(boot(True))


@pytest.mark.parametrize("intervention", ["round-trip", "metadata", "same-status-replay", "no-run-id"])
def test_sop_without_intermediate_status(tmp_path, monkeypatch, intervention):
    async def body(env):
        real_results(env)
        # SOP 无中间态，派单后保持 pending。
        a = await dispatch(env, "A", next_status=None)
        if intervention == "round-trip":
            for status in ("manual_review", "pending"):
                await env.db.update("tickets", {"status": status}, "id = ?", (TICKET_ID,))
            assert await handle_result(a) == "stale_result"
            assert env.calls["git"] == env.calls["cp_boundary"] == []
        elif intervention == "metadata":
            await env.db.update("tickets", {"status": "pending", "description": "edited",
                                            "updated_at": "new"}, "id = ?", (TICKET_ID,))
            assert await handle_result(a) is None
            assert (await _ticket(env))["status"] == "development_done"
        elif intervention == "same-status-replay":
            async def stages(*args):
                return [{"action": "develop", "closeout": "status", "success_status": "pending"}]
            env.orch._sop_stages_for = stages
            b = await dispatch(env, "B", next_status=None)
            assert await handle_result(b) is None
            assert await handle_result(a) == "stale_result"
            assert await handle_result(b) == "stale_result"
            assert json.loads((await _ticket(env))["result"])["message"] == "B"
            assert env.calls["git"] == ["B"]
            assert len(env.calls["cp_boundary"]) == 1
        else:
            assert not await env.orch._handle_agent_result(
                PROJECT_ID, TICKET_ID, a.ticket, a.agent_name, a.action, a.result)
            assert env.calls["git"] == []
            assert await handle_result(a) is None
    _run(body, tmp_path, monkeypatch)


@pytest.mark.parametrize("during_hook", [False, True], ids=["before-hook", "during-hook"])
def test_redispatch_invalidates_fragment_hook(tmp_path, monkeypatch, during_hook):
    async def body(env):
        real_results(env)
        a = await dispatch(env, "A")
        a.result["status"] = "failed"

        async def stages(*args):
            return [{"id": "build", "action": "develop", "closeout": "status",
                     "trigger_on": "pending", "on_failure": "rewind"}]

        async def hook(name, ctx):
            env.calls["hook"].append(name)
            await dispatch(env, "B")
            return {"rewind_to_stage": "build"}

        async def git(*args):
            if not during_hook:
                await dispatch(env, "B")
        env.orch._sop_stages_for = stages
        env.orch._invoke_stage_hook = hook
        env.orch._handle_git_files = git
        assert await handle_result(a) == "stale_result"
        assert env.calls["hook"] == (["rewind"] if during_hook else [])
        assert (await _ticket(env))["status"] == "building"
        assert env.calls["cp_boundary"] == []
    _run(body, tmp_path, monkeypatch)
