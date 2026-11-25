"""`process_ticket` 的特征测试。

特征测试只记录**现在的行为**，不评判对错。它是把 `process_ticket` 拆成
分步管线的安全网（方案文档：docs/20261124_01_代码重构方案.md，R0 第 3 步、
R2 第 2 步）。搬移之后这里任何一条变红，都说明搬运改了行为。

`process_ticket` 的出口很多，每一类都要钉住三件事：

1. 工单最后停在什么状态、写了哪些 `ticket_logs`、发了哪些 SSE；
2. Agent 有没有被执行；
3. 处理权有没有释放（`_processing` 和 `_running_tasks`）。

夹具沿用 `test_orchestrator_result_branches.py` 的做法：真实 SQLite，
`TicketOrchestrator.__new__` 造实例。止损计数、依赖检查、状态改写、日志、
Agent 忙闲标记都真跑；规则表、上下文构建、结果处理、Git、检查点打桩。
"""
import asyncio
import inspect
import json
from collections import defaultdict
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

import database as database_module
import llm_client as llm_module
import orchestrator as orch_module
from database import Database
from orchestration import ticket_pipeline
from orchestrator import TicketOrchestrator

PROJECT_ID = "P-PT"
REQ_ID = "REQ-20261124-pt0001"
TICKET_ID = "TK-20261124-pt0001"
DEP_ID = "TK-20261124-pt0002"
TITLE = "冲刺组件"
TS = "2026-11-24T00:00:00Z"

HARD_TERMINAL = ["blocked", "cancelled", "testing_done", "deployed", "done", "completed"]
IN_PROGRESS = "development_in_progress"


def _rule(**kw):
    rule = {"agent": "DevAgent", "action": "develop", "next_status": IN_PROGRESS}
    rule.update(kw)
    return rule


def _llm_ctx():
    c = llm_module._llm_ctx
    return (c.ticket_id, c.requirement_id, c.project_id, c.agent_type, c.action)


class _FakeAgent:
    """记录被调用时的现场：库里的工单、LLM 上下文、忙闲标记、处理权。"""

    def __init__(self, env, name):
        self.env, self.name = env, name

    async def execute(self, action, context):
        env = self.env
        await env.real_sleep(0)         # 让出一次事件循环，心跳任务得以启动
        row = await env.db.fetch_one("SELECT * FROM tickets WHERE id = ?", (TICKET_ID,))
        env.calls["execute"].append({
            "executor": self.name, "action": action, "context": dict(context),
            "row": dict(row), "llm": _llm_ctx(),
            "agent_status": dict(env.orch._agent_status),
            "claimed": TICKET_ID in env.orch._processing,
            "running": TICKET_ID in env.orch._running_tasks,
        })
        if env.agent_error is not None:
            raise env.agent_error
        return env.agent_result


