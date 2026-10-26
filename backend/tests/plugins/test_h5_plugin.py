"""H5 / Phaser 套件：知识注入、脚手架、tsc、SOP 不双阶段。"""
import asyncio

import pytest

from plugins.registry import create_action
from skills.executable_loader import discover_workflow_skills, load_executable_skill
from skills.loader import SkillLoader
from sop.loader import compose_sop, invalidate_sop_cache

from plugins.h5.actions.h5_typecheck import parse_tsc_output, phaser_api_hints
from plugins.h5.actions.h5_playtest import (
    _cmd_line,
    ensure_playwright_chromium,
    is_missing_browser,
    is_runtime_noise,
    playwright_driver_ok,
    run_and_trace,
)


pytestmark = pytest.mark.real_plugin_skills


@pytest.fixture(autouse=True)
def _clear_sop_cache():
    invalidate_sop_cache()
    yield
    invalidate_sop_cache()


def test_h5_typecheck_skill_is_loadable():
    skill = load_executable_skill("h5-typecheck")
    assert skill is not None
    assert "h5_typecheck" in skill.builtin_tools
    assert "typecheck_log.json" in skill.output_globs


def test_h5_typecheck_skill_is_discoverable():
    found = {wf.skill_id: wf for wf in discover_workflow_skills()}
    assert "h5-typecheck" in found
    wf = found["h5-typecheck"]
    assert wf.stage_id == "h5_typecheck"
    assert "typecheck_log" in wf.produce_kinds
    assert wf.required_traits == {"any_of": ["framework:phaser"]}


def test_compose_sop_does_not_duplicate_h5_typecheck():
    cfg = compose_sop(traits=["category:game", "platform:web", "framework:phaser"],
                      ticket_type="feature")
    ids = [s["id"] for s in cfg["stages"]]
    assert ids.count("h5_typecheck") == 1
    assert ids.count("h5_playtest") == 1
    assert "h5_typecheck" in cfg["composed_from_fragments"]
    assert "h5_playtest" in cfg["composed_from_fragments"]
    assert "h5_typecheck" not in cfg["composed_from_skills"]
    assert "h5_playtest" not in cfg["composed_from_skills"]
    assert "html_prototype" not in ids
    assert ids.index("development") < ids.index("h5_typecheck") < ids.index("h5_playtest")


def test_compose_sop_web_app_skips_h5_typecheck():
    cfg = compose_sop(traits=["platform:web", "category:app"], ticket_type="feature")
    ids = [s["id"] for s in cfg["stages"]]
    assert "h5_typecheck" not in ids
    assert "h5_playtest" not in ids


def test_phaser_knowledge_injects_for_dev_agent():
    loader = SkillLoader()
    ids = loader.get_skills_for_agent("DevAgent", traits=["framework:phaser"])
    assert "phaser-dev" in ids
    prompt = loader.get_skill_prompt("phaser-dev")
    assert prompt and "402×874" in prompt


def test_phaser_knowledge_skips_other_traits():
    loader = SkillLoader()
    ids = loader.get_skills_for_agent("DevAgent", traits=["engine:ue5"])
    assert "phaser-dev" not in ids


def test_instantiate_h5_template_copies_scaffold(tmp_path):
    action = create_action("instantiate_h5_template")
    result = asyncio.run(action.run({
        "target_dir": str(tmp_path),
        "project_name": "SnakeGame",
    }))
    assert result.success, result.message
    pkg = (tmp_path / "package.json").read_text(encoding="utf-8")
    assert '"snakegame"' in pkg.lower() or "snakegame" in pkg
    assert (tmp_path / "src" / "main.ts").is_file()
    assert (tmp_path / "tsconfig.json").is_file()
    assert "402" in (tmp_path / "src" / "main.ts").read_text(encoding="utf-8")


def test_instantiate_refuses_nonempty(tmp_path):
    (tmp_path / "already.txt").write_text("x", encoding="utf-8")
    action = create_action("instantiate_h5_template")
    result = asyncio.run(action.run({
        "target_dir": str(tmp_path),
        "project_name": "Foo",
    }))
    assert not result.success
    assert "非空" in result.message


