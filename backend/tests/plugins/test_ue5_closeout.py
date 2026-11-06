"""UE 阶段按片段收尾：状态和钩子都来自组合后的 stage。"""
import pytest

from orchestrator import (
    closeout_detail,
    closeout_log_level,
    closeout_message,
    rewind_trigger,
    stage_hook_names,
)
from plugins.registry import collect_stage_hooks
from plugins.ue5.pipeline import (
    STAGE_HOOKS,
    create_compile_bug,
    openspec_verify,
    resolve_compile_bug,
    uproject_heal,
)
from sop.loader import compose_sop


UE = ["category:game", "engine:ue5"]


def _stage(cfg, stage_id):
    return next(item for item in cfg["stages"] if item["id"] == stage_id)


def test_ue_stages_declare_closeout():
    cfg = compose_sop(traits=UE, ticket_type="feature")
    compile_stage = _stage(cfg, "engine_compile")
    assert compile_stage["closeout"] == "status"
    assert compile_stage["skip_when"] == "noncode_ticket"
    assert compile_stage["on_success"] == ["resolve_compile_bug"]
    assert compile_stage["on_failure"] == ["create_compile_bug"]
    assert compile_stage["success_status"] == "engine_compile_passed"
    assert compile_stage["reject_status"] == "engine_compile_failed"

    play = _stage(cfg, "play_test")
    assert play["closeout"] == "status"
    assert play["on_success"] == ["openspec_verify"]
    assert play["on_failure"] == ["uproject_heal"]
    assert play["success_status"] == "play_test_passed"
    assert play["reject_status"] == "play_test_failed"

    generated = _stage(cfg, "ue_test_gen")
    assert generated["closeout"] == "status"
    assert generated["success_status"] == "ue_test_gen_passed"
    assert not generated.get("on_success")
    assert not generated.get("on_failure")

    deploy_actions = [
        item for item in cfg["stages"] if item.get("action") == "run_ci_deploy"
    ]
    assert deploy_actions
    assert all(item.get("closeout") != "status" for item in deploy_actions)


def test_godot_and_unity_still_have_no_ue_stages():
    for traits in (
        ["category:game", "engine:godot4"],
        ["category:game", "engine:unity"],
    ):
        ids = [
            item["id"]
            for item in compose_sop(traits=traits, ticket_type="feature")["stages"]
        ]
        assert "engine_compile" not in ids
        assert "play_test" not in ids
        assert "deploy_ue" not in ids


def test_heal_rewind_uses_relinked_compile_trigger():
    cfg = compose_sop(traits=UE, ticket_type="feature")
    compile_stage = _stage(cfg, "engine_compile")
    assert compile_stage["trigger_on"] == "ue_test_gen_passed"
    assert rewind_trigger(cfg["stages"], "engine_compile") == "ue_test_gen_passed"
    assert rewind_trigger(cfg["stages"], "missing") is None


def test_stage_hooks_come_from_the_ue_plugin():
    assert set(STAGE_HOOKS) == {
        "resolve_compile_bug",
        "create_compile_bug",
        "openspec_verify",
        "uproject_heal",
    }
    found = collect_stage_hooks()
    for name, fn in STAGE_HOOKS.items():
        assert found[name] is fn


def test_closeout_message_keeps_bug_and_heal_notes():
    compile_stage = {"name": "引擎编译验证", "reject_goto": "development"}
    passed = closeout_message(
        compile_stage, {"duration_ms": 12000, "target_name": "TestFPS"}, True,
    )
    assert passed == "引擎编译验证 通过（12s，target=TestFPS）"
    failed = closeout_message(
        compile_stage, {"errors": [{}, {}]}, False, ["，已创建 Bug 记录"],
    )
    assert failed == "引擎编译验证 失败 · 2 个错误，打回 development，已创建 Bug 记录"

    play = {"name": "游戏玩法测试", "reject_goto": "development"}
    play_fail = closeout_message(
        play,
        {"summary": {"passed": 1, "failed": 2, "total": 3}, "duration_ms": 5000},
        False,
        ["（已尝试 uproject 自愈，无有效插件可补充）"],
    )
    assert "2/3" in play_fail
    assert play_fail.endswith("（已尝试 uproject 自愈，无有效插件可补充）")

    generated = closeout_message(
        {"name": "UE 测试生成"},
        {"ue_test_gen": {"summary": "生成了 1 个测试", "warnings": ["x"]}},
        True,
    )
    assert generated == "生成了 1 个测试"
    assert closeout_log_level({"ue_test_gen": {"warnings": ["x"]}}, True) == "warning"

    detail = closeout_detail({
        "errors": [{"file": r"Source\A.cpp", "line": 3, "code": "C1", "msg": "bad"}],
        "raw_tail": "z" * 5000,
        "command": "UnrealBuildTool",
    })
    assert detail["err_brief"].startswith("A.cpp:3")
    assert len(detail["raw_tail"]) == 4000
    assert detail["command"] == "UnrealBuildTool"