@asynccontextmanager
async def _env(tmp_path, monkeypatch, *, status="pending", ticket_extra=None):
    db_file = tmp_path / "pt.db"

    original_db = database_module.db
    test_db = Database(db_path=str(db_file))
    await test_db.connect()
    await test_db.init_tables()          # 建表 + 迁移，缺一不可
    database_module.db = test_db
    monkeypatch.setattr(orch_module, "db", test_db, raising=False)

    await test_db.insert("projects", {
        "id": PROJECT_ID, "name": "pt", "traits": "[]",
        "created_at": TS, "updated_at": TS,
    })
    await test_db.insert("requirements", {
        "id": REQ_ID, "project_id": PROJECT_ID, "title": "需求",
        "description": "描述", "created_at": TS, "updated_at": TS,
    })
    ticket = {
        "id": TICKET_ID, "project_id": PROJECT_ID, "requirement_id": REQ_ID,
        "title": TITLE, "description": "实现角色冲刺的体力消耗逻辑",
        "type": "feature", "module": "backend", "status": status,
        "created_at": TS, "updated_at": TS,
    }
    ticket.update(ticket_extra or {})
    await test_db.insert("tickets", ticket)

    env = SimpleNamespace(
        db=test_db, sse=[], calls=defaultdict(list), real_sleep=asyncio.sleep,
        rules={"pending": _rule()},     # `_get_rules_for_project` 的返回值
        rules_error=None,               # 非空时 `_get_rules_for_project` 抛它
        repaired=None,                  # `_repair_status_outside_sop` 的返回值
        stages={},                      # action -> SOP stage
        stage_error=None,               # 非空时 `_sop_stage_for` 抛它
        agent_result={"status": "success", "files": {"a.py": "x"}},
        agent_error=None,               # 非空时 Agent.execute 抛它
        result_status="development_done",   # `_handle_agent_result` 替身写回的状态
        forward_jump=False,             # `_is_forward_jump` 的返回值
        live_cli=False,                 # `ticket_has_live_cli` 的返回值
        git=SimpleNamespace(exists=False, current="main", switch_ok=True,
                            after_fail="main", error=None),
        fts_error=None, fl_error=None,
    )

    # ---- 模块级依赖 ----
    async def fake_publish(pid, event, payload):
        env.sse.append((event, payload))
    monkeypatch.setattr(orch_module.event_manager, "publish_to_project", fake_publish)

    # 函数内 `from llm_client import ...`，调用时才取属性，所以打在源模块上。
    monkeypatch.setattr(llm_module, "ticket_has_live_cli", lambda tid: env.live_cli)
    monkeypatch.setattr(llm_module, "clear_ticket_cli_abort",
                        lambda tid: env.calls["cli_abort"].append(tid))

    import capability_check as cap_module

    async def fake_repo_path(pid):
        return ""
    monkeypatch.setattr(cap_module, "_get_repo_path", fake_repo_path)

    from checkpoint.service import checkpoint_service

    async def fake_ticket_start(pid, tid, *a, **kw):
        env.calls["cp_start"].append((pid, tid))
    monkeypatch.setattr(checkpoint_service, "ensure_ticket_start", fake_ticket_start)

    async def fake_phase_boundary(pid, tid, **kw):
        env.calls["cp_boundary"].append(kw)
    monkeypatch.setattr(checkpoint_service, "create_phase_boundary", fake_phase_boundary)

    gm = orch_module.git_manager
    monkeypatch.setattr(gm, "repo_exists", lambda pid: env.git.exists)

    async def fake_current_branch(pid):
        if env.git.error is not None:
            raise env.git.error
        if env.calls["git_switch"] and not env.git.switch_ok:
            return env.git.after_fail
        return env.git.current
    monkeypatch.setattr(gm, "get_current_branch", fake_current_branch)

    async def fake_switch_branch(pid, branch):
        env.calls["git_switch"].append(branch)
        return env.git.switch_ok
    monkeypatch.setattr(gm, "switch_branch", fake_switch_branch)

    import api.knowledge as knowledge_module

    async def fake_fts(tid, pid, text):
        if env.fts_error is not None:
            raise env.fts_error
        env.calls["fts"].append((tid, pid, text))
    monkeypatch.setattr(knowledge_module, "_upsert_tickets_fts", fake_fts)

    import failure_library as fl_module

    async def fake_fl_record(**kw):
        if env.fl_error is not None:
            raise env.fl_error
        env.calls["fl_record"].append(kw)
    monkeypatch.setattr(fl_module.failure_library, "record", fake_fl_record)

    # `_log` 会把日志镜像到 backend/logs/session_<req>/，测试不该往仓库里写文件。
    import session_logger as sl_module

    async def no_transcript(*a, **kw):
        return None
    monkeypatch.setattr(sl_module.session_logger, "log_event", no_transcript)

    # 派单前固定 sleep 1s，换成只让出一次事件循环。
    async def fast_sleep(delay, *a, **kw):
        await env.real_sleep(0)
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    # ---- orchestrator 实例：绕过 __init__（它会实例化全部 Agent 并连事件总线）----
    orch = TicketOrchestrator.__new__(TicketOrchestrator)
    orch._HARD_TERMINAL = set(HARD_TERMINAL)
    orch._processing = set()
    orch._running_tasks = {}
    orch._pending_restart = {}
    orch._agent_status = {}
    orch.agents = {name: _FakeAgent(env, name)
                   for name in ("DevAgent", "UXAgent", "SkillAgent")}

    async def fake_rules(pid, traits_json=None, ticket_type=None):
        env.calls["rules"].append(ticket_type)
        if env.rules_error is not None:
            raise env.rules_error
        return env.rules
    orch._get_rules_for_project = fake_rules

    async def fake_repair(pid, ticket, current_status):
        env.calls["repair"].append(current_status)
        return env.repaired
    orch._repair_status_outside_sop = fake_repair

    async def fake_stage(pid, action, ticket_type=None):
        if env.stage_error is not None:
            raise env.stage_error
        return env.stages.get(action)
    orch._sop_stage_for = fake_stage

    async def fake_ready(pid, tid):
        env.calls["ready"].append({"ticket": tid, "claimed": tid in orch._processing})
    orch._publish_ticket_ready = fake_ready

    async def fake_build_context(ticket, agent_name=""):
        return {"ticket_id": ticket["id"], "built_for": agent_name}
    orch._build_context = fake_build_context

    async def fake_thought(pid, rid, tid, agent_name, action, phase, **kw):
        env.calls["thought"].append(phase)
    orch._log_agent_thought = fake_thought

    async def fake_heartbeat(tid, interval=20.0):
        env.calls["hb"].append("start")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            env.calls["hb"].append("cancel")
            raise
    orch._ticket_heartbeat = fake_heartbeat

    async def fake_handle_result(pid, tid, ticket, agent_name, action, result, *, assigned_status, run_id):
        env.calls["result"].append({
            "ticket_status": ticket["status"], "agent": agent_name,
            "action": action, "result": result,
        })
        if env.result_status:
            await test_db.update("tickets", {"status": env.result_status},
                                 "id = ?", (tid,))
        return True
    orch._handle_agent_result = fake_handle_result

    async def fake_forward_jump(pid, cur, target, ticket_type=None):
        return env.forward_jump
    orch._is_forward_jump = fake_forward_jump

    async def fake_rewind(tid, pid, cur, target, reason):
        env.calls["rewind"].append({
            "from": cur, "to": target, "reason": reason,
            "claimed": tid in orch._processing,
        })
    orch._apply_status_rewind = fake_rewind

    async def fake_diagnose(**kw):
        env.calls["diagnose"].append(kw)
    orch._diagnose_blocked_ticket = fake_diagnose

    env.orch = orch
    try:
        yield env
    finally:
        database_module.db = original_db
        await test_db.disconnect()


def _run(body, tmp_path, monkeypatch, **kw):
    async def main():
        async with _env(tmp_path, monkeypatch, **kw) as env:
            return await body(env)
    return asyncio.run(main())


async def _process(env, ticket_id=TICKET_ID):
    await env.orch.process_ticket(PROJECT_ID, ticket_id)
    await asyncio.sleep(0)      # 让 create_task 起的后台任务跑完
    await asyncio.sleep(0)


async def _ticket(env) -> dict:
    return await env.db.fetch_one("SELECT * FROM tickets WHERE id = ?", (TICKET_ID,))


async def _logs(env, action=None) -> list:
    rows = await env.db.fetch_all(
        "SELECT agent_type, action, level, from_status, to_status, detail "
        "FROM ticket_logs WHERE ticket_id = ? ORDER BY rowid", (TICKET_ID,)
    )
    logs = [dict(r, detail=json.loads(r["detail"])) for r in rows]
    return [x for x in logs if action is None or x["action"] == action]


def _sse(env, *events) -> list:
    """按事件名取 SSE 负载。`_log` 每写一条都会发 `log_added`，默认滤掉。"""
    return [(e, p) for e, p in env.sse
            if (e in events if events else e != "log_added")]


async def _seed_reject(env, reason, to_status="development_failed"):
    await env.orch._log(
        PROJECT_ID, REQ_ID, TICKET_ID, "DevAgent", "reject",
        IN_PROGRESS, to_status, "打回", "warning",
        detail_data={"reason": reason} if reason else None,
    )
    env.sse.clear()


def _assert_released(env):
    assert TICKET_ID not in env.orch._processing
    assert TICKET_ID not in env.orch._running_tasks


async def _assert_not_dispatched(env, status):
    """没有派单：Agent 没执行，状态停在 `status`，处理权已释放。"""
    assert env.calls["execute"] == []
    assert env.calls["result"] == []
    assert (await _ticket(env))["status"] == status
    _assert_released(env)


def _assert_dispatched(env, executor="DevAgent", action="develop"):
    assert [(c["executor"], c["action"]) for c in env.calls["execute"]] == [(executor, action)]
    assert len(env.calls["result"]) == 1
    _assert_released(env)
    return env.calls["execute"][0]


# =====================================================================
# 一、入口门闩
# =====================================================================