def test_parse_tsc_and_phaser_hints():
    raw = (
        "src/Game.ts(12,5): error TS2339: Property 'on' does not exist on type 'TimerEvent'.\n"
        "src/Player.ts(8,3): error TS2339: Property 'x' does not exist on type 'Body | null'.\n"
    )
    errors = parse_tsc_output(raw)
    assert len(errors) == 2
    assert errors[0]["code"] == "TS2339"
    hints = phaser_api_hints(errors)
    assert any("delayedCall" in h for h in hints)
    assert any("body!" in h for h in hints)


def test_h5_typecheck_missing_tsconfig(tmp_path):
    action = create_action("h5_typecheck")
    result = asyncio.run(action.run({"repo_path": str(tmp_path)}))
    assert not result.success
    assert result.data.get("status") == "error"
    assert "tsconfig" in (result.message or "").lower()


def test_h5_playtest_skill_is_loadable():
    skill = load_executable_skill("h5-playtest")
    assert skill is not None
    assert "h5_playtest" in skill.builtin_tools
    assert "playtest_log.json" in skill.output_globs


def test_h5_playtest_skill_is_discoverable():
    found = {wf.skill_id: wf for wf in discover_workflow_skills()}
    assert "h5-playtest" in found
    wf = found["h5-playtest"]
    assert wf.stage_id == "h5_playtest"
    assert "playtest_log" in wf.produce_kinds


def test_h5_playtest_missing_package(tmp_path):
    action = create_action("h5_playtest")
    result = asyncio.run(action.run({"repo_path": str(tmp_path)}))
    assert not result.success
    assert result.data.get("status") == "error"
    assert "package.json" in (result.message or "")


def test_runtime_noise_filter():
    assert is_runtime_noise("Failed to load resource: favicon.ico")
    assert is_runtime_noise("ResizeObserver loop limit exceeded")
    assert not is_runtime_noise("Uncaught TypeError: Cannot read properties of null")


def test_missing_browser_is_env_skip_not_game_bug():
    assert is_missing_browser(FileNotFoundError(2, "系统找不到指定的文件。"))
    assert is_missing_browser(RuntimeError("Executable doesn't exist at ..."))
    assert is_missing_browser(RuntimeError("[WinError 2] 系统找不到指定的文件。"))
    assert not is_missing_browser(RuntimeError("Uncaught TypeError: Cannot read properties of null"))


def test_ensure_playwright_installs_chromium(monkeypatch):
    calls: list = []

    async def fake_run(cmd, cwd, timeout):
        calls.append(cmd)
        return 0, "ok"

    monkeypatch.setattr("plugins.h5.actions.h5_playtest.playwright_driver_ok", lambda: True)
    monkeypatch.setattr("plugins.h5.actions.h5_playtest.run_cmd", fake_run)
    ok, msg = asyncio.run(ensure_playwright_chromium(timeout=10))
    assert ok
    assert any("install" in c and "chromium" in c for c in calls)
    assert "chromium" in msg


def test_run_and_trace_records_when_ticket_present(monkeypatch, tmp_path):
    recorded = []

    async def fake_run(cmd, cwd, timeout):
        return 0, "installed chromium\n"

    async def fake_rec(**kw):
        recorded.append(kw)
        return "TCMD-test-1"

    monkeypatch.setattr("plugins.h5.actions.h5_playtest.run_cmd", fake_run)
    monkeypatch.setattr("command_log.record_traced_command", fake_rec)
    code, raw, rid = asyncio.run(run_and_trace(
        ["python", "-m", "playwright", "install", "chromium"],
        tmp_path, 10,
        tool="playwright:install-chromium",
        trace={"ticket_id": "TK-1", "project_id": "PRJ-1", "agent_type": "TestAgent"},
    ))
    assert code == 0
    assert rid == "TCMD-test-1"
    assert recorded[0]["ticket_id"] == "TK-1"
    assert recorded[0]["tool"] == "playwright:install-chromium"
    assert "chromium" in recorded[0]["command"]
    assert recorded[0]["output"] == "installed chromium\n"


def test_run_and_trace_skips_record_without_ticket(monkeypatch, tmp_path):
    called = []

    async def fake_run(cmd, cwd, timeout):
        return 0, "ok"

    async def fake_rec(**kw):
        called.append(kw)
        return "TCMD-x"

    monkeypatch.setattr("plugins.h5.actions.h5_playtest.run_cmd", fake_run)
    monkeypatch.setattr("command_log.record_traced_command", fake_rec)
    code, raw, rid = asyncio.run(run_and_trace(
        ["echo", "hi"], tmp_path, 10, tool="echo", trace={},
    ))
    assert code == 0
    assert rid == ""
    assert called == []


