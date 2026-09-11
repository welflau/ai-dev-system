"""
launcher.tools — MCP Tool definitions + handlers for the launcher server.

Naming convention: every tool name is prefixed with `launcher_` to avoid
collisions with the editor server's existing tool catalog (whose names are
flat words like `save_all`, `is_ready`, etc.).

LLM-visible tool surface (5 tools, 2026-06-05 async refactor):
  * launcher_start_editor      — submits an async build+spawn+wait task
  * launcher_run_automation    — submits an async build+headless-runtests task
  * launcher_stop_editor       — synchronous stop (fast, < 5s)
  * launcher_task_status       — poll a task by id (state/stages/log_tail)
  * launcher_task_cancel       — request cancel of a running task

Why async
---------
MCP clients impose a hard ~10s per-call timeout. `start_editor` (which
includes UBT compile) and `run_automation` (which can run for hours) are
far too slow for synchronous return. Both are now submitted as background
tasks via `launcher.tasks` and the LLM polls progress with
`launcher_task_status`. State is persisted under
`<project_root>/.uemcp/tasks/`, so a server restart keeps logs and
results available; in-flight tasks are flagged `state="orphaned"` on the
next startup.

Hidden helpers (still reachable via direct `handle_tool(name, args)`):
  build_editor / is_editor_running / wait_until_ready /
  get_config / reset_config — kept for setup scripts and regression
  tests, intentionally NOT in `get_tools()`.
"""

from __future__ import annotations

import json
import socket
from dataclasses import asdict
from pathlib import Path
from typing import Any

from mcp.types import Tool, TextContent

from .config import LauncherConfig, load_config, reset_config
from .discovery import editor_cmd_relpath, editor_gui_relpath
from .runner import REGISTRY, list_running_editors, run_detached
from .tasks import (
    STATE_DONE, STATE_FAILED, STATE_CANCELLED, STATE_RUNNING,
    TaskHandle, get_store, render_snapshot,
)
from .validator import ValidationError, build_interactive_argv

# Lazy imports to avoid heavy import cost when the server hasn't loaded a config
def _builder():
    from . import builder as _b
    return _b

def _automation():
    from . import automation as _a
    return _a


# ── tool schema (LLM-visible surface: 5 tools, async submit/poll model) ──