def test_stage_hook_names_keep_only_strings():
    assert stage_hook_names(
        {"on_success": ["resolve_compile_bug", "", 3, " openspec_verify "]},
        "on_success",
    ) == ["resolve_compile_bug", "openspec_verify"]


class _Host:
    def __init__(self):
        self.calls = []
        self.heal = {"healed": False}

    async def _resolve_compile_bug(self, ticket_id, project_id):
        self.calls.append(("resolve", ticket_id, project_id))

    async def _create_compile_bug(self, project_id, requirement_id, ticket_id, errors, brief):
        self.calls.append(("create", brief, len(errors)))

    async def _maybe_openspec_verify(self, project_id, ticket_id, stage_label=""):
        self.calls.append(("verify", stage_label))

    async def _try_uproject_heal(self, project_id, ticket_id, result):
        self.calls.append(("heal",))
        return self.heal


@pytest.mark.asyncio
async def test_compile_hooks_delegate_to_host():
    host = _Host()
    ctx = {
        "ticket_id": "T",
        "project_id": "P",
        "requirement_id": "R",
        "result": {"errors": [{"file": "A.cpp", "line": 1, "code": "C", "msg": "m"}]},
    }
    assert await resolve_compile_bug(host, ctx) is None
    note = await create_compile_bug(host, ctx)
    assert "Bug" in note["log_note"]
    assert host.calls[0] == ("resolve", "T", "P")
    assert host.calls[1][0] == "create"
    assert "A.cpp:1" in host.calls[1][1]


@pytest.mark.asyncio
async def test_uproject_heal_rewinds_only_after_plugins_are_added():
    host = _Host()
    ctx = {
        "project_id": "P",
        "ticket_id": "T",
        "result": {"module_load_errors": ["Missing module"]},
    }
    note = await uproject_heal(host, ctx)
    assert "rewind_to_stage" not in note
    assert "已尝试" in note["log_note"]

    host.heal = {"healed": True, "added_plugins": ["Foo"]}
    rewound = await uproject_heal(host, ctx)
    assert rewound["rewind_to_stage"] == "engine_compile"
    assert "Foo" in rewound["log_message"]

    assert await uproject_heal(host, {"project_id": "P", "ticket_id": "T", "result": {}}) is None


@pytest.mark.asyncio
async def test_openspec_hook_uses_stage_id():
    host = _Host()
    await openspec_verify(
        host, {"project_id": "P", "ticket_id": "T", "stage": {"id": "play_test"}},
    )
    assert host.calls == [("verify", "play_test")]


@pytest.mark.asyncio
async def test_agents_run_registered_action_after_named_branches(monkeypatch):
    class _Result:
        def to_dict(self):
            return {"status": "success", "marker": 7}

    class _Action:
        async def run(self, ctx):
            return _Result()

    monkeypatch.setattr(
        "plugins.registry.create_action",
        lambda name: _Action() if name == "future_stage_action" else None,
    )

    from agents.dev import DevAgent
    from agents.test import TestAgent

    async def _named(self, ctx):
        return {"status": "success", "via": "named"}

    monkeypatch.setattr(DevAgent, "_do_run_engine_compile", _named)
    monkeypatch.setattr(TestAgent, "run_playtest", _named)

    dev = DevAgent()
    named = await dev.execute("run_engine_compile", {})
    assert named["via"] == "named"
    fallback = await dev.execute("future_stage_action", {})
    assert fallback["marker"] == 7
    missing = await dev.execute("not_a_real_action_zz", {})
    assert missing["status"] == "error"
    assert "未知任务" in missing["message"]

    tester = TestAgent()
    assert (await tester.execute("run_playtest", {}))["via"] == "named"
    assert (await tester.execute("future_stage_action", {}))["marker"] == 7