def test_ensure_missing_driver_emits_steps_and_records(monkeypatch):
    cmds = []
    steps = []
    records = []
    driver = {"ok": False}

    async def fake_run(cmd, cwd, timeout):
        cmds.append(cmd)
        if "--force-reinstall" in cmd:
            driver["ok"] = True
        return 0, "ok"

    async def fake_rec(**kw):
        records.append(kw["tool"])
        return f"TCMD-{len(records)}"

    async def fake_step(trace, name, phase, **kw):
        steps.append((name, phase, kw.get("task_id") or ""))
        return "LOG-1"

    monkeypatch.setattr(
        "plugins.h5.actions.h5_playtest.playwright_driver_ok",
        lambda: driver["ok"],
    )
    monkeypatch.setattr("plugins.h5.actions.h5_playtest.run_cmd", fake_run)
    monkeypatch.setattr("command_log.record_traced_command", fake_rec)
    monkeypatch.setattr("plugins.h5.actions.h5_playtest._emit_ticket_step", fake_step)

    ok, msg = asyncio.run(ensure_playwright_chromium(
        timeout=10,
        trace={"ticket_id": "TK-1", "project_id": "PRJ-1"},
    ))
    assert ok
    assert any(p == "start" for _, p, _ in steps)
    assert any(p == "done" for _, p, _ in steps)
    assert any(s[0] == "自动安装 Playwright Chromium" for s in steps)
    assert "pip:playwright-reinstall" in records
    assert "playwright:install-chromium" in records
    done = [s for s in steps if s[1] == "done"]
    assert done and done[-1][2].startswith("TCMD-")
    assert "chromium" in msg


def test_cmd_line_quotes_spaces():
    line = _cmd_line(["npm", "install", "some package"])
    assert "npm" in line
    assert "install" in line


def test_promote_in_flight_steps_lifts_unfinished_start():
    from api.tickets import _promote_in_flight_steps

    items = [
        {"_type": "log", "id": "L1", "action": "thought_start", "agent_type": "DevAgent", "_tier": "primary"},
        {"_type": "log", "id": "L2", "action": "skill_step_start", "agent_type": "DevAgent",
         "_tier": "secondary", "_detail": {"step_index": 1, "step_name": "拉取重试上下文"}},
        {"_type": "log", "id": "L3", "action": "skill_step_done", "agent_type": "DevAgent",
         "_tier": "primary", "_detail": {"step_index": 1, "step_name": "拉取重试上下文"}},
        {"_type": "log", "id": "L4", "action": "skill_step_start", "agent_type": "DevAgent",
         "_tier": "secondary", "_detail": {"step_index": 2, "step_name": "反思失败根因"}},
    ]
    out = _promote_in_flight_steps(items, ticket_status="developing")
    assert out[1]["_tier"] == "secondary"
    assert not out[1].get("_running")
    assert out[3]["_tier"] == "primary"
    assert out[3].get("_running") is True


def test_promote_in_flight_steps_ignores_finished_turn():
    from api.tickets import _promote_in_flight_steps

    items = [
        {"_type": "log", "id": "L1", "action": "thought_start", "agent_type": "DevAgent", "_tier": "primary"},
        {"_type": "log", "id": "L2", "action": "skill_step_start", "agent_type": "DevAgent",
         "_tier": "secondary", "_detail": {"step_index": 1, "step_name": "代码生成"}},
        {"_type": "log", "id": "L3", "action": "thought_done", "agent_type": "DevAgent", "_tier": "primary"},
    ]
    out = _promote_in_flight_steps(items, ticket_status="developing")
    assert out[1]["_tier"] == "secondary"
    assert not out[1].get("_running")


