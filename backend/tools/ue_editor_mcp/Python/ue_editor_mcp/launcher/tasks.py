"""
launcher.tasks — persistent async task store for the launcher MCP server.

Why this exists
---------------
MCP clients (codebuddy/copilot/etc.) impose a hard ~10s timeout on each
tool call. That makes it impossible to do *synchronous* "build editor +
spawn + wait for MCPBridge ready" or "compile + run automation suite"
inside a single tool invocation, because UBT alone can take minutes and
a full automation run can take hours.

Design
------
* Long actions are submitted via `submit_task(kind, worker_fn)`. The
  submit call returns a `task_id` in <1s. A background thread runs the
  worker.
* The worker updates progress through `TaskHandle.set_stage(...)`,
  `append_log(...)`, `heartbeat()`. All updates are flushed to disk so a
  server restart loses neither result nor diagnostic context.
* Clients poll `read_task(task_id)` to get the latest snapshot
  (state/progress/stages/log_tail). State machine:

      queued → running → done
                       → failed
                       → cancelled
                       → orphaned   (server died mid-flight; recovered on next start)

* Persistence layout (under <project_root>/.uemcp/tasks/):
      <task_id>.json         — task metadata (single source of truth)
      <task_id>.log          — combined stdout/stderr-style log lines
      _index.json            — fast list cache (rebuildable from *.json)

* Retention: terminal tasks (done/failed/cancelled) are kept 7 days then
  GC'd. `running`/`orphaned` are kept indefinitely (they need user action).

* Cancellation: a cancel request flips `_cancel_event` for the task. The
  worker is expected to honour it at safe points (between stages); for
  long blocking calls (UBT, headless RunTests) we additionally allow the
  worker to register a "kill PID" via `set_cancel_pid(pid)` so cancel can
  forcibly terminate the subprocess.

This module is intentionally stdlib-only (no asyncio, no third-party deps)
so it can be imported and used from any thread without surprising the
MCP server's asyncio event loop.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import sys
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ── State constants ────────────────────────────────────────────────────────

STATE_QUEUED = "queued"
STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_FAILED = "failed"
STATE_CANCELLED = "cancelled"
STATE_ORPHANED = "orphaned"

TERMINAL_STATES = {STATE_DONE, STATE_FAILED, STATE_CANCELLED, STATE_ORPHANED}

# Retention policy
TERMINAL_RETENTION_SEC = 7 * 24 * 3600  # 7 days

# Stall detection (worker must heartbeat at least this often or it's "stalled")
STALL_THRESHOLD_SEC = 120.0


# ── Data model ─────────────────────────────────────────────────────────────

@dataclass
class StageRecord:
    name: str
    started_at: float
    ended_at: Optional[float] = None
    ok: Optional[bool] = None
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TaskSnapshot:
    """JSON-serializable view of a task. This is what gets persisted and
    what `read_task()` returns."""
    task_id: str
    kind: str  # "start_editor" / "run_automation" / ...
    state: str
    created_at: float
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    last_heartbeat_at: Optional[float] = None
    progress: str = ""  # short human-readable phase, e.g. "building (UBT)"
    stages: list[StageRecord] = field(default_factory=list)
    args: dict[str, Any] = field(default_factory=dict)
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    cancel_requested: bool = False
    cancel_pid: Optional[int] = None
    pid: Optional[int] = None  # spawned editor / cmd PID (for start_editor / run_automation)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["stages"] = [s if isinstance(s, dict) else s.to_dict() for s in self.stages]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TaskSnapshot":
        stages_raw = d.get("stages") or []
        stages = [StageRecord(**s) for s in stages_raw]
        d2 = dict(d)
        d2["stages"] = stages
        # tolerate unknown keys from older versions
        allowed = {f for f in cls.__dataclass_fields__}
        d2 = {k: v for k, v in d2.items() if k in allowed}
        return cls(**d2)


# ── Store (filesystem-backed) ──────────────────────────────────────────────

class TaskStore:
    """One TaskStore per project root. Owns the on-disk task layout and
    the in-memory worker registry."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # PID handles for active workers (for cancel)
        self._cancel_events: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}
        # In-memory log tails (recent N lines per task) for cheap polling
        self._log_tails: dict[str, deque[str]] = {}
        # Hot snapshot cache so polling doesn't re-read the JSON every call
        self._snapshots: dict[str, TaskSnapshot] = {}

    # ── path helpers ──
    def _meta_path(self, task_id: str) -> Path:
        return self.root / f"{task_id}.json"

    def _log_path(self, task_id: str) -> Path:
        return self.root / f"{task_id}.log"

    def _index_path(self) -> Path:
        return self.root / "_index.json"

    # ── persistence ──
    def _flush(self, snap: TaskSnapshot) -> None:
        """Atomic write: dump to .tmp then rename."""
        path = self._meta_path(snap.task_id)
        tmp = path.with_suffix(".json.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(snap.to_dict(), f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError as exc:
            logger.warning("failed to flush task %s: %s", snap.task_id, exc)

    def _load_meta(self, task_id: str) -> Optional[TaskSnapshot]:
        path = self._meta_path(task_id)
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as f:
                return TaskSnapshot.from_dict(json.load(f))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.warning("failed to load task %s: %s", task_id, exc)
            return None

    def _rebuild_index(self) -> list[dict]:
        out: list[dict] = []
        for p in sorted(self.root.glob("*.json")):
            if p.name == "_index.json":
                continue
            try:
                with p.open("r", encoding="utf-8") as f:
                    d = json.load(f)
                out.append({
                    "task_id": d.get("task_id"),
                    "kind": d.get("kind"),
                    "state": d.get("state"),
                    "created_at": d.get("created_at"),
                    "finished_at": d.get("finished_at"),
                    "progress": d.get("progress", ""),
                })
            except (OSError, json.JSONDecodeError):
                continue
        try:
            with self._index_path().open("w", encoding="utf-8") as f:
                json.dump({"tasks": out}, f, indent=2, ensure_ascii=False)
        except OSError:
            pass
        return out

    # ── public API ──
    def new_task_id(self, kind: str) -> str:
        ts = time.strftime("%Y%m%d_%H%M%S")
        rnd = secrets.token_hex(3)
        return f"{kind}_{ts}_{rnd}"

    def create(self, kind: str, args: dict[str, Any]) -> TaskSnapshot:
        with self._lock:
            tid = self.new_task_id(kind)
            snap = TaskSnapshot(
                task_id=tid,
                kind=kind,
                state=STATE_QUEUED,
                created_at=time.time(),
                args=dict(args or {}),
            )
            self._snapshots[tid] = snap
            self._cancel_events[tid] = threading.Event()
            self._log_tails[tid] = deque(maxlen=400)
            self._flush(snap)
        return snap

    def list_tasks(self, *, include_terminal: bool = True, max_age_sec: Optional[float] = None) -> list[dict]:
        out: list[dict] = []
        with self._lock:
            ids = set(self._snapshots.keys())
        # union with on-disk
        for p in self.root.glob("*.json"):
            if p.name == "_index.json":
                continue
            ids.add(p.stem)
        now = time.time()
        for tid in ids:
            snap = self.get(tid)
            if not snap:
                continue
            if not include_terminal and snap.state in TERMINAL_STATES:
                continue
            if max_age_sec is not None and snap.finished_at:
                if now - snap.finished_at > max_age_sec:
                    continue
            out.append({
                "task_id": snap.task_id,
                "kind": snap.kind,
                "state": snap.state,
                "progress": snap.progress,
                "created_at": snap.created_at,
                "finished_at": snap.finished_at,
            })
        out.sort(key=lambda d: d.get("created_at") or 0, reverse=True)
        return out

    def get(self, task_id: str) -> Optional[TaskSnapshot]:
        with self._lock:
            snap = self._snapshots.get(task_id)
            if snap:
                return snap
        # cold path: load from disk
        snap = self._load_meta(task_id)
        if snap is not None:
            with self._lock:
                # cache only if no fresher in-memory copy appeared
                if task_id not in self._snapshots:
                    self._snapshots[task_id] = snap
        return snap

    def request_cancel(self, task_id: str) -> tuple[bool, str]:
        """Set the cancel flag. The worker decides where to honor it.
        Returns (ok, message)."""
        with self._lock:
            snap = self._snapshots.get(task_id) or self._load_meta(task_id)
            if not snap:
                return False, f"unknown task: {task_id}"
            if snap.state in TERMINAL_STATES:
                return False, f"task already in terminal state: {snap.state}"
            snap.cancel_requested = True
            self._snapshots[task_id] = snap
            self._flush(snap)
            ev = self._cancel_events.get(task_id)
            if ev:
                ev.set()
            kill_pid = snap.cancel_pid
        # Best-effort hard kill outside the lock
        if kill_pid:
            self._kill_pid(kill_pid)
        return True, "cancel signalled"

    @staticmethod
    def _kill_pid(pid: int) -> None:
        try:
            if sys.platform.startswith("win"):
                # Soft signal first via taskkill, escalate to /F
                import subprocess as _sp
                _sp.run(["taskkill", "/PID", str(pid), "/T"], capture_output=True, timeout=5)
                time.sleep(2.0)
                _sp.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=5)
            else:
                import signal as _sig
                os.kill(pid, _sig.SIGTERM)
                time.sleep(2.0)
                try:
                    os.kill(pid, _sig.SIGKILL)
                except OSError:
                    pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to kill cancel_pid=%s: %s", pid, exc)

    # ── worker submission ──
    def submit(self,
               kind: str,
               worker_fn: "Callable[[TaskHandle], dict[str, Any]]",
               args: Optional[dict[str, Any]] = None) -> TaskSnapshot:
        snap = self.create(kind, args or {})
        handle = TaskHandle(self, snap.task_id)

        def _run() -> None:
            handle._mark_running()
            try:
                result = worker_fn(handle)
                handle._mark_done(result if isinstance(result, dict) else {"value": result})
            except _Cancelled:
                handle._mark_cancelled()
            except Exception as exc:  # noqa: BLE001
                tb = traceback.format_exc()
                handle.append_log(tb)
                handle._mark_failed(f"{type(exc).__name__}: {exc}")

        t = threading.Thread(target=_run, name=f"task-{snap.task_id}", daemon=False)
        with self._lock:
            self._threads[snap.task_id] = t
        t.start()
        return snap

    # ── recovery ──
    def recover_orphans(self) -> list[str]:
        """Called at server startup. Any persisted task in non-terminal
        state must belong to a previous server process — flag it as
        orphaned so the user knows results are unreliable but the log
        is still on disk."""
        recovered: list[str] = []
        for p in self.root.glob("*.json"):
            if p.name == "_index.json":
                continue
            snap = self._load_meta(p.stem)
            if not snap:
                continue
            if snap.state in TERMINAL_STATES:
                continue
            snap.state = STATE_ORPHANED
            snap.error = (snap.error or "") + "[orphaned: server restarted while task was active]"
            snap.finished_at = snap.finished_at or time.time()
            self._flush(snap)
            recovered.append(snap.task_id)
        if recovered:
            self._rebuild_index()
        return recovered

    def gc(self) -> int:
        """Remove terminal tasks older than TERMINAL_RETENTION_SEC. Returns
        the number of tasks deleted."""
        now = time.time()
        deleted = 0
        for p in list(self.root.glob("*.json")):
            if p.name == "_index.json":
                continue
            snap = self._load_meta(p.stem)
            if not snap:
                continue
            if snap.state not in TERMINAL_STATES:
                continue
            ref_time = snap.finished_at or snap.created_at
            if not ref_time or (now - ref_time) < TERMINAL_RETENTION_SEC:
                continue
            try:
                self._meta_path(snap.task_id).unlink(missing_ok=True)
                self._log_path(snap.task_id).unlink(missing_ok=True)
                with self._lock:
                    self._snapshots.pop(snap.task_id, None)
                    self._cancel_events.pop(snap.task_id, None)
                    self._log_tails.pop(snap.task_id, None)
                deleted += 1
            except OSError:
                continue
        if deleted:
            self._rebuild_index()
        return deleted


