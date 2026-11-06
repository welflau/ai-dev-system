"""current-action 的 elapsed / health：naive 本地时间不能当 UTC 解析。"""
from datetime import datetime, timedelta, timezone

from api.tickets import compute_ticket_action_progress


def test_naive_local_started_at_is_not_future():
    now = datetime.now().astimezone()
    started = (now.replace(tzinfo=None) - timedelta(seconds=120)).isoformat()
    prog = compute_ticket_action_progress(started, started, now=now)
    assert prog["elapsed_ms"] >= 100_000
    assert prog["elapsed_ms"] < 180_000
    assert prog["health"] == "silent"


def test_naive_local_old_action_is_zombie():
    now = datetime.now().astimezone()
    started = (now.replace(tzinfo=None) - timedelta(seconds=400)).isoformat()
    prog = compute_ticket_action_progress(started, None, now=now)
    assert prog["elapsed_ms"] >= 350_000
    assert prog["health"] == "zombie"


def test_aware_utc_timestamps_still_work():
    now = datetime.now(timezone.utc)
    started = (now - timedelta(seconds=30)).isoformat()
    prog = compute_ticket_action_progress(started, started, now=now)
    assert prog["elapsed_ms"] >= 20_000
    assert prog["health"] == "active"


def test_future_naive_elapsed_clamped_not_negative():
    now = datetime.now().astimezone()
    future = (now.replace(tzinfo=None) + timedelta(hours=8)).isoformat()
    prog = compute_ticket_action_progress(future, future, now=now)
    assert prog["elapsed_ms"] == 0
    assert prog["silence_ms"] == 0
    assert prog["health"] == "active"
