"""`_handle_agent_result` 各 Agent 分支的特征测试。

特征测试只记录**现在的行为**，不评判对错。它是拆分 `_handle_agent_result`
的安全网：分支搬到别的模块之后，这里任何一条变红都说明搬运改了行为。
方案文档：docs/20261124_01_代码重构方案.md（R0 第 3 步、R2 第 1 步）。

每条用例断言四样东西：

1. 工单状态；
2. `ticket_logs` 的 action / level / from → to；
3. `artifacts` 的类型；
4. 这次结果有没有走到函数尾部。

第 4 条最容易在拆分时丢。函数有两种出口：一种在分支里直接 `return`，
状态写完就结束；另一种落到函数尾部，发 `ticket_status_changed` 并立刻
调用 `process_ticket` 继续流转。两种出口的后果不同，所以每条用例都用
`_assert_tail` 或 `_assert_no_tail` 钉住。

夹具沿用 `test_orchestrator_skill_branch.py` 的做法：真实 SQLite（必须跑
`init_tables()`），只把会递归派单、连 SSE、碰 Git、调 LLM 的依赖打桩。
`_log`、`_write_phase_comment`、`_apply_fragment_closeout`、
`_acceptance_retry_count` 都是真跑。
"""
import asyncio
import json
from collections import defaultdict
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

import database as database_module
import orchestrator as orch_module
from database import Database
from orchestrator import TicketOrchestrator

PROJECT_ID = "P-RB"
REQ_ID = "REQ-20261124-rb0001"
TICKET_ID = "TK-20261124-rb0001"
TITLE = "登录页"
TS = "2026-11-24T00:00:00Z"

HARD_TERMINAL = ["blocked", "cancelled", "testing_done", "deployed", "done", "completed"]


class _AnyStatus:
    """规则表替身：任何状态都算「还有下一条规则」。

    函数尾部只在「新状态命中规则」时才继续派单。用它之后，
    `dispatched` 非空就等价于「这次结果走到了尾部」。
    """

    def __contains__(self, status):
        return True


@asynccontextmanager
async def _env(tmp_path, monkeypatch, *, initial_status="pending"):
    db_file = tmp_path / "rb.db"

    original_db = database_module.db
    test_db = Database(db_path=str(db_file))
    await test_db.connect()
    await test_db.init_tables()          # 建表 + 迁移，缺一不可
    database_module.db = test_db
    monkeypatch.setattr(orch_module, "db", test_db, raising=False)

    # traits 为空：`_sop_stages_for` 返回 []，`_apply_fragment_closeout` 真跑并放行。
    await test_db.insert("projects", {
        "id": PROJECT_ID, "name": "rb", "traits": "[]",
        "created_at": TS, "updated_at": TS,
    })
    await test_db.insert("requirements", {
        "id": REQ_ID, "project_id": PROJECT_ID, "title": "需求",
        "description": "描述", "created_at": TS, "updated_at": TS,
    })
    await test_db.insert("tickets", {
        "id": TICKET_ID, "project_id": PROJECT_ID, "requirement_id": REQ_ID,
        "title": TITLE, "description": "账号密码登录",
        "type": "feature", "module": "auth", "status": initial_status,
        "created_at": TS, "updated_at": TS,
    })

    env = SimpleNamespace(
        db=test_db, sse=[], dispatched=[], calls=defaultdict(list),
        stages={},          # action -> SOP stage，供 `_sop_stage_for` 返回
        git_result=None,    # `_handle_git_files` 的返回值
        on_git=None,        # `_handle_git_files` 期间执行的回调，模拟并发改状态
    )

    # ---- 模块级依赖 ----
    async def fake_publish(pid, event, payload):
        env.sse.append((event, payload))
    monkeypatch.setattr(orch_module.event_manager, "publish_to_project", fake_publish)

    def fake_distill(pid, tid):
        env.calls["distill"].append((pid, tid))
    monkeypatch.setattr(orch_module, "_fire_knowledge_distill", fake_distill)

    import failure_library as fl_module

    async def fake_mark_resolved(tid):
        env.calls["fl_resolved"].append(tid)
        return 0
    monkeypatch.setattr(fl_module.failure_library, "mark_resolved", fake_mark_resolved)

    import api.milestones as milestones_module

    async def fake_refresh(pid):
        env.calls["milestones"].append(pid)
    monkeypatch.setattr(milestones_module, "refresh_all_milestones", fake_refresh)

    import hooks.registry as hooks_module

    async def fake_emit(ctx, blocking=False):
        env.calls["hook"].append(ctx)
    monkeypatch.setattr(hooks_module.hook_registry, "emit", fake_emit)

    # `_log` 会把日志镜像到 backend/logs/session_<req>/，测试不该往仓库里写文件。
    import session_logger as sl_module

    async def no_transcript(*a, **kw):
        return None
    monkeypatch.setattr(sl_module.session_logger, "log_event", no_transcript)

    # 函数尾部固定 sleep 0.5s，换成只让出一次事件循环。
    real_sleep = asyncio.sleep

    async def fast_sleep(delay, *a, **kw):
        await real_sleep(0)
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    # ---- orchestrator 实例：绕过 __init__（它会实例化全部 Agent 并连事件总线）----
    orch = TicketOrchestrator.__new__(TicketOrchestrator)
    orch._HARD_TERMINAL = set(HARD_TERMINAL)

    async def fake_process(pid, tid):
        env.dispatched.append(tid)
    orch.process_ticket = fake_process

    async def fake_rules(pid, traits_json=None, ticket_type=None):
        return _AnyStatus()
    orch._get_rules_for_project = fake_rules

    async def fake_stage(pid, action, ticket_type=None):
        return env.stages.get(action)
    orch._sop_stage_for = fake_stage

    async def fake_git(pid, tid, rid, agent_name, action, result):
        env.calls["git"].append({
            "agent": agent_name, "action": action,
            "had_media": "_media_files" in result,
        })
        if env.on_git:
            await env.on_git()
        return env.git_result
    orch._handle_git_files = fake_git

    async def fake_memory(**kw):
        env.calls["memory"].append(kw)
    orch._write_memory = fake_memory

    async def fake_dependents(pid, tid):
        env.calls["dependents"].append((pid, tid))
    orch._trigger_dependents = fake_dependents

    async def fake_req_completion(pid, rid):
        env.calls["req_completion"].append((pid, rid))
    orch._check_requirement_completion = fake_req_completion

    async def fake_openspec(pid, tid, stage_label=None):
        env.calls["openspec"].append((pid, tid, stage_label))
    orch._maybe_openspec_verify = fake_openspec

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