def test_already_claimed_ticket_is_skipped(tmp_path, monkeypatch):
    """抢不到处理权就直接返回。此时不进 try，所以也不会释放别人的占用。"""
    async def body(env):
        env.orch._processing.add(TICKET_ID)
        await _process(env)
        assert env.calls["execute"] == [] and env.calls["rules"] == []
        assert env.calls["cp_start"] == []
        assert TICKET_ID in env.orch._processing
        assert TICKET_ID not in env.orch._running_tasks
    _run(body, tmp_path, monkeypatch)


def test_live_cli_skips_dispatch(tmp_path, monkeypatch):
    async def body(env):
        env.live_cli = True
        await _process(env)
        await _assert_not_dispatched(env, "pending")
        assert env.calls["cp_start"] == [] and env.calls["rules"] == []
    _run(body, tmp_path, monkeypatch)


def test_missing_ticket_returns_quietly(tmp_path, monkeypatch):
    async def body(env):
        await _process(env, ticket_id="TK-not-exist")
        assert env.calls["execute"] == [] and env.calls["cp_start"] == []
        assert env.sse == []
        assert "TK-not-exist" not in env.orch._processing
        assert "TK-not-exist" not in env.orch._running_tasks
    _run(body, tmp_path, monkeypatch)


@pytest.mark.parametrize("status", HARD_TERMINAL)
def test_hard_terminal_ticket_is_not_dispatched(tmp_path, monkeypatch, status):
    """终态检查排在检查点锚点之后、清 CLI aborted 标记之前。"""
    async def body(env):
        env.rules = {status: _rule()}
        await _process(env)
        await _assert_not_dispatched(env, status)
        assert env.calls["cp_start"] == [(PROJECT_ID, TICKET_ID)]
        assert env.calls["cli_abort"] == []
        assert env.calls["rules"] == [] and env.sse == []
    _run(body, tmp_path, monkeypatch, status=status)


@pytest.mark.parametrize("req_status", ["paused", "cancelled"])
def test_paused_or_cancelled_requirement_stops_flow(tmp_path, monkeypatch, req_status):
    async def body(env):
        await env.db.update("requirements", {"status": req_status}, "id = ?", (REQ_ID,))
        await _process(env)
        await _assert_not_dispatched(env, "pending")
        assert env.calls["cli_abort"] == [TICKET_ID]
        assert env.calls["rules"] == [] and env.sse == []
    _run(body, tmp_path, monkeypatch)


# =====================================================================
# 二、全局止损：打回次数上限、同因连续失败
# =====================================================================

def test_global_reject_limit_blocks(tmp_path, monkeypatch):
    async def body(env):
        for reason in ("甲", "乙", "丙", "丁", "戊"):
            await _seed_reject(env, reason)
        await _process(env)
        await _assert_not_dispatched(env, "blocked")
        (log,) = await _logs(env, "blocked")
        assert (log["agent_type"], log["level"]) == ("Orchestrator", "warning")
        assert (log["from_status"], log["to_status"]) == ("pending", "blocked")
        assert log["detail"]["reason"] == "global_reject_limit"
        assert log["detail"]["reject_count"] == 5
        assert log["detail"]["max_retries"] == 5
        assert log["detail"]["consecutive_same_failure"] == 1
        assert log["detail"]["legacy_action"] == "force_pass"
        assert _sse(env) == [("ticket_blocked", {
            "ticket_id": TICKET_ID, "from": "pending", "to": "blocked",
            "reason": "global_reject_limit",
        })]
        (diag,) = env.calls["diagnose"]
        assert diag["agent_name"] == "Orchestrator"
        assert diag["action"] == "global_reject_limit"
        assert diag["blocked_from_status"] == "pending"
        assert env.calls["rules"] == []         # 止损排在规则匹配之前
    _run(body, tmp_path, monkeypatch)


def test_repeated_failure_fingerprint_blocks(tmp_path, monkeypatch):
    """同一原因连续 3 次即熔断。原因里的数字会被归一化，耗时不同也算同因。"""
    async def body(env):
        for ms in (12, 999, 7):
            await _seed_reject(env, f"LLM 输出无效，耗时 {ms}ms")
        await _process(env)
        await _assert_not_dispatched(env, "blocked")
        (log,) = await _logs(env, "blocked")
        assert log["detail"]["reason"] == "repeated_failure_fingerprint"
        assert log["detail"]["consecutive_same_failure"] == 3
        assert log["detail"]["reject_count"] == 3
        assert log["detail"]["failure_fingerprint"] == "LLM 输出无效，耗时 #ms"
        assert _sse(env)[0][1]["reason"] == "repeated_failure_fingerprint"
        assert env.calls["diagnose"][0]["action"] == "repeated_failure_fingerprint"
    _run(body, tmp_path, monkeypatch)


def test_acceptance_rejects_do_not_feed_repeated_failure(tmp_path, monkeypatch):
    """验收打回不计入同因熔断，只计入全局次数。3 次还没到全局上限。"""
    async def body(env):
        for _ in range(3):
            await _seed_reject(env, "验收不通过", to_status="acceptance_rejected")
        await _process(env)
        _assert_dispatched(env)
    _run(body, tmp_path, monkeypatch)


def test_unblock_resets_reject_counters(tmp_path, monkeypatch):
    async def body(env):
        for _ in range(5):
            await _seed_reject(env, "同一个原因")
        await env.orch._log(PROJECT_ID, REQ_ID, TICKET_ID, "Human", "unblock",
                            "blocked", "pending", "人工解除")
        await _process(env)
        _assert_dispatched(env)
        assert await _logs(env, "blocked") == []
    _run(body, tmp_path, monkeypatch)


# =====================================================================
# 三、前置依赖
# =====================================================================

async def _add_dep(env, status):
    await env.db.insert("tickets", {
        "id": DEP_ID, "project_id": PROJECT_ID, "requirement_id": REQ_ID,
        "title": "前置工单", "description": "d", "type": "feature",
        "module": "backend", "status": status, "created_at": TS, "updated_at": TS,
    })


def test_unfinished_dependency_makes_ticket_wait(tmp_path, monkeypatch):
    async def body(env):
        await _add_dep(env, "development_done")
        await _process(env)
        await _assert_not_dispatched(env, "pending")
        (log,) = await _logs(env)
        assert (log["agent_type"], log["action"], log["level"]) == ("Orchestrator", "info", "info")
        assert (log["from_status"], log["to_status"]) == ("pending", "pending")
        assert f"#{DEP_ID[-6:]}(前置工单)" in log["detail"]["message"]
        assert env.calls["rules"] == [] and _sse(env) == []
    _run(body, tmp_path, monkeypatch,
         ticket_extra={"dependencies": json.dumps([DEP_ID])})


