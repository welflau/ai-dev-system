"""`handle_requirement` 的特征测试。

特征测试只记录**现在的行为**，不评判对错。它是后面整理 `handle_requirement`
（需求分析加拆单，456 行）的安全网（方案文档：docs/20261124_01_代码重构方案.md，
R0 第 3 步、R2 第 3 步）。整理之后这里任何一条变红，都说明改动动了行为。

每个出口钉住四件事：

1. 需求最后停在什么状态，建了哪些工单、子任务、子工单；
2. 写了哪些 `ticket_logs`、发了哪些 SSE；
3. 有没有继续派单；
4. 分析占用标记（`_analyzing_reqs`）有没有释放。

夹具沿用 `test_orchestrator_process_ticket.py` 的做法：真实 SQLite，
`TicketOrchestrator.__new__` 造实例。拆单落库、依赖回填、状态改写、日志都真跑；
ProductAgent、代码上下文、里程碑关联、Git、派单打桩。

文件里标了「现状」的用例记的是读代码时觉得可疑的行为，按现在的样子断言，没有修。
"""
import asyncio
import json
import logging
import re
from collections import defaultdict
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

import database as database_module
import llm_client as llm_module
import orchestrator as orch_module
from database import Database
from orchestrator import TicketOrchestrator, analysis_progress_message

PROJECT_ID = "P-HR"
REQ_ID = "REQ-20261124-hr0001"
REQ_TITLE = "角色冲刺"
REQ_DESC = "按住 Shift 冲刺，消耗体力"
TS = "2026-11-24T00:00:00Z"
ACTION = "analyze_and_decompose"
LLM_CTX = (None, REQ_ID, PROJECT_ID, "ProductAgent", ACTION)
NO_LLM_CTX = (None, None, None, None, None)


def _llm_ctx():
    c = llm_module._llm_ctx
    return (c.ticket_id, c.requirement_id, c.project_id, c.agent_type, c.action)


def _tk(title, **kw):
    data = {"title": title}
    data.update(kw)
    return data


def _result(*tickets, **kw):
    """模拟 ProductAgent.analyze_and_decompose 的回传。默认 complex，两张以上都从 pending 起步。"""
    data = {
        "status": "success", "prd_summary": "PRD 摘要",
        "complexity": "complex", "tickets": list(tickets),
    }
    data.update(kw)
    return data


class _FakeProductAgent:
    """记录被调用时的现场：需求状态、LLM 上下文、占用标记。"""

    def __init__(self, env):
        self.env = env

    async def execute(self, action, context):
        env = self.env
        await env.real_sleep(0)         # 让出一次事件循环，心跳任务得以启动
        row = await env.db.fetch_one(
            "SELECT status FROM requirements WHERE id = ?", (REQ_ID,)
        )
        env.calls["execute"].append({
            "action": action, "context": dict(context),
            "req_status": row["status"] if row else None, "llm": _llm_ctx(),
            "analyzing": REQ_ID in env.orch._analyzing_reqs,
        })
        if env.agent_hook is not None:
            await env.agent_hook(context)
        if env.agent_error is not None:
            raise env.agent_error
        return env.agent_result