async def _call(env, agent_name, action, result, *, ticket_extra=None):
    """走真实入口 `_handle_agent_result`。`ticket` 参数用库里的当前状态拼。"""
    row = await env.db.fetch_one("SELECT status FROM tickets WHERE id = ?", (TICKET_ID,))
    ticket = {"id": TICKET_ID, "requirement_id": REQ_ID, "title": TITLE,
              "type": "feature", "status": row["status"]}
    ticket.update(ticket_extra or {})
    await env.orch._handle_agent_result(
        PROJECT_ID, TICKET_ID, ticket, agent_name, action, result,
    )
    await asyncio.sleep(0)      # 让 create_task 起的后台任务跑完


async def _ticket(env) -> dict:
    return await env.db.fetch_one("SELECT * FROM tickets WHERE id = ?", (TICKET_ID,))


async def _logs(env) -> list:
    rows = await env.db.fetch_all(
        "SELECT agent_type, action, level, from_status, to_status, detail "
        "FROM ticket_logs WHERE ticket_id = ? ORDER BY rowid", (TICKET_ID,)
    )
    return [dict(r, detail=json.loads(r["detail"])) for r in rows]


def _keys(logs) -> list:
    return [(l["action"], l["level"], l["from_status"], l["to_status"]) for l in logs]


async def _artifacts(env) -> list:
    return await env.db.fetch_all(
        "SELECT type, name, path, content, metadata FROM artifacts "
        "WHERE ticket_id = ? ORDER BY rowid", (TICKET_ID,)
    )


async def _comments(env) -> list:
    return await env.db.fetch_all(
        "SELECT author, phase, content FROM ticket_comments "
        "WHERE ticket_id = ? ORDER BY rowid", (TICKET_ID,)
    )


def _status_events(env) -> list:
    return [p for e, p in env.sse if e == "ticket_status_changed"]


def _assert_tail(env, from_status, to_status, agent):
    """结果落到了函数尾部：发状态事件，并继续派单。"""
    assert _status_events(env) == [
        {"ticket_id": TICKET_ID, "from": from_status, "to": to_status, "agent": agent}
    ]
    assert env.dispatched == [TICKET_ID]


def _assert_no_tail(env):
    """结果在分支里收尾：不发状态事件，也不在这里继续派单。"""
    assert _status_events(env) == []
    assert env.dispatched == []


# ════════════════ 公共前置：终态门闩 / error 止血 / 媒体 / closeout ════════════════

@pytest.mark.parametrize("terminal", HARD_TERMINAL)
def test_terminal_ticket_ignores_late_result(tmp_path, monkeypatch, terminal):
    async def body(env):
        await _call(env, "DevAgent", "fix_issues",
                    {"status": "success", "files": {"a.py": "x"}})
        t = await _ticket(env)
        assert t["status"] == terminal
        assert t["result"] is None
        logs = await _logs(env)
        assert _keys(logs) == [("stale_ignored", "warning", terminal, terminal)]
        assert logs[0]["agent_type"] == "Orchestrator"
        assert logs[0]["detail"]["ignored_agent"] == "DevAgent"
        assert logs[0]["detail"]["ignored_action"] == "fix_issues"
        assert logs[0]["detail"]["result_status"] == "success"
        assert env.calls["git"] == []
        assert await _artifacts(env) == []
        _assert_no_tail(env)
    _run(body, tmp_path, monkeypatch, initial_status=terminal)