def get_tools() -> list[Tool]:
    return [
        Tool(
            name="launcher_start_editor",
            description=(
                "Submit an async task that builds (optional), spawns UnrealEditor, "
                "and waits for MCPBridge to be ready. Returns IMMEDIATELY (<1s) with "
                "a `task_id`. The actual build+launch can take minutes — poll status "
                "with `launcher_task_status(task_id=...)`.\n\n"
                "Pipeline (executed by the background worker):\n"
                "  (1) optional UBT incremental build (default: build=true)\n"
                "  (2) process self-check (managed/external/mode-mismatch)\n"
                "  (3) spawn editor (headless via -Cmd+-nullrhi, or interactive GUI)\n"
                "  (4) wait for MCPBridge TCP port to accept connections\n\n"
                "Mode 'headless' uses -nullrhi for automation; mode 'interactive' "
                "(default) starts the GUI editor — use when tests need Slate, real "
                "RHI, PIE networking, or human-in-the-loop verification.\n\n"
                "Fast-path short-circuits (return done synchronously without spawning "
                "a worker thread):\n"
                "  - if a launcher-managed editor with the same mode is already alive, "
                "    result.status='already_running_managed'\n"
                "  - if only an external (non-launcher) editor is alive, "
                "    result.status='already_running_external' (NOT touched)\n"
                "  - if a launcher-managed editor is alive in a DIFFERENT mode, the "
                "    task fails with status='mode_mismatch'; caller should call "
                "    launcher_stop_editor first."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["headless", "interactive"],
                        "description": "Default 'interactive'. Use 'headless' for automation runs without GUI."
                    },
                    "build": {
                        "type": "boolean",
                        "description": "If true (default) run UBT before launch. Set to false only if you just compiled and want to skip the redundant pass."
                    },
                    "wait_ready": {
                        "type": "boolean",
                        "description": "If true (default) the worker waits until MCPBridge is ready before marking the task done. Set to false to mark done as soon as the editor PID is spawned."
                    },
                    "wait_timeout_sec": {
                        "type": "number",
                        "description": "Bridge readiness probe timeout in seconds (default 300)."
                    },
                    "build_timeout_sec": {
                        "type": "integer",
                        "description": "Per-build timeout in seconds (default: from launcher.json process_timeout_sec)."
                    },
                    "project_root_hint": {"type": "string"}
                }
            },
        ),
        Tool(
            name="launcher_run_automation",
            description=(
                "Submit an async task that builds (optional) and runs a headless UE "
                "Automation test suite. Returns IMMEDIATELY (<1s) with a `task_id`. "
                "Test runs commonly take 5min–2h — poll progress with "
                "`launcher_task_status(task_id=...)`.\n\n"
                "Pipeline (executed by the background worker):\n"
                "  (1) optional UBT incremental build (default: build=true)\n"
                "  (2) preflight — refuses to run if any UnrealEditor process is alive\n"
                "  (3) spawn UnrealEditor-Cmd with 'Automation RunTests <suite>; Quit'\n"
                "  (4) parse Saved/Automation/Reports/<ts>/index.json\n\n"
                "On task completion the result field carries "
                "{passed, failed, skipped, failures[], report_dir, log_path}. "
                "Suite name must match the project's test_suite_prefix policy "
                "(e.g. 'P111.LJC+')."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "suite": {
                        "type": "string",
                        "description": "Automation test suite, e.g. 'P111.LJC+'. Trailing '+' is the standard UE glob."
                    },
                    "build": {
                        "type": "boolean",
                        "description": "If true (default) run UBT before tests. Set to false only if the binary is known to be up-to-date."
                    },
                    "timeout_sec": {
                        "type": "integer",
                        "description": "Per-run-tests timeout in seconds."
                    },
                    "build_timeout_sec": {
                        "type": "integer",
                        "description": "Per-build timeout in seconds."
                    },
                    "project_root_hint": {"type": "string"}
                },
                "required": ["suite"]
            },
        ),
        Tool(
            name="launcher_stop_editor",
            description=(
                "Stop launcher-managed UnrealEditor processes. Synchronous (returns "
                "in <5s). Auto-detects state — the LLM does NOT need to probe "
                "processes first.\n\n"
                "Default safety: only kills editors THIS launcher server spawned. "
                "External editors (e.g. ones launched by an IDE debug session, or "
                "started manually before the launcher was running) are left alone.\n\n"
                "Status field in the response:\n"
                "  - 'stopped'           : at least one managed editor was terminated\n"
                "  - 'already_stopped'   : no managed editor was alive (no-op success)\n"
                "  - 'external_only'     : only external editors are alive; nothing was "
                "killed. The LLM should tell the user to close their IDE debug session "
                "manually if needed."
            ),
            inputSchema={
                "type": "object",
                "properties": {}
            },
        ),
        Tool(
            name="launcher_task_status",
            description=(
                "Poll the status of an async launcher task. Returns the latest "
                "snapshot: state ∈ {queued, running, done, failed, cancelled, "
                "orphaned}, current `progress` text, full `stages[]` timeline, "
                "`pid` of the spawned subprocess (when applicable), and the final "
                "`result` (when state=done) or `error` (when state=failed).\n\n"
                "Set `log_tail_lines` > 0 to additionally include the most recent "
                "lines of the task's combined stdout/stderr log (capped to keep "
                "payloads small). The full log file path is returned in `log_path` "
                "so the caller can read more if needed.\n\n"
                "Recommended polling cadence: 3-5s for short tasks (start_editor), "
                "15-30s for long tasks (run_automation). The response also includes "
                "`stalled=true` if the worker hasn't heartbeat-ed for 120s — a hint "
                "that the underlying subprocess may be hung (but it could also just "
                "be a long UBT step with no output)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "The task id returned by launcher_start_editor / launcher_run_automation."
                    },
                    "log_tail_lines": {
                        "type": "integer",
                        "description": "How many recent log lines to include (default 0; max ~400). Higher values consume more output budget."
                    },
                    "project_root_hint": {"type": "string"}
                },
                "required": ["task_id"]
            },
        ),
        Tool(
            name="launcher_task_cancel",
            description=(
                "Request cancellation of a running launcher task. The worker checks "
                "the cancel flag at safe points (between stages); for blocking "
                "subprocess calls (UBT, headless RunTests) the registered subprocess "
                "is hard-killed. Returns immediately (<5s); poll "
                "`launcher_task_status` to confirm the task ends in state='cancelled'.\n\n"
                "NOTE: cancelling `launcher_start_editor` mid-build will NOT undo a "
                "partial UBT compile. Cancelling after the editor PID has been "
                "spawned will hard-kill the editor. Use `launcher_stop_editor` for "
                "the normal-shutdown path."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "The task id to cancel."
                    },
                    "project_root_hint": {"type": "string"}
                },
                "required": ["task_id"]
            },
        ),
    ]

