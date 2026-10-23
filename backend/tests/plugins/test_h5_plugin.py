"""H5 / Phaser 套件：知识注入、脚手架、tsc、SOP 不双阶段。"""
import asyncio

import pytest

from plugins.registry import create_action
from skills.executable_loader import discover_workflow_skills, load_executable_skill
from skills.loader import SkillLoader
from sop.loader import compose_sop, invalidate_sop_cache

from plugins.h5.actions.h5_typecheck import parse_tsc_output, phaser_api_hints
from plugins.h5.actions.h5_playtest import is_runtime_noise


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
