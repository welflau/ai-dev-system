"""停止按钮必须认 director_*_in_progress，且不能误关人审 *_ready。"""
from api.tickets import ticket_status_is_stoppable


def test_director_visual_in_progress_is_stoppable():
    assert ticket_status_is_stoppable("director_visual_in_progress")
    assert ticket_status_is_stoppable("director_brief_in_progress")
    assert ticket_status_is_stoppable("in_progress")
    assert ticket_status_is_stoppable("pending")
    assert ticket_status_is_stoppable("running")


def test_human_gate_ready_is_not_stoppable():
    assert not ticket_status_is_stoppable("director_script_ready")
    assert not ticket_status_is_stoppable("director_brief_ready")
    assert not ticket_status_is_stoppable("architecture_done")
    assert not ticket_status_is_stoppable("cancelled")
    assert not ticket_status_is_stoppable("blocked")
    assert not ticket_status_is_stoppable("deployed")
    assert not ticket_status_is_stoppable("")
    assert not ticket_status_is_stoppable(None)
