"""UE 编译成套：插件 skill 可发现，且不会在 SOP 里插出第二个编译阶段。"""
import pytest

from skills.executable_loader import (
    discover_workflow_skills,
    load_executable_skill,
)
from sop.loader import compose_sop, invalidate_sop_cache


pytestmark = pytest.mark.real_plugin_skills


@pytest.fixture(autouse=True)
def _clear_sop_cache():
    invalidate_sop_cache()
    yield
    invalidate_sop_cache()


def test_engine_compile_skill_is_loadable():
    skill = load_executable_skill("engine-compile")
    assert skill is not None
    assert "ue_compile_check" in skill.builtin_tools
    assert "compile_log.json" in skill.output_globs


def test_engine_compile_skill_is_discoverable():
    found = {wf.skill_id: wf for wf in discover_workflow_skills()}
    assert "engine-compile" in found
    wf = found["engine-compile"]
    assert wf.stage_id == "engine_compile"
    assert "compile_log" in wf.produce_kinds
    assert wf.required_traits == {"any_of": ["engine:ue5", "engine:ue4"]}


def test_compose_sop_does_not_duplicate_engine_compile():
    """fragment 仍驱动 SOP；skill 因 stage_id 撞名被跳过。"""
    cfg = compose_sop(traits=["category:game", "engine:ue5"], ticket_type="feature")
    ids = [s["id"] for s in cfg["stages"]]
    assert ids.count("engine_compile") == 1
    assert "engine_compile" in cfg["composed_from_fragments"]
    assert "engine_compile" not in cfg["composed_from_skills"]
    diags = " ".join(cfg.get("sop_diagnostics") or [])
    assert "engine_compile" in diags
    assert "与已有阶段重名" in diags
    # 插入顺序仍由 fragment priority 决定，不被 skill 链打乱
    assert ids.index("ue_test_gen") < ids.index("engine_compile") < ids.index("play_test")