@asynccontextmanager
async def _env(tmp_path, monkeypatch, *, req_extra=None, traits="[]"):
    db_file = tmp_path / "hr.db"

    original_db = database_module.db
    test_db = Database(db_path=str(db_file))
    await test_db.connect()
    await test_db.init_tables()          # 建表 + 迁移，缺一不可
    database_module.db = test_db
    monkeypatch.setattr(orch_module, "db", test_db, raising=False)

    await test_db.insert("projects", {
        "id": PROJECT_ID, "name": "hr", "traits": traits,
        "created_at": TS, "updated_at": TS,
    })
    requirement = {
        "id": REQ_ID, "project_id": PROJECT_ID, "title": REQ_TITLE,
        "description": REQ_DESC, "priority": "high", "status": "analyzing",
        "created_at": TS, "updated_at": TS,
    }
    requirement.update(req_extra or {})
    await test_db.insert("requirements", requirement)

    env = SimpleNamespace(
        db=test_db, sse=[], calls=defaultdict(list), real_sleep=asyncio.sleep,
        agent_result=_result(_tk("A"), _tk("B")),
        agent_error=None,               # 非空时 Agent.execute 抛它
        agent_hook=None,                # Agent 执行中途要做的事
        code_ctx={"file_list": [], "code": {}},
        code_ctx_error=None,            # 非空时读代码上下文抛它
        git=SimpleNamespace(primary="main", switch_ok=True, create_ok=True, error=None),
        milestone_error=None,
        process_error=None,             # 非空时 process_ticket 抛它
        hb_gate=asyncio.Event(),        # 置位一次放行一次心跳
    )

    # ---- 模块级依赖 ----
    async def fake_publish(pid, event, payload):
        env.sse.append((event, payload))
    monkeypatch.setattr(orch_module.event_manager, "publish_to_project", fake_publish)

    # `handle_requirement` 只用 getattr 读 llm_client 的几个属性拼提示文案。
    def set_llm(**attrs):
        monkeypatch.setattr(orch_module, "llm_client", SimpleNamespace(**attrs))
    env.set_llm = set_llm
    set_llm(api_format="openai", model="gpt-test", timeout=600)

    # 函数内 `from memory import AgentMemory`，调用时才取属性，所以打在源模块上。
    import memory as memory_module

    class FakeMemory:
        def __init__(self, pid):
            env.calls["memory"].append(pid)

        async def get_code_context(self):
            if env.code_ctx_error is not None:
                raise env.code_ctx_error
            return env.code_ctx
    monkeypatch.setattr(memory_module, "AgentMemory", FakeMemory)

    import api.milestones as ms_module

    async def fake_associate(pid, rid, title, desc, **kw):
        row = await test_db.fetch_one(
            "SELECT status FROM requirements WHERE id = ?", (rid,)
        )
        env.calls["milestone"].append({
            "args": (pid, rid, title, desc), "kw": kw, "req_status": row["status"],
        })
        if env.milestone_error is not None:
            raise env.milestone_error
    monkeypatch.setattr(ms_module, "auto_associate_requirement", fake_associate)

    gm = orch_module.git_manager

    async def fake_primary(pid):
        if env.git.error is not None:
            raise env.git.error
        env.calls["git"].append(("primary",))
        return env.git.primary
    monkeypatch.setattr(gm, "get_primary_branch", fake_primary)

    async def fake_ensure(pid, name, from_branch=None):
        env.calls["git"].append(("ensure", name, from_branch))
    monkeypatch.setattr(gm, "ensure_branch", fake_ensure)

    async def fake_switch(pid, name):
        env.calls["git"].append(("switch", name))
        return env.git.switch_ok
    monkeypatch.setattr(gm, "switch_branch", fake_switch)

    async def fake_create(pid, name):
        env.calls["git"].append(("create", name))
        return env.git.create_ok
    monkeypatch.setattr(gm, "create_branch", fake_create)

    # `_log` 会把日志镜像到 backend/logs/session_<req>/，测试不该往仓库里写文件。
    import session_logger as sl_module

    async def no_transcript(*a, **kw):
        return None
    monkeypatch.setattr(sl_module.session_logger, "log_event", no_transcript)

    # 心跳每 20s 一次。换成由 `hb_gate` 放行：置位一次跑一次，否则一直等到被取消。
    async def gated_sleep(delay, *a, **kw):
        if delay == 20:
            await env.hb_gate.wait()
            env.hb_gate.clear()
        await env.real_sleep(0)
    monkeypatch.setattr(asyncio, "sleep", gated_sleep)

    # ---- orchestrator 实例：绕过 __init__（它会实例化全部 Agent 并连事件总线）----
    orch = TicketOrchestrator.__new__(TicketOrchestrator)
    orch._analyzing_reqs = set()
    orch.agents = {"ProductAgent": _FakeProductAgent(env)}

    async def fake_thought(pid, rid, tid, agent_name, action, phase, **kw):
        env.calls["thought"].append((phase, kw))
    orch._log_agent_thought = fake_thought

    async def fake_git_files(pid, tid, rid, agent_name, action, result):
        env.calls["git_files"].append((pid, tid, rid, agent_name, action, result))
        return {"committed": True}
    orch._handle_git_files = fake_git_files

    async def fake_process(pid, tid):
        row = await test_db.fetch_one(
            "SELECT status FROM requirements WHERE id = ?", (REQ_ID,)
        )
        env.calls["process"].append({"ticket": tid, "req_status": row["status"]})
        if env.process_error is not None:
            raise env.process_error
    orch.process_ticket = fake_process

    env.orch = orch
    try:
        yield env
    finally:
        llm_module.clear_llm_context()   # 异常路径不清上下文，别漏到别的用例里
        database_module.db = original_db
        await test_db.disconnect()


def _run(body, tmp_path, monkeypatch, **kw):
    async def main():
        async with _env(tmp_path, monkeypatch, **kw) as env:
            return await body(env)
    return asyncio.run(main())


async def _handle(env, req_id=REQ_ID):
    await env.orch.handle_requirement(PROJECT_ID, req_id)


async def _req(env) -> dict:
    return await env.db.fetch_one("SELECT * FROM requirements WHERE id = ?", (REQ_ID,))


async def _tickets(env) -> list:
    rows = await env.db.fetch_all(
        "SELECT * FROM tickets WHERE requirement_id = ? ORDER BY rowid", (REQ_ID,)
    )
    return [dict(r) for r in rows]


async def _logs(env, action=None) -> list:
    rows = await env.db.fetch_all(
        "SELECT ticket_id, agent_type, action, level, from_status, to_status, detail "
        "FROM ticket_logs WHERE requirement_id = ? ORDER BY rowid", (REQ_ID,)
    )
    logs = [dict(r, detail=json.loads(r["detail"])) for r in rows]
    return [x for x in logs if action is None or x["action"] == action]


def _msgs(logs) -> list:
    return [x["detail"]["message"] for x in logs]


def _sse(env, *events) -> list:
    """按事件名取 SSE 负载。`_log` 每写一条都会发 `log_added`，默认滤掉。"""
    return [(e, p) for e, p in env.sse
            if (e in events if events else e != "log_added")]


def _stray_tasks() -> list:
    current = asyncio.current_task()
    return [t for t in asyncio.all_tasks() if t is not current and not t.done()]


def _assert_released(env):
    assert REQ_ID not in env.orch._analyzing_reqs
    assert _stray_tasks() == [], "心跳任务没有收掉"


async def _assert_reverted(env, error_part):
    """走了异常兜底：需求退回已提交，写 error 日志，发 `requirement_error`。"""
    assert (await _req(env))["status"] == "submitted"
    err = [x for x in await _logs(env) if x["level"] == "error"]
    assert [(x["action"], x["from_status"], x["to_status"]) for x in err] == [
        ("error", "analyzing", "submitted"),
    ]
    assert err[0]["detail"]["message"].startswith("需求处理异常: ")
    assert error_part in err[0]["detail"]["message"]
    events = _sse(env, "requirement_error")
    assert len(events) == 1
    assert events[0][1]["requirement_id"] == REQ_ID
    assert error_part in events[0][1]["error"]
    _assert_released(env)


# ════════════════════ 1. 入口 ════════════════════

def test_skips_when_already_analyzing(tmp_path, monkeypatch):
    """同一条需求已经在分析：直接返回，不碰别人的占用标记。"""
    async def body(env):
        env.orch._analyzing_reqs.add(REQ_ID)
        await _handle(env)
        assert env.calls["execute"] == []
        assert await _logs(env) == []
        assert env.sse == []
        assert REQ_ID in env.orch._analyzing_reqs
    _run(body, tmp_path, monkeypatch)