@pytest.mark.parametrize("dep_status", ["testing_done", "deployed"])
def test_finished_dependency_lets_ticket_run(tmp_path, monkeypatch, dep_status):
    async def body(env):
        await _add_dep(env, dep_status)
        await _process(env)
        _assert_dispatched(env)
    _run(body, tmp_path, monkeypatch,
         ticket_extra={"dependencies": json.dumps([DEP_ID])})


@pytest.mark.parametrize("deps", [
    json.dumps([TICKET_ID, "TK-not-exist"]),    # 自引用被过滤，不存在的依赖被忽略
    "这不是 JSON",
    None,
])
def test_unusable_dependencies_are_ignored(tmp_path, monkeypatch, deps):
    async def body(env):
        await _process(env)
        _assert_dispatched(env)
    _run(body, tmp_path, monkeypatch, ticket_extra={"dependencies": deps})


def test_dependencies_only_gate_pending_tickets(tmp_path, monkeypatch):
    async def body(env):
        await _add_dep(env, "pending")
        env.rules = {"development_done": _rule(action="code_review",
                                               next_status="code_review_in_progress")}
        await _process(env)
        _assert_dispatched(env, action="code_review")
    _run(body, tmp_path, monkeypatch, status="development_done",
         ticket_extra={"dependencies": json.dumps([DEP_ID])})


# =====================================================================
# 四、规则匹配与阶段级止损
# =====================================================================

def test_status_without_rule_returns(tmp_path, monkeypatch):
    async def body(env):
        env.rules = {}
        await _process(env)
        await _assert_not_dispatched(env, "pending")
        assert env.calls["rules"] == ["feature"]
        assert env.calls["repair"] == ["pending"]
        assert await _logs(env) == [] and _sse(env) == []
    _run(body, tmp_path, monkeypatch)


def test_repaired_status_is_used_for_rule_lookup(tmp_path, monkeypatch):
    """状态不在 SOP 里时用修复后的状态继续派单，触发态也跟着换。"""
    async def body(env):
        env.repaired = "pending"
        await _process(env)
        call = _assert_dispatched(env)
        assert call["context"]["trigger_status"] == "pending"
        (log,) = await _logs(env, "assign")
        assert (log["from_status"], log["to_status"]) == ("pending", IN_PROGRESS)
    _run(body, tmp_path, monkeypatch, status="architecture_done")


def _rework_rule():
    return _rule(action="fix_issues", _rework_source_stage="engine_compile",
                 config={"max_retries": 2})


def test_rework_rule_blocks_after_max_retries(tmp_path, monkeypatch):
    async def body(env):
        env.rules = {"engine_compile_failed": _rework_rule()}
        for reason in ("甲", "乙"):
            await _seed_reject(env, reason, to_status="engine_compile_failed")
        await _process(env)
        await _assert_not_dispatched(env, "blocked")
        (log,) = await _logs(env, "blocked")
        assert (log["agent_type"], log["level"]) == ("Orchestrator", "warning")
        assert (log["from_status"], log["to_status"]) == ("engine_compile_failed", "blocked")
        assert log["detail"]["reject_count"] == 2
        assert log["detail"]["max_retries"] == 2
        assert log["detail"]["source_stage"] == "engine_compile"
        assert log["detail"]["failed_status"] == "engine_compile_failed"
        assert _sse(env) == [("ticket_blocked", {
            "ticket_id": TICKET_ID, "from": "engine_compile_failed", "to": "blocked",
            "reason": "max_retries_exceeded",
        })]
        (diag,) = env.calls["diagnose"]
        assert (diag["agent_name"], diag["action"]) == ("DevAgent", "engine_compile")
        assert env.orch._agent_status == {}
    _run(body, tmp_path, monkeypatch, status="engine_compile_failed")


def test_rework_rule_runs_below_max_retries(tmp_path, monkeypatch):
    """只数打回到当前状态的次数；打回到别的状态的不算。"""
    async def body(env):
        env.rules = {"engine_compile_failed": _rework_rule()}
        await _seed_reject(env, "甲", to_status="engine_compile_failed")
        await _seed_reject(env, "乙", to_status="development_failed")
        await _process(env)
        call = _assert_dispatched(env, action="fix_issues")
        assert call["context"]["sop_config"] == {"max_retries": 2}
        assert call["context"]["trigger_status"] == "engine_compile_failed"
    _run(body, tmp_path, monkeypatch, status="engine_compile_failed")


def test_rule_without_next_status_falls_back_to_action_in_progress(tmp_path, monkeypatch):
    async def body(env):
        env.rules = {"pending": {"agent": "DevAgent", "action": "develop"}}
        await _process(env)
        call = _assert_dispatched(env)
        assert call["row"]["status"] == "develop_in_progress"
    _run(body, tmp_path, monkeypatch)


# =====================================================================
# 五、跳过阶段
# =====================================================================

NONCODE_TITLE = "验证流程：跑一遍提案到归档"
COMPILE_STAGE = {"skip_when": "noncode_ticket", "success_status": "engine_compile_done",
                 "name": "引擎编译"}


def test_noncode_ticket_skips_stage(tmp_path, monkeypatch):
    async def body(env):
        env.stages = {"develop": COMPILE_STAGE}
        await _process(env)
        await _assert_not_dispatched(env, "engine_compile_done")
        assert (await _ticket(env))["assigned_agent"] == "DevAgent"
        (log,) = await _logs(env)
        assert (log["agent_type"], log["action"], log["level"]) == ("Orchestrator", "skip", "info")
        assert (log["from_status"], log["to_status"]) == ("pending", "engine_compile_done")
        assert log["detail"]["reason"] == "noncode_ticket"
        assert log["detail"]["skipped_action"] == "develop"
        assert "跳过引擎编译" in log["detail"]["message"]
        assert _sse(env) == [("ticket_status_changed", {
            "ticket_id": TICKET_ID, "from": "pending", "to": "engine_compile_done",
            "agent": "Orchestrator",
        })]
        # 先释放处理权再发续跑事件，否则事件侧会撞 claim
        assert env.calls["ready"] == [{"ticket": TICKET_ID, "claimed": False}]
        assert env.orch._agent_status == {}
    _run(body, tmp_path, monkeypatch, ticket_extra={"title": NONCODE_TITLE})


@pytest.mark.parametrize("title, stage", [
    (TITLE, COMPILE_STAGE),                                 # 普通代码工单
    (NONCODE_TITLE, {"skip_when": "noncode_ticket"}),       # 没声明 success_status
    (NONCODE_TITLE, {"success_status": "engine_compile_done"}),  # 没声明 skip_when
])
def test_stage_is_not_skipped(tmp_path, monkeypatch, title, stage):
    async def body(env):
        env.stages = {"develop": stage}
        await _process(env)
        _assert_dispatched(env)
        assert await _logs(env, "skip") == []
    _run(body, tmp_path, monkeypatch, ticket_extra={"title": title})