# ── helpers ────────────────────────────────────────────────────────────────

def _ok(payload: dict) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps({"success": True, **payload}, indent=2, ensure_ascii=False))]


def _err(message: str, **extra) -> list[TextContent]:
    body = {"success": False, "error": message}
    body.update(extra)
    return [TextContent(type="text", text=json.dumps(body, indent=2, ensure_ascii=False))]


def _load(args: dict[str, Any]) -> tuple[LauncherConfig | None, list[str]]:
    return load_config(project_root_hint=args.get("project_root_hint"))


def _config_summary(cfg: LauncherConfig) -> dict:
    d = {
        "schema_version": cfg.schema_version,
        "project": asdict(cfg.project),
        "build_target_suffix": cfg.build_target_suffix,
        "build_platform": cfg.build_platform,
        "build_config": cfg.build_config,
        "test_suite_prefix": cfg.test_suite_prefix,
        "process_timeout_sec": cfg.process_timeout_sec,
        "log_tail_root": cfg.log_tail_root,
        "report_root": cfg.report_root,
        "allow_gui_launch": cfg.allow_gui_launch,
        "bridge_host": cfg.bridge_host,
        "bridge_port": cfg.bridge_port,
        "auto_generated": cfg.auto_generated,
    }
    return d


# ── per-tool handlers ──────────────────────────────────────────────────────

async def _h_get_config(args: dict[str, Any]) -> list[TextContent]:
    cfg, notes = _load(args)
    if not cfg:
        return _err("could not auto-detect project — no *.uproject found", notes=notes)
    return _ok({"config": _config_summary(cfg), "notes": notes})


async def _h_reset_config(args: dict[str, Any]) -> list[TextContent]:
    deleted = reset_config(args.get("project_root_hint"))
    return _ok({"deleted": deleted})


async def _h_is_editor_running(args: dict[str, Any]) -> list[TextContent]:
    procs = list_running_editors()
    managed = [p.pid for p in REGISTRY.list_alive()]
    return _ok({
        "running": bool(procs),
        "count": len(procs),
        "processes": procs,
        "managed_by_this_server": managed,
    })


async def _h_build_editor(args: dict[str, Any]) -> list[TextContent]:
    cfg, notes = _load(args)
    if not cfg:
        return _err("config unavailable", notes=notes)
    try:
        outcome = _builder().build_target(
            cfg,
            target=args.get("target"),
            platform=args.get("platform"),
            build_config=args.get("config"),
            timeout_sec=args.get("timeout_sec"),
        )
    except ValidationError as exc:
        return _err(f"validation failed: {exc}", notes=notes)
    except Exception as exc:  # noqa: BLE001
        return _err(f"build failed: {exc}", notes=notes)
    return _ok({"outcome": outcome.to_dict(), "notes": notes})