@pytest.mark.parametrize("result, expected_error", [
    ({"status": "error", "message": "未知任务: run_engine_compile"}, "未知任务: run_engine_compile"),
    ({"status": "error", "error": "boom"}, "boom"),
    ({"status": "error"}, "Agent 返回 error"),
])
def test_error_result_blocks_ticket(tmp_path, monkeypatch, result, expected_error):
    async def body(env):
        await _call(env, "DevAgent", "run_engine_compile", dict(result))
        t = await _ticket(env)
        assert t["status"] == "blocked"
        assert json.loads(t["result"]) == result

        logs = await _logs(env)
        assert _keys(logs) == [("blocked", "error", "architecture_done", "blocked")]
        assert logs[0]["agent_type"] == "DevAgent"
        assert logs[0]["detail"]["action"] == "run_engine_compile"
        assert logs[0]["detail"]["error"] == expected_error
        assert logs[0]["detail"]["raw_result"] == result

        assert [p for e, p in env.sse if e == "ticket_blocked"] == [{
            "ticket_id": TICKET_ID, "from": "architecture_done", "to": "blocked",
            "agent": "DevAgent", "action": "run_engine_compile", "error": expected_error,
        }]
        assert len(env.calls["hook"]) == 1
        assert env.calls["hook"][0].tool_name == "agent:DevAgent.run_engine_compile"
        assert len(env.calls["diagnose"]) == 1
        assert env.calls["diagnose"][0]["blocked_from_status"] == "architecture_done"
        assert env.calls["diagnose"][0]["error_msg"] == expected_error

        assert env.calls["git"] == []           # error 不写 Git
        assert await _artifacts(env) == []
        _assert_no_tail(env)
    _run(body, tmp_path, monkeypatch, initial_status="architecture_done")


def test_media_files_kept_out_of_saved_result(tmp_path, monkeypatch):
    """二进制媒体不进 `tickets.result`，只留路径；但要原样交给 Git 写入。"""
    async def body(env):
        await _call(env, "ArtAgent", "design_art",
                    {"art_content": "规范", "_media_files": {"art/a.png": b"\x89PNG"}})
        saved = json.loads((await _ticket(env))["result"])
        assert saved["media_paths"] == ["art/a.png"]
        assert "_media_files" not in saved
        assert env.calls["git"] == [
            {"agent": "ArtAgent", "action": "design_art", "had_media": True}
        ]
    _run(body, tmp_path, monkeypatch)


def test_fragment_closeout_short_circuits_branches(tmp_path, monkeypatch):
    """`_apply_fragment_closeout` 返回 True 时，后面的 Agent 分支一律不跑。"""
    async def body(env):
        async def closeout(*a, **kw):
            return True
        env.orch._apply_fragment_closeout = closeout
        await _call(env, "DevAgent", "develop", {"status": "success", "files": {}})
        t = await _ticket(env)
        assert t["status"] == "architecture_done"
        assert t["result"] is None
        assert await _logs(env) == []
        assert await _artifacts(env) == []
        _assert_no_tail(env)
    _run(body, tmp_path, monkeypatch, initial_status="architecture_done")


# ════════════════ 在分支里收尾的 Agent（不走尾部） ════════════════

def test_html_prototype(tmp_path, monkeypatch):
    async def body(env):
        html = "<html>" + "x" * 3000
        await _call(env, "DevAgent", "write_html_prototype",
                    {"html_content": html, "core_mechanics": "三消"})
        assert (await _ticket(env))["status"] == "html_prototype_done"
        assert _keys(await _logs(env)) == [
            ("write_html_prototype", "info", "pending", "html_prototype_done")
        ]
        arts = await _artifacts(env)
        assert [(a["type"], a["name"]) for a in arts] == [
            ("html_prototype", f"HTML原型 - {TITLE}")
        ]
        assert arts[0]["content"] == html[:2000]
        comments = await _comments(env)
        assert [(c["author"], c["phase"]) for c in comments] == [
            ("DevAgent", "html_prototype_done")
        ]
        assert "三消" in comments[0]["content"]
        _assert_no_tail(env)
    _run(body, tmp_path, monkeypatch)


def test_html_prototype_wins_over_skill_dispatch(tmp_path, monkeypatch):
    """分发顺序：HTML 原型判断排在 skill 判断之前。带 skill_id 也走 HTML 分支。"""
    async def body(env):
        await _call(env, "DevAgent", "write_html_prototype",
                    {"html_content": "<html/>", "skill_id": "some-skill"})
        assert (await _ticket(env))["status"] == "html_prototype_done"
        assert [a["type"] for a in await _artifacts(env)] == ["html_prototype"]
    _run(body, tmp_path, monkeypatch)


def test_artist_agent_with_assets(tmp_path, monkeypatch):
    async def body(env):
        env.git_result = {"commit_hash": "abc123", "files": ["assets/a.png"]}
        await _call(env, "ArtistAgent", "generate_assets", {
            "assets_total": 5, "sourced": 2, "placeholder": 2, "skipped": 1,
            "_media_files": {"assets/a.png": b"x"},
        })
        assert (await _ticket(env))["status"] == "assets_ready"
        logs = await _logs(env)
        assert _keys(logs) == [("generate_assets", "info", "pending", "assets_ready")]
        assert logs[0]["detail"]["media_paths"] == ["assets/a.png"]
        assert logs[0]["detail"]["git_files"] == ["assets/a.png"]
        arts = await _artifacts(env)
        assert [a["type"] for a in arts] == ["asset_manifest"]
        assert json.loads(arts[0]["metadata"]) == {
            "total": 5, "sourced": 2, "placeholder": 2, "skipped": 1,
        }
        comments = await _comments(env)
        assert [(c["author"], c["phase"]) for c in comments] == [("ArtistAgent", "assets_ready")]
        assert "2 个占位图需替换" in comments[0]["content"]
        assert "1 项需人工提供" in comments[0]["content"]
        assert "`assets/a.png`" in comments[0]["content"]
        _assert_no_tail(env)
    _run(body, tmp_path, monkeypatch)