@pytest.mark.parametrize("action, stage, skip_to, label", [
    ("write_ux_design", None, "ux_design_done", "UX 交互设计"),
    ("write_art_design", None, "art_design_done", "美术视觉设计"),
    ("write_ux_design", {"success_status": "ux_ready"}, "ux_ready", "UX 交互设计"),
])
def test_ticket_without_ui_skips_design_stage(tmp_path, monkeypatch,
                                              action, stage, skip_to, label):
    async def body(env):
        env.rules = {"pending": _rule(agent="UXAgent", action=action,
                                      next_status="ux_design_in_progress")}
        if stage:
            env.stages = {action: stage}
        await _process(env)
        await _assert_not_dispatched(env, skip_to)
        (log,) = await _logs(env)
        assert log["action"] == "skip"
        assert log["detail"]["reason"] == "no_ui_ticket"
        assert log["detail"]["module"] == "backend"
        assert f"跳过{label}阶段" in log["detail"]["message"]
        assert env.calls["ready"] == [{"ticket": TICKET_ID, "claimed": False}]
    _run(body, tmp_path, monkeypatch)


def test_ui_ticket_runs_design_stage(tmp_path, monkeypatch):
    async def body(env):
        env.rules = {"pending": _rule(agent="UXAgent", action="write_ux_design",
                                      next_status="ux_design_in_progress")}
        await _process(env)
        _assert_dispatched(env, executor="UXAgent", action="write_ux_design")
    _run(body, tmp_path, monkeypatch, ticket_extra={"module": "frontend"})


# =====================================================================
# 六、Agent 未注册
# =====================================================================

def test_unregistered_agent_blocks_ticket(tmp_path, monkeypatch):
    async def body(env):
        env.rules = {"pending": _rule(agent="GhostAgent")}
        await _process(env)
        await _assert_not_dispatched(env, "blocked")
        (log,) = await _logs(env)
        assert (log["agent_type"], log["action"], log["level"]) == ("GhostAgent", "blocked", "error")
        assert (log["from_status"], log["to_status"]) == ("pending", "blocked")
        assert log["detail"]["missing_agent"] == "GhostAgent"
        assert log["detail"]["action"] == "develop"
        assert _sse(env) == [("ticket_blocked", {
            "ticket_id": TICKET_ID, "from": "pending", "to": "blocked",
            "reason": "agent_not_registered", "agent": "GhostAgent",
        })]
        assert env.calls["diagnose"] == []
        assert env.orch._agent_status == {}
    _run(body, tmp_path, monkeypatch)


# =====================================================================
# 七、正常派单
# =====================================================================

def test_dispatch_happy_path(tmp_path, monkeypatch):
    async def body(env):
        env.rules = {"pending": _rule(), "development_done": _rule(action="code_review")}
        await _process(env)
        call = _assert_dispatched(env)

        # Agent 执行时的现场
        assert call["context"] == {"ticket_id": TICKET_ID, "built_for": "DevAgent",
                                   "trigger_status": "pending"}
        row = call["row"]
        assert row["status"] == IN_PROGRESS
        assert row["assigned_agent"] == "DevAgent"
        assert row["current_owner"] == "developer"
        assert row["started_at"]
        assert row["current_action"] == "DevAgent.develop"
        assert call["llm"] == (TICKET_ID, REQ_ID, PROJECT_ID, "DevAgent", "develop")
        assert call["agent_status"]["DevAgent"]["status"] == "working"
        assert call["agent_status"]["DevAgent"]["ticket_id"] == TICKET_ID
        assert call["claimed"] and call["running"]

        # 执行之后
        assert env.calls["result"] == [{
            "ticket_status": "pending",     # 传给结果处理的是派单前读到的工单
            "agent": "DevAgent", "action": "develop", "result": env.agent_result,
        }]
        assert _llm_ctx() == (None, None, None, None, None)
        assert (await _ticket(env))["current_action"] is None
        status = env.orch._agent_status["DevAgent"]
        assert (status["status"], status["completed_count"]) == ("idle", 1)
        assert env.calls["hb"] == ["start", "cancel"]
        assert env.calls["thought"] == ["start", "done"]
        assert env.calls["cp_start"] == [(PROJECT_ID, TICKET_ID)]
        assert env.calls["cp_boundary"] == [{
            "agent_type": "DevAgent", "action": "develop", "note": "DevAgent.develop 完成",
        }]
        assert env.calls["cli_abort"] == [TICKET_ID]

        (log,) = await _logs(env)
        assert (log["agent_type"], log["action"]) == ("DevAgent", "assign")
        assert (log["from_status"], log["to_status"]) == ("pending", IN_PROGRESS)
        assert _sse(env) == [
            ("ticket_status_changed", {"ticket_id": TICKET_ID, "from": "pending",
                                       "to": IN_PROGRESS, "agent": "DevAgent"}),
            ("agent_working", {"agent": "DevAgent", "action": "develop",
                               "ticket_id": TICKET_ID}),
        ]
        # 新状态还有规则：先释放处理权，再发续跑事件
        assert env.calls["ready"] == [{"ticket": TICKET_ID, "claimed": False}]
        assert env.calls["rules"] == ["feature", "feature"]
        assert env.calls["git_switch"] == []
    _run(body, tmp_path, monkeypatch)


def test_no_followup_when_new_status_has_no_rule(tmp_path, monkeypatch):
    async def body(env):
        env.result_status = "deployed"
        await _process(env)
        _assert_dispatched(env)
        assert env.calls["ready"] == []
    _run(body, tmp_path, monkeypatch)


def test_existing_started_at_is_kept(tmp_path, monkeypatch):
    async def body(env):
        await _process(env)
        assert _assert_dispatched(env)["row"]["started_at"] == "2026-01-01T00:00:00Z"
    _run(body, tmp_path, monkeypatch, ticket_extra={"started_at": "2026-01-01T00:00:00Z"})