# ── Worker-facing handle ───────────────────────────────────────────────────

class _Cancelled(Exception):
    """Raised by TaskHandle.check_cancelled() to unwind the worker."""


class TaskHandle:
    """Handed to the worker thread. The worker uses it to update progress,
    log, heartbeat, and check cancellation."""

    def __init__(self, store: TaskStore, task_id: str) -> None:
        self._store = store
        self.task_id = task_id

    # ── private state mutators ──
    def _mutate(self, fn: "Callable[[TaskSnapshot], None]") -> TaskSnapshot:
        with self._store._lock:
            snap = self._store._snapshots.get(self.task_id) or self._store._load_meta(self.task_id)
            if snap is None:
                raise RuntimeError(f"task vanished: {self.task_id}")
            fn(snap)
            self._store._snapshots[self.task_id] = snap
            self._store._flush(snap)
            return snap

    def _mark_running(self) -> None:
        def _f(s: TaskSnapshot) -> None:
            s.state = STATE_RUNNING
            s.started_at = time.time()
            s.last_heartbeat_at = s.started_at
        self._mutate(_f)

    def _mark_done(self, result: dict[str, Any]) -> None:
        def _f(s: TaskSnapshot) -> None:
            now = time.time()
            s.state = STATE_DONE
            s.finished_at = now
            s.last_heartbeat_at = now
            s.result = result
            s.progress = "done"
            # close any still-open stage
            if s.stages and s.stages[-1].ended_at is None:
                s.stages[-1].ended_at = now
                s.stages[-1].ok = True
        self._mutate(_f)

    def _mark_failed(self, error: str) -> None:
        def _f(s: TaskSnapshot) -> None:
            now = time.time()
            s.state = STATE_FAILED
            s.finished_at = now
            s.last_heartbeat_at = now
            s.error = error
            s.progress = "failed"
            if s.stages and s.stages[-1].ended_at is None:
                s.stages[-1].ended_at = now
                s.stages[-1].ok = False
        self._mutate(_f)

    def _mark_cancelled(self) -> None:
        def _f(s: TaskSnapshot) -> None:
            now = time.time()
            s.state = STATE_CANCELLED
            s.finished_at = now
            s.last_heartbeat_at = now
            s.progress = "cancelled"
            if s.stages and s.stages[-1].ended_at is None:
                s.stages[-1].ended_at = now
                s.stages[-1].ok = False
        self._mutate(_f)

    # ── worker-facing API ──
    def set_stage(self, name: str, *, note: str = "") -> None:
        """Open a new stage. Closes the previous one as 'ok=True'."""
        def _f(s: TaskSnapshot) -> None:
            now = time.time()
            if s.stages and s.stages[-1].ended_at is None:
                s.stages[-1].ended_at = now
                s.stages[-1].ok = True
            s.stages.append(StageRecord(name=name, started_at=now, note=note))
            s.progress = name + (f" — {note}" if note else "")
            s.last_heartbeat_at = now
        self._mutate(_f)

    def heartbeat(self, *, progress: Optional[str] = None) -> None:
        def _f(s: TaskSnapshot) -> None:
            s.last_heartbeat_at = time.time()
            if progress is not None:
                s.progress = progress
        self._mutate(_f)

    def append_log(self, text: str) -> None:
        """Append free-form log text. Persists to <task_id>.log; also keeps
        an in-memory tail for cheap polling."""
        if not text:
            return
        line = text.rstrip("\n")
        with self._store._lock:
            tail = self._store._log_tails.setdefault(self.task_id, deque(maxlen=400))
            tail.append(line)
        try:
            with self._store._log_path(self.task_id).open("a", encoding="utf-8", errors="replace") as f:
                f.write(line + "\n")
        except OSError:
            pass

    def set_pid(self, pid: int) -> None:
        """Record the spawned subprocess PID (visible in snapshot)."""
        def _f(s: TaskSnapshot) -> None:
            s.pid = pid
        self._mutate(_f)

    def set_cancel_pid(self, pid: Optional[int]) -> None:
        """Register a PID to be hard-killed when the user requests cancel.
        Pass None to clear."""
        def _f(s: TaskSnapshot) -> None:
            s.cancel_pid = pid
        self._mutate(_f)

    def cancel_event(self) -> threading.Event:
        return self._store._cancel_events.setdefault(self.task_id, threading.Event())

    def check_cancelled(self) -> None:
        """Raise _Cancelled if a cancel was requested. Workers should call
        this between blocking sub-stages."""
        if self.cancel_event().is_set():
            raise _Cancelled()

    def log_tail(self, max_lines: int = 80) -> list[str]:
        with self._store._lock:
            tail = self._store._log_tails.get(self.task_id)
            if not tail:
                return []
            return list(tail)[-max_lines:]