def test_missing_requirement_returns_quietly(tmp_path, monkeypatch, caplog):
    """查不到需求就直接返回，不进异常兜底。

    兜底里写日志会撞外键、被吞掉，库和事件上看不出它跑没跑过，所以连 error 日志一起查。
    """
    async def body(env):
        await _handle(env, "REQ-none")
        assert env.calls["execute"] == []
        assert env.sse == []
        assert await env.db.fetch_all("SELECT id FROM ticket_logs") == []
        assert env.orch._analyzing_reqs == set()
        assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []
    _run(body, tmp_path, monkeypatch)


def test_reentrant_call_is_skipped_while_running(tmp_path, monkeypatch):
    """分析进行中再来一次调度：第二次什么都不做，第一次照常跑完。"""
    async def body(env):
        async def hook(context):
            await env.orch.handle_requirement(PROJECT_ID, REQ_ID)
        env.agent_hook = hook
        await _handle(env)
        assert len(env.calls["execute"]) == 1
        assert (await _req(env))["status"] == "in_progress"
        assert len(await _tickets(env)) == 2
        _assert_released(env)
    _run(body, tmp_path, monkeypatch)


# ════════════════════ 2. 准备和执行 ════════════════════

def test_announces_start_and_calls_agent(tmp_path, monkeypatch):
    async def body(env):
        await _handle(env)

        progress = await _logs(env, "progress")
        assert _msgs(progress) == [
            f"开始 PRD 分析「{REQ_TITLE}」：openai gpt-test，超时 600s。"
            "分析期间会写进度，不会一直空白。",
            "正在读取项目代码上下文…",
            "项目还没有代码，直接按需求拆单。",
        ]
        assert {(x["ticket_id"], x["agent_type"], x["level"], x["from_status"], x["to_status"])
                for x in progress} == {(None, "ProductAgent", "info", "analyzing", "analyzing")}

        assert len(env.calls["execute"]) == 1
        call = env.calls["execute"][0]
        context = dict(call["context"])
        assert callable(context.pop("on_step"))
        assert call["action"] == ACTION
        assert context == {
            "title": REQ_TITLE, "description": REQ_DESC, "priority": "high",
            "project_id": PROJECT_ID, "existing_files": [], "existing_code": {},
            "project_traits": [],
        }
        assert call["req_status"] == "analyzing"
        assert call["analyzing"] is True
        assert call["llm"] == LLM_CTX
        assert _llm_ctx() == NO_LLM_CTX, "执行完要清 LLM 上下文"
        assert env.calls["memory"] == [PROJECT_ID]

        assert _sse(env, "agent_working") == [("agent_working", {
            "agent": "ProductAgent", "action": ACTION, "requirement_id": REQ_ID,
        })]
        phases = env.calls["thought"]
        assert [p for p, _ in phases] == ["start", "done"]
        assert phases[0][1] == {"title": REQ_TITLE}
        assert phases[1][1]["result"] is env.agent_result
        assert isinstance(phases[1][1]["elapsed_ms"], int)
        _assert_released(env)
    _run(body, tmp_path, monkeypatch)


@pytest.mark.parametrize("llm, expected", [
    (dict(api_format="cli", cli_type="claude", cli_model="opus", model="x",
          cli_timeout=900, timeout=60), "：CLI claude，超时 900s。"),
    (dict(api_format="cli", cli_type="", cli_model="opus"), "：CLI opus，超时 1800s。"),
    (dict(api_format="cli"), "：CLI，超时 1800s。"),
    (dict(api_format="", model="m1", timeout=45), "：unknown m1，超时 45s。"),
    (dict(), "：unknown，超时 1800s。"),
])
def test_llm_label_and_timeout_in_announcement(tmp_path, monkeypatch, llm, expected):
    """开场文案里的模型名和超时：CLI 取 cli_type 再取 cli_model；超时取 cli_timeout、timeout、1800。"""
    async def body(env):
        env.set_llm(**llm)
        await _handle(env)
        first = _msgs(await _logs(env, "progress"))[0]
        assert expected in first
    _run(body, tmp_path, monkeypatch)


def test_code_context_is_passed_to_agent(tmp_path, monkeypatch):
    async def body(env):
        env.code_ctx = {"file_list": ["a.py", "b.py"], "code": {"a.py": "x = 1"}}
        await _handle(env)
        assert _msgs(await _logs(env, "progress"))[2] == "已读取 2 个文件、1 段代码，开始理解项目。"
        context = env.calls["execute"][0]["context"]
        assert context["existing_files"] == ["a.py", "b.py"]
        assert context["existing_code"] == {"a.py": "x = 1"}
    _run(body, tmp_path, monkeypatch)


def test_code_context_failure_falls_back_to_plain_requirement(tmp_path, monkeypatch):
    async def body(env):
        env.code_ctx_error = RuntimeError("仓库不存在")
        await _handle(env)
        assert _msgs(await _logs(env, "progress"))[2] == (
            "读取代码上下文失败（仓库不存在），将按需求原文拆单。"
        )
        context = env.calls["execute"][0]["context"]
        assert (context["existing_files"], context["existing_code"]) == ([], {})
        assert (await _req(env))["status"] == "in_progress"
    _run(body, tmp_path, monkeypatch)


@pytest.mark.parametrize("traits, expected", [
    ('["engine:ue5", "pipeline:game"]', ["engine:ue5", "pipeline:game"]),
    ("not json", []),
    (None, []),
])
def test_project_traits_passed_to_agent(tmp_path, monkeypatch, traits, expected):
    async def body(env):
        await _handle(env)
        assert env.calls["execute"][0]["context"]["project_traits"] == expected
    _run(body, tmp_path, monkeypatch, traits=traits)


