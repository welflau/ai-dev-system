"""验证实际 lifespan 在 Uvicorn 子进程内的启动、清理顺序和最终退出。"""
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

PROBE = Path(__file__).with_name("lifespan_probe.py")


def run_probe(case, folder):
    result = folder / "result.json"
    with subprocess.Popen([sys.executable, str(PROBE), case, str(folder)],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as process:
        try:
            end = time.monotonic() + 45
            while not result.exists() and process.poll() is None and time.monotonic() < end:
                time.sleep(0.05)
            assert result.exists(), f"{case}: no report, exit={process.poll()}"
            try:
                code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                code = None
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    return {**json.loads(result.read_text(encoding="utf8")), "exit": code}


@pytest.mark.parametrize("case", ["normal", "mcp-stop-error", "schema-error", "startup-cancel"])
def test_lifespan_releases_resources_and_process_exits(case, tmp_path):
    data = run_probe(case, tmp_path)
    events = data["events"]
    assert data["port_closed"] and data["exit"] == 0, data
    assert events[0] == "db.open" and events[-1] == "db.close", events
    assert not data["workers_at_db_close"] and not data["workers_after_serve"]
    if case == "schema-error":
        assert events == ["db.open", "db.close"]
    else:
        assert events[:5] == ["db.open", "db.schema", "hooks", "projects.restore", "mcp.start"]
        assert not data["workers_at_mcp_stop"] and events[-2] == "mcp.stop"
        if case == "startup-cancel":
            assert "http.200" not in events
            assert "stop.image" in events
        else:
            assert data["port_closed_at_db_close"]
            assert data["gc_at_ready"] == data["gc_done_at_db_close"] == 2
            assert data["workers_at_ready"] == ["automation", "bus", "ci", "image", "poll"]
            assert "http.200" in events