async def _h_run_automation_sync(args: dict[str, Any]) -> list[TextContent]:
    """[hidden helper] Auto-build (optional) → preflight → headless RunTests → parse report.

    NOTE: this is the *synchronous* implementation kept for setup scripts and
    regression tests. The LLM-visible `launcher_run_automation` tool now
    submits a background task (see `_h_run_automation`).
    """
    cfg, notes = _load(args)
    if not cfg:
        return _err("config unavailable", notes=notes)
    suite = args.get("suite")
    if not suite:
        return _err("'suite' is required")

    do_build = bool(args.get("build", True))
    build_timeout = args.get("build_timeout_sec")

    # 1) optional pre-build
    build_summary: dict | None = None
    if do_build:
        try:
            outcome = _builder().build_target(
                cfg, target=None, platform=None, build_config=None,
                timeout_sec=build_timeout,
            )
        except ValidationError as exc:
            return _err(f"build validation failed: {exc}", notes=notes)
        except Exception as exc:  # noqa: BLE001
            return _err(f"build failed: {exc}", notes=notes)
        build_summary = outcome.to_dict()
        if not outcome.success:
            return _err(
                "build_failed",
                status="build_failed",
                build=build_summary,
                advice="fix the compile errors above and retry; pass build=false to skip rebuild",
                notes=notes,
            )

    # 2) headless run
    try:
        outc = _automation().run_automation(
            cfg, suite=suite, timeout_sec=args.get("timeout_sec"),
        )
    except ValidationError as exc:
        return _err(f"validation failed: {exc}", notes=notes)
    except RuntimeError as exc:
        return _err(str(exc), notes=notes)
    return _ok({"outcome": outc.to_dict(), "build": build_summary, "notes": notes})


# ── Async worker bodies (run inside background threads via tasks.submit) ─

def _worker_start_editor(handle: TaskHandle, cfg: LauncherConfig, notes: list[str], args: dict[str, Any]) -> dict[str, Any]:
    """Background body for `launcher_start_editor`. Honours cancellation
    between stages; reports progress via `handle.set_stage` /
    `handle.heartbeat`."""
    mode = (args.get("mode") or "interactive").lower()
    do_build = bool(args.get("build", True))
    do_wait = bool(args.get("wait_ready", True))
    wait_timeout = float(args.get("wait_timeout_sec", 300.0))
    build_timeout = args.get("build_timeout_sec")

    handle.append_log(f"[start_editor] mode={mode} build={do_build} wait_ready={do_wait}")

    # ---- 1) optional pre-build ------------------------------------------
    build_summary: dict | None = None
    if do_build:
        handle.set_stage("build", note="running UBT (this may take several minutes)")
        handle.check_cancelled()
        try:
            outcome = _builder().build_target(
                cfg, target=None, platform=None, build_config=None,
                timeout_sec=build_timeout,
            )
        except ValidationError as exc:
            raise RuntimeError(f"build validation failed: {exc}") from exc
        build_summary = outcome.to_dict()
        # Tail a few build log lines into the task log so the caller can see context
        for line in (outcome.stdout_tail or [])[-40:]:
            handle.append_log("[ubt] " + line)
        if not outcome.success:
            return {
                "status": "build_failed",
                "build": build_summary,
                "advice": "fix the compile errors above and retry; pass build=false to skip rebuild",
                "notes": notes,
            }

    handle.check_cancelled()

    # ---- 2) spawn -------------------------------------------------------
    handle.set_stage("spawn", note=f"launching editor ({mode})")
    engine_root = Path(cfg.project.engine_root)
    project_root = Path(cfg.project.project_root)
    uproject = Path(cfg.project.uproject_path)

    if mode == "headless":
        editor_cmd = engine_root / editor_cmd_relpath()
        argv = [
            str(editor_cmd), str(uproject),
            "-unattended", "-nopause", "-nullrhi", "-nosplash", "-log",
        ]
        gui_mode = False
    else:  # interactive
        editor_gui = engine_root / editor_gui_relpath()
        try:
            argv = build_interactive_argv(editor_gui=editor_gui, uproject=uproject)
        except ValidationError as exc:
            raise RuntimeError(str(exc)) from exc
        gui_mode = True

    log_path = project_root / cfg.log_tail_root / f"uemcp_{mode}_launch.log"
    pid = run_detached(
        argv,
        cwd=project_root,
        log_path=log_path,
        gui_mode=gui_mode,
        mode_tag=mode,
    )
    handle.set_pid(pid)
    handle.set_cancel_pid(pid)  # cancel during wait_ready will hard-kill the editor
    handle.append_log(f"[start_editor] spawned pid={pid}")

    # ---- 3) wait for bridge ready ---------------------------------------
    bridge_ready: bool | None = None
    if do_wait:
        handle.set_stage("wait_ready", note=f"polling MCPBridge at {cfg.bridge_host}:{cfg.bridge_port}")
        # custom poll loop so we can heartbeat + check cancel every second
        deadline = (__import__("time")).time() + wait_timeout
        while (__import__("time")).time() < deadline:
            handle.check_cancelled()
            try:
                with socket.create_connection((cfg.bridge_host, cfg.bridge_port), timeout=2.0):
                    bridge_ready = True
                    break
            except OSError:
                handle.heartbeat(progress=f"wait_ready — bridge not yet up ({int(deadline - (__import__('time')).time())}s left)")
                (__import__("time")).sleep(1.0)
        if bridge_ready is None:
            bridge_ready = False

    # release cancel_pid: from now on cancel should NOT auto-kill the editor
    handle.set_cancel_pid(None)

    payload: dict[str, Any] = {
        "status": "started",
        "pid": pid,
        "mode": mode,
        "gui_mode": gui_mode,
        "log_path": str(log_path) if not gui_mode else None,
        "bridge_host": cfg.bridge_host,
        "bridge_port": cfg.bridge_port,
        "bridge_ready": bridge_ready,
        "build": build_summary,
        "notes": notes,
    }
    if do_wait and bridge_ready is False:
        payload["warning"] = (
            f"editor PID {pid} spawned but MCPBridge did not become ready within "
            f"{wait_timeout:.0f}s; check Saved/Logs or retry."
        )
    return payload