def test_agent_steps_and_heartbeat_are_logged(tmp_path, monkeypatch):
    """Agent 经 on_step 报的进度落日志；心跳文案带上最近一步和超时。"""
    async def body(env):
        async def hook(context):
            await context["on_step"]("正在拆分工单")
            env.hb_gate.set()
            for _ in range(400):
                if await _logs(env, "heartbeat"):
                    break
                await env.real_sleep(0.005)
        env.agent_hook = hook
        await _handle(env)

        assert _msgs(await _logs(env, "progress"))[-1] == "正在拆分工单"
        beats = await _logs(env, "heartbeat")
        assert _msgs(beats) == [analysis_progress_message(20, "正在拆分工单", 600)]
        assert (beats[0]["from_status"], beats[0]["to_status"]) == ("analyzing", "analyzing")
        _assert_released(env)
    _run(body, tmp_path, monkeypatch)


def test_heartbeat_text_is_pinned():
    """心跳文案的原文。上一条拿函数自己的返回值当期望，文案改了也看不出来。"""
    assert analysis_progress_message(80, "正在调用 LLM 拆单", 1800) == (
        "PRD 分析仍在进行（已 80s / 超时 1800s）：正在调用 LLM 拆单"
    )
    assert analysis_progress_message(20.9, None, 120.5) == (
        "PRD 分析仍在进行（已 20s / 超时 120s）：等待 LLM"
    )
    # 现状：只有空白的步骤名不算空，不回落到默认值，去掉空白后冒号后面什么都没有。
    assert analysis_progress_message(20, "  ", 120) == "PRD 分析仍在进行（已 20s / 超时 120s）："


def test_heartbeat_failure_is_swallowed(tmp_path, monkeypatch):
    async def body(env):
        real_log = env.orch._log

        async def flaky_log(pid, rid, tid, agent, action, *a, **kw):
            if action == "heartbeat":
                env.calls["hb_fail"].append(1)
                raise RuntimeError("库忙")
            return await real_log(pid, rid, tid, agent, action, *a, **kw)
        env.orch._log = flaky_log

        async def hook(context):
            env.hb_gate.set()
            for _ in range(400):
                if env.calls["hb_fail"]:
                    break
                await env.real_sleep(0.005)
        env.agent_hook = hook
        await _handle(env)

        assert env.calls["hb_fail"] == [1]
        assert (await _req(env))["status"] == "in_progress"
        _assert_released(env)
    _run(body, tmp_path, monkeypatch)


# ════════════════════ 3. Agent 失败 ════════════════════

@pytest.mark.parametrize("result, message", [
    ({"status": "error", "message": "LLM 超时"}, "需求分析失败: LLM 超时"),
    ({"status": "failed"}, "需求分析失败: 未知错误"),
    ({}, "需求分析失败: 未知错误"),
])
def test_agent_failure_reverts_to_submitted(tmp_path, monkeypatch, result, message):
    """Agent 回传非 success：写 error 日志，需求退回已提交，不发 `requirement_error`。"""
    async def body(env):
        env.agent_result = result
        await _handle(env)

        assert (await _req(env))["status"] == "submitted"
        err = [x for x in await _logs(env) if x["level"] == "error"]
        assert [(x["action"], x["from_status"], x["to_status"], x["detail"]["message"])
                for x in err] == [("error", "analyzing", "analyzing", message)]
        assert await _tickets(env) == []
        assert [e for e, _ in _sse(env)] == ["agent_working"]
        assert [p for p, _ in env.calls["thought"]] == ["start", "done"]
        assert env.calls["process"] == []
        assert env.calls["git"] == []
        assert _llm_ctx() == NO_LLM_CTX
        _assert_released(env)
    _run(body, tmp_path, monkeypatch)


def test_agent_exception_reverts_and_publishes_error(tmp_path, monkeypatch):
    async def body(env):
        env.agent_error = RuntimeError("CLI 崩了")
        await _handle(env)

        await _assert_reverted(env, "CLI 崩了")
        assert [e for e, _ in _sse(env)] == ["agent_working", "requirement_error"]
        assert [p for p, _ in env.calls["thought"]] == ["start"]
        assert await _tickets(env) == []
        assert env.calls["process"] == []
        # 现状：异常路径跳过了 clear_llm_context，上下文留着这条需求的信息。
        assert _llm_ctx() == LLM_CTX
    _run(body, tmp_path, monkeypatch)


def test_cancellation_propagates_and_leaves_requirement_analyzing(tmp_path, monkeypatch):
    """现状：分析被取消时异常原样抛出，需求停在分析中，不写日志也不发事件。"""
    async def body(env):
        env.agent_error = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await _handle(env)

        assert (await _req(env))["status"] == "analyzing"
        assert [x for x in await _logs(env) if x["level"] == "error"] == []
        assert _sse(env, "requirement_error") == []
        _assert_released(env)
    _run(body, tmp_path, monkeypatch)


def test_cancelled_analysis_is_picked_up_by_resume_poll(tmp_path, monkeypatch):
    """取消之后需求停在分析中、占用标记已释放，下一轮 `_resume_stuck_analyses` 会把它重新拆一遍。

    现状：续跑日志写的是「进程重启后中断」，被取消的情况也用这句话。
    """
    async def body(env):
        env.agent_error = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await _handle(env)

        env.agent_error = None
        await env.orch._resume_stuck_analyses()
        await asyncio.gather(*_stray_tasks())      # 续跑是 create_task 出去的

        assert len(env.calls["execute"]) == 2
        assert (await _req(env))["status"] == "in_progress"
        assert len(await _tickets(env)) == 2
        zombie = await _logs(env, "zombie_reset")
        assert [(x["agent_type"], x["level"]) for x in zombie] == [("Orchestrator", "warning")]
        assert _msgs(zombie) == ["需求分析在进程重启后中断，正在重新开始 PRD 分析。"]
        _assert_released(env)
    _run(body, tmp_path, monkeypatch)


