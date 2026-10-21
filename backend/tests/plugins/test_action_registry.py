"""Action 注册表：公共白名单 + 插件发现 + skill 目录内 Action。"""
from pathlib import Path

from plugins.registry import (
    PUBLIC_TOOL_NAMES,
    available_action_names,
    create_action,
    require_action_class,
)

UE_PLUGIN_ACTIONS = (
    "ue_compile_check",
    "ue_playtest",
    "ue_run_python",
    "ue_call",
    "ue_editor_control",
    "launch_ue_editor",
    "install_ucp",
    "ue_blueprint_gen",
    "ue_level_gen",
    "ue_screenshot",
    "ue_package",
    "ue_test_gen",
    "ue_uproject_heal",
    "instantiate_ue_template",
    "propose_ue_framework",
)

CONTENT_PLUGIN_ACTIONS = (
    "generate_assets",
    "write_ux_design",
    "write_art_design",
    "write_html_prototype",
    "search_art_assets",
    "search_design_knowledge",
)
from skills.executable_loader import ExecutableSkill
from skills.runner import SkillRunner


def _skill(builtin_tools, source="SKILL.md") -> ExecutableSkill:
    return ExecutableSkill(
        skill_id="x", name="x", description="", body="",
        source_path=Path(source),
        builtin_tools=list(builtin_tools),
        outputs={"root": "out", "globs": []},
    )


def test_public_whitelist_still_resolves():
    assert PUBLIC_TOOL_NAMES == {"write_file", "read_file", "shell", "gen_image"}
    for name in PUBLIC_TOOL_NAMES:
        action = create_action(name)
        assert action is not None, name
        assert action.name == name


def test_gen_image_subdir_syntax():
    action = create_action("gen_image:images")
    assert action is not None
    assert action.name == "gen_image"
    assert action._subdir == "images"


def test_unknown_and_mcp_return_none():
    assert create_action("not_a_real_tool") is None
    assert create_action("mcp__foo__bar") is None
    assert create_action("") is None


def test_ue_plugin_actions_are_discovered():
    names = available_action_names()
    for name in UE_PLUGIN_ACTIONS:
        action = create_action(name)
        assert action is not None, name
        assert action.name == name
        assert name in names
        assert require_action_class(name)().name == name


def test_content_plugin_actions_are_discovered():
    names = available_action_names()
    for name in CONTENT_PLUGIN_ACTIONS:
        action = create_action(name)
        assert action is not None, name
        assert action.name == name
        assert name in names
        assert require_action_class(name)().name == name


def test_public_reexport_still_imports():
    from actions.ue_compile_check import UECompileCheckAction
    from actions.ue_playtest import UEPlaytestAction, _parse_automation_output
    from actions.ue_editor_control import probe_ucp
    from actions.instantiate_ue_template import pick_template_by_traits
    from actions.ue_lint import run_all_rules
    from actions.write_ux_design import WriteUXDesignAction
    from actions.generate_assets import GenerateAssetsAction
    from plugins.ue5.actions.ue_compile_check import (
        UECompileCheckAction as PluginCls,
    )
    assert UECompileCheckAction is PluginCls
    assert UECompileCheckAction().name == "ue_compile_check"
    assert UEPlaytestAction().name == "ue_playtest"
    assert callable(_parse_automation_output)
    assert callable(probe_ucp)
    assert callable(pick_template_by_traits)
    assert callable(run_all_rules)
    assert WriteUXDesignAction().name == "write_ux_design"
    assert GenerateAssetsAction().name == "generate_assets"


def test_skill_local_action_overrides_plugin(tmp_path):
    """SKILL.md 旁边的 actions/*.py 优先于插件注册表。"""
    actions_dir = tmp_path / "actions"
    actions_dir.mkdir()
    (actions_dir / "local.py").write_text(
        "from actions.base import ActionBase, ActionResult\n"
        "class LocalCompile(ActionBase):\n"
        "    @property\n"
        "    def name(self):\n"
        "        return 'ue_compile_check'\n"
        "    async def run(self, context):\n"
        "        return ActionResult(message='local')\n",
        encoding="utf-8",
    )
    action = create_action("ue_compile_check", skill_dir=tmp_path)
    assert action is not None
    assert action.__class__.__name__ == "LocalCompile"


def test_skill_runner_resolves_plugin_action():
    actions = SkillRunner(_skill(["ue_compile_check"]))._build_actions()
    assert "ue_compile_check" in actions
    assert actions["ue_compile_check"].name == "ue_compile_check"


def test_skill_runner_keeps_public_tools_and_skips_mcp():
    actions = SkillRunner(
        _skill(["write_file", "read_file", "gen_image:images", "mcp__foo__bar"])
    )._build_actions()
    assert set(actions) == {"write_file", "read_file", "gen_image"}
    assert actions["gen_image"]._subdir == "images"