def test_extract_json_value_with_prose_and_inner_arrays():
    from llm_client import LLMClient

    raw = (
        "All acceptance checks pass. First byte of package.json is '{'. "
        "Let me return the deliverable.{\n"
        '  "files": {"package.json": "{\\n  \\"name\\": \\"phaser-game\\"\\n}"},\n'
        '  "notes": "done",\n'
        '  "key_implementations": ["scaffold", "scene"],\n'
        '  "estimated_hours": 4\n'
        "}"
    )
    obj, pos = LLMClient._extract_json_value(raw)
    assert isinstance(obj, dict)
    assert "files" in obj
    assert obj["key_implementations"] == ["scaffold", "scene"]
    assert pos > 0


def test_classify_board_column_covers_h5_and_ue_dynamic_statuses():
    from api.tickets import _classify_board_column
    from models import BOARD_COLUMNS

    smap = {
        (s.value if hasattr(s, "value") else str(s)): col
        for col, lst in BOARD_COLUMNS.items()
        for s in lst
    }
    assert _classify_board_column("h5_typecheck_in_progress", smap) == "in_progress"
    assert _classify_board_column("h5_playtest_in_progress", smap) == "in_progress"
    assert _classify_board_column("h5_typecheck_passed", smap) == "in_review"
    assert _classify_board_column("h5_playtest_passed", smap) == "in_review"
    assert _classify_board_column("h5_typecheck_failed", smap) == "blocked"
    assert _classify_board_column("h5_playtest_failed", smap) == "blocked"
    assert _classify_board_column("development_failed", smap) == "blocked"
    assert _classify_board_column("assets_ready", smap) == "in_review"


def test_resolve_tsc_cmd_npx_uses_typescript_package(tmp_path):
    from plugins.h5.actions.h5_typecheck import resolve_tsc_cmd

    cmd = resolve_tsc_cmd(tmp_path)
    if cmd is not None:
        assert "--package" in cmd
        assert "typescript" in cmd


def test_reflection_builds_h5_failure_signal(monkeypatch):
    from actions.reflection import ReflectionAction

    seen_prompts = []

    async def fake_chat(messages, **kwargs):
        seen_prompts.append(messages[-1]["content"])
        return '{"root_cause":"tsc 报错 TS2345","strategy_change":"颜色传 number","specific_changes":["改 levelBuilder.ts"],"confidence":0.9}'

    monkeypatch.setattr("actions.reflection.llm_client.chat", fake_chat)
    res = asyncio.run(ReflectionAction().run({
        "ticket_description": "搭建关卡",
        "failure_type": "h5_typecheck_failed",
        "compile_errors": [{"file": "src/level/levelBuilder.ts", "line": 98, "column": 7, "code": "TS2345", "msg": "Argument of type string is not assignable to number"}],
        "compile_hints": ["Phaser rectangle 颜色只接受 number"],
        "compile_raw_tail": "src/level/levelBuilder.ts(98,7): error TS2345",
        "compile_command": "tsc --noEmit",
    }))
    assert res.success
    assert seen_prompts
    assert "src/level/levelBuilder.ts:98:7" in seen_prompts[0]
    assert "TS2345" in seen_prompts[0]
    assert "Phaser rectangle 颜色只接受 number" in seen_prompts[0]


def test_plugin_reflection_registry_hooks():
    from plugins.registry import (
        build_plugin_reflection_signal,
        enrich_plugin_fix_context,
        is_plugin_failure_type,
    )

    assert is_plugin_failure_type("h5_typecheck_failed")
    assert is_plugin_failure_type("h5_playtest_failed")
    assert not is_plugin_failure_type("unknown_failed")

    ctx: dict = {}
    assert enrich_plugin_fix_context(
        "h5_typecheck_failed",
        {
            "errors": [{"file": "src/a.ts", "line": 10, "column": 3, "code": "TS2345", "msg": "Argument of type 'string' is not assignable to parameter of type 'number'"}],
            "command": "tsc --noEmit",
            "raw_tail": "\x1b[41merror\x1b[0m",
        },
        ctx,
    )
    sig = build_plugin_reflection_signal("h5_typecheck_failed", ctx)
    assert sig is not None
    assert "src/a.ts:10:3" in sig
    assert "0x1e293b" in sig
    assert "\x1b[" not in sig