def test_sop_config_and_human_comments_reach_agent(tmp_path, monkeypatch):
    async def body(env):
        env.rules = {"pending": _rule(config={"pass_score": 6})}
        for i, (author_type, content) in enumerate([
            ("human", "先做体力条"), ("agent", "这是 Agent 的阶段评论"), ("human", "不要改存档格式"),
        ]):
            await env.db.insert("ticket_comments", {
                "id": f"CM-{i}", "ticket_id": TICKET_ID, "project_id": PROJECT_ID,
                "author": "u", "author_type": author_type, "content": content,
                "created_at": f"2026-11-24T00:0{i}:00Z",
            })
        await _process(env)
        ctx = _assert_dispatched(env)["context"]
        assert ctx["sop_config"] == {"pass_score": 6}
        text = ctx["human_instructions"]
        assert text.startswith("## ⚠️ 人工指令（最高优先级，必须严格遵循）")
        assert text.endswith("- [2026-11-24T00:00] 先做体力条\n- [2026-11-24T00:02] 不要改存档格式")
        assert "Agent 的阶段评论" not in text
    _run(body, tmp_path, monkeypatch)


def test_skill_stage_is_executed_by_skill_agent(tmp_path, monkeypatch):
    """SOP 上的 agent 只是宿主 Role；带 skill_id 的阶段交给 SkillAgent 执行。"""
    async def body(env):
        env.rules = {"pending": _rule(action="skill_demo", config={"skill_id": "demo"})}
        await _process(env)
        call = _assert_dispatched(env, executor="SkillAgent", action="skill_demo")
        assert call["llm"][3] == "DevAgent"
        assert call["row"]["assigned_agent"] == "DevAgent"
        assert env.calls["result"][0]["agent"] == "DevAgent"
    _run(body, tmp_path, monkeypatch)


@pytest.mark.parametrize("timing", ["during-agent", "during-git", "current"])
def test_dev_completion_respects_assigned_status(tmp_path, monkeypatch, timing):
    """从真正派单一路走到收尾；自定义进行态有效，过期结果不再触发外层管线。"""
    async def body(env):
        del env.orch._handle_agent_result  # 使用真实处理入口
        env.rules = {"pending": _rule(next_status="custom_building"), "review_passed": _rule()}
        execute = env.orch.agents["DevAgent"].execute
        git_calls = []

        async def advance():
            await env.db.update("tickets", {"status": "review_passed", "result": "newer"},
                                "id = ?", (TICKET_ID,))

        async def run_agent(action, context):
            result = await execute(action, context)
            if timing == "during-agent":
                await advance()
            return result

        async def git(*args):
            git_calls.append(True)
            if timing == "during-git":
                await advance()

        env.orch.agents["DevAgent"].execute = run_agent
        env.orch._handle_git_files = git
        await _process(env)
        row = await _ticket(env)
        if timing == "current":
            assert row["status"] == "development_done"
            assert json.loads(row["result"]) == env.agent_result
            assert len(env.calls["cp_boundary"]) == 1
        else:
            assert (row["status"], row["result"]) == ("review_passed", "newer")
            assert env.calls["cp_boundary"] == env.calls["ready"] == []
            assert [p["to"] for _, p in _sse(env, "ticket_status_changed")] == ["custom_building"]
        assert len(git_calls) == (0 if timing == "during-agent" else 1)
        assert _sse(env, "ticket_error") == []
        _assert_released(env)
    _run(body, tmp_path, monkeypatch)


def test_error_result_skips_phase_boundary(tmp_path, monkeypatch):
    async def body(env):
        env.agent_result = {"status": "error", "message": "x"}
        await _process(env)
        _assert_dispatched(env)
        assert env.calls["cp_boundary"] == []
        assert env.orch._agent_status["DevAgent"]["completed_count"] == 1
    _run(body, tmp_path, monkeypatch)


# =====================================================================
# 八、切换需求分支
# =====================================================================

async def _use_feature_branch(env, *, current="main", switch_ok=True, after_fail="main"):
    await env.db.update("requirements", {"branch_name": "feat/sprint"}, "id = ?", (REQ_ID,))
    env.git.exists, env.git.current = True, current
    env.git.switch_ok, env.git.after_fail = switch_ok, after_fail


def test_switches_to_requirement_branch(tmp_path, monkeypatch):
    async def body(env):
        await _use_feature_branch(env)
        await _process(env)
        _assert_dispatched(env)
        assert env.calls["git_switch"] == ["feat/sprint"]
    _run(body, tmp_path, monkeypatch)


def test_no_switch_when_already_on_branch(tmp_path, monkeypatch):
    async def body(env):
        await _use_feature_branch(env, current="feat/sprint")
        await _process(env)
        _assert_dispatched(env)
        assert env.calls["git_switch"] == []
    _run(body, tmp_path, monkeypatch)


def test_failed_switch_on_main_aborts_before_agent(tmp_path, monkeypatch):
    """切分支失败且停在主分支：不执行 Agent。

    此时工单已经改成进行中、Agent 已标忙碌，这条路径不会改回去。
    现状如此，靠轮询里的僵尸检测兜底。
    """
    async def body(env):
        await _use_feature_branch(env, switch_ok=False, after_fail="main")
        await _process(env)
        await _assert_not_dispatched(env, IN_PROGRESS)
        assert env.orch._agent_status["DevAgent"]["status"] == "working"
        assert [e for e, _ in _sse(env)] == ["ticket_status_changed"]
        assert env.calls["hb"] == [] and env.calls["ready"] == []
        assert await _logs(env, "error") == []
    _run(body, tmp_path, monkeypatch)


def test_failed_switch_off_main_continues(tmp_path, monkeypatch):
    async def body(env):
        await _use_feature_branch(env, switch_ok=False, after_fail="feat/other")
        await _process(env)
        _assert_dispatched(env)
    _run(body, tmp_path, monkeypatch)


def test_branch_error_is_not_fatal(tmp_path, monkeypatch):
    async def body(env):
        await _use_feature_branch(env)
        env.git.error = RuntimeError("git 不可用")
        await _process(env)
        _assert_dispatched(env)
        assert await _logs(env, "error") == []
    _run(body, tmp_path, monkeypatch)


# =====================================================================
# 九、反思记录
# =====================================================================

REFLECTION = {
    "retry_count": 2, "root_cause": "空指针", "strategy_change": "先判空",
    "specific_changes": ["加判空", "补用例", "改日志", "第四条不进摘要"],
    "confidence": 0.8,
}