def test_error_handler_failure_is_swallowed(tmp_path, monkeypatch):
    """连错误日志都写不进去：不往外抛，需求状态原样，占用标记照常释放。"""
    async def body(env):
        async def broken_log(*a, **kw):
            raise RuntimeError("库挂了")
        env.orch._log = broken_log
        await _handle(env)

        assert (await _req(env))["status"] == "analyzing"
        assert env.calls["execute"] == []
        assert env.sse == []
        _assert_released(env)
    _run(body, tmp_path, monkeypatch)


# ════════════════════ 4. 记录分析结果 ════════════════════

def test_prd_saved_and_artifact_recorded(tmp_path, monkeypatch):
    async def body(env):
        env.agent_result = _result(_tk("A"), _tk("B"), prd_summary="# PRD\n冲刺")
        await _handle(env)

        assert (await _req(env))["prd_content"] == "# PRD\n冲刺"
        arts = await env.db.fetch_all(
            "SELECT * FROM artifacts WHERE requirement_id = ?", (REQ_ID,)
        )
        assert len(arts) == 1
        art = dict(arts[0])
        assert art["id"].startswith("ART")
        assert (art["project_id"], art["ticket_id"], art["type"], art["path"]) == (
            PROJECT_ID, None, "prd", None,
        )
        assert art["name"] == f"PRD - {REQ_TITLE}"
        assert art["content"] == "# PRD\n冲刺"
        assert json.loads(art["metadata"]) == {"ticket_count": 2}
        assert [x for x in await _logs(env) if x["level"] == "warning"] == []
        assert env.calls["git_files"] == []
    _run(body, tmp_path, monkeypatch)


def test_rule_engine_fallback_is_flagged(tmp_path, monkeypatch):
    async def body(env):
        env.agent_result = _result(_tk("A"), _tk("B"), prd_summary="[规则引擎] 简单拆单")
        await _handle(env)
        warn = [x for x in await _logs(env) if x["level"] == "warning"]
        assert [(x["action"], x["detail"]["message"]) for x in warn] == [
            ("info", "[WARNING] LLM 不可用，使用规则引擎降级拆单"),
        ]
        assert (await _req(env))["status"] == "in_progress"
    _run(body, tmp_path, monkeypatch)


@pytest.mark.parametrize("fallback, mark", [(True, " (judge fallback)"), (False, "")])
def test_consistency_vote_is_logged(tmp_path, monkeypatch, fallback, mark):
    async def body(env):
        vote = {"n_candidates": 3, "best_index": 1, "reasoning": "理" * 200,
                "fallback": fallback}
        env.agent_result = _result(_tk("A"), _tk("B"), _consistency_vote=vote)
        await _handle(env)

        logs = await _logs(env, "consistency_vote")
        assert len(logs) == 1
        assert logs[0]["detail"]["message"] == (
            f"🗳️ 拆单投票: 3 候选 → 选 #1{mark} | {'理' * 150}"
        )
        assert logs[0]["detail"]["consistency_vote"] == vote
        assert (logs[0]["from_status"], logs[0]["to_status"]) == (None, None)
    _run(body, tmp_path, monkeypatch)


def test_prd_files_go_through_git(tmp_path, monkeypatch):
    async def body(env):
        env.agent_result = _result(_tk("A"), _tk("B"), files={"docs/prd.md": "# PRD"})
        await _handle(env)
        assert env.calls["git_files"] == [
            (PROJECT_ID, None, REQ_ID, "ProductAgent", ACTION, env.agent_result),
        ]
    _run(body, tmp_path, monkeypatch)


# ════════════════════ 5. 建工单 ════════════════════

@pytest.mark.parametrize("complexity, count, expected", [
    ("simple", 3, "architecture_done"),
    ("complex", 1, "architecture_done"),
    ("medium", 1, "architecture_done"),
    ("medium", 2, "planning_done"),
    ("medium", 3, "pending"),
    ("complex", 2, "pending"),
    (None, 2, "planning_done"),         # 没给复杂度按 medium 算
])
def test_initial_status_by_scale(tmp_path, monkeypatch, complexity, count, expected):
    """按规模跳过阶段：simple 或只有一张，直接到架构完成；medium 且不超过两张，到策划完成。"""
    async def body(env):
        result = _result(*[_tk(f"T{i}") for i in range(count)])
        if complexity is None:
            result.pop("complexity")
        else:
            result["complexity"] = complexity
        env.agent_result = result
        await _handle(env)

        assert [t["status"] for t in await _tickets(env)] == [expected] * count
        # 现状：建单日志里的目标状态固定写 pending，和工单真实的起始状态无关。
        created = await _logs(env, "create")
        assert [(x["from_status"], x["to_status"]) for x in created] == [(None, "pending")] * count
    _run(body, tmp_path, monkeypatch)


def test_non_dict_entries_count_toward_scale(tmp_path, monkeypatch):
    """现状：规模按回传的原始条数算。不是字典的条目不建工单，但计入条数。"""
    async def body(env):
        env.agent_result = _result(_tk("A"), "junk", complexity="medium")
        await _handle(env)

        tickets = await _tickets(env)
        assert [(t["title"], t["status"]) for t in tickets] == [("A", "planning_done")]
        assert _sse(env, "requirement_decomposed")[0][1]["ticket_count"] == 1
    _run(body, tmp_path, monkeypatch)


