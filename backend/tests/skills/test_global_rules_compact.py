"""global 硬基线常驻；global-coding 仅 scene=coding。"""
from skills.loader import SkillLoader
from agents.chat_assistant import _infer_rules_scene


def test_global_always_and_coding_scene_gated():
    loader = SkillLoader()
    always = loader.get_rules_for_context(traits=[], enabled_packs=set(), scene=None)
    assert "global" in always
    assert "global-coding" not in always

    coding = loader.get_rules_for_context(traits=[], enabled_packs=set(), scene="coding")
    assert "global" in coding
    assert "global-coding" in coding

    body = loader.rules["global"]["content"]
    assert "硬基线" in body or "代码标识符" in body
    assert "Conventional Commits" not in body  # 细则已拆出
    assert "Conventional Commits" in loader.rules["global-coding"]["content"]


def test_infer_rules_scene():
    assert _infer_rules_scene({"user_message": "工单卡在哪了"}) is None
    assert _infer_rules_scene({"user_message": "帮我修一下这个 bug"}) == "coding"
    assert _infer_rules_scene({"user_message": "改 foo.py 的实现"}) == "coding"