def _worker_run_automation(handle: TaskHandle, cfg: LauncherConfig, notes: list[str], args: dict[str, Any]) -> dict[str, Any]:
    """Background body for `launcher_run_automation`."""
    suite = args.get("suite")
    do_build = bool(args.get("build", True))
    build_timeout = args.get("build_timeout_sec")
    run_timeout = args.get("timeout_sec")

    handle.append_log(f"[run_automation] suite={suite} build={do_build}")

    # ---- 1) optional pre-build ------------------------------------------
    build_summary: dict | None = None
    if do_build:
        handle.set_stage("build", note="running UBT")
        handle.check_cancelled()
        try:
            outcome = _builder().build_target(
                cfg, target=None, platform=None, build_config=None,
                timeout_sec=build_timeout,
            )
        except ValidationError as exc:
            raise RuntimeError(f"build validation failed: {exc}") from exc
        build_summary = outcome.to_dict()
        for line in (outcome.stdout_tail or [])[-40:]:
            handle.append_log("[ubt] " + line)
        if not outcome.success:
            return {
                "status": "build_failed",
                "build": build_summary,
                "advice": "fix the compile errors above and retry; pass build=false to skip rebuild",
                "notes": notes,
            }

    handle.check_cancelled()

    # ---- 2) headless RunTests ------------------------------------------
    handle.set_stage("run_tests", note=f"Automation RunTests {suite}")
    try:
        outc = _automation().run_automation(
            cfg, suite=suite, timeout_sec=run_timeout,
        )
    except ValidationError as exc:
        raise RuntimeError(f"validation failed: {exc}") from exc

    handle.append_log(f"[run_automation] passed={outc.passed} failed={outc.failed} skipped={outc.skipped}")
    return {
        "status": "done",
        "outcome": outc.to_dict(),
        "build": build_summary,
        "notes": notes,
    }