def test_ticket_fields_and_defaults(tmp_path, monkeypatch):
    async def body(env):
        env.agent_result = _result(
            _tk("登录接口", description="校验口令", type="bug", module="backend",
                priority=1, estimated_hours=2.5),
            {},
            _tk("第三张"),
        )
        await _handle(env)

        tickets = await _tickets(env)
        assert len(tickets) == 3
        assert len({t["id"] for t in tickets}) == 3
        assert all(t["id"].startswith("TK") for t in tickets)
        first, second, _third = tickets
        wanted = ("title", "description", "type", "module", "priority", "sort_order",
                  "estimated_hours")
        assert tuple(first[k] for k in wanted) == (
            "登录接口", "校验口令", "bug", "backend", 1, 0, 2.5,
        )
        assert tuple(second[k] for k in wanted) == (
            "工单 2", "", "feature", "other", 3, 1, None,
        )
        for t in tickets:
            assert (t["requirement_id"], t["project_id"], t["parent_ticket_id"]) == (
                REQ_ID, PROJECT_ID, None,
            )
            assert (t["status"], t["current_owner"], t["assigned_agent"]) == (
                "pending", "product", None,
            )
            assert (t["dependencies"], t["result"], t["use_aigc"]) == ("[]", None, 1)

        created = await _logs(env, "create")
        assert [x["ticket_id"] for x in created] == [t["id"] for t in tickets]
        assert _msgs(created) == [
            "工单「登录接口」已创建，模块: backend",
            f"工单「{second['id']}」已创建，模块: other",
            "工单「第三张」已创建，模块: other",
        ]
    _run(body, tmp_path, monkeypatch, req_extra={"use_aigc": 1})


def test_use_aigc_lookup_failure_defaults_off(tmp_path, monkeypatch):
    async def body(env):
        original = env.db.fetch_one

        async def flaky(sql, params=()):
            if sql.startswith("SELECT use_aigc"):
                raise RuntimeError("查不了")
            return await original(sql, params)
        monkeypatch.setattr(env.db, "fetch_one", flaky)
        await _handle(env)

        assert [t["use_aigc"] for t in await _tickets(env)] == [0, 0]
        assert (await _req(env))["status"] == "in_progress"
    _run(body, tmp_path, monkeypatch, req_extra={"use_aigc": 1})


def test_subtasks_accept_strings_and_dicts(tmp_path, monkeypatch):
    async def body(env):
        only_desc = {"description": "只有描述"}
        env.agent_result = _result(
            _tk("A", subtasks=["写接口", {"title": "写测试", "description": "pytest"}, only_desc]),
            _tk("B"),
        )
        await _handle(env)

        first, second = await _tickets(env)
        rows = await env.db.fetch_all(
            "SELECT * FROM subtasks WHERE ticket_id = ? ORDER BY sort_order", (first["id"],)
        )
        assert [(r["title"], r["description"], r["status"], r["sort_order"]) for r in rows] == [
            ("写接口", "", "pending", 0),
            ("写测试", "pytest", "pending", 1),
            (str(only_desc), "只有描述", "pending", 2),
        ]
        assert all(r["id"].startswith("ST") for r in rows)
        assert await env.db.fetch_all(
            "SELECT id FROM subtasks WHERE ticket_id = ?", (second["id"],)
        ) == []
    _run(body, tmp_path, monkeypatch)


def test_children_inherit_parent_and_are_not_dispatched(tmp_path, monkeypatch):
    async def body(env):
        env.agent_result = _result(
            _tk("父", type="bug", module="frontend", priority=2, children=[
                {"title": "子1", "priority": 5, "estimated_hours": 1, "description": "细活"},
                {},
            ]),
            _tk("另一张"),
        )
        await _handle(env)

        tickets = await _tickets(env)
        tops = [t for t in tickets if t["parent_ticket_id"] is None]
        kids = [t for t in tickets if t["parent_ticket_id"] is not None]
        assert [t["title"] for t in tops] == ["父", "另一张"]
        assert {k["parent_ticket_id"] for k in kids} == {tops[0]["id"]}
        wanted = ("title", "description", "type", "module", "priority", "sort_order",
                  "estimated_hours", "status", "current_owner", "dependencies")
        assert [tuple(k[w] for w in wanted) for k in kids] == [
            ("子1", "细活", "bug", "frontend", 5, 0, 1, "pending", "product", "[]"),
            ("子工单 2", "", "bug", "frontend", 2, 1, None, "pending", "product", "[]"),
        ]
        # 现状：子工单不继承需求级的 AI 生图开关，父工单继承。
        assert [t["use_aigc"] for t in tops] == [1, 1]
        assert [k["use_aigc"] for k in kids] == [0, 0]

        # 现状：子工单不写建单日志，不计入拆单数，也不在这里派单。
        created = await _logs(env, "create")
        assert _msgs(created) == [
            "工单「父」已创建，模块: frontend，含 2 个子工单",
            "工单「另一张」已创建，模块: other",
        ]
        top_ids = [t["id"] for t in tops]
        assert _sse(env, "requirement_decomposed")[0][1] == {
            "requirement_id": REQ_ID, "ticket_count": 2, "ticket_ids": top_ids,
        }
        assert [c["ticket"] for c in env.calls["process"]] == top_ids
    _run(body, tmp_path, monkeypatch, req_extra={"use_aigc": 1})


def test_children_start_pending_even_when_parent_skips_stages(tmp_path, monkeypatch):
    async def body(env):
        env.agent_result = _result(
            _tk("父", children=[{"title": "子"}]), complexity="simple",
        )
        await _handle(env)
        assert {t["title"]: t["status"] for t in await _tickets(env)} == {
            "父": "architecture_done", "子": "pending",
        }
    _run(body, tmp_path, monkeypatch)


# ════════════════════ 6. 回填依赖 ════════════════════

