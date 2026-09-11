"""
launcher.automation — headless Automation RunTests + report parsing.

Spawns UnrealEditor-Cmd.exe with the standard "Automation RunTests <suite>; Quit"
template, points -ReportExportPath at a fresh timestamped folder, then parses
the resulting index.json to summarize pass/fail counts.
"""

from __future__ import annotations

import json
import socket
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from .config import LauncherConfig
from .discovery import editor_cmd_relpath
from .runner import RunResult, list_running_editors, run_blocking
from .validator import ValidationError, build_automation_argv


@dataclass
class TestFailure:
    test_name: str
    error_message: str = ""


@dataclass
class AutomationOutcome:
    success: bool
    suite: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    failures: list[TestFailure] = field(default_factory=list)
    report_dir: Optional[str] = None
    log_path: Optional[str] = None
    duration_sec: float = 0.0
    timed_out: bool = False
    returncode: Optional[int] = None
    error: Optional[str] = None  # populated on preflight failure

    def to_dict(self) -> dict:
        return asdict(self)


# ── preflight ──────────────────────────────────────────────────────────────

def assert_no_running_editor() -> None:
    procs = list_running_editors()
    if procs:
        names = ", ".join(f"{p['name']}(PID {p['pid']})" for p in procs)
        raise RuntimeError(
            f"Cannot run headless tests while UnrealEditor is running: {names}. "
            "Close the editor first or call launcher.stop_editor."
        )


# ── report parsing ─────────────────────────────────────────────────────────

def _parse_report(report_dir: Path) -> AutomationOutcome:
    """Parse Saved/Automation/Reports/<ts>/index.json (UE's standard format)."""
    out = AutomationOutcome(success=False, suite="", report_dir=str(report_dir))
    index = report_dir / "index.json"
    if not index.is_file():
        out.error = f"index.json not found at {index}"
        return out
    try:
        # UE 5.7 writes index.json with a UTF-8 BOM; use utf-8-sig so we
        # transparently strip it. Falls back identically for plain UTF-8.
        data = json.loads(index.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        out.error = f"failed to parse {index}: {exc}"
        return out

    tests = data.get("tests") or []
    out.total = len(tests)
    for t in tests:
        state = (t.get("state") or "").lower()
        if state == "success":
            out.passed += 1
        elif state == "skipped":
            out.skipped += 1
        elif state in ("fail", "failed", "error"):
            out.failed += 1
            entries = t.get("entries") or []
            msg_parts: list[str] = []
            for e in entries:
                if (e.get("event") or {}).get("type") in ("Error", "Warning"):
                    m = (e.get("event") or {}).get("message")
                    if m:
                        msg_parts.append(str(m))
            out.failures.append(TestFailure(
                test_name=t.get("fullTestPath") or t.get("testDisplayName") or "<unnamed>",
                error_message=" | ".join(msg_parts)[:500],
            ))
    out.success = out.failed == 0 and out.total > 0
    return out


# ── runner ─────────────────────────────────────────────────────────────────

def run_automation(cfg: LauncherConfig,
                   *,
                   suite: str,
                   timeout_sec: Optional[int] = None) -> AutomationOutcome:
    if not cfg.project.engine_root:
        raise RuntimeError("engine_root is unknown — fill it in .uemcp/launcher.json")

    engine_root = Path(cfg.project.engine_root)
    project_root = Path(cfg.project.project_root)
    uproject = Path(cfg.project.uproject_path)

    # 1) preflight — no running editor (would fight for .uproject mutex)
    assert_no_running_editor()

    # 2) prepare report dir
    ts = time.strftime("%Y%m%d_%H%M%S")
    report_dir = (project_root / cfg.report_root / ts).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)

    # 3) build & validate argv (validator enforces suite prefix policy)
    editor_cmd = engine_root / editor_cmd_relpath()
    try:
        argv = build_automation_argv(
            editor_cmd=editor_cmd,
            uproject=uproject,
            suite=suite,
            report_dir=report_dir,
            required_prefix=cfg.test_suite_prefix,
        )
    except ValidationError as exc:
        outc = AutomationOutcome(success=False, suite=suite, report_dir=str(report_dir))
        outc.error = str(exc)
        return outc

    # 4) spawn (sync)
    log_path = project_root / cfg.log_tail_root / f"uemcp_autotest_{ts}.log"
    rr: RunResult = run_blocking(
        argv,
        cwd=project_root,
        timeout_sec=timeout_sec or cfg.process_timeout_sec,
        tail_lines=200,
        log_path=log_path,
    )

    # 5) parse
    outc = _parse_report(report_dir)
    outc.suite = suite
    outc.log_path = rr.log_path
    outc.duration_sec = rr.duration_sec
    outc.timed_out = rr.timed_out
    outc.returncode = rr.returncode
    if outc.error is None and rr.returncode not in (0, None) and outc.total == 0:
        outc.error = f"editor returned code {rr.returncode} and no test report was produced"
    return outc


# ── readiness probe (for after start_editor) ───────────────────────────────

def wait_for_bridge_ready(host: str, port: int, timeout_sec: float = 60.0,
                          poll_interval_sec: float = 1.0) -> bool:
    """TCP-level probe: wait until UEEditorMCP's MCPBridge socket accepts."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2.0):
                return True
        except OSError:
            time.sleep(poll_interval_sec)
    return False