def test_artist_agent_without_assets_writes_no_manifest(tmp_path, monkeypatch):
    async def body(env):
        await _call(env, "ArtistAgent", "generate_assets", {})
        assert (await _ticket(env))["status"] == "assets_ready"
        assert await _artifacts(env) == []
        comments = await _comments(env)
        assert len(comments) == 1 and "⚠️" not in comments[0]["content"]
        _assert_no_tail(env)
    _run(body, tmp_path, monkeypatch)


@pytest.mark.parametrize("agent, action, result, status, art_type, content", [
    ("ArtAgent", "design_art", {"art_content": "视觉规范正文"},
     "art_design_done", "art_design", "视觉规范正文"),
    ("UXAgent", "design_ux", {"ux_content": "交互稿", "component_wireframe": "abc"},
     "ux_design_done", "ux_design", "交互稿"),
    ("PlannerAgent", "write_prd", {"prd_content": "PRD 正文", "acceptance_criteria": "能登录"},
     "planning_done", "prd", "PRD 正文"),
])
def test_design_agents(tmp_path, monkeypatch, agent, action, result, status, art_type, content):
    async def body(env):
        await _call(env, agent, action, dict(result))
        assert (await _ticket(env))["status"] == status
        assert _keys(await _logs(env)) == [(action, "info", "pending", status)]
        arts = await _artifacts(env)
        assert [(a["type"], a["content"], a["metadata"]) for a in arts] == [
            (art_type, content, None)
        ]
        comments = await _comments(env)
        assert [(c["author"], c["phase"]) for c in comments] == [(agent, status)]
        _assert_no_tail(env)
    _run(body, tmp_path, monkeypatch)


def test_design_agent_details(tmp_path, monkeypatch):
    """三个设计类分支各自特有的字段。"""
    async def body(env):
        await _call(env, "ArtAgent", "design_art", {"design_tokens": {"primary": "#fff"}})
        art = (await _artifacts(env))[0]
        assert json.loads(art["metadata"]) == {"tokens": {"primary": "#fff"}}
        # 没有 art_content 时，产物内容退回整个 result JSON
        assert art["content"] == (await _ticket(env))["result"]

        await _call(env, "UXAgent", "design_ux", {"component_wireframe": "abc"})
        assert (await _logs(env))[-1]["detail"]["message"] == "UX 设计完成：3 字符"

        await _call(env, "PlannerAgent", "write_prd", {"acceptance_criteria": "能登录"})
        assert "能登录" in (await _comments(env))[-1]["content"]
    _run(body, tmp_path, monkeypatch)


def test_ue_editor_agent_success(tmp_path, monkeypatch):
    async def body(env):
        await _call(env, "UEEditorAgent", "generate_ue_content", {
            "status": "success", "message": "已生成 BP_Player",
            "imported": ["a"], "assets": ["b"],
        })
        assert (await _ticket(env))["status"] == "ue_content_done"
        logs = await _logs(env)
        assert _keys(logs) == [("complete", "info", "pending", "ue_content_done")]
        assert logs[0]["detail"]["imported"] == ["a"]
        assert [a["type"] for a in await _artifacts(env)] == ["ue_content"]
        assert [(c["author"], c["phase"]) for c in await _comments(env)] == [
            ("UEEditorAgent", "ue_content_done")
        ]
        _assert_no_tail(env)
    _run(body, tmp_path, monkeypatch)


def test_ue_editor_agent_failure(tmp_path, monkeypatch):
    async def body(env):
        await _call(env, "UEEditorAgent", "generate_ue_content", {
            "status": "failed", "message": "蓝图编译失败", "failed": ["BP_X"],
        })
        assert (await _ticket(env))["status"] == "ue_content_failed"
        logs = await _logs(env)
        assert _keys(logs) == [("reject", "warning", "pending", "ue_content_failed")]
        assert logs[0]["detail"]["error"] == "蓝图编译失败"
        assert logs[0]["detail"]["failed"] == ["BP_X"]
        assert await _artifacts(env) == []
        assert await _comments(env) == []
        _assert_no_tail(env)
    _run(body, tmp_path, monkeypatch)


# ════════════════ ArchitectAgent ════════════════

