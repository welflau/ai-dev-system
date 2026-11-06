"""本地阻塞说明：CLI 超时不能再去调一轮 LLM。"""
from actions.diagnose_ticket import synthesize_blocked_diagnosis, _is_timeout_block


def test_timeout_explains_prompts_budget():
    d = synthesize_blocked_diagnosis(
        skill_id="director-prompts",
        skill_status="budget_exceeded",
        error_msg="CLI 调用超时（400s）",
        extra_files=["works/dragon-triangle-ep1/character-bible.md"],
    )
    assert "分镜 Prompt" in d["symptom"]
    assert "400s" in d["root_cause"]
    assert "shot_prompts.md" in d["root_cause"]
    assert d["suggested_actions"][0]["who"] == "user"
    assert "character-bible.md" in d["related_files"][0]
    assert "未再调模型" in d["note"]


def test_timeout_detects_budget_status():
    assert _is_timeout_block("budget_exceeded", "")
    assert _is_timeout_block("", "CLI 调用超时（400s）")
    assert not _is_timeout_block("waiting_human", "")


def test_generic_skill_failure_still_human_readable():
    d = synthesize_blocked_diagnosis(
        skill_id="director-visual",
        skill_status="error",
        error_msg="LIGHTAI_API_KEY 未配置",
    )
    assert "人物与音色" in d["symptom"]
    assert "LIGHTAI_API_KEY" in d["root_cause"]