def test_h5_deterministic_fix_patches_ts2345_color(tmp_path):
    from plugins.registry import apply_plugin_deterministic_fixes

    src_code = (
        "export class LevelBuilder {\n"
        "  addStaticRect(scene: any, rect: any, fillColor: string): void {\n"
        "    scene.add.rectangle(\n"
        "      rect.x,\n"
        "      rect.y,\n"
        "      rect.width,\n"
        "      rect.height,\n"
        "      fillColor,\n"
        "    );\n"
        "  }\n"
        "}\n"
    )
    errs = [{
        "file": "src/level/levelBuilder.ts",
        "line": 8,
        "column": 7,
        "code": "TS2345",
        "msg": "Argument of type 'string' is not assignable to parameter of type 'number'.",
    }]
    patched = apply_plugin_deterministic_fixes(
        "h5_typecheck_failed",
        str(tmp_path),
        errs,
        {"src/level/levelBuilder.ts": src_code},
    )
    assert "src/level/levelBuilder.ts" in patched
    assert "Number.parseInt" in patched["src/level/levelBuilder.ts"]


def test_h5_deterministic_fix_patches_ts2307_ts6133_ts2353_ts2532_ts2339(tmp_path):
    from plugins.registry import apply_plugin_deterministic_fixes

    files = {
        "src/config/gameConfig.ts": (
            'import Phaser from "phaser";\n'
            'import BootScene from "../scenes/BootScene";\n'
            'import { PreloadScene } from "../scenes/PreloadScene";\n'
            'import { GameScene } from "../scenes/GameScene";\n'
            'import { UIScene } from "../scenes/UIScene";\n'
            "export const gameConfig = {\n"
            "  scene: [BootScene, PreloadScene, GameScene, UIScene],\n"
            "};\n"
        ),
        "src/utils/color.ts": (
            "export function normalizeHex(hex: string): string {\n"
            "  const short = hex.match(/^#?([0-9a-f]{3})$/i);\n"
            "  if (short) {\n"
            "    const [r, g, b] = short[1].split('');\n"
            "    return `#${r}${g}${b}`;\n"
            "  }\n"
            "  return hex;\n"
            "}\n"
        ),
        "src/acceptance/acceptanceProbe.ts": (
            "const { PNG } = require('pngjs') as {\n"
            "  sync: { read(buffer: Buffer): { width: number; height: number; data: Buffer } };\n"
            "};\n"
        ),
    }
    errs = [
        {"file": "src/config/gameConfig.ts", "line": 3, "code": "TS2307", "msg": "Cannot find module '../scenes/PreloadScene' or its corresponding type declarations."},
        {"file": "src/config/gameConfig.ts", "line": 5, "code": "TS2307", "msg": "Cannot find module '../scenes/UIScene' or its corresponding type declarations."},
        {"file": "src/utils/color.ts", "line": 4, "code": "TS2532", "msg": "Object is possibly 'undefined'."},
        {"file": "src/acceptance/acceptanceProbe.ts", "line": 1, "code": "TS2339", "msg": "Property 'PNG' does not exist on type '{ sync: ... }'."},
    ]
    patched = apply_plugin_deterministic_fixes("h5_typecheck_failed", str(tmp_path), errs, files)
    assert set(patched.keys()) == {"src/config/gameConfig.ts", "src/utils/color.ts", "src/acceptance/acceptanceProbe.ts"}
    assert "scene: [BootScene, GameScene]" in patched["src/config/gameConfig.ts"]
    assert "short[1]!" in patched["src/utils/color.ts"]
    assert "const PNG = require('pngjs')" in patched["src/acceptance/acceptanceProbe.ts"]



@pytest.mark.asyncio
async def test_h5_acceptance_evidence_provider():
    from plugins.registry import build_plugin_acceptance_evidence

    ctx = {
        "project_traits": ["platform:web", "framework:phaser"],
        "existing_code": {
            "src/level/levelBuilder.ts": "export class LevelBuilder { build() {} }",
        },
        "dev_result": {
            "files": {"src/level/levelBuilder.ts": "..."},
        },
    }
    ev = await build_plugin_acceptance_evidence(ctx)
    assert ev is not None
    assert "H5 / Phaser 插件自动化验收证据" in ev["evidence_markdown"]
    assert "src/level/levelBuilder.ts" in ev["evidence_markdown"]
    assert len(ev["extra_check_items"]) >= 2
    assert "严禁因为无法直接用工具读取本地截图文件而判 0 分" in ev["acceptance_rules"]