def test_architect_agent_full(tmp_path, monkeypatch):
    async def body(env):
        env.git_result = {"commit_hash": "c1", "files": ["docs/arch.md"]}
        await _call(env, "ArchitectAgent", "design_architecture", {
            "architecture": "前后端分离", "estimated_hours": 6,
            "_consistency_vote": {"n_candidates": 3, "best_index": 1, "reasoning": "更简单"},
        })
        t = await _ticket(env)
        assert t["status"] == "architecture_done"
        assert t["estimated_hours"] == 6
        assert t["estimated_completion"]

        logs = await _logs(env)
        assert _keys(logs) == [
            ("consistency_vote", "info", None, None),
            ("complete", "info", "pending", "architecture_done"),
        ]
        assert logs[1]["detail"]["estimated_hours"] == 6
        assert logs[1]["detail"]["git_commit"] == "c1"
        assert logs[1]["detail"]["git_files"] == ["docs/arch.md"]

        arts = await _artifacts(env)
        assert [a["type"] for a in arts] == ["architecture"]
        assert json.loads(arts[0]["metadata"]) == {"git": env.git_result}

        assert len(env.calls["memory"]) == 1
        mem = env.calls["memory"][0]
        assert mem["mem_type"] == "decision"
        assert mem["agent_type"] == "ArchitectAgent"
        assert mem["tags"] == ["architecture", "decision"]

        assert [(c["author"], c["phase"]) for c in await _comments(env)] == [
            ("ArchitectAgent", "architecture_done")
        ]
        _assert_tail(env, "pending", "architecture_done", "ArchitectAgent")
    _run(body, tmp_path, monkeypatch)


def test_architect_agent_minimal(tmp_path, monkeypatch):
    async def body(env):
        await _call(env, "ArchitectAgent", "design_architecture", {})
        t = await _ticket(env)
        assert t["status"] == "architecture_done"
        assert t["estimated_hours"] == 4                 # 默认工时
        assert _keys(await _logs(env)) == [
            ("complete", "info", "pending", "architecture_done")
        ]
        arts = await _artifacts(env)
        assert [(a["type"], a["metadata"]) for a in arts] == [("architecture", None)]
        assert env.calls["memory"] == []                 # 没有架构摘要就不写记忆
        _assert_tail(env, "pending", "architecture_done", "ArchitectAgent")
    _run(body, tmp_path, monkeypatch)


# ════════════════ DevAgent ════════════════

@pytest.mark.parametrize("result_status, stage, status, log_action, level", [
    ("success", None, "h5_typecheck_passed", "complete", "info"),
    ("success", {"success_status": "tsc_ok"}, "tsc_ok", "complete", "info"),
    ("failed", None, "h5_typecheck_failed", "reject", "warning"),
    ("failed", {"reject_status": "tsc_bad"}, "tsc_bad", "reject", "warning"),
])
def test_dev_agent_h5_typecheck(tmp_path, monkeypatch, result_status, stage,
                                status, log_action, level):
    async def body(env):
        if stage:
            env.stages["run_h5_typecheck"] = stage
        await _call(env, "DevAgent", "run_h5_typecheck", {
            "status": result_status,
            "errors": [{"file": "a.ts", "line": 3, "code": "TS2304", "msg": "Cannot find name"}],
        })
        assert (await _ticket(env))["status"] == status
        logs = await _logs(env)
        assert _keys(logs) == [(log_action, level, "development_done", status)]
        if log_action == "reject":
            assert logs[0]["detail"]["err_brief"] == "a.ts:3 TS2304 Cannot find name"
        assert await _artifacts(env) == []
        _assert_no_tail(env)
    _run(body, tmp_path, monkeypatch, initial_status="development_done")


def test_dev_agent_development_failed(tmp_path, monkeypatch):
    async def body(env):
        await _call(env, "DevAgent", "develop", {
            "status": "development_failed", "message": "零文件",
            "code_gen_failure": {"file_count": 0, "files": [], "notes": "LLM 超时"},
        })
        assert (await _ticket(env))["status"] == "development_failed"
        logs = await _logs(env)
        assert _keys(logs) == [("reject", "error", "architecture_done", "development_failed")]
        assert logs[0]["detail"]["reason"] == "零文件"
        assert logs[0]["detail"]["notes"] == "LLM 超时"
        assert await _artifacts(env) == []
        assert await _comments(env) == []
        _assert_no_tail(env)
    _run(body, tmp_path, monkeypatch, initial_status="architecture_done")


def test_dev_agent_self_test_blocking(tmp_path, monkeypatch):
    async def body(env):
        await _call(env, "DevAgent", "develop", {
            "status": "success", "files": {"Source/A.cpp": "x"},
            "self_test": {
                "summary": "lint 失败", "ue_lint_summary": "1 blocking",
                "ue_blocking_issues": [
                    {"rule": "R1", "file": "Source/A.cpp", "line": 10, "msg": "bad"},
                ],
            },
        })
        assert (await _ticket(env))["status"] == "self_test_failed"
        logs = await _logs(env)
        assert _keys(logs) == [("reject", "warning", "architecture_done", "self_test_failed")]
        assert logs[0]["detail"]["err_brief"] == "[R1] A.cpp:10 bad"
        assert logs[0]["detail"]["summary"] == "1 blocking"
        assert await _artifacts(env) == []
        _assert_no_tail(env)
    _run(body, tmp_path, monkeypatch, initial_status="architecture_done")