@pytest.mark.parametrize("action, failure_type", [
    ("fix_issues", "testing_failed"),
    ("rework", "acceptance_rejected"),
])
def test_reflection_is_recorded(tmp_path, monkeypatch, action, failure_type):
    async def body(env):
        env.rules = {"pending": _rule(action=action)}
        env.agent_result = {"status": "success", "last_reflection": REFLECTION}
        await _process(env)
        _assert_dispatched(env, action=action)
        (log,) = await _logs(env, "reflection")
        assert (log["agent_type"], log["level"]) == ("DevAgent", "info")
        assert (log["from_status"], log["to_status"]) == (None, None)
        assert log["detail"]["message"] == (
            "[反思 #2] | 根因: 空指针 | 策略: 先判空 | "
            "修改: 加判空; 补用例; 改日志 | (confidence=0.80)"
        )
        assert log["detail"]["reflection"] == REFLECTION
        assert env.calls["fts"] == [(
            TICKET_ID, PROJECT_ID,
            f"{TITLE} 实现角色冲刺的体力消耗逻辑 空指针 加判空 补用例 改日志",
        )]
        (rec,) = env.calls["fl_record"]
        assert rec["failure_type"] == failure_type
        assert rec["agent_type"] == "DevAgent"
        assert rec["reflection"] == REFLECTION
        assert (rec["ticket_id"], rec["module"]) == (TICKET_ID, "backend")
    _run(body, tmp_path, monkeypatch)


def test_reflection_side_effect_failures_are_swallowed(tmp_path, monkeypatch):
    async def body(env):
        env.agent_result = {"status": "success", "last_reflection": REFLECTION}
        env.fts_error = RuntimeError("fts 坏了")
        env.fl_error = RuntimeError("失败库坏了")
        await _process(env)
        _assert_dispatched(env)
        assert len(await _logs(env, "reflection")) == 1
        assert await _logs(env, "error") == []
    _run(body, tmp_path, monkeypatch)


# =====================================================================
# 十、排队中的阶段回退
# =====================================================================

def _queue_restart(env, target="pending"):
    env.orch._pending_restart[TICKET_ID] = {"status": target, "reason": "评论触发"}


def test_pending_restart_is_applied_after_run(tmp_path, monkeypatch):
    async def body(env):
        env.rules = {"pending": _rule(), "development_done": _rule()}
        _queue_restart(env)
        await _process(env)
        _assert_dispatched(env)
        assert env.calls["rewind"] == [{
            "from": "development_done", "to": "pending", "reason": "评论触发",
            "claimed": False,       # 先释放处理权再改写
        }]
        assert env.calls["ready"] == []     # 回退之后不再发续跑事件
        assert env.orch._pending_restart == {}
    _run(body, tmp_path, monkeypatch)


def test_pending_restart_is_dropped_when_ticket_is_terminal(tmp_path, monkeypatch):
    async def body(env):
        env.result_status = "blocked"
        _queue_restart(env)
        await _process(env)
        _assert_dispatched(env)
        assert env.calls["rewind"] == [] and env.calls["ready"] == []
        assert env.orch._pending_restart == {}
    _run(body, tmp_path, monkeypatch)


def test_pending_restart_is_dropped_when_it_would_jump_forward(tmp_path, monkeypatch):
    async def body(env):
        env.rules = {"pending": _rule(), "development_done": _rule()}
        env.forward_jump = True
        _queue_restart(env, target="acceptance_passed")
        await _process(env)
        _assert_dispatched(env)
        assert env.calls["rewind"] == []
        assert env.calls["ready"] == [{"ticket": TICKET_ID, "claimed": False}]
        assert env.orch._pending_restart == {}
    _run(body, tmp_path, monkeypatch)


# =====================================================================
# 十一、异常与取消
# =====================================================================

def test_agent_exception_is_logged_and_ticket_released(tmp_path, monkeypatch):
    """Agent 抛异常：记日志、发 `ticket_error`、Agent 记一次失败。

    工单停在进行中，LLM 上下文也不会被清掉——现状如此。
    """
    async def body(env):
        env.agent_error = RuntimeError("boom")
        await _process(env)                 # 异常不向外抛
        assert len(env.calls["execute"]) == 1 and env.calls["result"] == []
        _assert_released(env)
        row = await _ticket(env)
        assert row["status"] == IN_PROGRESS
        assert row["current_action"] is None
        (log,) = await _logs(env, "error")
        assert (log["agent_type"], log["level"]) == ("Orchestrator", "error")
        assert (log["from_status"], log["to_status"]) == (None, None)
        assert log["detail"]["message"] == "工单处理异常: boom"
        assert _sse(env, "ticket_error") == [
            ("ticket_error", {"ticket_id": TICKET_ID, "error": "boom"}),
        ]
        status = env.orch._agent_status["DevAgent"]
        assert (status["status"], status["error_count"]) == ("idle", 1)
        assert "completed_count" not in status
        assert env.calls["hb"] == ["start", "cancel"]
        assert env.calls["thought"] == ["start"]
        assert env.calls["cp_boundary"] == [] and env.calls["ready"] == []
        assert _llm_ctx() == (TICKET_ID, REQ_ID, PROJECT_ID, "DevAgent", "develop")
    _run(body, tmp_path, monkeypatch)


def test_exception_before_rule_match_leaves_agent_status_alone(tmp_path, monkeypatch):
    """还没选出 Agent 就出错：只记日志，不动任何 Agent 的忙闲计数。"""
    async def body(env):
        env.rules_error = RuntimeError("规则表坏了")
        await _process(env)
        await _assert_not_dispatched(env, "pending")
        (log,) = await _logs(env, "error")
        assert log["detail"]["message"] == "工单处理异常: 规则表坏了"
        assert [e for e, _ in _sse(env)] == ["ticket_error"]
        assert env.orch._agent_status == {}
    _run(body, tmp_path, monkeypatch)


def test_exception_after_agent_chosen_counts_as_agent_error(tmp_path, monkeypatch):
    """选出 Agent 之后、标忙碌之前出错：这个 Agent 也会被记一次失败。"""
    async def body(env):
        env.stage_error = RuntimeError("SOP 读不出来")
        await _process(env)
        await _assert_not_dispatched(env, "pending")
        assert len(await _logs(env, "error")) == 1
        status = env.orch._agent_status["DevAgent"]
        assert (status["status"], status["error_count"]) == ("idle", 1)
    _run(body, tmp_path, monkeypatch)


def test_queued_restart_still_applies_after_exception(tmp_path, monkeypatch):
    async def body(env):
        env.agent_error = RuntimeError("boom")
        _queue_restart(env)
        await _process(env)
        assert env.calls["rewind"] == [{
            "from": IN_PROGRESS, "to": "pending", "reason": "评论触发", "claimed": False,
        }]
        assert env.orch._pending_restart == {}
        _assert_released(env)
    _run(body, tmp_path, monkeypatch)


