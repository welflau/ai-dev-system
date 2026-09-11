"""
launcher.validator — strict allowlist + denylist for build/launch parameters.

Every external-process invocation in this package MUST flow through
build_args() / launch_args() to make sure the LLM cannot inject
unauthorized command lines. The rules here are PROJECT-AGNOSTIC; per-project
tightening (e.g. test_suite_prefix) lives in LauncherConfig and is consumed
here as a parameter.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

# ── enums / constants ──────────────────────────────────────────────────────

ALLOWED_PLATFORMS = {"Win64", "Mac", "Linux"}
ALLOWED_CONFIGS = {"Debug", "DebugGame", "Development", "Shipping", "Test"}

# Editor target name: must look like "<ProjectName>Editor" with a safe ProjectName.
_TARGET_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}Editor$")

# Suite name: dotted identifiers + optional trailing '+' (UE Automation glob).
_SUITE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)*\+?$")

# Forbidden anywhere in any final argv element (case-insensitive).
_DENY_TOKENS = (
    ";", "&&", "||", "|",
    "open ", "travel ", "exit", "quit", "restart",
    "..\\", "../",
    "obj gc", "rhi.",
)


class ValidationError(ValueError):
    """Raised when caller-supplied parameters violate the allowlist."""


# ── helpers ────────────────────────────────────────────────────────────────

def _ensure(cond: bool, msg: str) -> None:
    if not cond:
        raise ValidationError(msg)


def _has_deny_token(s: str) -> Optional[str]:
    low = s.lower()
    for tok in _DENY_TOKENS:
        if tok in low:
            return tok
    return None


def _is_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


# ── target / config validation ─────────────────────────────────────────────

def validate_target(target_name: str) -> str:
    _ensure(isinstance(target_name, str) and bool(target_name), "target_name is empty")
    _ensure(bool(_TARGET_RE.match(target_name)),
            f"target_name '{target_name}' must match <ProjectName>Editor")
    return target_name


def validate_platform(platform: str) -> str:
    _ensure(platform in ALLOWED_PLATFORMS,
            f"platform '{platform}' not in {sorted(ALLOWED_PLATFORMS)}")
    return platform


def validate_config(config: str) -> str:
    _ensure(config in ALLOWED_CONFIGS,
            f"config '{config}' not in {sorted(ALLOWED_CONFIGS)}")
    return config


def validate_uproject(uproject_path: str, project_root: Optional[Path] = None) -> Path:
    _ensure(isinstance(uproject_path, str) and bool(uproject_path), "uproject_path is empty")
    p = Path(uproject_path)
    _ensure(p.is_absolute(), f"uproject_path must be absolute: {uproject_path}")
    _ensure(p.suffix.lower() == ".uproject", f"uproject_path must end with .uproject: {p}")
    _ensure(p.is_file(), f"uproject not found: {p}")
    if project_root is not None:
        _ensure(_is_under(p, project_root),
                f"uproject {p} must reside under project_root {project_root}")
    return p


def validate_engine_root(engine_root: str) -> Path:
    _ensure(isinstance(engine_root, str) and bool(engine_root), "engine_root is empty")
    p = Path(engine_root)
    _ensure(p.is_absolute(), f"engine_root must be absolute: {engine_root}")
    _ensure((p / "Engine").is_dir(), f"engine_root invalid (no Engine/): {p}")
    return p


def validate_binary(path: Path, allowed_relpaths: tuple[str, ...]) -> Path:
    _ensure(path.is_file(), f"binary not found: {path}")
    norm = str(path).replace("\\", "/").lower()
    _ensure(any(norm.endswith(rel.lower()) for rel in allowed_relpaths),
            f"binary {path} is not in the allowlist {allowed_relpaths}")
    return path


# ── automation suite validation ────────────────────────────────────────────

def validate_suite(suite: str, required_prefix: Optional[str]) -> str:
    _ensure(isinstance(suite, str) and bool(suite), "suite is empty")
    bad = _has_deny_token(suite)
    _ensure(bad is None, f"suite contains forbidden token '{bad}'")
    _ensure(bool(_SUITE_RE.match(suite)),
            f"suite '{suite}' must be dotted identifier (optionally trailing '+')")
    if required_prefix:
        _ensure(suite.startswith(required_prefix),
                f"suite '{suite}' must start with project prefix '{required_prefix}'")
    return suite


def validate_exec_cmds(exec_cmds: str) -> str:
    """Final string about to be passed as -ExecCmds=. Belt-and-suspenders
    after suite has already been validated.

    NOTE: do NOT reuse the generic _DENY_TOKENS here — that list intentionally
    forbids ';', 'quit', and 'exit' for *suite names*, but the only template
    we accept ('Automation RunTests <suite>; Quit') by definition contains
    exactly one ';' and the literal word 'Quit'. Reusing _DENY_TOKENS would
    make validate_exec_cmds reject every legal input. The structural safety
    of the template is enforced below by:
      - startswith('Automation RunTests ')   → exact verb pinned
      - endswith('Quit')                     → exact terminator pinned
      - exactly one ';'                      → no command chaining
    Combined with validate_suite() having already rejected dangerous tokens
    inside the suite portion, this gives equivalent protection without the
    self-contradiction.
    """
    # Tokens that are dangerous in -ExecCmds even within a templated form
    # (i.e. cannot be part of any legal Automation/Quit phrase).
    EXEC_CMDS_DENY = (
        "&&", "||", "|",
        "open ", "travel ", "restart",
        "..\\", "../",
        "obj gc", "rhi.",
    )
    low = exec_cmds.lower()
    for tok in EXEC_CMDS_DENY:
        if tok in low:
            raise ValidationError(f"-ExecCmds contains forbidden token '{tok}'")

    # Only one of these templates is allowed
    _ensure(exec_cmds.startswith("Automation RunTests "),
            "-ExecCmds must start with 'Automation RunTests '")
    _ensure(exec_cmds.rstrip().endswith("Quit") or exec_cmds.rstrip().endswith("Quit;"),
            "-ExecCmds must end with 'Quit'")
    # Reject anything with semicolons except the one separating RunTests from Quit
    semis = exec_cmds.count(";")
    _ensure(semis == 1, "-ExecCmds template allows exactly one ';' separator")
    return exec_cmds


# ── per-call argv builders ─────────────────────────────────────────────────

def build_build_argv(*,
                     build_bat: Path,
                     target: str,
                     platform: str,
                     config: str,
                     uproject: Path) -> list[str]:
    """Construct the EXACT argv for Build.bat. No extra args ever accepted."""
    validate_binary(build_bat,
                    ("Engine/Build/BatchFiles/Build.bat",
                     "Engine/Build/BatchFiles/Build.sh"))
    validate_target(target)
    validate_platform(platform)
    validate_config(config)
    return [
        str(build_bat),
        target,
        platform,
        config,
        str(uproject),
        "-waitmutex",
    ]


def build_automation_argv(*,
                          editor_cmd: Path,
                          uproject: Path,
                          suite: str,
                          report_dir: Path,
                          required_prefix: Optional[str]) -> list[str]:
    """Headless Automation RunTests. Returns argv for UnrealEditor-Cmd."""
    validate_binary(editor_cmd,
                    ("Engine/Binaries/Win64/UnrealEditor-Cmd.exe",
                     "Engine/Binaries/Mac/UnrealEditor-Cmd",
                     "Engine/Binaries/Linux/UnrealEditor-Cmd"))
    validate_suite(suite, required_prefix)

    exec_cmds = f"Automation RunTests {suite}; Quit"
    validate_exec_cmds(exec_cmds)

    return [
        str(editor_cmd),
        str(uproject),
        f"-ExecCmds={exec_cmds}",
        "-unattended",
        "-nopause",
        "-nullrhi",
        "-nosplash",
        "-log",
        f"-ReportExportPath={report_dir}",
    ]


def build_interactive_argv(*,
                           editor_gui: Path,
                           uproject: Path) -> list[str]:
    """GUI editor launch.

    NOTE (2026-06-05): The previous ``allow_gui_launch`` hard gate has been
    removed. GUI launch is a normal capability — callers (LLM or user) decide
    whether to use ``mode='headless'`` or ``mode='interactive'`` based on the
    test scenario. Only the binary-allowlist check remains.
    """
    validate_binary(editor_gui,
                    ("Engine/Binaries/Win64/UnrealEditor.exe",
                     "Engine/Binaries/Mac/UnrealEditor",
                     "Engine/Binaries/Linux/UnrealEditor"))
    # Launcher-managed sessions must not block before MCPBridge startup on
    # Unreal's modal crash-recovery prompt. This is the engine-supported
    # equivalent of selecting "Skip Restore"; it also clears the stale restore
    # manifest once startup reaches FPackageAutoSaver::OfferToRestorePackages.
    return [
        str(editor_gui),
        str(uproject),
        "-AutoDeclinePackageRecovery",
    ]