def test_dev_agent_success(tmp_path, monkeypatch):
    async def body(env):
        env.git_result = {"commit_hash": "d1", "files": ["src/a.py", "src/b.py"]}
        await _call(env, "DevAgent", "develop", {
            "status": "success",
            "files": {"src/a.py": "x", "src/b.py": "y"},
            "dev_result": {"notes": "完成登录"},
            "self_test": {"summary": "3/3 通过",
                          "screenshots": [{"url": "/s/1.png"}, "/s/2.png"]},
            "_media_files": {"shots/1.png": b"x"},
        })
        assert (await _ticket(env))["status"] == "development_done"

        logs = await _logs(env)
        assert _keys(logs) == [("complete", "info", "architecture_done", "development_done")]
        detail = logs[0]["detail"]
        assert detail["files_count"] == 3                      # 2 个代码文件 + 1 个媒体路径
        assert detail["files"] == ["a.py", "b.py", "1.png"]
        assert detail["file_paths"] == ["src/a.py", "src/b.py", "shots/1.png"]
        assert detail["screenshots"] == ["/s/1.png", "/s/2.png"]
        assert detail["git_commit"] == "d1"

        comments = await _comments(env)
        assert [(c["author"], c["phase"]) for c in comments] == [("DevAgent", "development_done")]
        assert "共提交 2 个文件" in comments[0]["content"]
        assert "3/3 通过" in comments[0]["content"]
        assert "备注：完成登录" in comments[0]["content"]

        arts = await _artifacts(env)
        assert [a["type"] for a in arts] == ["code"]
        assert json.loads(arts[0]["metadata"]) == {"git": env.git_result}
        _assert_tail(env, "architecture_done", "development_done", "DevAgent")
    _run(body, tmp_path, monkeypatch, initial_status="architecture_done")


@pytest.mark.parametrize("raced_to", ["blocked", "testing_done", "deployed"])
def test_dev_agent_drops_result_when_ticket_moved_on(tmp_path, monkeypatch, raced_to):
    """写 development_done 之前会再读一次库。期间工单已进终态或越过开发，就丢弃。"""
    async def body(env):
        async def race():
            await env.db.update("tickets", {"status": raced_to}, "id = ?", (TICKET_ID,))
        env.on_git = race
        await _call(env, "DevAgent", "develop", {"status": "success", "files": {"a.py": "x"}})
        t = await _ticket(env)
        assert t["status"] == raced_to
        assert t["result"] is None
        assert await _logs(env) == []
        assert await _artifacts(env) == []
        _assert_no_tail(env)
    _run(body, tmp_path, monkeypatch, initial_status="architecture_done")


# ════════════════ ReviewAgent ════════════════

@pytest.mark.parametrize("score, sop_cfg, level", [
    (5, None, "warning"),
    (8, None, "info"),
    (8, {"pass_score": 9}, "warning"),
    ("N/A", None, "info"),          # 解析不了的分数按 7 分算
])
def test_review_agent(tmp_path, monkeypatch, score, sop_cfg, level):
    async def body(env):
        extra = {"_sop_config": sop_cfg} if sop_cfg else None
        await _call(env, "ReviewAgent", "code_review",
                    {"score": score, "issues": ["命名混乱"], "suggestions": ["拆函数"]},
                    ticket_extra=extra)
        assert (await _ticket(env))["status"] == "review_passed"       # 低分也不阻塞
        logs = await _logs(env)
        assert _keys(logs) == [("code_review", level, "development_done", "review_passed")]
        assert logs[0]["detail"]["pass_score"] == (sop_cfg or {}).get("pass_score", 7)
        arts = await _artifacts(env)
        assert [a["type"] for a in arts] == ["code_review"]
        assert json.loads(arts[0]["metadata"]) == {"score": score}
        _assert_tail(env, "development_done", "review_passed", "ReviewAgent")
    _run(body, tmp_path, monkeypatch, initial_status="development_done")


def test_review_agent_metadata_with_git(tmp_path, monkeypatch):
    async def body(env):
        env.git_result = {"commit_hash": "r1", "files": []}
        await _call(env, "ReviewAgent", "code_review", {"score": 9})
        art = (await _artifacts(env))[0]
        assert json.loads(art["metadata"]) == {"git": env.git_result, "score": 9}
        assert (await _logs(env))[0]["detail"]["git_commit"] == "r1"
    _run(body, tmp_path, monkeypatch, initial_status="development_done")


# ════════════════ ProductAgent.acceptance_review ════════════════

@pytest.mark.parametrize("raw_status", ["acceptance_passed", "success", None])
def test_acceptance_passed(tmp_path, monkeypatch, raw_status):
    """非标状态（如 "success"）和缺省状态都按通过处理。"""
    async def body(env):
        result = {"screenshot_path": "/s/acc.png"}
        if raw_status is not None:
            result["status"] = raw_status
        await _call(env, "ProductAgent", "acceptance_review", result)
        assert (await _ticket(env))["status"] == "acceptance_passed"
        logs = await _logs(env)
        assert _keys(logs) == [("accept", "info", "review_passed", "acceptance_passed")]
        assert logs[0]["detail"]["screenshots"] == ["/s/acc.png"]
        assert env.calls["fl_resolved"] == [TICKET_ID]
        assert env.calls["distill"] == [(PROJECT_ID, TICKET_ID)]
        assert await _artifacts(env) == []
        _assert_tail(env, "review_passed", "acceptance_passed", "ProductAgent")
    _run(body, tmp_path, monkeypatch, initial_status="review_passed")