async def _h_start_editor(args: dict[str, Any]) -> list[TextContent]:
    """Submit-task entry. Returns IMMEDIATELY with `task_id` (and possibly
    a synchronous fast-path result for already_running cases)."""
    cfg, notes = _load(args)
    if not cfg:
        return _err("config unavailable", notes=notes)
    if not cfg.project.engine_root:
        return _err("engine_root is unknown — fill it in .uemcp/launcher.json")

    mode = (args.get("mode") or "interactive").lower()
    if mode not in ("headless", "interactive"):
        return _err(f"invalid mode: {mode}")

    # ---- fast-path: process self-check (synchronous, < 1s) -------------
    managed = REGISTRY.list_alive_with_mode()
    same_mode = [(pid, m) for pid, m in managed if m == mode]
    diff_mode = [(pid, m) for pid, m in managed if m and m != mode]

    if same_mode:
        pid, _ = same_mode[0]
        return _ok({
            "status": "already_running_managed",
            "task_id": None,
            "pid": pid,
            "mode": mode,
            "note": "reusing existing launcher-managed editor with the same mode; no task spawned. Call ue_ping to verify the bridge.",
            "notes": notes,
        })

    if diff_mode:
        pid, running_mode = diff_mode[0]
        return _err(
            "mode_mismatch",
            status="mode_mismatch",
            running_pid=pid,
            running_mode=running_mode,
            requested_mode=mode,
            advice="call launcher_stop_editor first, then retry with the desired mode",
            notes=notes,
        )

    external_procs = list_running_editors()
    if external_procs:
        return _ok({
            "status": "already_running_external",
            "task_id": None,
            "external_processes": external_procs,
            "requested_mode": mode,
            "advice": (
                "An editor is already running but was NOT spawned by this launcher "
                "(likely a user IDE debug session). Not touching it. If you need a "
                "clean slate, ask the user to close it manually — launcher_stop_editor "
                "will not kill external processes by default."
            ),
            "notes": notes,
        })

    # ---- slow-path: submit background task -----------------------------
    project_root = Path(cfg.project.project_root)
    store = get_store(project_root)

    def _worker(handle: TaskHandle) -> dict[str, Any]:
        return _worker_start_editor(handle, cfg, notes, args)

    snap = store.submit("start_editor", _worker, args=args)
    return _ok({
        "status": "submitted",
        "task_id": snap.task_id,
        "kind": snap.kind,
        "poll_with": "launcher_task_status",
        "hint": "Call launcher_task_status(task_id=...) every 3-5s to track progress. Final result will appear in `result` when state='done'.",
        "notes": notes,
    })


async def _h_run_automation(args: dict[str, Any]) -> list[TextContent]:
    """Submit-task entry for headless automation. Returns IMMEDIATELY with `task_id`."""
    cfg, notes = _load(args)
    if not cfg:
        return _err("config unavailable", notes=notes)
    if not cfg.project.engine_root:
        return _err("engine_root is unknown — fill it in .uemcp/launcher.json")
    suite = args.get("suite")
    if not suite:
        return _err("'suite' is required")

    project_root = Path(cfg.project.project_root)
    store = get_store(project_root)

    def _worker(handle: TaskHandle) -> dict[str, Any]:
        return _worker_run_automation(handle, cfg, notes, args)

    snap = store.submit("run_automation", _worker, args=args)
    return _ok({
        "status": "submitted",
        "task_id": snap.task_id,
        "kind": snap.kind,
        "poll_with": "launcher_task_status",
        "hint": "Call launcher_task_status(task_id=..., log_tail_lines=20) every 15-30s to track progress. Final {passed, failed, skipped, failures[]} will appear in `result.outcome`.",
        "notes": notes,
    })


async def _h_task_status(args: dict[str, Any]) -> list[TextContent]:
    """Poll an async task by id."""
    cfg, _notes = _load(args)
    project_root = Path(cfg.project.project_root) if cfg else Path.cwd()
    store = get_store(project_root)
    task_id = args.get("task_id")
    if not task_id:
        return _err("'task_id' is required")
    snap = store.get(task_id)
    if not snap:
        return _err(f"unknown task_id: {task_id}",
                    advice="Task may have been GC'd (terminal tasks are kept 7 days).")
    log_tail_lines = int(args.get("log_tail_lines", 0) or 0)
    log_tail_lines = max(0, min(log_tail_lines, 400))
    return _ok(render_snapshot(snap, log_tail_lines=log_tail_lines, store=store))


