"""orchestrator 里含 L3 导入的 7 个方法和 2 个模块级函数的特征测试。

覆盖范围：
  _maybe_openspec_verify / _finalize_openspec_after_done
  _handle_git_files / _build_context / _diagnose_blocked_ticket
  _poll_once / _check_subtasks_complete
  模块级 _synthesize_blocked_diagnosis / _fire_knowledge_distill

这些方法都在函数体里导入 L3 模块（agents.*、actions.*）。测试调的是真方法，
桩一律打在类或源模块的属性上（TestAgent._run_openspec_verify、
actions.diagnose_ticket.DiagnoseTicketAction ……）。所以方法体里无论写
`from agents.test import TestAgent`，还是经 runtime_facade / contracts 取，
断言都成立——改导入方式、把方法搬到 orchestration/ 之后这份测试不用改。
"""
import asyncio
import json
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import database as database_module
import orchestrator as orch_module
from database import Database
from models import TicketStatus
from orchestrator import TicketOrchestrator

PROJECT_ID = "P-L3"
REQ_ID = "REQ-20261125-l30001"
TICKET_ID = "TK-20261125-l30001"
TITLE = "登录页"
TS = "2026-11-25T00:00:00Z"
OLD_TS = "2026-01-01T00:00:00"
CTX = {"project_id": PROJECT_ID, "ticket_id": TICKET_ID}


def _recorder(sink):
    async def fake(*args, **kwargs):
        sink.append((args, kwargs))
    return fake


@asynccontextmanager
async def _env(tmp_path, monkeypatch, *, project=None, ticket=None):
    """临时库 + 一个项目、一条需求、一张工单 + 绕过 __init__ 的编排器。"""
    test_db = Database(db_path=str(tmp_path / "l3.db"))
    await test_db.connect()
    await test_db.init_tables()
    original_db = database_module.db
    database_module.db = test_db
    monkeypatch.setattr(orch_module, "db", test_db, raising=False)
    try:
        await test_db.insert("projects", {
            "id": PROJECT_ID, "name": "l3", "description": "演示项目",
            "traits": "[]", "created_at": TS, "updated_at": TS,
            **(project or {}),
        })
        await test_db.insert("requirements", {
            "id": REQ_ID, "project_id": PROJECT_ID, "title": "需求标题",
            "description": "需求描述", "created_at": TS, "updated_at": TS,
        })
        await test_db.insert("tickets", {
            "id": TICKET_ID, "requirement_id": REQ_ID, "project_id": PROJECT_ID,
            "title": TITLE, "description": "账号密码登录", "type": "feature",
            "module": "auth", "status": "pending",
            "created_at": TS, "updated_at": TS,
            **(ticket or {}),
        })
        env = SimpleNamespace(
            db=test_db, sse=[], calls=[], agents=[], git=[], logs=[],
            commands=[], layer_logs=[], inject_extra={}, tail=[],
        )

        async def fake_publish(*args):
            env.sse.append(args)

        monkeypatch.setattr(
            orch_module.event_manager, "publish_to_project", fake_publish,
        )

        orch = TicketOrchestrator.__new__(TicketOrchestrator)
        orch._log = _recorder(env.logs)
        orch._record_command = _recorder(env.commands)
        orch._add_layer_log = _recorder(env.layer_logs)
        env.orch = orch
        yield env
    finally:
        database_module.db = original_db
        await test_db.disconnect()


def _run(body, tmp_path, monkeypatch, **kw):
    async def main():
        async with _env(tmp_path, monkeypatch, **kw) as env:
            return await body(env)
    return asyncio.run(main())


async def _set_stage(env, stage):
    await env.db.update(
        "tickets", {"openspec_stage": stage}, "id = ?", (TICKET_ID,),
    )


async def _ticket_row(env):
    return await env.db.fetch_one(
        "SELECT * FROM tickets WHERE id = ?", (TICKET_ID,),
    )


async def _stage(env):
    return (await _ticket_row(env))["openspec_stage"]


# ---------------------------------------------------------------- OpenSpec


def _patch_openspec_agents(monkeypatch, env, *, verify=True, verify_error=None,
                           stage_after_verify=None, stage_after_archive="archived"):
    """把 TestAgent / DeployAgent 的 OpenSpec 入口换成记录用的假方法。

    桩打在类上：编排器直接 import 类，或经门面拿到模块再取类，命中的都是同一个类对象。
    """
    from agents.base import BaseAgent
    from agents.deploy import DeployAgent
    from agents.test import TestAgent

    monkeypatch.setattr(BaseAgent, "__init__", lambda self: None)
    env.instances = []

    async def fake_verify(self, ctx, **kwargs):
        env.instances.append(self)
        env.calls.append(("verify", type(self).__name__, dict(ctx), dict(kwargs)))
        if verify_error is not None:
            raise verify_error
        if stage_after_verify is not None:
            await _set_stage(env, stage_after_verify)
        return verify

    async def fake_archive(self, ctx):
        env.instances.append(self)
        env.calls.append(("archive", type(self).__name__, dict(ctx)))
        if stage_after_archive is not None:
            await _set_stage(env, stage_after_archive)

    monkeypatch.setattr(TestAgent, "_run_openspec_verify", fake_verify)
    monkeypatch.setattr(DeployAgent, "_run_openspec_archive", fake_archive)


VERIFY_CALL = ("verify", "TestAgent", CTX, {})
SOFT_VERIFY_CALL = ("verify", "TestAgent", CTX, {"block_on_fail": False})
ARCHIVE_CALL = ("archive", "DeployAgent", CTX)
ARCHIVE_LAYER_LOG = (
    (TICKET_ID, PROJECT_ID),
    {"action": "openspec_archive", "layer": "spec",
     "detail": {"message": "终态收尾 Archive 完成"}},
)


@pytest.mark.parametrize("stage", ["verified", "archived", " verified "])
def test_maybe_verify_skips_finished_stage(tmp_path, monkeypatch, stage):
    async def body(env):
        _patch_openspec_agents(monkeypatch, env)
        await _set_stage(env, stage)
        assert await env.orch._maybe_openspec_verify(PROJECT_ID, TICKET_ID) is True
        assert env.calls == []

    _run(body, tmp_path, monkeypatch)


@pytest.mark.parametrize("stage", [None, "", "applied", "proposed"])
@pytest.mark.parametrize("verify", [True, False])
def test_maybe_verify_returns_agent_answer(tmp_path, monkeypatch, stage, verify):
    async def body(env):
        _patch_openspec_agents(monkeypatch, env, verify=verify)
        await _set_stage(env, stage)
        got = await env.orch._maybe_openspec_verify(
            PROJECT_ID, TICKET_ID, stage_label="testing",
        )
        assert got is verify
        assert env.calls == [VERIFY_CALL]

    _run(body, tmp_path, monkeypatch)


def test_maybe_verify_swallows_agent_error(tmp_path, monkeypatch):
    async def body(env):
        _patch_openspec_agents(monkeypatch, env, verify_error=RuntimeError("boom"))
        await _set_stage(env, "applied")
        assert await env.orch._maybe_openspec_verify(PROJECT_ID, TICKET_ID) is False
        assert env.calls == [VERIFY_CALL]

    _run(body, tmp_path, monkeypatch)


