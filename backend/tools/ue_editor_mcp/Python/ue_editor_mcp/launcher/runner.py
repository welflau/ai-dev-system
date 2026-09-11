"""
launcher.runner — process lifecycle for spawned UE / UBT subprocesses.

We DON'T use psutil unconditionally; if missing we fall back to the stdlib's
subprocess + os helpers. This keeps `psutil` an optional dep so the plugin
can ship without it on minimal setups.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

try:  # optional, only used for richer process inspection
    import psutil  # type: ignore[import-not-found]
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


# ── Windows specifics: detached process group so we can kill children ─────

if sys.platform.startswith("win"):
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_CONSOLE = 0x00000010
    CREATE_NO_WINDOW = 0x08000000
    CREATE_BREAKAWAY_FROM_JOB = 0x01000000
    _SPAWN_FLAGS = CREATE_NEW_PROCESS_GROUP
else:
    _SPAWN_FLAGS = 0


@dataclass
class RunResult:
    pid: int
    returncode: Optional[int]
    stdout_tail: list[str] = field(default_factory=list)
    stderr_tail: list[str] = field(default_factory=list)
    duration_sec: float = 0.0
    timed_out: bool = False
    log_path: Optional[str] = None
    started_at: float = 0.0


class _ManagedProcessRegistry:
    """Tracks every subprocess launched by THIS server, so stop_editor can
    only ever kill what we started ourselves.

    Also records an optional ``mode`` tag per PID (e.g. ``"interactive"``,
    ``"headless"``, ``"build"``, ``"automation"``) so :func:`tools._h_start_editor`
    can decide whether to reuse an existing managed editor or refuse with a
    mode-mismatch error without making the LLM probe processes itself.
    """

    def __init__(self) -> None:
        self._procs: dict[int, subprocess.Popen] = {}
        self._modes: dict[int, str] = {}
        self._lock = threading.Lock()

    def add(self, proc: subprocess.Popen, *, mode: Optional[str] = None) -> None:
        with self._lock:
            self._procs[proc.pid] = proc
            if mode:
                self._modes[proc.pid] = mode

    def list_alive(self) -> list[subprocess.Popen]:
        with self._lock:
            alive = [p for p in self._procs.values() if p.poll() is None]
            alive_pids = {p.pid for p in alive}
            self._procs = {p.pid: p for p in alive}
            # GC mode tags for dead PIDs
            self._modes = {pid: m for pid, m in self._modes.items() if pid in alive_pids}
            return list(alive)

    def list_alive_with_mode(self) -> list[tuple[int, Optional[str]]]:
        """Snapshot of (pid, mode) for every still-alive managed process."""
        alive = self.list_alive()
        with self._lock:
            return [(p.pid, self._modes.get(p.pid)) for p in alive]

    def get_mode(self, pid: int) -> Optional[str]:
        with self._lock:
            return self._modes.get(pid)

    def remove(self, pid: int) -> None:
        with self._lock:
            self._procs.pop(pid, None)
            self._modes.pop(pid, None)

    def kill_all(self, timeout_sec: float = 10.0) -> int:
        killed = 0
        for proc in self.list_alive():
            try:
                if _HAS_PSUTIL:
                    parent = psutil.Process(proc.pid)
                    children = parent.children(recursive=True)
                    for ch in children:
                        try:
                            ch.terminate()
                        except psutil.Error:
                            pass
                proc.terminate()
                try:
                    proc.wait(timeout=timeout_sec)
                except subprocess.TimeoutExpired:
                    proc.kill()
                killed += 1
            except (OSError, ProcessLookupError):
                pass
            finally:
                self.remove(proc.pid)
        return killed

    def kill_pid(self, pid: int, timeout_sec: float = 10.0) -> bool:
        with self._lock:
            proc = self._procs.get(pid)
        if not proc:
            return False
        try:
            if _HAS_PSUTIL:
                try:
                    parent = psutil.Process(pid)
                    for ch in parent.children(recursive=True):
                        try:
                            ch.terminate()
                        except psutil.Error:
                            pass
                except psutil.NoSuchProcess:
                    pass
            proc.terminate()
            try:
                proc.wait(timeout=timeout_sec)
            except subprocess.TimeoutExpired:
                proc.kill()
            return True
        except (OSError, ProcessLookupError):
            return False
        finally:
            self.remove(pid)


# Module-level singleton: this server owns these processes.
REGISTRY = _ManagedProcessRegistry()


# ── editor existence probe (covers BOTH our spawns and external ones) ─────

def list_running_editors() -> list[dict]:
    """Return a list of {pid, name, exe} for every currently running
    UnrealEditor*.exe / UnrealEditor-Cmd. Uses psutil if available, else
    falls back to platform tools."""
    out: list[dict] = []
    if _HAS_PSUTIL:
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if name.startswith("unrealeditor"):
                    out.append({
                        "pid": proc.info["pid"],
                        "name": proc.info.get("name"),
                        "exe": proc.info.get("exe"),
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return out

    # Fallback: parse `tasklist` / `ps`
    try:
        if sys.platform.startswith("win"):
            res = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True, text=False, check=False, timeout=10,
            )
            stdout = (res.stdout or b"").decode("mbcs", errors="replace")
            for line in stdout.splitlines():
                parts = [p.strip('"') for p in line.split('","')]
                if not parts:
                    continue
                name = parts[0].lstrip('"')
                if name.lower().startswith("unrealeditor"):
                    try:
                        pid = int(parts[1])
                    except (ValueError, IndexError):
                        continue
                    out.append({"pid": pid, "name": name, "exe": None})
        else:
            res = subprocess.run(
                ["ps", "-axo", "pid,comm"],
                capture_output=True, text=False, check=False, timeout=10,
            )
            stdout = (res.stdout or b"").decode("utf-8", errors="replace")
            for line in stdout.splitlines()[1:]:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(None, 1)
                if len(parts) != 2:
                    continue
                pid_s, comm = parts
                if "unrealeditor" in comm.lower():
                    try:
                        out.append({"pid": int(pid_s), "name": comm, "exe": None})
                    except ValueError:
                        continue
    except (OSError, subprocess.SubprocessError):
        return out
    return out


# ── core runners ───────────────────────────────────────────────────────────

def run_blocking(argv: list[str],
                 *,
                 cwd: Optional[Path] = None,
                 env: Optional[dict[str, str]] = None,
                 timeout_sec: int = 1800,
                 tail_lines: int = 200,
                 on_line: Optional[Callable[[str], None]] = None,
                 log_path: Optional[Path] = None) -> RunResult:
    """Run a process synchronously, capturing stdout/stderr (combined)."""
    started_at = time.time()
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = log_path.open("w", encoding="utf-8", errors="replace")
    else:
        log_handle = None

    proc = subprocess.Popen(
        argv,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_SPAWN_FLAGS,
    )
    REGISTRY.add(proc)

    tail: list[str] = []
    timed_out = False
    deadline = started_at + timeout_sec
    try:
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            line = raw_line.rstrip("\r\n")
            if log_handle:
                log_handle.write(raw_line)
            tail.append(line)
            if len(tail) > tail_lines:
                tail.pop(0)
            if on_line:
                try:
                    on_line(line)
                except Exception:  # noqa: BLE001
                    pass
            if time.time() > deadline:
                timed_out = True
                break
        proc.wait(timeout=max(1.0, deadline - time.time()) if not timed_out else 1.0)
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                proc.kill()
        if log_handle:
            log_handle.close()
        REGISTRY.remove(proc.pid)

    return RunResult(
        pid=proc.pid,
        returncode=proc.returncode,
        stdout_tail=tail,
        duration_sec=round(time.time() - started_at, 3),
        timed_out=timed_out,
        log_path=str(log_path) if log_path else None,
        started_at=started_at,
    )


def run_detached(argv: list[str],
                 *,
                 cwd: Optional[Path] = None,
                 env: Optional[dict[str, str]] = None,
                 log_path: Optional[Path] = None,
                 gui_mode: bool = False,
                 mode_tag: Optional[str] = None) -> int:
    """Launch a long-running process and return its PID immediately.

    Two spawn profiles:

    * default (``gui_mode=False``) — for headless ``UnrealEditor-Cmd`` runs.
      Uses ``DETACHED_PROCESS`` + stdio redirection to ``log_path``. Suitable
      for processes the caller never plans to interact with via window/input.

    * GUI mode (``gui_mode=True``) — for ``UnrealEditor.exe`` interactive
      launches. Designed to mirror a manual ``Start-Process UnrealEditor.exe``
      from a foreground console:

        - DROPS ``DETACHED_PROCESS`` (causes the child to lose the parent's
          window-station/desktop association in some sessions; symptoms
          include "GUI window appears but cannot receive input").
        - ADDS ``CREATE_BREAKAWAY_FROM_JOB`` so that when the launcher MCP
          server itself is hosted as a child of an IDE (VSCode/Cursor/etc.)
          inside a Windows Job Object, the editor escapes the Job. Without
          this, IDE-imposed Job limits (e.g.
          ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``,
          ``JOB_OBJECT_UILIMIT_*``) propagate into UE and can disable input
          processing or kill the editor when the IDE detaches.
        - DOES **NOT** set ``CREATE_NEW_CONSOLE``. We tried it; the splash
          rendered fine but the main Slate window lost mouse/keyboard input
          right after first frame. Allocating a fresh conhost appears to
          either steal foreground focus or race with UE's ``LogConsole``
          module on the freshly-attached console handles. Inheriting the
          parent's stdio (or having none, with stdio==DEVNULL) is what the
          working CLI/IDE-F5 paths do, so we mirror that.
        - REFUSES ``log_path`` redirection (UE writes its own logs to
          ``Saved/Logs/`` and pipes from the GUI process can hang
          UE's ``UE_LOG`` writer when the parent's pipe buffer fills).
    """
    flags = _SPAWN_FLAGS
    use_log = (log_path is not None) and not gui_mode

    if use_log:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_handle = log_path.open("w", encoding="utf-8", errors="replace")
        stderr_handle = subprocess.STDOUT  # merge into the log file
    else:
        stdout_handle = subprocess.DEVNULL  # type: ignore[assignment]
        stderr_handle = subprocess.DEVNULL  # type: ignore[assignment]

    # stdin is ALWAYS detached. The launcher MCP server is hosted as a
    # stdio child of an IDE (VSCode / Cursor / gongfeng-copilot-chat-agent
    # / etc.); its own stdin is a named pipe owned by the IDE. If we let
    # subprocess.Popen default-inherit that handle into UnrealEditor.exe,
    # UE's LogConsole / FCommandLine plumbing sees a connected-but-silent
    # pipe and can wedge Slate input dispatch (symptom: GUI window paints
    # but does not receive mouse/keyboard). DEVNULL fully severs the
    # inheritance.
    stdin_handle = subprocess.DEVNULL  # type: ignore[assignment]

    if sys.platform.startswith("win"):
        if gui_mode:
            # Plan B (2026-06-05): the previous GUI flag set
            # (CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB only,
            # no DETACHED_PROCESS, stdio inherited) reproducibly yielded
            # a UnrealEditor whose Slate window painted but ignored
            # input — both when launched through the launcher MCP under
            # an IDE host AND after the user manually restarted MCP.
            # Diagnosed cause: the editor inherited the IDE's stdio pipe
            # handles plus the IDE's Job Object, so once Slate started
            # pumping input it competed with whichever IDE-side reader
            # was draining the same pipe.
            #
            # Plan B replicates a clean "double-click .uproject" spawn:
            #   - DETACHED_PROCESS  : drop the parent console handle
            #   - CREATE_NO_WINDOW  : do NOT allocate a new conhost
            #                         (avoids the foreground-focus race
            #                         that broke CREATE_NEW_CONSOLE)
            #   - CREATE_BREAKAWAY_FROM_JOB : escape any IDE Job Object
            #   - CREATE_NEW_PROCESS_GROUP  : keep, so we can still
            #                                 GenerateConsoleCtrlEvent
            #                                 to gracefully shut down
            # Combined with stdin=stdout=stderr=DEVNULL above, the child
            # has no inherited handles linking it back to the IDE.
            flags |= DETACHED_PROCESS | CREATE_NO_WINDOW | CREATE_BREAKAWAY_FROM_JOB
        else:
            flags |= DETACHED_PROCESS

    proc = subprocess.Popen(
        argv,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdin=stdin_handle,
        stdout=stdout_handle,
        stderr=stderr_handle,
        creationflags=flags,
        close_fds=True,
    )
    REGISTRY.add(proc, mode=mode_tag)
    return proc.pid
