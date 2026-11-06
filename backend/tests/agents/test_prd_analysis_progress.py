"""PRD 分析进度文案。"""
from orchestrator import analysis_progress_message


def test_progress_message_shows_elapsed_timeout_and_step():
    msg = analysis_progress_message(80, "正在调用 LLM 拆单", 1800)
    assert "80s" in msg
    assert "1800s" in msg
    assert "拆单" in msg


def test_progress_message_fallback_step():
    msg = analysis_progress_message(20, "", 120)
    assert "等待 LLM" in msg
    assert "20s" in msg