async def _h_task_cancel(args: dict[str, Any]) -> list[TextContent]:
    """Request cancellation of a running task."""
    cfg, _notes = _load(args)
    project_root = Path(cfg.project.project_root) if cfg else Path.cwd()
    store = get_store(project_root)
    task_id = args.get("task_id")
    if not task_id:
        return _err("'task_id' is required")
    ok, msg = store.request_cancel(task_id)
    snap = store.get(task_id)
    payload: dict[str, Any] = {"task_id": task_id, "cancel_signalled": ok, "message": msg}
    if snap:
        payload["snapshot"] = render_snapshot(snap, store=store)
    return _ok(payload) if ok else _err(msg, **payload)


async def _h_stop_editor(args: dict[str, Any]) -> list[TextContent]:
    """Stop launcher-managed editors. Auto-detects state — the LLM does not
    need to probe processes first.

    Hidden args (not in the public schema, used by setup scripts/tests):
      * pid                    : kill a single PID we own
      * force_kill_external    : also kill non-managed UnrealEditor processes
    """
    pid = args.get("pid")
    force_external = bool(args.get("force_kill_external", False))

    if pid is not None:
        ok = REGISTRY.kill_pid(int(pid))
        return _ok({
            "status": "stopped" if ok else "already_stopped",
            "killed_pid": pid,
            "ok": ok,
        })

    managed_alive = REGISTRY.list_alive()
    external = list_running_editors()
    # "external" includes both managed PIDs and outside processes — filter to
    # the ones we DON'T own so we can report them honestly.
    managed_pids = {p.pid for p in managed_alive}
    truly_external = [p for p in external if p["pid"] not in managed_pids]

    if not managed_alive and not truly_external:
        return _ok({
            "status": "already_stopped",
            "killed_managed": 0,
            "killed_external": 0,
        })

    if not managed_alive and truly_external and not force_external:
        return _ok({
            "status": "external_only",
            "killed_managed": 0,
            "killed_external": 0,
            "external_processes": truly_external,
            "advice": (
                "Only external (non-launcher-managed) editors are alive. "
                "Not killing them by default — they may be the user's IDE "
                "debug session. Ask the user to close them manually if needed."
            ),
        })

    killed = REGISTRY.kill_all() if managed_alive else 0
    killed_ext = 0
    if force_external:
        for p in truly_external:
            try:
                import os as _os
                _os.kill(p["pid"], 9)
                killed_ext += 1
            except OSError:
                pass
    return _ok({
        "status": "stopped",
        "killed_managed": killed,
        "killed_external": killed_ext,
    })


async def _h_wait_until_ready(args: dict[str, Any]) -> list[TextContent]:
    cfg, notes = _load({})
    timeout = float(args.get("timeout_sec", 60.0))
    poll = float(args.get("poll_interval_sec", 1.0))
    host = cfg.bridge_host if cfg else "127.0.0.1"
    port = cfg.bridge_port if cfg else 55558
    ok = _automation().wait_for_bridge_ready(host, port, timeout_sec=timeout, poll_interval_sec=poll)
    return _ok({"ready": ok, "host": host, "port": port, "timeout_sec": timeout})


# ── dispatch table (matches server_factory contract) ──────────────────────

TOOL_HANDLERS: dict[str, Any] = {
    # LLM-visible (5 tools)
    "launcher_start_editor": _h_start_editor,
    "launcher_run_automation": _h_run_automation,
    "launcher_stop_editor": _h_stop_editor,
    "launcher_task_status": _h_task_status,
    "launcher_task_cancel": _h_task_cancel,
    # hidden helpers (still reachable via direct handle_tool(...))
    "launcher_get_config": _h_get_config,
    "launcher_reset_config": _h_reset_config,
    "launcher_is_editor_running": _h_is_editor_running,
    "launcher_build_editor": _h_build_editor,
    "launcher_wait_until_ready": _h_wait_until_ready,
    # legacy synchronous run_automation (kept under a renamed key so power
    # users / setup scripts can still bypass the async layer if they want
    # blocking behaviour; the LLM tool name maps to the async submit version)
    "launcher_run_automation_sync": _h_run_automation_sync,
}


async def handle_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return _err(f"unknown tool: {name}")
    return await handler(arguments or {})