def test_acceptance_rejected(tmp_path, monkeypatch):
    async def body(env):
        await _call(env, "ProductAgent", "acceptance_review", {
            "status": "acceptance_rejected", "review": {"issues": ["按钮无响应"]},
        })
        assert (await _ticket(env))["status"] == "acceptance_rejected"
        logs = await _logs(env)
        assert _keys(logs) == [("reject", "info", "review_passed", "acceptance_rejected")]
        assert "按钮无响应" in logs[0]["detail"]["message"]
        assert env.calls["fl_resolved"] == []
        assert env.calls["distill"] == []
        _assert_tail(env, "review_passed", "acceptance_rejected", "ProductAgent")
    _run(body, tmp_path, monkeypatch, initial_status="review_passed")


def test_acceptance_degraded_retries_then_blocks(tmp_path, monkeypatch):
    """LLM 降级：前两次直接重派验收，第三次转 blocked。全程不记 reject，不走尾部。"""
    async def body(env):
        degraded = {"status": "acceptance_rejected", "degraded": True,
                    "degrade_reason": "CLI 超时"}
        await _call(env, "ProductAgent", "acceptance_review", dict(degraded))
        assert (await _ticket(env))["status"] == "review_passed"
        await _call(env, "ProductAgent", "acceptance_review", dict(degraded))
        assert (await _ticket(env))["status"] == "review_passed"
        await _call(env, "ProductAgent", "acceptance_review", dict(degraded))
        assert (await _ticket(env))["status"] == "blocked"

        logs = await _logs(env)
        assert _keys(logs) == [
            ("acceptance_retry", "warning", "review_passed", "review_passed"),
            ("acceptance_retry", "warning", "review_passed", "review_passed"),
            ("blocked", "warning", "review_passed", "blocked"),
        ]
        assert logs[0]["detail"]["degraded"] is True
        assert logs[0]["detail"]["degrade_reason"] == "CLI 超时"
        assert env.calls["fl_resolved"] == []
        assert env.calls["distill"] == []
        _assert_no_tail(env)
    _run(body, tmp_path, monkeypatch, initial_status="review_passed")


def test_acceptance_degraded_uses_sop_trigger_status(tmp_path, monkeypatch):
    async def body(env):
        env.stages["acceptance_review"] = {"trigger_on": "smoke_test_passed"}
        await _call(env, "ProductAgent", "acceptance_review", {"degraded": True})
        assert (await _ticket(env))["status"] == "smoke_test_passed"
        assert (await _logs(env))[0]["detail"]["degrade_reason"] == "LLM 降级"
        _assert_no_tail(env)
    _run(body, tmp_path, monkeypatch, initial_status="smoke_test_passed")


# ════════════════ 没有专属分支的结果 ════════════════

@pytest.mark.parametrize("agent, action", [
    ("ProductAgent", "analyze_requirement"),     # ProductAgent 只有 acceptance_review 有分支
    ("MysteryAgent", "do_something"),
])
def test_unhandled_agent_keeps_status_but_still_reaches_tail(tmp_path, monkeypatch, agent, action):
    """现状：状态不变、不写库，但仍发状态事件并继续派单。

    这就是多处注释提到的「同一条 rule 反复命中」。这里只把现状钉住；
    改成显式 blocked 属于行为变更，见重构方案 R2 第 1 步。
    """
    async def body(env):
        await _call(env, agent, action, {"status": "success"})
        t = await _ticket(env)
        assert t["status"] == "development_done"
        assert t["result"] is None
        assert await _logs(env) == []
        assert await _artifacts(env) == []
        _assert_tail(env, "development_done", "development_done", agent)
    _run(body, tmp_path, monkeypatch, initial_status="development_done")


# ════════════════ TestAgent ════════════════

@pytest.mark.parametrize("result_status, stage, status, log_action, level", [
    ("success", None, "h5_playtest_passed", "complete", "info"),
    ("success", {"success_status": "play_ok"}, "play_ok", "complete", "info"),
    ("failed", None, "h5_playtest_failed", "reject", "warning"),
    ("failed", {"reject_status": "play_bad"}, "play_bad", "reject", "warning"),
])
def test_test_agent_h5_playtest(tmp_path, monkeypatch, result_status, stage,
                                status, log_action, level):
    async def body(env):
        if stage:
            env.stages["run_h5_playtest"] = stage
        await _call(env, "TestAgent", "run_h5_playtest", {
            "status": result_status, "runtime_skipped": True,
            "errors": [{"source": "console", "msg": "boom"}],
        })
        assert (await _ticket(env))["status"] == status
        logs = await _logs(env)
        assert _keys(logs) == [(log_action, level, "development_done", status)]
        if log_action == "complete":
            assert "（运行时跳过）" in logs[0]["detail"]["message"]
            assert env.calls["openspec"] == [(PROJECT_ID, TICKET_ID, "h5_playtest")]
        else:
            assert logs[0]["detail"]["err_brief"] == "console: boom"
            assert env.calls["openspec"] == []
        assert await _artifacts(env) == []
        _assert_no_tail(env)
    _run(body, tmp_path, monkeypatch, initial_status="development_done")