def test_queued_restart_after_exception_respects_forward_jump(tmp_path, monkeypatch):
    async def body(env):
        env.agent_error = RuntimeError("boom")
        env.forward_jump = True
        _queue_restart(env, target="acceptance_passed")
        await _process(env)
        assert env.calls["rewind"] == []
        assert env.orch._pending_restart == {}
    _run(body, tmp_path, monkeypatch)


def test_cancellation_propagates_and_releases(tmp_path, monkeypatch):
    """取消要原样抛出去：不记错误日志，不把 Agent 标成空闲，但处理权要释放。"""
    async def body(env):
        env.agent_error = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await env.orch.process_ticket(PROJECT_ID, TICKET_ID)
        _assert_released(env)
        assert env.calls["result"] == []
        assert await _logs(env, "error") == []
        assert _sse(env, "ticket_error") == []
        assert env.orch._agent_status["DevAgent"]["status"] == "working"
        assert env.calls["hb"] == ["start", "cancel"]
        assert (await _ticket(env))["status"] == IN_PROGRESS
    _run(body, tmp_path, monkeypatch)


# =====================================================================
# 十二、管线约定：步骤顺序、停止原因
# =====================================================================

STEP_NAMES = [
    "load_ticket", "check_entry_gates", "check_global_circuit_breaker",
    "check_dependencies", "match_rule", "check_stage_retry_limit", "select_agent",
    "skip_inapplicable_stage", "ensure_agent_registered", "assign_ticket",
    "switch_to_feature_branch", "build_agent_context", "run_agent",
    "record_reflection", "handle_result", "apply_pending_restart",
    "publish_next_stage",
]


def test_pipeline_step_order():
    """顺序就是行为：止损排在派单前，反思排在结果处理前，回退排在续跑前。"""
    assert [step.__name__ for step in ticket_pipeline.STEPS] == STEP_NAMES
    assert all(inspect.iscoroutinefunction(step) for step in ticket_pipeline.STEPS)


async def _process_capturing(env, monkeypatch, ticket_id=TICKET_ID):
    """跑一次 process_ticket，返回这一次的 TicketRun。"""
    runs = []
    real = ticket_pipeline.run_pipeline

    async def spy(run):
        runs.append(run)
        return await real(run)

    monkeypatch.setattr(ticket_pipeline, "run_pipeline", spy)
    await _process(env, ticket_id)
    (run,) = runs
    return run


async def _prep_live_cli(env):
    env.live_cli = True


async def _prep_paused(env):
    await env.db.update("requirements", {"status": "paused"}, "id = ?", (REQ_ID,))


async def _prep_global_limit(env):
    for reason in ("甲", "乙", "丙", "丁", "戊"):
        await _seed_reject(env, reason)


async def _prep_dependency(env):
    await _add_dep(env, "development_done")


async def _prep_no_rule(env):
    env.rules = {}


async def _prep_stage_limit(env):
    env.rules = {"engine_compile_failed": _rework_rule()}
    for reason in ("甲", "乙"):
        await _seed_reject(env, reason, to_status="engine_compile_failed")


async def _prep_skip(env):
    env.stages = {"develop": COMPILE_STAGE}


async def _prep_ghost_agent(env):
    env.rules = {"pending": _rule(agent="GhostAgent")}


async def _prep_stuck_on_main(env):
    await _use_feature_branch(env, switch_ok=False, after_fail="main")


async def _prep_rewind(env):
    env.rules = {"pending": _rule(), "development_done": _rule()}
    _queue_restart(env)


STOP_CASES = [
    (_prep_live_cli, {}, "load_ticket", "live_cli"),
    (_prep_paused, {}, "check_entry_gates", "requirement_inactive"),
    (None, {"status": "blocked"}, "check_entry_gates", "hard_terminal"),
    (_prep_global_limit, {}, "check_global_circuit_breaker", "global_circuit_breaker"),
    (_prep_dependency, {"ticket_extra": {"dependencies": json.dumps([DEP_ID])}},
     "check_dependencies", "waiting_dependencies"),
    (_prep_no_rule, {}, "match_rule", "no_rule"),
    (_prep_stage_limit, {"status": "engine_compile_failed"},
     "check_stage_retry_limit", "stage_retry_limit"),
    (_prep_skip, {"ticket_extra": {"title": NONCODE_TITLE}},
     "skip_inapplicable_stage", "stage_skipped"),
    (_prep_ghost_agent, {}, "ensure_agent_registered", "agent_not_registered"),
    (_prep_stuck_on_main, {}, "switch_to_feature_branch", "branch_switch_failed_on_main"),
    (_prep_rewind, {}, "apply_pending_restart", "status_rewound"),
]


@pytest.mark.parametrize("prep, env_kw, step, reason", STOP_CASES,
                         ids=[case[3] for case in STOP_CASES])
def test_stop_is_recorded_on_run(tmp_path, monkeypatch, prep, env_kw, step, reason):
    """每个提前出口都记下停在哪一步和原因，之后的步骤不再执行。"""
    async def body(env):
        if prep:
            await prep(env)
        run = await _process_capturing(env, monkeypatch)
        assert (run.stopped_at, run.stop_reason) == (step, reason)
        # 派单之前停下的，Agent 一定没跑过
        if STEP_NAMES.index(step) < STEP_NAMES.index("run_agent"):
            assert run.result is None and env.calls["execute"] == []
        # 取到 Agent 名之前停下的，出错也不该记到任何 Agent 头上
        assert run.agent_chosen == (
            STEP_NAMES.index(step) > STEP_NAMES.index("select_agent"))
        _assert_released(env)
    _run(body, tmp_path, monkeypatch, **env_kw)


def test_missing_ticket_stops_at_load(tmp_path, monkeypatch):
    async def body(env):
        run = await _process_capturing(env, monkeypatch, ticket_id="TK-not-exist")
        assert (run.stopped_at, run.stop_reason) == ("load_ticket", "ticket_not_found")
        assert run.ticket is None
    _run(body, tmp_path, monkeypatch)


def test_full_run_has_no_stop_reason(tmp_path, monkeypatch):
    async def body(env):
        run = await _process_capturing(env, monkeypatch)
        _assert_dispatched(env)
        assert (run.stopped_at, run.stop_reason) == ("", None)
        assert (run.agent_name, run.action, run.next_status) == ("DevAgent", "develop", IN_PROGRESS)
        assert run.agent_chosen is True
        assert run.current_status == "pending"
        assert run.ticket["status"] == "pending"    # 派单前读到的那一行，不刷新
        assert run.context["trigger_status"] == "pending"
        assert run.result is env.calls["result"][0]["result"]
    _run(body, tmp_path, monkeypatch)