def test_dependencies_backfilled_with_real_ids(tmp_path, monkeypatch):
    """下标换成真实工单号；自引用、越界下标、认不出的字符串丢掉；`TK-` 开头的字符串原样留。"""
    async def body(env):
        env.agent_result = _result(
            _tk("A"),
            _tk("B", dependencies=[0]),
            _tk("C", dependencies=[0, 1, 2, 9, "TK-external", "junk", -1]),
            _tk("D", dependencies=[3]),
            _tk("E", dependencies=None),
        )
        await _handle(env)

        a, b, c, d, e = await _tickets(env)
        assert json.loads(b["dependencies"]) == [a["id"]]
        assert json.loads(c["dependencies"]) == [a["id"], b["id"], "TK-external"]
        assert (a["dependencies"], d["dependencies"], e["dependencies"]) == ("[]", "[]", "[]")

        # 现状：建单日志里的依赖按下标取标题，不滤自引用，所以 C、D 把自己也列进去了。
        assert _msgs(await _logs(env, "create")) == [
            "工单「A」已创建，模块: other",
            "工单「B」已创建，模块: other，依赖: A",
            "工单「C」已创建，模块: other，依赖: A, B, C",
            "工单「D」已创建，模块: other，依赖: D",
            "工单「E」已创建，模块: other",
        ]
    _run(body, tmp_path, monkeypatch)


def test_dependencies_are_backfilled_before_decomposed_event(tmp_path, monkeypatch):
    """`requirement_decomposed` 发出的那一刻，库里的依赖已经从占位的 `[]` 换成了工单号。"""
    async def body(env):
        env.agent_result = _result(_tk("A"), _tk("B", dependencies=[0]))
        seen = []

        async def publish(pid, event, payload):
            env.sse.append((event, payload))
            if event == "requirement_decomposed":
                req = await _req(env)
                seen.append((
                    req["status"],
                    [json.loads(t["dependencies"]) for t in await _tickets(env)],
                ))
        monkeypatch.setattr(orch_module.event_manager, "publish_to_project", publish)
        await _handle(env)

        a, b = await _tickets(env)
        assert seen == [("decomposed", [[], [a["id"]]])]
    _run(body, tmp_path, monkeypatch)


def test_dependency_on_untitled_ticket_uses_index_label(tmp_path, monkeypatch):
    async def body(env):
        env.agent_result = _result({}, _tk("B", dependencies=[0]))
        await _handle(env)
        assert _msgs(await _logs(env, "create"))[1] == "工单「B」已创建，模块: other，依赖: 工单0"
    _run(body, tmp_path, monkeypatch)


def test_log_omits_dependencies_when_none_resolve(tmp_path, monkeypatch):
    """依赖全是认不出的东西时，建单日志不带依赖信息，落库的依赖也是空。"""
    async def body(env):
        env.agent_result = _result(_tk("A", dependencies=[9, "junk", -1]), _tk("B"))
        await _handle(env)
        a, _b = await _tickets(env)
        assert a["dependencies"] == "[]"
        assert _msgs(await _logs(env, "create"))[0] == "工单「A」已创建，模块: other"
    _run(body, tmp_path, monkeypatch)


def test_string_dependency_on_itself_is_dropped(tmp_path, monkeypatch):
    """字符串形式的工单号也滤自引用。

    工单号是现生成的，Agent 的回传里写不出自己的号。这里在 B 的建单日志写入时，
    把 B、A 的真实工单号追加进 B 的依赖列表，回填那一遍读到的就是带自引用的输入。
    """
    async def body(env):
        deps, ids = [], []
        real_log = env.orch._log

        async def log(pid, rid, tid, agent, action, *a, **kw):
            if action == "create":
                ids.append(tid)
                if len(ids) == 2:
                    deps.extend([ids[1], ids[0]])
            return await real_log(pid, rid, tid, agent, action, *a, **kw)
        env.orch._log = log

        env.agent_result = _result(_tk("A"), _tk("B", dependencies=deps))
        await _handle(env)
        a, b = await _tickets(env)
        assert deps == [b["id"], a["id"]]
        assert json.loads(b["dependencies"]) == [a["id"]]
    _run(body, tmp_path, monkeypatch)


def test_dependency_indexes_follow_filtered_list(tmp_path, monkeypatch):
    """现状：依赖下标按滤掉非字典条目之后的列表算。

    Agent 回传里夹一条坏数据，它后面的下标就整体错一位：按原始下标 B、C 都依赖 A，
    落库后 B 指向自己被滤掉，C 指向了 B。
    """
    async def body(env):
        env.agent_result = _result(
            "junk",
            _tk("A"),
            _tk("B", dependencies=[1]),
            _tk("C", dependencies=[1]),
        )
        await _handle(env)
        a, b, c = await _tickets(env)
        assert a["dependencies"] == "[]"
        assert b["dependencies"] == "[]"
        assert json.loads(c["dependencies"]) == [b["id"]]
    _run(body, tmp_path, monkeypatch)


# ════════════════════ 7. 收尾：状态、里程碑、分支、派单 ════════════════════

def test_decompose_marks_progress_and_dispatches_in_order(tmp_path, monkeypatch):
    async def body(env):
        env.agent_result = _result(_tk("A"), _tk("B"), _tk("C"))
        await _handle(env)

        ids = [t["id"] for t in await _tickets(env)]
        assert (await _req(env))["status"] == "in_progress"
        logs = await _logs(env, "decompose")
        assert [(x["from_status"], x["to_status"], x["detail"]["message"]) for x in logs] == [
            ("analyzing", "decomposed", "需求已拆分为 3 个工单"),
        ]
        assert _sse(env) == [
            ("agent_working", {
                "agent": "ProductAgent", "action": ACTION, "requirement_id": REQ_ID,
            }),
            ("requirement_decomposed", {
                "requirement_id": REQ_ID, "ticket_count": 3, "ticket_ids": ids,
            }),
        ]
        assert env.calls["milestone"] == [{
            "args": (PROJECT_ID, REQ_ID, REQ_TITLE, REQ_DESC),
            "kw": {"ticket_count": 3}, "req_status": "decomposed",
        }]
        assert env.calls["process"] == [
            {"ticket": tid, "req_status": "in_progress"} for tid in ids
        ]
        assert _llm_ctx() == NO_LLM_CTX
        _assert_released(env)
    _run(body, tmp_path, monkeypatch)