@pytest.mark.parametrize("raw_status, stage, status", [
    ("testing_done", None, "testing_done"),
    ("success", None, "testing_done"),                                   # 非标状态按通过算
    ("testing_done", {"success_status": "smoke_test_passed"}, "smoke_test_passed"),
])
def test_test_agent_passed(tmp_path, monkeypatch, raw_status, stage, status):
    async def body(env):
        if stage:
            env.stages["run_tests"] = stage
        await _call(env, "TestAgent", "run_tests", {
            "status": raw_status,
            "test_result": {"summary": "10/10",
                            "screenshots": [{"label": "首页", "url": "/s/home.png"}]},
        })
        assert (await _ticket(env))["status"] == status
        logs = await _logs(env)
        assert _keys(logs) == [("complete", "info", "acceptance_passed", status)]
        assert logs[0]["detail"]["screenshots"] == ["/s/home.png"]

        arts = await _artifacts(env)
        assert [(a["type"], a["name"], a["path"]) for a in arts] == [
            ("test", f"测试报告 - {TITLE}", None),
            ("screenshot", "首页", "/s/home.png"),
        ]
        assert env.calls["fl_resolved"] == [TICKET_ID]
        assert env.calls["dependents"] == [(PROJECT_ID, TICKET_ID)]
        assert env.calls["req_completion"] == [(PROJECT_ID, REQ_ID)]
        assert env.calls["milestones"] == [PROJECT_ID]
        _assert_tail(env, "acceptance_passed", status, "TestAgent")
    _run(body, tmp_path, monkeypatch, initial_status="acceptance_passed")


def test_test_agent_failed(tmp_path, monkeypatch):
    async def body(env):
        # 声明了 success_status 也不影响失败结果
        env.stages["run_tests"] = {"success_status": "smoke_test_passed"}
        await _call(env, "TestAgent", "run_tests", {
            "status": "testing_failed",
            "test_result": {"summary": {"pass_rate": 40, "issues": ["登录失败", "注册失败"]}},
        })
        assert (await _ticket(env))["status"] == "testing_failed"
        logs = await _logs(env)
        assert _keys(logs) == [("reject", "info", "acceptance_passed", "testing_failed")]
        assert logs[0]["detail"]["pass_rate"] == 40
        assert logs[0]["detail"]["issues"] == ["登录失败", "注册失败"]
        arts = await _artifacts(env)
        assert [(a["type"], a["name"]) for a in arts] == [
            ("test", f"测试报告(未通过) - {TITLE}")
        ]
        assert env.calls["fl_resolved"] == []
        assert env.calls["dependents"] == []
        assert env.calls["req_completion"] == []
        assert env.calls["milestones"] == []
        _assert_tail(env, "acceptance_passed", "testing_failed", "TestAgent")
    _run(body, tmp_path, monkeypatch, initial_status="acceptance_passed")


# ════════════════ DeployAgent ════════════════

def test_deploy_agent_packaged_is_intermediate(tmp_path, monkeypatch):
    """SOP 声明 run_ci_deploy 的成功状态不是 deployed 时，只推进状态，在分支里收尾。"""
    async def body(env):
        env.stages["run_ci_deploy"] = {"success_status": "packaged"}
        await _call(env, "DeployAgent", "run_ci_deploy", {
            "deploy_result": {"strategy": "ue_package", "build_type": "Development",
                              "build_id": "B1"},
        })
        t = await _ticket(env)
        assert t["status"] == "packaged"
        assert t["completed_at"] is None
        logs = await _logs(env)
        assert _keys(logs) == [("complete", "info", "smoke_test_passed", "packaged")]
        assert logs[0]["detail"]["build_id"] == "B1"
        assert await _artifacts(env) == []
        assert env.calls["req_completion"] == []
        assert env.calls["dependents"] == []
        _assert_no_tail(env)
    _run(body, tmp_path, monkeypatch, initial_status="smoke_test_passed")


@pytest.mark.parametrize("action", ["run_ci_deploy", "deploy"])
def test_deploy_agent_deployed(tmp_path, monkeypatch, action):
    async def body(env):
        await _call(env, "DeployAgent", action, {
            "deploy_result": {"preview_url": "http://127.0.0.1:9000/preview"},
        })
        t = await _ticket(env)
        assert t["status"] == "deployed"
        assert t["completed_at"]
        logs = await _logs(env)
        assert _keys(logs) == [("complete", "info", "smoke_test_passed", "deployed")]
        assert logs[0]["detail"]["preview_url"] == "http://127.0.0.1:9000/preview"
        assert "http://127.0.0.1:9000/preview" in logs[0]["detail"]["message"]
        assert [a["type"] for a in await _artifacts(env)] == ["deploy_config"]
        assert env.calls["req_completion"] == [(PROJECT_ID, REQ_ID)]
        assert env.calls["milestones"] == [PROJECT_ID]
        assert env.calls["dependents"] == [(PROJECT_ID, TICKET_ID)]
        _assert_tail(env, "smoke_test_passed", "deployed", "DeployAgent")
    _run(body, tmp_path, monkeypatch, initial_status="smoke_test_passed")