def test_maybe_verify_swallows_db_error(tmp_path, monkeypatch):
    async def body(env):
        _patch_openspec_agents(monkeypatch, env)

        async def boom(*args, **kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr(env.db, "fetch_one", boom)
        assert await env.orch._maybe_openspec_verify(PROJECT_ID, TICKET_ID) is False
        assert env.calls == []

    _run(body, tmp_path, monkeypatch)


def test_maybe_verify_builds_a_new_agent_each_time(tmp_path, monkeypatch):
    async def body(env):
        _patch_openspec_agents(monkeypatch, env)
        await _set_stage(env, "applied")
        await env.orch._maybe_openspec_verify(PROJECT_ID, TICKET_ID)
        await env.orch._maybe_openspec_verify(PROJECT_ID, TICKET_ID)
        assert len(env.instances) == 2
        assert env.instances[0] is not env.instances[1]

    _run(body, tmp_path, monkeypatch)


def test_finalize_unknown_ticket_is_noop(tmp_path, monkeypatch):
    async def body(env):
        _patch_openspec_agents(monkeypatch, env)
        got = await env.orch._finalize_openspec_after_done(PROJECT_ID, "TK-missing")
        assert got is None
        assert env.calls == []
        assert env.layer_logs == []

    _run(body, tmp_path, monkeypatch)


@pytest.mark.parametrize("stage", [None, "", "archived", "drafting"])
def test_finalize_ignores_other_stages(tmp_path, monkeypatch, stage):
    async def body(env):
        _patch_openspec_agents(monkeypatch, env)
        await _set_stage(env, stage)
        assert await env.orch._finalize_openspec_after_done(PROJECT_ID, TICKET_ID) is None
        assert env.calls == []
        assert env.layer_logs == []
        assert await _stage(env) == stage

    _run(body, tmp_path, monkeypatch)


@pytest.mark.parametrize("stage", ["proposed", "applied"])
def test_finalize_stops_when_verify_fails(tmp_path, monkeypatch, stage):
    async def body(env):
        _patch_openspec_agents(monkeypatch, env, verify=False)
        await _set_stage(env, stage)
        await env.orch._finalize_openspec_after_done(PROJECT_ID, TICKET_ID)
        assert env.calls == [SOFT_VERIFY_CALL]
        assert env.layer_logs == []
        assert await _stage(env) == stage

    _run(body, tmp_path, monkeypatch)


@pytest.mark.parametrize("stage", ["proposed", "applied"])
def test_finalize_verifies_then_archives(tmp_path, monkeypatch, stage):
    async def body(env):
        _patch_openspec_agents(monkeypatch, env, stage_after_verify="verified")
        await _set_stage(env, stage)
        await env.orch._finalize_openspec_after_done(PROJECT_ID, TICKET_ID)
        assert env.calls == [SOFT_VERIFY_CALL, ARCHIVE_CALL]
        assert await _stage(env) == "archived"
        assert env.layer_logs == [ARCHIVE_LAYER_LOG]
        assert env.instances[0] is not env.instances[1]

    _run(body, tmp_path, monkeypatch)


def test_finalize_does_not_archive_when_stage_stays(tmp_path, monkeypatch):
    """Verify 返回通过但没把阶段推进到 verified：不归档。"""
    async def body(env):
        _patch_openspec_agents(monkeypatch, env)
        await _set_stage(env, "applied")
        await env.orch._finalize_openspec_after_done(PROJECT_ID, TICKET_ID)
        assert env.calls == [SOFT_VERIFY_CALL]
        assert env.layer_logs == []
        assert await _stage(env) == "applied"

    _run(body, tmp_path, monkeypatch)


def test_finalize_archives_verified_directly(tmp_path, monkeypatch):
    async def body(env):
        _patch_openspec_agents(monkeypatch, env)
        await _set_stage(env, "verified")
        await env.orch._finalize_openspec_after_done(PROJECT_ID, TICKET_ID)
        assert env.calls == [ARCHIVE_CALL]
        assert env.layer_logs == [ARCHIVE_LAYER_LOG]

    _run(body, tmp_path, monkeypatch)


def test_finalize_no_layer_log_when_archive_leaves_stage(tmp_path, monkeypatch):
    async def body(env):
        _patch_openspec_agents(monkeypatch, env, stage_after_archive=None)
        await _set_stage(env, "verified")
        await env.orch._finalize_openspec_after_done(PROJECT_ID, TICKET_ID)
        assert env.calls == [ARCHIVE_CALL]
        assert env.layer_logs == []
        assert await _stage(env) == "verified"

    _run(body, tmp_path, monkeypatch)


def test_finalize_lets_verify_error_propagate(tmp_path, monkeypatch):
    """这个方法没有外层 try：Agent 抛的异常原样冒给调用方。"""
    async def body(env):
        _patch_openspec_agents(monkeypatch, env, verify_error=RuntimeError("boom"))
        await _set_stage(env, "applied")
        with pytest.raises(RuntimeError, match="boom"):
            await env.orch._finalize_openspec_after_done(PROJECT_ID, TICKET_ID)
        assert env.calls == [SOFT_VERIFY_CALL]
        assert env.layer_logs == []

    _run(body, tmp_path, monkeypatch)


# ---------------------------------------------------------------------------
# _handle_git_files：落盘、提交、媒体文件、自动部署 dev
# ---------------------------------------------------------------------------

COMMITTED = {"commit_hash": "c0ffee1", "pushed": True}


def _patch_git(monkeypatch, env, tmp_path, *, git_result=None, exists=True,
               push_status=None, commit_error=None):
    """把 git_manager 单例上用到的方法换成记录用的假方法。"""
    gm = orch_module.git_manager
    env.repo_dir = tmp_path / "repo"
    env.repo_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(gm, "_custom_paths", {}, raising=False)
    monkeypatch.setattr(gm, "repo_exists", lambda pid: exists)
    monkeypatch.setattr(gm, "_repo_path", lambda pid: env.repo_dir)
    monkeypatch.setattr(
        gm, "set_project_path",
        lambda pid, path: env.git.append(("set_project_path", pid, path)),
    )
    monkeypatch.setattr(gm, "get_last_push_status", lambda pid: dict(push_status or {}))

    async def init_repo(pid, name, description=""):
        env.git.append(("init_repo", pid, name, description))
        return str(env.repo_dir)

    async def write_and_commit(pid, files, message, **kwargs):
        env.git.append(("write_and_commit", pid, dict(files), message, kwargs))
        return None if git_result is None else dict(git_result)

    async def write_files_only(pid, files):
        env.git.append(("write_files_only", pid, dict(files)))
        return None if git_result is None else dict(git_result)

    async def get_current_branch(pid):
        return "main"

    async def commit(pid, message, author="AI Agent"):
        env.git.append(("commit", pid, message, author))
        if commit_error is not None:
            raise commit_error
        return "m3d1a00"

    async def push(pid, *args, **kwargs):
        env.git.append(("push", pid))
        return True

    for name, fake in (
        ("init_repo", init_repo), ("write_and_commit", write_and_commit),
        ("write_files_only", write_files_only), ("get_current_branch", get_current_branch),
        ("commit", commit), ("push", push),
    ):
        monkeypatch.setattr(gm, name, fake)


def _patch_deploy(monkeypatch, env, *, error=None):
    from agents.deploy import DeployAgent

    async def fake(cls, project_id, env_name):
        env.calls.append(("deploy_env", cls.__name__, project_id, env_name))
        if error is not None:
            raise error

    monkeypatch.setattr(DeployAgent, "deploy_env", classmethod(fake))


def _git_names(env):
    return [g[0] for g in env.git]


def _command_kinds(env):
    return [c[0][6] for c in env.commands]


async def _git_files(env, result, agent="DevAgent", action="develop", ticket_id=TICKET_ID):
    return await env.orch._handle_git_files(
        PROJECT_ID, ticket_id, REQ_ID, agent, action, result,
    )


DEPLOY_DEV_CALL = ("deploy_env", "DeployAgent", PROJECT_ID, "dev")


@pytest.mark.parametrize("result", [{}, {"files": {}}, {"files": ["a.py"]}, {"files": "a.py"}])
def test_git_files_ignores_results_without_file_map(tmp_path, monkeypatch, result):
    async def body(env):
        _patch_git(monkeypatch, env, tmp_path, git_result=COMMITTED)
        _patch_deploy(monkeypatch, env)
        assert await _git_files(env, result) is None
        assert env.git == [] and env.calls == [] and env.commands == []

    _run(body, tmp_path, monkeypatch)


@pytest.mark.parametrize("agent,deploys", [
    ("DevAgent", True), ("ArchitectAgent", True), ("TestAgent", False), ("ReviewAgent", False),
])
def test_git_files_deploys_dev_only_for_code_agents(tmp_path, monkeypatch, agent, deploys):
    async def body(env):
        _patch_git(monkeypatch, env, tmp_path, git_result=COMMITTED)
        _patch_deploy(monkeypatch, env)
        out = await _git_files(env, {"files": {"src/a.py": "x"}}, agent=agent)
        assert out == {"commit_hash": "c0ffee1", "pushed": True, "branch": "main"}
        assert env.calls == ([DEPLOY_DEV_CALL] if deploys else [])

    _run(body, tmp_path, monkeypatch)


@pytest.mark.parametrize("git_result,expected", [
    (None, None),
    ({"files_written": 1}, {"files_written": 1, "branch": "main"}),
])
def test_git_files_without_commit_hash_skips_commit_record_and_deploy(
    tmp_path, monkeypatch, git_result, expected,
):
    async def body(env):
        _patch_git(monkeypatch, env, tmp_path, git_result=git_result)
        _patch_deploy(monkeypatch, env)
        assert await _git_files(env, {"files": {"src/a.py": "x"}}) == expected
        assert _command_kinds(env) == ["write_file"]
        assert env.calls == [] and env.logs == []

    _run(body, tmp_path, monkeypatch)


def test_git_files_survives_deploy_error(tmp_path, monkeypatch):
    async def body(env):
        _patch_git(monkeypatch, env, tmp_path, git_result=COMMITTED)
        _patch_deploy(monkeypatch, env, error=RuntimeError("deploy down"))
        out = await _git_files(env, {"files": {"src/a.py": "x"}})
        assert out["commit_hash"] == "c0ffee1"
        assert env.calls == [DEPLOY_DEV_CALL]

    _run(body, tmp_path, monkeypatch)


def test_git_files_commit_message_and_command_records(tmp_path, monkeypatch):
    files = {"src/a.py": "1", "src/b.py": "2", "src/c.py": "3", "src/d.py": "4"}
    message = "[DevAgent] 开发: 登录页 (a.py, b.py, c.py +1)"

    async def body(env):
        _patch_git(monkeypatch, env, tmp_path, git_result=COMMITTED)
        _patch_deploy(monkeypatch, env)
        await _git_files(env, {"files": dict(files)})
        assert env.git == [("write_and_commit", PROJECT_ID, files, message, {"agent": "DevAgent"})]
        assert _command_kinds(env) == ["write_file"] * 4 + ["git_commit", "git_push"]
        for args, kwargs in env.commands:
            assert args[:5] == (PROJECT_ID, TICKET_ID, REQ_ID, "DevAgent", "develop")
            assert args[8] == "success" and kwargs == {}
        assert [c[0][5] for c in env.commands] == [0, 1, 2, 3, 4, 5]
        assert [c[0][7] for c in env.commands] == [
            "写入文件: src/a.py", "写入文件: src/b.py", "写入文件: src/c.py", "写入文件: src/d.py",
            f'git commit -m "{message}" → c0ffee1',
            "git push origin main",
        ]
        commit_args = env.commands[4][0]
        assert len(commit_args) == 10 and isinstance(commit_args[9], int)
        assert env.logs == []

    _run(body, tmp_path, monkeypatch)


@pytest.mark.parametrize("action,label", [
    ("design_architecture", "架构设计"), ("develop", "开发"), ("rework", "返工"),
    ("fix_issues", "修复"), ("acceptance_review", "验收"), ("run_tests", "测试"),
    ("polish", "polish"),
])
def test_git_files_action_label_in_commit_message(tmp_path, monkeypatch, action, label):
    async def body(env):
        _patch_git(monkeypatch, env, tmp_path, git_result=COMMITTED)
        _patch_deploy(monkeypatch, env)
        await _git_files(env, {"files": {"src/a.py": "x"}}, agent="ReviewAgent", action=action)
        assert env.git[0][3] == f"[ReviewAgent] {label}: 登录页 (a.py)"

    _run(body, tmp_path, monkeypatch)


def test_git_files_uses_ticket_id_when_ticket_row_is_missing(tmp_path, monkeypatch):
    async def body(env):
        _patch_git(monkeypatch, env, tmp_path, git_result=COMMITTED)
        _patch_deploy(monkeypatch, env)
        await _git_files(env, {"files": {"src/a.py": "x"}}, ticket_id="TK-missing")
        assert env.git[0][3] == "[DevAgent] 开发: TK-missing (a.py)"

    _run(body, tmp_path, monkeypatch)


# ---------------------------------------------------------------------------
# _handle_git_files：推送失败、手动挡、媒体文件、文件名改写、仓库初始化
# ---------------------------------------------------------------------------

UNPUSHED = {"commit_hash": "c0ffee1", "pushed": False}
MEDIA_PATH = "docs/shots/a.png"


def _media_result():
    return {"files": {"docs/r.md": "x"}, "_media_files": {MEDIA_PATH: b"png"}}


def test_git_files_push_failure_logs_default_message(tmp_path, monkeypatch):
    async def body(env):
        _patch_git(monkeypatch, env, tmp_path, git_result=UNPUSHED)
        _patch_deploy(monkeypatch, env)
        out = await _git_files(env, {"files": {"src/a.py": "x"}})
        assert out == {"commit_hash": "c0ffee1", "pushed": False, "branch": "main"}
        assert env.logs == [((
            PROJECT_ID, REQ_ID, TICKET_ID, "DevAgent", "git_push_failed", None, None,
            "DevAgent.develop git push 失败。代码已 commit 但未推送到远端。 工单: 5-l30001。",
            "warn",
        ), {})]
        assert _command_kinds(env) == ["write_file", "git_commit"]
        # 部署段挂在 commit_hash 分支下，和 push 结果无关
        assert env.calls == [DEPLOY_DEV_CALL]

    _run(body, tmp_path, monkeypatch)


def test_git_files_push_failure_uses_push_status_text(tmp_path, monkeypatch):
    async def body(env):
        _patch_git(monkeypatch, env, tmp_path, git_result=UNPUSHED, push_status={
            "title": "远端拒绝", "summary": "分支受保护。", "next_step": "请改用 PR。",
        })
        _patch_deploy(monkeypatch, env)
        await _git_files(env, {"files": {"src/a.py": "x"}})
        assert [entry[0][7] for entry in env.logs] == [
            "DevAgent.develop 远端拒绝。分支受保护。 工单: 5-l30001。请改用 PR。",
        ]

    _run(body, tmp_path, monkeypatch)


def test_git_files_manual_mode_writes_without_commit(tmp_path, monkeypatch):
    async def body(env):
        _patch_git(monkeypatch, env, tmp_path, git_result={"files_written": 1})
        _patch_deploy(monkeypatch, env)
        result = _media_result()
        out = await _git_files(env, result)
        assert out == {"files_written": 1, "branch": "main"}
        assert env.git == [("write_files_only", PROJECT_ID, {"docs/r.md": "x"})]
        assert (env.repo_dir / MEDIA_PATH).read_bytes() == b"png"
        assert "_media_files" not in result
        assert _command_kinds(env) == ["write_file"]
        assert env.calls == []
        assert env.logs == []

    _run(body, tmp_path, monkeypatch, project={"mode": "manual"})


@pytest.mark.parametrize("agent, action, label", [
    ("TestAgent", "run_tests", "测试截图"),
    ("TestAgent", "run_playtest", "Playtest 截图"),
    ("TestAgent", "smoke", "测试截图"),
    ("ArtistAgent", "generate_assets", "资产占位图"),
    ("ArtistAgent", "paint", "美术资产"),
    ("UEEditorAgent", "capture", "UE 编辑器截图"),
    ("ReviewAgent", "review", "媒体文件"),
])
def test_git_files_media_commit_label(tmp_path, monkeypatch, agent, action, label):
    async def body(env):
        _patch_git(monkeypatch, env, tmp_path, git_result=COMMITTED)
        _patch_deploy(monkeypatch, env)
        result = _media_result()
        await _git_files(env, result, agent=agent, action=action)
        assert _git_names(env) == ["write_and_commit", "commit", "push"]
        assert env.git[1] == ("commit", PROJECT_ID, f"[{agent}] {label}: {TITLE}", agent)
        assert env.git[2] == ("push", PROJECT_ID)
        assert (env.repo_dir / MEDIA_PATH).read_bytes() == b"png"
        assert "_media_files" not in result

    _run(body, tmp_path, monkeypatch)


def test_git_files_media_commit_error_does_not_break_main_flow(tmp_path, monkeypatch):
    async def body(env):
        _patch_git(monkeypatch, env, tmp_path, git_result=COMMITTED,
                   commit_error=RuntimeError("media boom"))
        _patch_deploy(monkeypatch, env)
        out = await _git_files(env, _media_result())
        assert out == {"commit_hash": "c0ffee1", "pushed": True, "branch": "main"}
        assert _git_names(env) == ["write_and_commit", "commit"]
        assert (env.repo_dir / MEDIA_PATH).read_bytes() == b"png"
        assert _command_kinds(env) == ["write_file", "git_commit", "git_push"]

    _run(body, tmp_path, monkeypatch)


def test_git_files_without_media_makes_no_extra_commit(tmp_path, monkeypatch):
    async def body(env):
        _patch_git(monkeypatch, env, tmp_path, git_result=COMMITTED)
        _patch_deploy(monkeypatch, env)
        await _git_files(env, {"files": {"src/a.py": "x"}, "_media_files": {}})
        assert _git_names(env) == ["write_and_commit"]

    _run(body, tmp_path, monkeypatch)


def test_git_files_strips_non_ascii_from_code_file_names(tmp_path, monkeypatch):
    async def body(env):
        _patch_git(monkeypatch, env, tmp_path, git_result=COMMITTED)
        _patch_deploy(monkeypatch, env)
        result = {"files": {
            "src/登录_view.py": "a",
            "docs/设计.md": "b",
            "src/ok.py": "c",
            "src/登录.py": "d",
        }}
        await _git_files(env, result)
        keys = list(result["files"])
        assert keys[:3] == ["src/view.py", "docs/设计.md", "src/ok.py"]
        assert re.fullmatch(r"src/module_\d+\.py", keys[3])
        assert list(result["files"].values()) == ["a", "b", "c", "d"]
        # 落盘和写入记录用的都是改写后的名字
        assert env.git[0][2] == result["files"]
        assert [c[0][7] for c in env.commands[:4]] == [f"写入文件: {k}" for k in keys]

    _run(body, tmp_path, monkeypatch)


def test_git_files_registers_custom_repo_path_and_inits_missing_repo(tmp_path, monkeypatch):
    custom = str(tmp_path / "custom")

    async def body(env):
        _patch_git(monkeypatch, env, tmp_path, git_result=COMMITTED, exists=False)
        _patch_deploy(monkeypatch, env)
        await _git_files(env, {"files": {"src/a.py": "x"}})
        assert _git_names(env) == ["set_project_path", "init_repo", "write_and_commit"]
        assert env.git[0] == ("set_project_path", PROJECT_ID, custom)
        assert env.git[1] == ("init_repo", PROJECT_ID, "l3", "演示项目")

    _run(body, tmp_path, monkeypatch, project={"git_repo_path": custom})


def test_git_files_skips_path_registration_for_default_location(tmp_path, monkeypatch):
    from git_manager import PROJECTS_DIR

    async def body(env):
        _patch_git(monkeypatch, env, tmp_path, git_result=COMMITTED)
        _patch_deploy(monkeypatch, env)
        await _git_files(env, {"files": {"src/a.py": "x"}})
        assert _git_names(env) == ["write_and_commit"]

    _run(body, tmp_path, monkeypatch,
         project={"git_repo_path": str(PROJECTS_DIR / PROJECT_ID)})


def test_git_files_skips_path_registration_when_already_registered(tmp_path, monkeypatch):
    async def body(env):
        _patch_git(monkeypatch, env, tmp_path, git_result=COMMITTED)
        _patch_deploy(monkeypatch, env)
        monkeypatch.setattr(orch_module.git_manager, "_custom_paths", {PROJECT_ID: "x"})
        await _git_files(env, {"files": {"src/a.py": "x"}})
        assert _git_names(env) == ["write_and_commit"]

    _run(body, tmp_path, monkeypatch, project={"git_repo_path": str(tmp_path / "custom")})


# ---------------------------------------------------------------- _build_context

KNOWLEDGE = {"project_knowledge": "PK", "domain_knowledge": "DK", "agent_spec": "SPEC"}
WEB_TRAITS = json.dumps(["platform:web", "", "lang:ts"])


def _patch_context_sources(monkeypatch, env, tmp_path, *, memory_error=None,
                           loader_error=None, knowledge=KNOWLEDGE,
                           insights_error=None, repo_error=None, repo_none=False):
    """把 _build_context 读的外部来源换成假的；调用顺序记到 env.calls。"""
    import knowledge_loader
    import memory

    env.repo_dir = tmp_path / "repo"
    env.repo_dir.mkdir(exist_ok=True)

    def fake_repo_path(project_id):
        if repo_error:
            raise repo_error
        return None if repo_none else env.repo_dir

    monkeypatch.setattr(orch_module.git_manager, "_repo_path", fake_repo_path)

    class FakeMemory:
        def __init__(self, project_id):
            env.calls.append(("memory", project_id))
            if memory_error:
                raise memory_error

        async def get_code_context(self):
            return {"file_list": ["src/a.py"], "code": {"src/a.py": "print(1)"}}

        async def get_sibling_tickets(self, requirement_id, exclude_ticket_id=None):
            env.calls.append(("siblings", requirement_id, exclude_ticket_id))
            return [{"id": "TK-sib", "title": "兄弟工单"}]

    class FakeLoader:
        def __init__(self, agent_name, project_id, traits):
            env.calls.append(("loader", agent_name, project_id, list(traits)))

        async def load(self):
            if loader_error:
                raise loader_error
            return dict(knowledge)

    monkeypatch.setattr(memory, "AgentMemory", FakeMemory)
    monkeypatch.setattr(knowledge_loader, "KnowledgeLoader", FakeLoader)

    async def fake_inject(context, ticket):
        env.calls.append(("inject", ticket["id"]))
        context.update(env.inject_extra)

    async def fake_insights(title, project_id):
        env.calls.append(("insights", title, project_id))
        if insights_error:
            raise insights_error
        return "历史经验"

    def fake_docs(project_id, *args, **kwargs):
        env.calls.append(("legacy_docs", project_id))
        return "旧知识库"

    env.orch._make_ticket_progress_callback = lambda pid, tid: ("cb", pid, tid)
    env.orch._inject_rejection_context = fake_inject
    env.orch._fetch_prior_insights = fake_insights
    env.orch._load_knowledge_docs = fake_docs


def _patch_probe(monkeypatch, env, *, answer=True, error=None):
    import actions.ue_editor_control as uec

    async def fake_probe(*args, **kwargs):
        env.calls.append(("probe_ucp", args, kwargs))
        if error:
            raise error
        return answer

    monkeypatch.setattr(uec, "probe_ucp", fake_probe)


def _call_names(env):
    return [c[0] for c in env.calls]


def test_build_context_full_shape(tmp_path, monkeypatch):
    async def body(env):
        _patch_context_sources(monkeypatch, env, tmp_path)
        _patch_probe(monkeypatch, env)
        context = await env.orch._build_context(await _ticket_row(env), "DevAgent")
        assert context == {
            "ticket_id": TICKET_ID,
            "ticket_title": TITLE,
            "ticket_description": "账号密码登录",
            "ticket_type": "feature",
            "module": "auth",
            "project_id": PROJECT_ID,
            "requirement_id": REQ_ID,
            "agent_type": "DevAgent",
            "repo_path": str(env.repo_dir),
            "requirement_description": "需求描述",
            "requirement_title": "需求标题",
            "docs_prefix": "docs/Reqs/l30001/l30001/",
            "src_prefix": "src/auth/",
            "tests_prefix": "tests/l30001/",
            "_ticket_progress_cb": ("cb", PROJECT_ID, TICKET_ID),
            "traits": ["platform:web", "lang:ts"],
            "ue_target_platform": "Win64",
            "ue_target_config": "Development",
            "existing_files": ["src/a.py"],
            "existing_code": {"src/a.py": "print(1)"},
            "sibling_tickets": [{"id": "TK-sib", "title": "兄弟工单"}],
            "project_knowledge": "PK",
            "domain_knowledge": "DK",
            "agent_spec": "SPEC",
            "knowledge_docs": "PK\n\nDK",
            "prior_insights": "历史经验",
            "ucp_available": False,
        }
        assert env.calls == [
            ("inject", TICKET_ID),
            ("memory", PROJECT_ID),
            ("siblings", REQ_ID, TICKET_ID),
            ("loader", "DevAgent", PROJECT_ID, ["platform:web", "lang:ts"]),
            ("insights", TITLE, PROJECT_ID),
        ]

    _run(body, tmp_path, monkeypatch, project={"traits": WEB_TRAITS})


def test_build_context_defaults_for_minimal_ticket(tmp_path, monkeypatch):
    """没有需求、没有项目的工单字典：各字段落到默认值。"""

    async def body(env):
        _patch_context_sources(monkeypatch, env, tmp_path)
        ticket = {"id": TICKET_ID, "title": TITLE, "requirement_id": None}
        context = await env.orch._build_context(ticket)
        assert context["ticket_description"] == ""
        assert context["ticket_type"] == "feature"
        assert context["module"] == "other"
        assert context["project_id"] == ""
        assert context["requirement_id"] == ""
        assert context["agent_type"] == ""
        assert context["requirement_description"] == ""
        assert context["requirement_title"] == ""
        assert context["docs_prefix"] == "docs/Reqs/dalone/l30001/"
        assert context["src_prefix"] == "src/other/"
        assert context["tests_prefix"] == "tests/dalone/"
        assert context["traits"] == []
        assert "ue_target_platform" not in context
        assert ("siblings", None, TICKET_ID) in env.calls
        assert ("loader", "", "", []) in env.calls

    _run(body, tmp_path, monkeypatch)


@pytest.mark.parametrize("kw", [{"repo_error": RuntimeError("no repo")}, {"repo_none": True}])
def test_build_context_repo_path_empty_when_unavailable(tmp_path, monkeypatch, kw):
    async def body(env):
        _patch_context_sources(monkeypatch, env, tmp_path, **kw)
        context = await env.orch._build_context(await _ticket_row(env), "DevAgent")
        assert context["repo_path"] == ""

    _run(body, tmp_path, monkeypatch)


def test_build_context_bug_ticket_and_prior_artifacts(tmp_path, monkeypatch):
    async def body(env):
        _patch_context_sources(monkeypatch, env, tmp_path)
        await env.db.insert("bugs", {
            "id": "BUG-1", "project_id": PROJECT_ID, "title": "登录失败",
            "description": "点登录没反应", "ticket_id": TICKET_ID,
            "created_at": TS, "updated_at": TS,
        })
        rows = [("architecture", '{"layers": 3}'), ("code", "not json"), ("test", ""),
                ("other", '{"x": 1}')]
        for i, (kind, content) in enumerate(rows):
            await env.db.insert("artifacts", {
                "id": f"ART-{i}", "project_id": PROJECT_ID, "ticket_id": TICKET_ID,
                "type": kind, "content": content,
                "created_at": f"2026-11-25T00:00:0{i}Z",
            })
        context = await env.orch._build_context(await _ticket_row(env), "DevAgent")
        assert context["bug_id"] == "BUG-1"
        assert context["bug_priority"] == "medium"
        assert context["bug_description"] == "点登录没反应"
        assert context["bug_fix_notes"] == ""
        assert context["architecture"] == {"layers": 3}
        assert context["dev_result"] == {}
        assert context["test_result"] == {}

    _run(body, tmp_path, monkeypatch, ticket={"type": "bug"})


def test_build_context_feature_ticket_ignores_bug_rows(tmp_path, monkeypatch):
    async def body(env):
        _patch_context_sources(monkeypatch, env, tmp_path)
        await env.db.insert("bugs", {
            "id": "BUG-1", "project_id": PROJECT_ID, "title": "登录失败",
            "description": "点登录没反应", "ticket_id": TICKET_ID,
            "created_at": TS, "updated_at": TS,
        })
        context = await env.orch._build_context(await _ticket_row(env), "DevAgent")
        assert "bug_id" not in context
        assert "architecture" not in context

    _run(body, tmp_path, monkeypatch)


def test_build_context_relative_uproject_becomes_absolute(tmp_path, monkeypatch):
    async def body(env):
        _patch_context_sources(monkeypatch, env, tmp_path)
        context = await env.orch._build_context(await _ticket_row(env), "DevAgent")
        assert context["uproject_path"] == str(Path(env.repo_dir) / "Game/Game.uproject")
        assert context["ue_engine_version"] == "5.4"

    _run(body, tmp_path, monkeypatch,
         project={"uproject_path": "Game/Game.uproject", "ue_engine_version": "5.4"})


def test_build_context_absolute_uproject_is_kept(tmp_path, monkeypatch):
    absolute = str(tmp_path / "abs" / "Game.uproject")

    async def body(env):
        _patch_context_sources(monkeypatch, env, tmp_path)
        context = await env.orch._build_context(await _ticket_row(env), "DevAgent")
        assert context["uproject_path"] == absolute

    _run(body, tmp_path, monkeypatch, project={"uproject_path": absolute})


def test_build_context_default_knowledge_skips_legacy_docs(tmp_path, monkeypatch):
    async def body(env):
        _patch_context_sources(monkeypatch, env, tmp_path)
        context = await env.orch._build_context(await _ticket_row(env), "DevAgent")
        assert context["knowledge_docs"] == "PK\n\nDK"
        assert context["project_knowledge"] == "PK"
        assert context["domain_knowledge"] == "DK"
        assert context["agent_spec"] == "SPEC"
        assert "legacy_docs" not in _call_names(env)

    _run(body, tmp_path, monkeypatch)


def test_build_context_loader_error_falls_back_to_legacy_docs(tmp_path, monkeypatch):
    async def body(env):
        _patch_context_sources(
            monkeypatch, env, tmp_path, loader_error=RuntimeError("loader down"),
        )
        context = await env.orch._build_context(await _ticket_row(env), "DevAgent")
        assert context["knowledge_docs"] == "旧知识库"
        assert context["project_knowledge"] == ""
        assert context["domain_knowledge"] == ""
        assert context["agent_spec"] == ""
        assert ("legacy_docs", PROJECT_ID) in env.calls

    _run(body, tmp_path, monkeypatch)


def test_build_context_empty_knowledge_falls_back_to_legacy_docs(tmp_path, monkeypatch):
    async def body(env):
        _patch_context_sources(monkeypatch, env, tmp_path, knowledge={})
        context = await env.orch._build_context(await _ticket_row(env), "DevAgent")
        assert context["knowledge_docs"] == "旧知识库"
        assert context["project_knowledge"] == ""
        assert context["domain_knowledge"] == ""
        assert context["agent_spec"] == ""
        assert ("legacy_docs", PROJECT_ID) in env.calls

    _run(body, tmp_path, monkeypatch)


def test_build_context_memory_error_leaves_code_and_siblings_empty(tmp_path, monkeypatch):
    """AgentMemory 构造失败时 mem 没有绑定，兄弟工单那一段跟着落空（现状）。"""
    async def body(env):
        _patch_context_sources(
            monkeypatch, env, tmp_path, memory_error=RuntimeError("memory down"),
        )
        context = await env.orch._build_context(await _ticket_row(env), "DevAgent")
        assert context["existing_files"] == []
        assert context["existing_code"] == {}
        assert context["sibling_tickets"] == []
        names = _call_names(env)
        assert "memory" in names
        assert "siblings" not in names
        # 后面的段落照常执行
        assert context["knowledge_docs"] == "PK\n\nDK"
        assert context["prior_insights"] == "历史经验"

    _run(body, tmp_path, monkeypatch)


def test_build_context_insights_error_gives_empty_string(tmp_path, monkeypatch):
    async def body(env):
        _patch_context_sources(
            monkeypatch, env, tmp_path, insights_error=RuntimeError("insights down"),
        )
        context = await env.orch._build_context(await _ticket_row(env), "DevAgent")
        assert context["prior_insights"] == ""
        assert ("insights", TITLE, PROJECT_ID) in env.calls

    _run(body, tmp_path, monkeypatch)


def test_build_context_ue_project_traits_do_not_trigger_probe(tmp_path, monkeypatch):
    """现状：项目是 UE 也不探测 UCP。

    `_build_context` 把项目特征写进 `traits`，UCP 段读的是 `project_traits`，
    这个键在本函数里没有写入点，所以 `ucp_available` 恒为 False。
    这里按现状钉住，要不要改成读 `traits` 留给评审决定。
    """
    async def body(env):
        _patch_context_sources(monkeypatch, env, tmp_path)
        _patch_probe(monkeypatch, env, answer=True)
        context = await env.orch._build_context(await _ticket_row(env), "DevAgent")
        assert context["traits"] == ["engine:ue5"]
        assert "project_traits" not in context
        assert context["ucp_available"] is False
        assert "probe_ucp" not in _call_names(env)

    _run(body, tmp_path, monkeypatch, project={"traits": json.dumps(["engine:ue5"])})


@pytest.mark.parametrize("trait", ["engine:ue5", "engine:ue4"])
@pytest.mark.parametrize("answer", [True, False])
def test_build_context_probes_ucp_when_project_traits_present(
    tmp_path, monkeypatch, trait, answer,
):
    """`project_traits` 由上游放进 context 时才会探测；生产路径上目前没有写入点。"""
    async def body(env):
        _patch_context_sources(monkeypatch, env, tmp_path)
        _patch_probe(monkeypatch, env, answer=answer)
        env.inject_extra = {"project_traits": [trait]}
        context = await env.orch._build_context(await _ticket_row(env), "DevAgent")
        assert context["ucp_available"] is answer
        probes = [c for c in env.calls if c[0] == "probe_ucp"]
        assert probes == [("probe_ucp", (), {"timeout": 1.0})]

    _run(body, tmp_path, monkeypatch)


def test_build_context_probe_error_means_unavailable(tmp_path, monkeypatch):
    async def body(env):
        _patch_context_sources(monkeypatch, env, tmp_path)
        _patch_probe(monkeypatch, env, error=RuntimeError("no editor"))
        env.inject_extra = {"project_traits": ["engine:ue5"]}
        context = await env.orch._build_context(await _ticket_row(env), "DevAgent")
        assert context["ucp_available"] is False
        assert "probe_ucp" in _call_names(env)

    _run(body, tmp_path, monkeypatch)


def test_build_context_non_ue_project_traits_skip_probe(tmp_path, monkeypatch):
    async def body(env):
        _patch_context_sources(monkeypatch, env, tmp_path)
        _patch_probe(monkeypatch, env, answer=True)
        env.inject_extra = {"project_traits": ["platform:web"]}
        context = await env.orch._build_context(await _ticket_row(env), "DevAgent")
        assert context["ucp_available"] is False
        assert "probe_ucp" not in _call_names(env)

    _run(body, tmp_path, monkeypatch)


# ---------------------------------------------------------------- 阻塞诊断
DIAGNOSIS = {"symptom": "超时", "root_cause": "编译卡住", "confidence": 0.5}
STAGES = [
    {"agent": "ArchitectAgent", "action": "develop", "name": "arch"},
    {"agent": "DevAgent", "action": "develop", "name": "dev", "timeout": 60},
    {"agent": "DevAgent", "action": "develop", "name": "dev-second"},
]
UE_PROJECT = {"traits": json.dumps(["engine:ue5"])}
SKILL_RESULT = json.dumps({
    "skill_id": "ue-build", "skill_status": "budget_exceeded",
    "outputs": ["o1"], "artifacts": ["a1"],
})
RECENT_LOGS = [
    {"agent_type": "DevAgent", "action": "error", "from_status": "pending",
     "to_status": "development_in_progress", "detail": "d1",
     "created_at": "2026-11-25T00:00:01"},
    {"agent_type": "DevAgent", "action": "start", "from_status": "pending",
     "to_status": "development_in_progress", "detail": "d0",
     "created_at": "2026-11-25T00:00:00"},
]
DIAGNOSE_DONE = "\U0001fa7a 诊断完成: 超时 | 根因: 编译卡住 | 置信度=0.50"
DIAGNOSE_EMPTY = "\U0001fa7a 诊断完成:  | 根因:  | 置信度=0.00"
_UNSET = object()


def _patch_diagnose(monkeypatch, env, *, timeout, action_error=None,
                    action_data=_UNSET, compose_error=None):
    """桩打在 sop.loader 和 actions.diagnose_ticket 的模块属性上。"""
    import actions.diagnose_ticket as diag_module
    import sop.loader as sop_loader

    def fake_compose(*args, **kwargs):
        env.calls.append(("compose_sop", args, kwargs))
        if compose_error:
            raise compose_error
        return {"stages": [dict(s) for s in STAGES]}

    def fake_is_timeout(skill_status, error_msg):
        env.calls.append(("is_timeout", skill_status, error_msg))
        return timeout

    def fake_synthesize(**kwargs):
        env.calls.append(("synthesize", kwargs))
        return dict(DIAGNOSIS)

    class FakeAction:
        def __init__(self):
            env.calls.append(("action_init",))

        async def run(self, context):
            env.calls.append(("action_run", context))
            if action_error:
                raise action_error
            data = {"diagnosis": dict(DIAGNOSIS)} if action_data is _UNSET else action_data
            return SimpleNamespace(data=data)

    monkeypatch.setattr(sop_loader, "compose_sop", fake_compose)
    monkeypatch.setattr(diag_module, "_is_timeout_block", fake_is_timeout)
    monkeypatch.setattr(diag_module, "synthesize_blocked_diagnosis", fake_synthesize)
    monkeypatch.setattr(diag_module, "DiagnoseTicketAction", FakeAction)


async def _seed_diagnose_rows(env, *, artifacts=True):
    for i, (action, detail) in enumerate((("start", "d0"), ("error", "d1"))):
        await env.db.insert("ticket_logs", {
            "id": f"LOG-{i}", "ticket_id": TICKET_ID, "project_id": PROJECT_ID,
            "agent_type": "DevAgent", "action": action, "from_status": "pending",
            "to_status": "development_in_progress", "detail": detail,
            "created_at": f"2026-11-25T00:00:0{i}",
        })
    if not artifacts:
        return
    for i, path in enumerate(("src/a.py", None, "src/b.py")):
        await env.db.insert("artifacts", {
            "id": f"ART-{i}", "project_id": PROJECT_ID, "ticket_id": TICKET_ID,
            "type": "code", "path": path, "created_at": f"2026-11-25T00:00:0{i}",
        })


async def _diagnose(env, *, result=None, error="boom", agent="DevAgent"):
    ticket = {
        "title": TITLE, "description": "账号密码登录",
        "requirement_id": REQ_ID, "result": result,
    }
    return await env.orch._diagnose_blocked_ticket(
        PROJECT_ID, TICKET_ID, ticket, agent, "develop", error,
        "development_in_progress",
    )


async def _assert_diagnosis_saved(env, diagnosis=None, message=DIAGNOSE_DONE):
    diagnosis = DIAGNOSIS if diagnosis is None else diagnosis
    row = await _ticket_row(env)
    assert row["diagnosis"] == json.dumps(diagnosis, ensure_ascii=False)
    assert row["updated_at"] != TS
    assert env.logs == [(
        (PROJECT_ID, REQ_ID, TICKET_ID, "System", "diagnose", None, None, message, "info"),
        {"detail_data": {"diagnosis": diagnosis}},
    )]
    assert env.sse == [
        (PROJECT_ID, "ticket_diagnosed", {"ticket_id": TICKET_ID, "diagnosis": diagnosis}),
    ]


def test_diagnose_timeout_branch_uses_local_synthesis(tmp_path, monkeypatch):
    async def body(env):
        _patch_diagnose(monkeypatch, env, timeout=True)
        await _seed_diagnose_rows(env)
        assert await _diagnose(env, result=SKILL_RESULT, error="执行超时") is None
        assert env.calls == [
            ("compose_sop", (), {"traits": ["engine:ue5"], "ticket_type": None}),
            ("is_timeout", "budget_exceeded", "执行超时"),
            ("synthesize", {
                "skill_id": "ue-build", "skill_status": "budget_exceeded",
                "error_msg": "执行超时", "action": "develop",
                "outputs": ["o1"], "artifacts": ["a1"],
                "extra_files": ["src/b.py", "src/a.py"],
            }),
        ]
        await _assert_diagnosis_saved(env)

    _run(body, tmp_path, monkeypatch, project=UE_PROJECT)


def test_diagnose_llm_branch_passes_full_context(tmp_path, monkeypatch):
    async def body(env):
        _patch_diagnose(monkeypatch, env, timeout=False)
        await _seed_diagnose_rows(env)
        assert await _diagnose(env, result=SKILL_RESULT) is None
        assert _call_names(env) == ["compose_sop", "is_timeout", "action_init", "action_run"]
        assert env.calls[1] == ("is_timeout", "budget_exceeded", "boom")
        context = env.calls[-1][1]
        assert list(context) == [
            "ticket_id", "ticket_title", "ticket_description", "project_id",
            "project_traits", "current_status", "failed_agent", "failed_action",
            "failed_error_message", "recent_logs", "sop_stage",
        ]
        normalized = dict(context, recent_logs=[dict(r) for r in context["recent_logs"]])
        assert normalized == {
            "ticket_id": TICKET_ID,
            "ticket_title": TITLE,
            "ticket_description": "账号密码登录",
            "project_id": PROJECT_ID,
            "project_traits": ["engine:ue5"],
            "current_status": "development_in_progress",
            "failed_agent": "DevAgent",
            "failed_action": "develop",
            "failed_error_message": "boom",
            "recent_logs": RECENT_LOGS,
            "sop_stage": STAGES[1],
        }
        await _assert_diagnosis_saved(env)

    _run(body, tmp_path, monkeypatch, project=UE_PROJECT)


@pytest.mark.parametrize("result", [None, "not json", "[1, 2]", "", 7])
def test_diagnose_unusable_result_gives_empty_skill_fields(tmp_path, monkeypatch, result):
    async def body(env):
        _patch_diagnose(monkeypatch, env, timeout=True)
        await _seed_diagnose_rows(env, artifacts=False)
        await _diagnose(env, result=result)
        assert env.calls[1:] == [
            ("is_timeout", "", "boom"),
            ("synthesize", {
                "skill_id": "", "skill_status": "", "error_msg": "boom",
                "action": "develop", "outputs": [], "artifacts": [], "extra_files": [],
            }),
        ]
        await _assert_diagnosis_saved(env)

    _run(body, tmp_path, monkeypatch)


def test_diagnose_accepts_result_already_parsed_as_dict(tmp_path, monkeypatch):
    async def body(env):
        _patch_diagnose(monkeypatch, env, timeout=True)
        await _diagnose(env, result={"skill_id": 12, "skill_status": None, "outputs": None})
        kwargs = env.calls[-1][1]
        assert (kwargs["skill_id"], kwargs["skill_status"]) == ("12", "")
        assert (kwargs["outputs"], kwargs["artifacts"]) == ([], [])

    _run(body, tmp_path, monkeypatch)


@pytest.mark.parametrize("action_data", [None, {}, {"diagnosis": None}])
def test_diagnose_empty_action_data_stores_empty_diagnosis(tmp_path, monkeypatch, action_data):
    async def body(env):
        _patch_diagnose(monkeypatch, env, timeout=False, action_data=action_data)
        await _diagnose(env)
        await _assert_diagnosis_saved(env, diagnosis={}, message=DIAGNOSE_EMPTY)

    _run(body, tmp_path, monkeypatch)


def test_diagnose_long_symptom_and_root_cause_are_truncated_in_log(tmp_path, monkeypatch):
    diagnosis = {"symptom": "症" * 90, "root_cause": "因" * 120, "confidence": 1}

    async def body(env):
        _patch_diagnose(monkeypatch, env, timeout=False, action_data={"diagnosis": diagnosis})
        await _diagnose(env)
        message = "\U0001fa7a 诊断完成: " + "症" * 80 + " | 根因: " + "因" * 100 + " | 置信度=1.00"
        await _assert_diagnosis_saved(env, diagnosis=diagnosis, message=message)

    _run(body, tmp_path, monkeypatch)


def test_diagnose_action_error_is_swallowed_and_nothing_is_written(tmp_path, monkeypatch):
    async def body(env):
        _patch_diagnose(monkeypatch, env, timeout=False, action_error=RuntimeError("llm down"))
        assert await _diagnose(env) is None
        row = await _ticket_row(env)
        assert row["diagnosis"] is None
        assert row["updated_at"] == TS
        assert env.logs == []
        assert env.sse == []

    _run(body, tmp_path, monkeypatch)


def test_diagnose_compose_error_leaves_sop_stage_empty(tmp_path, monkeypatch):
    async def body(env):
        _patch_diagnose(monkeypatch, env, timeout=False, compose_error=RuntimeError("no sop"))
        await _diagnose(env)
        assert env.calls[-1][1]["sop_stage"] == {}
        await _assert_diagnosis_saved(env)

    _run(body, tmp_path, monkeypatch)


def test_diagnose_sop_stage_empty_when_no_stage_matches(tmp_path, monkeypatch):
    async def body(env):
        _patch_diagnose(monkeypatch, env, timeout=False)
        await _diagnose(env, agent="TestAgent")
        context = env.calls[-1][1]
        assert context["sop_stage"] == {}
        assert context["failed_agent"] == "TestAgent"

    _run(body, tmp_path, monkeypatch)


@pytest.mark.parametrize("raw, expected", [
    (WEB_TRAITS, ["platform:web", "", "lang:ts"]),
    ("not json", []),
    (json.dumps({"a": 1}), []),
    (json.dumps([1, "x"]), ["1", "x"]),
])
def test_diagnose_project_traits_parsing(tmp_path, monkeypatch, raw, expected):
    """和 `_build_context` 不同，这里不过滤空串。"""
    async def body(env):
        _patch_diagnose(monkeypatch, env, timeout=False)
        await _diagnose(env)
        assert env.calls[0] == ("compose_sop", (), {"traits": expected, "ticket_type": None})
        assert env.calls[-1][1]["project_traits"] == expected

    _run(body, tmp_path, monkeypatch, project={"traits": raw})


def test_module_level_synthesize_forwards_kwargs(monkeypatch):
    import actions.diagnose_ticket as diag_module

    seen = []
    sentinel = {"symptom": "x"}

    def fake(**kwargs):
        seen.append(kwargs)
        return sentinel

    monkeypatch.setattr(diag_module, "synthesize_blocked_diagnosis", fake)
    kwargs = {"skill_id": "s", "error_msg": "e"}
    assert orch_module._synthesize_blocked_diagnosis(**kwargs) is sentinel
    assert seen == [kwargs]


# ---------------------------------------------------------------- 知识蒸馏

DISTILL_CALLS = [
    ("distill_init",),
    ("distill_run", {"ticket_id": TICKET_ID, "project_id": PROJECT_ID}),
]


async def _drain():
    """等掉事件循环里除当前任务外的所有任务，返回等了几个。"""
    current = asyncio.current_task()
    pending = [t for t in asyncio.all_tasks() if t is not current]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    return len(pending)


def _patch_distill(monkeypatch, env, *, error=None):
    import actions.knowledge_distill as distill_module

    class FakeDistill:
        def __init__(self):
            env.calls.append(("distill_init",))

        async def run(self, context):
            env.calls.append(("distill_run", dict(context)))
            if error:
                raise error
            return SimpleNamespace(data={})

    monkeypatch.setattr(distill_module, "KnowledgeDistillAction", FakeDistill)


async def _seed_log(env, action, *, log_id="LOG-D0", ticket_id=TICKET_ID):
    await env.db.insert("ticket_logs", {
        "id": log_id, "ticket_id": ticket_id, "project_id": PROJECT_ID,
        "agent_type": "DevAgent", "action": action, "from_status": "pending",
        "to_status": "development_in_progress", "detail": "d",
        "created_at": "2026-11-25T00:00:00",
    })


@pytest.mark.parametrize("action", ["reject", "error", "reflection"])
def test_distill_runs_when_ticket_had_a_failure_cycle(tmp_path, monkeypatch, action):
    async def body(env):
        _patch_distill(monkeypatch, env)
        await _seed_log(env, action)
        assert orch_module._fire_knowledge_distill(PROJECT_ID, TICKET_ID) is None
        await _drain()
        assert env.calls == DISTILL_CALLS

    _run(body, tmp_path, monkeypatch)


def test_distill_is_scheduled_in_background_not_awaited(tmp_path, monkeypatch):
    async def body(env):
        _patch_distill(monkeypatch, env)
        await _seed_log(env, "reject")
        orch_module._fire_knowledge_distill(PROJECT_ID, TICKET_ID)
        assert env.calls == []
        assert await _drain() == 1
        assert env.calls == DISTILL_CALLS

    _run(body, tmp_path, monkeypatch)


@pytest.mark.parametrize("actions_seen", [[], ["complete"], ["complete", "start"]])
def test_distill_skipped_without_failure_cycle(tmp_path, monkeypatch, actions_seen):
    async def body(env):
        _patch_distill(monkeypatch, env)
        for i, action in enumerate(actions_seen):
            await _seed_log(env, action, log_id=f"LOG-D{i}")
        orch_module._fire_knowledge_distill(PROJECT_ID, TICKET_ID)
        assert await _drain() == 1
        assert env.calls == []

    _run(body, tmp_path, monkeypatch)


def test_distill_counts_only_logs_of_the_same_ticket(tmp_path, monkeypatch):
    async def body(env):
        _patch_distill(monkeypatch, env)
        await env.db.insert("tickets", {
            "id": "TK-20261125-other1", "requirement_id": REQ_ID,
            "project_id": PROJECT_ID, "title": "另一张工单",
            "status": "pending", "created_at": TS, "updated_at": TS,
        })
        await _seed_log(env, "reject", ticket_id="TK-20261125-other1")
        orch_module._fire_knowledge_distill(PROJECT_ID, TICKET_ID)
        await _drain()
        assert env.calls == []

    _run(body, tmp_path, monkeypatch)


def test_distill_action_error_does_not_escape(tmp_path, monkeypatch):
    async def body(env):
        _patch_distill(monkeypatch, env, error=RuntimeError("llm down"))
        await _seed_log(env, "error")
        orch_module._fire_knowledge_distill(PROJECT_ID, TICKET_ID)
        current = asyncio.current_task()
        tasks = [t for t in asyncio.all_tasks() if t is not current]
        assert len(tasks) == 1
        await asyncio.gather(*tasks, return_exceptions=True)
        assert tasks[0].exception() is None
        assert env.calls == DISTILL_CALLS

    _run(body, tmp_path, monkeypatch)


def test_distill_without_running_loop_does_nothing(monkeypatch):
    import actions.knowledge_distill as distill_module

    built = []
    monkeypatch.setattr(
        distill_module, "KnowledgeDistillAction", lambda: built.append("init"),
    )
    assert orch_module._fire_knowledge_distill(PROJECT_ID, TICKET_ID) is None
    assert built == []


# ---------------------------------------------------------------- 轮询
DEP_ID = "TK-20261125-dep001"
PARENT_ID = "TK-20261125-parent"
IN_PROGRESS = "development_in_progress"
ZOMBIE = {"status": IN_PROGRESS, "updated_at": OLD_TS}
ZOMBIE_MESSAGE = re.compile(
    r"工单在「development_in_progress」卡死 \d+s（进程重启/Agent 崩溃），"
    r"回退到「pending」重跑该阶段。"
    r"注意：不再直接标记为完成——半路死掉的阶段没有产出可言。"
)
POLL_TAIL = ["bugs", "stuck"]
POLL_CALL = ((PROJECT_ID, TICKET_ID), {"is_subtask": False, "source": "poll"})
POLL_SUB_CALL = ((PROJECT_ID, TICKET_ID), {"is_subtask": True, "source": "poll-sub"})


def _waiting_status():
    from actions.chat.dispatch_subtask import WAITING_SUBTASKS_STATUS
    return WAITING_SUBTASKS_STATUS


def _wire_poll(monkeypatch, env, *, actionable=("pending",), held=False,
               rewind="pending", abort_error=None):
    """把 _poll_once 调用的其他方法换成记录用的假实现，僵尸判定用真的。"""
    import llm_client

    env.enqueued, env.subtask_checks, env.rewinds, env.aborted = [], [], [], []

    async def fake_actionable():
        return list(actionable)

    def fake_held(ticket_id):
        return held

    async def fake_check(parent_id, project_id, row):
        env.subtask_checks.append((parent_id, project_id, row["status"]))

    def fake_enqueue(*args, **kwargs):
        env.enqueued.append((args, kwargs))

    async def fake_bugs():
        env.tail.append("bugs")

    async def fake_stuck():
        env.tail.append("stuck")

    async def fake_rewind(ticket_id, status):
        env.rewinds.append((ticket_id, status))
        return rewind

    async def fake_abort(ticket_id):
        env.aborted.append(ticket_id)
        if abort_error:
            raise abort_error

    env.orch._get_all_actionable_statuses = fake_actionable
    env.orch._ticket_held_by_this_process = fake_held
    env.orch._check_subtasks_complete = fake_check
    env.orch._enqueue_ticket = fake_enqueue
    env.orch._poll_open_bugs = fake_bugs
    env.orch._resume_stuck_analyses = fake_stuck
    env.orch._zombie_rewind_status = fake_rewind
    monkeypatch.setattr(llm_client, "abort_ticket_cli", fake_abort)


async def _extra_ticket(env, ticket_id, **fields):
    await env.db.insert("tickets", {
        "id": ticket_id, "requirement_id": REQ_ID, "project_id": PROJECT_ID,
        "title": "另一张工单", "status": "pending",
        "created_at": TS, "updated_at": TS, **fields,
    })


async def _set_ticket(env, **fields):
    await env.db.update("tickets", fields, "id = ?", (TICKET_ID,))


def _enqueued_ids(env):
    return [args[1] for args, _ in env.enqueued]


def _ago(seconds):
    from datetime import datetime as _dt, timedelta
    return (_dt.now() - timedelta(seconds=seconds)).isoformat()


def test_waiting_subtasks_status_value():
    assert _waiting_status() == "waiting_subtasks"


def test_poll_enqueues_actionable_ticket(tmp_path, monkeypatch):
    async def body(env):
        _wire_poll(monkeypatch, env)
        assert await env.orch._poll_once() is None
        assert env.enqueued == [POLL_CALL]
        assert env.subtask_checks == [] and env.rewinds == [] and env.aborted == []
        assert env.tail == POLL_TAIL
        assert env.logs == [] and env.sse == []
        assert (await _ticket_row(env))["status"] == "pending"

    _run(body, tmp_path, monkeypatch)


def test_poll_marks_child_ticket_as_subtask(tmp_path, monkeypatch):
    async def body(env):
        _wire_poll(monkeypatch, env)
        await _extra_ticket(env, PARENT_ID, status="testing_done")
        await _set_ticket(env, parent_ticket_id=PARENT_ID)
        await env.orch._poll_once()
        assert env.enqueued == [POLL_SUB_CALL]
        assert env.tail == POLL_TAIL

    _run(body, tmp_path, monkeypatch)


def test_poll_ignores_tickets_outside_actionable_statuses(tmp_path, monkeypatch):
    async def body(env):
        _wire_poll(monkeypatch, env)
        await env.orch._poll_once()
        assert env.enqueued == [] and env.subtask_checks == [] and env.rewinds == []
        assert env.tail == POLL_TAIL

    _run(body, tmp_path, monkeypatch, ticket={"status": "testing_done"})


def test_poll_enqueues_in_priority_then_sort_order(tmp_path, monkeypatch):
    async def body(env):
        _wire_poll(monkeypatch, env)
        await _extra_ticket(env, "TK-20261125-sort01", sort_order=-1)
        await _extra_ticket(env, "TK-20261125-prio01", priority=1)
        await env.orch._poll_once()
        assert _enqueued_ids(env) == [
            "TK-20261125-prio01", "TK-20261125-sort01", TICKET_ID,
        ]

    _run(body, tmp_path, monkeypatch)


def test_poll_skips_ticket_held_by_this_process(tmp_path, monkeypatch):
    async def body(env):
        _wire_poll(monkeypatch, env, held=True)
        await env.orch._poll_once()
        assert env.enqueued == []
        assert env.tail == POLL_TAIL

    _run(body, tmp_path, monkeypatch)


def test_poll_skips_held_ticket_before_zombie_check(tmp_path, monkeypatch):
    async def body(env):
        _wire_poll(monkeypatch, env, held=True)
        await env.orch._poll_once()
        assert env.rewinds == [] and env.aborted == [] and env.logs == []
        assert (await _ticket_row(env))["status"] == IN_PROGRESS

    _run(body, tmp_path, monkeypatch, ticket=ZOMBIE)


@pytest.mark.parametrize("req_status", ["paused", "cancelled"])
@pytest.mark.parametrize("ticket", [{}, ZOMBIE, {"status": "waiting_subtasks"}])
def test_poll_skips_ticket_of_stopped_requirement(tmp_path, monkeypatch, req_status, ticket):
    async def body(env):
        _wire_poll(monkeypatch, env)
        await env.db.update("requirements", {"status": req_status}, "id = ?", (REQ_ID,))
        before = await _ticket_row(env)
        await env.orch._poll_once()
        assert env.enqueued == [] and env.subtask_checks == [] and env.rewinds == []
        assert await _ticket_row(env) == before
        assert env.tail == POLL_TAIL

    _run(body, tmp_path, monkeypatch, ticket=ticket)


@pytest.mark.parametrize("actionable", [["pending"], [], ["waiting_subtasks"]])
def test_poll_hands_waiting_parent_to_subtask_check(tmp_path, monkeypatch, actionable):
    async def body(env):
        _wire_poll(monkeypatch, env, actionable=actionable)
        await env.orch._poll_once()
        assert env.subtask_checks == [(TICKET_ID, PROJECT_ID, "waiting_subtasks")]
        assert env.enqueued == [] and env.rewinds == []
        assert env.tail == POLL_TAIL

    _run(body, tmp_path, monkeypatch, ticket={"status": _waiting_status()})


@pytest.mark.parametrize("dep_status, enqueued", [
    ("blocked", False),
    ("development_done", False),
    (TicketStatus.TESTING_DONE.value, True),
    (TicketStatus.DEPLOYED.value, True),
])
def test_poll_waits_for_dependencies(tmp_path, monkeypatch, dep_status, enqueued):
    async def body(env):
        _wire_poll(monkeypatch, env)
        await _extra_ticket(env, DEP_ID, status=dep_status)
        await _set_ticket(env, dependencies=json.dumps([DEP_ID]))
        await env.orch._poll_once()
        assert env.enqueued == ([POLL_CALL] if enqueued else [])
        assert env.tail == POLL_TAIL

    _run(body, tmp_path, monkeypatch)


def test_poll_needs_every_dependency_done(tmp_path, monkeypatch):
    async def body(env):
        _wire_poll(monkeypatch, env)
        await _extra_ticket(env, DEP_ID, status="deployed")
        await _extra_ticket(env, "TK-20261125-dep002", status="blocked")
        await _set_ticket(env, dependencies=json.dumps([DEP_ID, "TK-20261125-dep002"]))
        await env.orch._poll_once()
        assert env.enqueued == []

    _run(body, tmp_path, monkeypatch)


def test_poll_does_not_enqueue_when_dependency_row_is_missing(tmp_path, monkeypatch):
    async def body(env):
        _wire_poll(monkeypatch, env)
        await env.orch._poll_once()
        assert env.enqueued == []
        assert env.tail == POLL_TAIL

    _run(body, tmp_path, monkeypatch,
         ticket={"dependencies": json.dumps(["TK-20261125-nosuch"])})


@pytest.mark.parametrize("raw", ["", "[]", "not json"])
def test_poll_treats_unusable_dependencies_as_none(tmp_path, monkeypatch, raw):
    async def body(env):
        _wire_poll(monkeypatch, env)
        await env.orch._poll_once()
        assert env.enqueued == [POLL_CALL]

    _run(body, tmp_path, monkeypatch, ticket={"dependencies": raw})


def _assert_zombie_reset(env, status=IN_PROGRESS, to="pending"):
    assert len(env.logs) == 1
    args, kwargs = env.logs[0]
    assert args[:7] == (
        PROJECT_ID, REQ_ID, TICKET_ID, "Orchestrator", "zombie_reset", status, to,
    )
    if status == IN_PROGRESS and to == "pending":
        assert ZOMBIE_MESSAGE.fullmatch(args[7])
    else:
        assert args[7].startswith(f"工单在「{status}」卡死 ")
        assert f"回退到「{to}」重跑该阶段。" in args[7]
    assert args[8] == "warning"
    stale = kwargs["detail_data"]["stale_seconds"]
    assert isinstance(stale, int) and stale >= 300
    assert kwargs == {"detail_data": {"stale_seconds": stale, "from": status, "to": to}}


def _assert_untouched(env, row, status=IN_PROGRESS):
    assert row["status"] == status
    assert env.logs == []
    assert env.aborted == []
    assert env.enqueued == []
    assert env.tail == POLL_TAIL


def test_poll_rewinds_zombie_ticket(tmp_path, monkeypatch):
    async def body(env):
        _wire_poll(monkeypatch, env)
        assert await env.orch._poll_once() is None
        row = await _ticket_row(env)
        assert row["status"] == "pending"
        assert row["updated_at"] != OLD_TS
        assert env.rewinds == [(TICKET_ID, IN_PROGRESS)]
        assert env.aborted == [TICKET_ID]
        _assert_zombie_reset(env)
        assert env.enqueued == []
        assert env.subtask_checks == []
        assert env.tail == POLL_TAIL

    _run(body, tmp_path, monkeypatch, ticket=ZOMBIE)


def test_poll_zombie_rewinds_even_when_cli_abort_fails(tmp_path, monkeypatch):
    async def body(env):
        _wire_poll(monkeypatch, env, abort_error=RuntimeError("x"))
        await env.orch._poll_once()
        assert (await _ticket_row(env))["status"] == "pending"
        assert env.aborted == [TICKET_ID]
        _assert_zombie_reset(env)
        assert env.enqueued == []
        assert env.tail == POLL_TAIL

    _run(body, tmp_path, monkeypatch, ticket=ZOMBIE)


@pytest.mark.parametrize("rewind", [None, "", IN_PROGRESS])
def test_poll_zombie_without_rewind_target_stays_put(tmp_path, monkeypatch, rewind):
    async def body(env):
        _wire_poll(monkeypatch, env, rewind=rewind)
        await env.orch._poll_once()
        row = await _ticket_row(env)
        assert env.rewinds == [(TICKET_ID, IN_PROGRESS)]
        assert row["updated_at"] == OLD_TS
        _assert_untouched(env, row)

    _run(body, tmp_path, monkeypatch, ticket=ZOMBIE)


def test_poll_zombie_uses_rewind_target_returned_by_helper(tmp_path, monkeypatch):
    async def body(env):
        _wire_poll(monkeypatch, env, rewind="architecture_done")
        await env.orch._poll_once()
        assert (await _ticket_row(env))["status"] == "architecture_done"
        _assert_zombie_reset(env, to="architecture_done")
        assert env.enqueued == []

    _run(body, tmp_path, monkeypatch, ticket=ZOMBIE)


def test_poll_treats_stale_deploying_ticket_as_zombie(tmp_path, monkeypatch):
    async def body(env):
        _wire_poll(monkeypatch, env)
        await env.orch._poll_once()
        assert env.rewinds == [(TICKET_ID, "deploying")]
        assert (await _ticket_row(env))["status"] == "pending"
        assert env.aborted == [TICKET_ID]
        _assert_zombie_reset(env, status="deploying")
        assert env.enqueued == []

    _run(body, tmp_path, monkeypatch, ticket={"status": "deploying", "updated_at": OLD_TS})


@pytest.mark.parametrize("seconds", [10, 200])
def test_poll_leaves_recently_updated_running_ticket_alone(tmp_path, monkeypatch, seconds):
    async def body(env):
        stamp = _ago(seconds)
        await _set_ticket(env, status=IN_PROGRESS, updated_at=stamp)
        _wire_poll(monkeypatch, env)
        await env.orch._poll_once()
        row = await _ticket_row(env)
        assert env.rewinds == []
        assert row["updated_at"] == stamp
        _assert_untouched(env, row)

    _run(body, tmp_path, monkeypatch)


def test_poll_rewinds_running_ticket_older_than_five_minutes(tmp_path, monkeypatch):
    async def body(env):
        await _set_ticket(env, status=IN_PROGRESS, updated_at=_ago(400))
        _wire_poll(monkeypatch, env)
        await env.orch._poll_once()
        assert env.rewinds == [(TICKET_ID, IN_PROGRESS)]
        assert (await _ticket_row(env))["status"] == "pending"
        _assert_zombie_reset(env)
        stale = env.logs[0][1]["detail_data"]["stale_seconds"]
        assert 400 <= stale < 460

    _run(body, tmp_path, monkeypatch)


@pytest.mark.parametrize("stamp", ["garbage", ""])
def test_poll_skips_running_ticket_with_unparseable_timestamp(tmp_path, monkeypatch, stamp):
    async def body(env):
        _wire_poll(monkeypatch, env)
        await env.orch._poll_once()
        row = await _ticket_row(env)
        assert env.rewinds == []
        assert row["updated_at"] == stamp
        _assert_untouched(env, row)

    _run(body, tmp_path, monkeypatch, ticket={"status": IN_PROGRESS, "updated_at": stamp})


@pytest.mark.parametrize("stamp", [
    "2026-01-01T00:00:00Z",
    "2026-01-01T00:00:00+08:00",
    "2026-01-01T00:00:00.123456",
])
def test_poll_zombie_check_accepts_timestamp_suffixes(tmp_path, monkeypatch, stamp):
    async def body(env):
        _wire_poll(monkeypatch, env)
        await env.orch._poll_once()
        assert env.rewinds == [(TICKET_ID, IN_PROGRESS)]
        assert (await _ticket_row(env))["status"] == "pending"
        _assert_zombie_reset(env)

    _run(body, tmp_path, monkeypatch, ticket={"status": IN_PROGRESS, "updated_at": stamp})


def test_poll_zombie_branch_wins_over_actionable_status(tmp_path, monkeypatch):
    async def body(env):
        _wire_poll(monkeypatch, env, actionable=[IN_PROGRESS])
        await env.orch._poll_once()
        assert env.rewinds == [(TICKET_ID, IN_PROGRESS)]
        assert (await _ticket_row(env))["status"] == "pending"
        assert env.enqueued == []

    _run(body, tmp_path, monkeypatch, ticket=ZOMBIE)


def test_poll_never_enqueues_fresh_running_ticket_even_if_actionable(tmp_path, monkeypatch):
    async def body(env):
        await _set_ticket(env, status=IN_PROGRESS, updated_at=_ago(10))
        _wire_poll(monkeypatch, env, actionable=[IN_PROGRESS])
        await env.orch._poll_once()
        assert env.rewinds == []
        _assert_untouched(env, await _ticket_row(env))

    _run(body, tmp_path, monkeypatch)


def test_poll_zombie_does_not_block_other_tickets(tmp_path, monkeypatch):
    async def body(env):
        await _extra_ticket(env, DEP_ID, priority=5)
        _wire_poll(monkeypatch, env)
        await env.orch._poll_once()
        assert (await _ticket_row(env))["status"] == "pending"
        assert _enqueued_ids(env) == [DEP_ID]

    _run(body, tmp_path, monkeypatch, ticket=ZOMBIE)


# ---------------------------------------------------------------- 子工单
DONE_A = TicketStatus.TESTING_DONE.value
DONE_B = TicketStatus.DEPLOYED.value


def _wire_resume(env):
    env.resumed = []

    async def fake_resume(parent_id, project_id, parent_row):
        env.resumed.append((parent_id, project_id, parent_row))

    env.orch._resume_parent_ticket = fake_resume


async def _subtasks(env, statuses, *, parent=TICKET_ID, prefix="sub"):
    for index, status in enumerate(statuses):
        await _extra_ticket(
            env, f"TK-20261125-{prefix}{index:03d}",
            parent_ticket_id=parent, status=status, title=f"子任务{index}",
        )


def test_done_status_values():
    assert (DONE_A, DONE_B) == ("testing_done", "deployed")


@pytest.mark.parametrize("statuses, resumed", [
    ([], True),
    ([DONE_A], True),
    ([DONE_B], True),
    ([DONE_A, DONE_B, DONE_A], True),
    ([DONE_A, "pending"], False),
    (["pending", "pending", "pending", "pending"], False),
    (["blocked"], False),
    (["development_done"], False),
    (["cancelled"], False),
    ([DONE_B, "waiting_subtasks"], False),
])
def test_subtasks_complete_resumes_parent_only_when_all_done(
    tmp_path, monkeypatch, statuses, resumed,
):
    async def body(env):
        _wire_resume(env)
        await _subtasks(env, statuses)
        row = await _ticket_row(env)
        assert await env.orch._check_subtasks_complete(TICKET_ID, PROJECT_ID, row) is None
        assert env.resumed == ([(TICKET_ID, PROJECT_ID, row)] if resumed else [])
        if resumed:
            assert env.resumed[0][2] is row

    _run(body, tmp_path, monkeypatch, ticket={"status": "waiting_subtasks"})


def test_subtasks_complete_itself_writes_nothing(tmp_path, monkeypatch):
    async def body(env):
        _wire_resume(env)
        await _subtasks(env, [DONE_A])
        await env.orch._check_subtasks_complete(TICKET_ID, PROJECT_ID, await _ticket_row(env))
        row = await _ticket_row(env)
        assert (row["status"], row["updated_at"]) == ("waiting_subtasks", TS)
        assert env.logs == [] and env.sse == [] and env.commands == []

    _run(body, tmp_path, monkeypatch, ticket={"status": "waiting_subtasks"})


def test_subtasks_complete_ignores_children_of_other_parents(tmp_path, monkeypatch):
    async def body(env):
        _wire_resume(env)
        await _extra_ticket(env, PARENT_ID, status="waiting_subtasks")
        await _subtasks(env, ["pending"], parent=PARENT_ID, prefix="oth")
        await _subtasks(env, [DONE_A])
        row = await _ticket_row(env)
        await env.orch._check_subtasks_complete(TICKET_ID, PROJECT_ID, row)
        assert env.resumed == [(TICKET_ID, PROJECT_ID, row)]

        env.resumed.clear()
        await env.orch._check_subtasks_complete(PARENT_ID, PROJECT_ID, row)
        assert env.resumed == []

    _run(body, tmp_path, monkeypatch, ticket={"status": "waiting_subtasks"})


def test_subtasks_complete_looks_up_children_by_argument_not_by_row(tmp_path, monkeypatch):
    async def body(env):
        _wire_resume(env)
        await _subtasks(env, ["pending"])
        fake_row = {"id": "TK-unrelated", "status": "anything"}
        await env.orch._check_subtasks_complete("TK-no-children", "P-other", fake_row)
        assert env.resumed == [("TK-no-children", "P-other", fake_row)]

    _run(body, tmp_path, monkeypatch)


def test_subtasks_complete_does_not_look_at_grandchildren(tmp_path, monkeypatch):
    async def body(env):
        _wire_resume(env)
        await _subtasks(env, [DONE_A])
        await _subtasks(env, ["pending"], parent="TK-20261125-sub000", prefix="grand")
        row = await _ticket_row(env)
        await env.orch._check_subtasks_complete(TICKET_ID, PROJECT_ID, row)
        assert env.resumed == [(TICKET_ID, PROJECT_ID, row)]

    _run(body, tmp_path, monkeypatch, ticket={"status": "waiting_subtasks"})


# ---------------------------------------------------------------- 改坏检查补漏
def test_finalize_stops_on_failed_verify_even_if_stage_moved(tmp_path, monkeypatch):
    async def body(env):
        _patch_openspec_agents(monkeypatch, env, verify=False, stage_after_verify="verified")
        await _set_stage(env, "proposed")
        await env.orch._finalize_openspec_after_done(PROJECT_ID, TICKET_ID)
        assert env.calls == [SOFT_VERIFY_CALL]
        assert env.layer_logs == []
        assert await _stage(env) == "verified"

    _run(body, tmp_path, monkeypatch)


def test_git_files_strips_non_ascii_from_non_markdown_under_docs(tmp_path, monkeypatch):
    async def body(env):
        _patch_git(monkeypatch, env, tmp_path, git_result=COMMITTED)
        _patch_deploy(monkeypatch, env)
        result = {"files": {"docs/图表a.json": "{}"}}
        await _git_files(env, result)
        assert list(result["files"]) == ["docs/a.json"]

    _run(body, tmp_path, monkeypatch)


def test_git_files_push_failure_without_ticket_says_requirement_level(tmp_path, monkeypatch):
    async def body(env):
        _patch_git(monkeypatch, env, tmp_path, git_result=UNPUSHED)
        _patch_deploy(monkeypatch, env)
        await _git_files(env, {"files": {"src/a.py": "x"}}, ticket_id=None)
        assert env.logs[0][0][4] == "git_push_failed"
        assert env.logs[0][0][7].endswith(" 工单: (需求级)。")

    _run(body, tmp_path, monkeypatch)


def test_build_context_bug_fix_notes_and_priority_come_from_row(tmp_path, monkeypatch):
    async def body(env):
        _patch_context_sources(monkeypatch, env, tmp_path)
        await env.db.insert("bugs", {
            "id": "BUG-1", "project_id": PROJECT_ID, "title": "登录失败",
            "description": "点登录没反应", "ticket_id": TICKET_ID,
            "created_at": TS, "updated_at": TS,
            "fix_notes": "重置了会话", "priority": "high",
        })
        context = await env.orch._build_context(await _ticket_row(env), "DevAgent")
        assert context["bug_fix_notes"] == "重置了会话"
        assert context["bug_priority"] == "high"

    _run(body, tmp_path, monkeypatch, ticket={"type": "bug"})


def test_build_context_latest_artifact_of_a_type_wins(tmp_path, monkeypatch):
    async def body(env):
        _patch_context_sources(monkeypatch, env, tmp_path)
        rows = [("ART-NEW", "2026-11-25T00:00:09Z", '{"v": "new"}'),
                ("ART-OLD", "2026-11-25T00:00:01Z", '{"v": "old"}')]
        for art_id, created_at, content in rows:
            await env.db.insert("artifacts", {
                "id": art_id, "project_id": PROJECT_ID, "ticket_id": TICKET_ID,
                "type": "code", "content": content, "created_at": created_at,
            })
        context = await env.orch._build_context(await _ticket_row(env), "DevAgent")
        assert context["dev_result"] == {"v": "new"}

    _run(body, tmp_path, monkeypatch)


@pytest.mark.parametrize("kind, key", [("architecture", "architecture"), ("test", "test_result")])
def test_build_context_bad_json_artifact_gives_empty_dict(tmp_path, monkeypatch, kind, key):
    async def body(env):
        _patch_context_sources(monkeypatch, env, tmp_path)
        await env.db.insert("artifacts", {
            "id": "ART-BAD", "project_id": PROJECT_ID, "ticket_id": TICKET_ID,
            "type": kind, "content": "{坏", "created_at": TS,
        })
        context = await env.orch._build_context(await _ticket_row(env), "DevAgent")
        assert context[key] == {}

    _run(body, tmp_path, monkeypatch)


def test_build_context_skips_empty_ue_columns(tmp_path, monkeypatch):
    async def body(env):
        _patch_context_sources(monkeypatch, env, tmp_path)
        context = await env.orch._build_context(await _ticket_row(env), "DevAgent")
        assert "ue_engine_path" not in context
        assert context["ue_engine_version"] == "5.4"

    _run(body, tmp_path, monkeypatch, project={"ue_engine_path": "", "ue_engine_version": "5.4"})


def test_diagnose_sop_stage_requires_matching_action(tmp_path, monkeypatch):
    target = {"action": "develop", "agent": "DevAgent", "name": "目标"}

    async def body(env):
        import sop.loader as sop_loader
        _patch_diagnose(monkeypatch, env, timeout=False)
        monkeypatch.setattr(sop_loader, "compose_sop", lambda **kw: {"stages": [
            {"action": "self_test", "agent": "DevAgent"}, dict(target),
        ]})
        await _seed_diagnose_rows(env)
        await _diagnose(env)
        assert env.calls[-1][1]["sop_stage"] == target

    _run(body, tmp_path, monkeypatch, project=UE_PROJECT)