def test_milestone_failure_is_not_fatal(tmp_path, monkeypatch):
    async def body(env):
        env.milestone_error = RuntimeError("里程碑表坏了")
        await _handle(env)
        assert (await _req(env))["status"] == "in_progress"
        assert len(env.calls["process"]) == 2
        assert _sse(env, "requirement_error") == []
    _run(body, tmp_path, monkeypatch)


def test_milestone_is_associated_before_branch_is_created(tmp_path, monkeypatch):
    """里程碑关联在建分支之前：关联时还没有任何 Git 调用，需求上也还没有分支名。"""
    async def body(env):
        import api.milestones as ms_module
        inner = ms_module.auto_associate_requirement
        seen = []

        async def spy(*a, **kw):
            seen.append((list(env.calls["git"]), (await _req(env))["branch_name"]))
            return await inner(*a, **kw)
        monkeypatch.setattr(ms_module, "auto_associate_requirement", spy)
        await _handle(env)

        assert seen == [([], None)]
        assert len(env.calls["git"]) == 4
        assert (await _req(env))["branch_name"]
    _run(body, tmp_path, monkeypatch)


@pytest.mark.parametrize("primary", ["main", "master"])
def test_branch_created_from_develop_and_recorded(tmp_path, monkeypatch, primary):
    async def body(env):
        env.git.primary = primary
        await _handle(env)

        branch = (await _req(env))["branch_name"]
        assert re.fullmatch(r"feat/\d{8}-req-hr0001", branch)
        assert env.calls["git"] == [
            ("primary",), ("ensure", "develop", primary),
            ("switch", "develop"), ("create", branch),
        ]
        logs = [x for x in await _logs(env) if x["agent_type"] == "Orchestrator"]
        assert [(x["action"], x["from_status"], x["to_status"], x["detail"]["message"])
                for x in logs] == [
            ("info", "decomposed", "decomposed", f"已创建开发分支: {branch}"),
        ]
    _run(body, tmp_path, monkeypatch)


def test_switch_failure_still_creates_branch(tmp_path, monkeypatch):
    async def body(env):
        env.git.switch_ok = False
        await _handle(env)
        branch = (await _req(env))["branch_name"]
        assert branch and env.calls["git"][-1] == ("create", branch)
    _run(body, tmp_path, monkeypatch)


def test_branch_create_failure_leaves_no_branch(tmp_path, monkeypatch):
    async def body(env):
        env.git.create_ok = False
        await _handle(env)

        req = await _req(env)
        assert (req["branch_name"], req["status"]) == (None, "in_progress")
        assert [x for x in await _logs(env) if x["agent_type"] == "Orchestrator"] == []
        assert len(env.calls["process"]) == 2
    _run(body, tmp_path, monkeypatch)


def test_git_error_is_not_fatal(tmp_path, monkeypatch):
    async def body(env):
        env.git.error = RuntimeError("不是仓库")
        await _handle(env)

        req = await _req(env)
        assert (req["branch_name"], req["status"]) == (None, "in_progress")
        assert env.calls["git"] == []
        assert len(env.calls["process"]) == 2
        assert _sse(env, "requirement_error") == []
    _run(body, tmp_path, monkeypatch)


@pytest.mark.parametrize("tickets", [[], None, "missing", ["junk"]])
def test_zero_tickets_still_goes_in_progress(tmp_path, monkeypatch, tickets):
    """现状：一张工单都没拆出来，需求照样走到进行中，分支照建。"""
    async def body(env):
        result = _result()
        if tickets == "missing":
            result.pop("tickets")
        else:
            result["tickets"] = tickets
        env.agent_result = result
        await _handle(env)

        req = await _req(env)
        assert req["status"] == "in_progress"
        assert req["branch_name"]
        assert await _tickets(env) == []
        assert _sse(env, "requirement_decomposed")[0][1] == {
            "requirement_id": REQ_ID, "ticket_count": 0, "ticket_ids": [],
        }
        assert _msgs(await _logs(env, "decompose")) == ["需求已拆分为 0 个工单"]
        assert env.calls["process"] == []
        _assert_released(env)
    _run(body, tmp_path, monkeypatch)


# ════════════════════ 8. 拆单中途出错 ════════════════════

def test_midway_failure_keeps_created_tickets_and_reverts(tmp_path, monkeypatch):
    """现状：拆单不在事务里。第二张出错时前面的已经落库，需求退回已提交，重试会再建一遍。"""
    async def body(env):
        env.agent_result = _result(_tk("A"), _tk("B", subtasks=None), _tk("C"))
        await _handle(env)

        await _assert_reverted(env, "NoneType")
        assert [t["title"] for t in await _tickets(env)] == ["A", "B"]
        assert (await _req(env))["prd_content"] == "PRD 摘要"
        assert await env.db.fetch_all(
            "SELECT id FROM artifacts WHERE requirement_id = ?", (REQ_ID,)
        ) == []
        assert env.calls["process"] == []
        assert env.calls["git"] == []
        assert _llm_ctx() == NO_LLM_CTX
    _run(body, tmp_path, monkeypatch)


def test_bad_prd_summary_goes_to_error_path(tmp_path, monkeypatch):
    async def body(env):
        env.agent_result = _result(_tk("A"), prd_summary=None)
        await _handle(env)
        await _assert_reverted(env, "NoneType")
        assert await _tickets(env) == []
    _run(body, tmp_path, monkeypatch)


def test_dispatch_failure_reverts_requirement_after_tickets_exist(tmp_path, monkeypatch):
    """现状：派单抛异常也走同一个兜底。需求从进行中退回已提交，工单和分支都留着。"""
    async def body(env):
        env.process_error = RuntimeError("派单失败")
        await _handle(env)

        await _assert_reverted(env, "派单失败")
        assert len(env.calls["process"]) == 1, "第一张就抛了，后面的不再派"
        assert len(await _tickets(env)) == 2
        assert (await _req(env))["branch_name"]
    _run(body, tmp_path, monkeypatch)
