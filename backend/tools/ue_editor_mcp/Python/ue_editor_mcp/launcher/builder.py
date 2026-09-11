"""
launcher.builder — wrapper around UBT's Build.bat / Build.sh.

Purely orchestrates: validates parameters, runs the binary via runner.run_blocking,
and post-processes the output to surface compile errors in a structured form.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from .config import LauncherConfig
from .runner import RunResult, run_blocking
from .validator import build_build_argv

# ── compile-error parser ───────────────────────────────────────────────────

# Matches MSVC + Clang style errors emitted by UBT
_ERROR_PATTERNS = [
    re.compile(r"^(?P<file>[A-Za-z]:[^()]+)\((?P<line>\d+)\)\s*:\s*error\s+(?P<code>\w+)\s*:\s*(?P<msg>.+)$"),
    re.compile(r"^(?P<file>[A-Za-z]:[^:]+):(?P<line>\d+):\d+:\s*error:\s*(?P<msg>.+)$"),
    re.compile(r"^Error:\s*(?P<msg>.+)$"),
    re.compile(r"^FATAL ERROR:\s*(?P<msg>.+)$"),
]
_WARN_RE = re.compile(r"^(?P<file>[A-Za-z]:[^()]+)\((?P<line>\d+)\)\s*:\s*warning\s+(?P<code>\w+)\s*:\s*(?P<msg>.+)$")


@dataclass
class CompileMessage:
    file: Optional[str] = None
    line: Optional[int] = None
    code: Optional[str] = None
    message: str = ""


@dataclass
class BuildOutcome:
    success: bool
    returncode: Optional[int]
    target: str
    platform: str
    config: str
    duration_sec: float
    timed_out: bool
    log_path: Optional[str]
    errors: list[CompileMessage] = field(default_factory=list)
    warnings: list[CompileMessage] = field(default_factory=list)
    stdout_tail: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def _parse_messages(lines: list[str]) -> tuple[list[CompileMessage], list[CompileMessage]]:
    errors: list[CompileMessage] = []
    warnings: list[CompileMessage] = []
    for line in lines:
        wm = _WARN_RE.match(line)
        if wm:
            warnings.append(CompileMessage(
                file=wm.group("file"),
                line=int(wm.group("line")),
                code=wm.group("code"),
                message=wm.group("msg"),
            ))
            continue
        for pat in _ERROR_PATTERNS:
            m = pat.match(line)
            if not m:
                continue
            d = m.groupdict()
            errors.append(CompileMessage(
                file=d.get("file"),
                line=int(d["line"]) if d.get("line") else None,
                code=d.get("code"),
                message=d.get("msg") or line,
            ))
            break
    return errors, warnings


def build_target(cfg: LauncherConfig,
                 *,
                 target: Optional[str] = None,
                 platform: Optional[str] = None,
                 build_config: Optional[str] = None,
                 timeout_sec: Optional[int] = None) -> BuildOutcome:
    """Run UBT to (re)compile the editor target.

    All overrides are subject to validator's allowlist; pass nothing to use
    the project defaults (recommended)."""
    if not cfg.project.engine_root:
        raise RuntimeError("engine_root is unknown — fill it in .uemcp/launcher.json")

    engine_root = Path(cfg.project.engine_root)
    project_root = Path(cfg.project.project_root)
    uproject = Path(cfg.project.uproject_path)

    target_name = target or cfg.project.target_name or f"{cfg.project.project_name}{cfg.build_target_suffix}"
    plat = platform or cfg.build_platform
    bcfg = build_config or cfg.build_config

    from .discovery import build_bat_relpath
    build_bat = engine_root / build_bat_relpath()

    argv = build_build_argv(
        build_bat=build_bat,
        target=target_name,
        platform=plat,
        config=bcfg,
        uproject=uproject,
    )

    log_path = project_root / cfg.log_tail_root / f"uemcp_build_{target_name}_{int(__import__('time').time())}.log"
    rr: RunResult = run_blocking(
        argv,
        cwd=project_root,
        timeout_sec=timeout_sec or cfg.process_timeout_sec,
        tail_lines=400,
        log_path=log_path,
    )

    errs, warns = _parse_messages(rr.stdout_tail)

    return BuildOutcome(
        success=(rr.returncode == 0 and not rr.timed_out and not errs),
        returncode=rr.returncode,
        target=target_name,
        platform=plat,
        config=bcfg,
        duration_sec=rr.duration_sec,
        timed_out=rr.timed_out,
        log_path=rr.log_path,
        errors=errs,
        warnings=warns,
        stdout_tail=rr.stdout_tail[-100:],
    )