# ── Global accessor (one TaskStore per project root) ──────────────────────

_STORES: dict[str, TaskStore] = {}
_STORES_LOCK = threading.Lock()


def get_store(project_root: Path) -> TaskStore:
    """Return a process-wide singleton TaskStore for the given project root.
    Tasks live under ``<project_root>/.uemcp/tasks/``."""
    key = str(Path(project_root).resolve())
    with _STORES_LOCK:
        store = _STORES.get(key)
        if store is None:
            tasks_root = Path(key) / ".uemcp" / "tasks"
            store = TaskStore(tasks_root)
            _STORES[key] = store
        return store


def render_snapshot(snap: TaskSnapshot, *, log_tail_lines: int = 0,
                    store: Optional[TaskStore] = None) -> dict:
    """JSON-friendly dict for tool responses. Optionally includes recent
    log tail (capped, not the entire log file — keep tool payloads small)."""
    d = snap.to_dict()
    # detect stalled
    if snap.state == STATE_RUNNING and snap.last_heartbeat_at:
        if time.time() - snap.last_heartbeat_at > STALL_THRESHOLD_SEC:
            d["stalled"] = True
            d["stall_age_sec"] = round(time.time() - snap.last_heartbeat_at, 1)
    if log_tail_lines > 0 and store is not None:
        try:
            log_path = store._log_path(snap.task_id)
            if log_path.exists():
                # read last N lines without slurping the whole file
                with log_path.open("rb") as f:
                    f.seek(0, os.SEEK_END)
                    size = f.tell()
                    chunk = min(size, 65536)
                    f.seek(size - chunk)
                    blob = f.read().decode("utf-8", errors="replace")
                lines = blob.splitlines()[-log_tail_lines:]
                d["log_tail"] = lines
                d["log_path"] = str(log_path)
        except OSError:
            pass
    return d
