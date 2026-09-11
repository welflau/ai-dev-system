"""
launcher.discovery — auto-detect project root, .uproject, engine root, target name.

All discovery here is read-only and idempotent. Used by config.py on first
run to materialize <ProjectRoot>/.uemcp/launcher.json without any human input.

Detection order mirrors setup_mcp.ps1's 5-tier engine probe:
  1) Explicit override (config field / parameter)
  2) .uproject's EngineAssociation -> Windows registry
  3) *.code-workspace folders that look like UE engine roots
  4) UE_ENGINE_DIR environment variable
  5) Disk scan (common Epic Games install paths)
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ── platform-specific bits ─────────────────────────────────────────────────

def _engine_python_relpath() -> str:
    if sys.platform.startswith("win"):
        return "Engine/Binaries/ThirdParty/Python3/Win64/python.exe"
    if sys.platform == "darwin":
        return "Engine/Binaries/ThirdParty/Python3/Mac/bin/python3"
    return "Engine/Binaries/ThirdParty/Python3/Linux/bin/python3"


def build_bat_relpath() -> str:
    if sys.platform.startswith("win"):
        return "Engine/Build/BatchFiles/Build.bat"
    return "Engine/Build/BatchFiles/Build.sh"


def editor_cmd_relpath() -> str:
    if sys.platform.startswith("win"):
        return "Engine/Binaries/Win64/UnrealEditor-Cmd.exe"
    if sys.platform == "darwin":
        return "Engine/Binaries/Mac/UnrealEditor-Cmd"
    return "Engine/Binaries/Linux/UnrealEditor-Cmd"


def editor_gui_relpath() -> str:
    if sys.platform.startswith("win"):
        return "Engine/Binaries/Win64/UnrealEditor.exe"
    if sys.platform == "darwin":
        return "Engine/Binaries/Mac/UnrealEditor"
    return "Engine/Binaries/Linux/UnrealEditor"


# ── result types ───────────────────────────────────────────────────────────

@dataclass
class DiscoveryResult:
    project_root: Optional[Path] = None
    uproject_path: Optional[Path] = None
    project_name: Optional[str] = None
    engine_root: Optional[Path] = None
    engine_association: Optional[str] = None
    notes: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.notes is None:
            self.notes = []

    @property
    def target_name(self) -> Optional[str]:
        return f"{self.project_name}Editor" if self.project_name else None

    @property
    def build_bat(self) -> Optional[Path]:
        return self.engine_root / build_bat_relpath() if self.engine_root else None

    @property
    def editor_cmd(self) -> Optional[Path]:
        return self.engine_root / editor_cmd_relpath() if self.engine_root else None

    @property
    def editor_gui(self) -> Optional[Path]:
        return self.engine_root / editor_gui_relpath() if self.engine_root else None


# ── project root / uproject discovery ──────────────────────────────────────

def _walk_up_for_uproject(start: Path) -> Optional[Path]:
    """Walk parents until we find a directory containing exactly one *.uproject."""
    for d in [start, *start.parents]:
        try:
            ups = sorted(d.glob("*.uproject"))
        except OSError:
            continue
        if len(ups) == 1:
            return ups[0]
        if len(ups) > 1:
            # multiple projects under one folder — ambiguous, caller must pick
            return None
    return None


def discover_uproject(explicit_path: Optional[str] = None,
                      project_root_hint: Optional[str] = None) -> tuple[Optional[Path], list[str]]:
    """Return (uproject_path, notes). uproject_path is None if ambiguous/not found."""
    notes: list[str] = []

    # 1) explicit absolute path
    if explicit_path:
        p = Path(explicit_path).expanduser().resolve()
        if p.is_file() and p.suffix.lower() == ".uproject":
            notes.append(f"uproject: explicit param → {p}")
            return p, notes
        notes.append(f"uproject: explicit path invalid: {p}")
        return None, notes

    # 2) project_root_hint
    if project_root_hint:
        root = Path(project_root_hint).expanduser().resolve()
        ups = sorted(root.glob("*.uproject")) if root.is_dir() else []
        if len(ups) == 1:
            notes.append(f"uproject: from project_root_hint → {ups[0]}")
            return ups[0], notes
        if len(ups) > 1:
            notes.append(f"uproject: ambiguous under {root} ({len(ups)} candidates)")
            return None, notes

    # 3) walk up from CWD
    cwd = Path.cwd().resolve()
    found = _walk_up_for_uproject(cwd)
    if found:
        notes.append(f"uproject: walk-up from CWD → {found}")
        return found, notes

    # 4) walk up from this file (Plugins/<X>/Python/...)
    here = Path(__file__).resolve()
    found = _walk_up_for_uproject(here.parent)
    if found:
        notes.append(f"uproject: walk-up from package → {found}")
        return found, notes

    notes.append("uproject: not found (none in CWD ancestors or package ancestors)")
    return None, notes


# ── engine root discovery ──────────────────────────────────────────────────

_GUID_RE = re.compile(r"^\{?[0-9A-Fa-f-]{32,38}\}?$")


def _read_engine_association(uproject: Path) -> Optional[str]:
    try:
        data = json.loads(uproject.read_text(encoding="utf-8"))
        ea = data.get("EngineAssociation")
        if isinstance(ea, str) and ea.strip():
            return ea.strip()
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _engine_from_registry(association: str) -> Optional[Path]:
    """Windows registry lookup. Returns None on non-Windows or miss."""
    if not sys.platform.startswith("win"):
        return None
    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError:
        return None

    # Installed engine: HKLM\SOFTWARE\EpicGames\Unreal Engine\<ver>
    if not _GUID_RE.match(association):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                rf"SOFTWARE\EpicGames\Unreal Engine\{association}") as k:
                installed_dir, _ = winreg.QueryValueEx(k, "InstalledDirectory")
                p = Path(installed_dir)
                if p.is_dir():
                    return p
        except OSError:
            pass

    # Custom build: HKCU\SOFTWARE\Epic Games\Unreal Engine\Builds (key name = GUID or version)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"SOFTWARE\Epic Games\Unreal Engine\Builds") as k:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                if name == association or association in (value or ""):
                    p = Path(value)
                    if p.is_dir():
                        return p
    except OSError:
        pass
    return None


def _engine_from_workspace_files(project_root: Path) -> Optional[Path]:
    """Scan *.code-workspace 'folders' for one that looks like a UE engine root."""
    pattern = re.compile(r"UE_\d|Unreal.?Engine|EpicGame", re.IGNORECASE)
    for ws in project_root.glob("*.code-workspace"):
        try:
            data = json.loads(ws.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for folder in data.get("folders", []) or []:
            fp = folder.get("path") if isinstance(folder, dict) else None
            if not fp or not pattern.search(fp):
                continue
            p = Path(fp)
            if not p.is_absolute():
                p = (project_root / p).resolve()
            if (p / "Engine").is_dir():
                return p
    return None


def _engine_from_env() -> Optional[Path]:
    v = os.environ.get("UE_ENGINE_DIR")
    if not v:
        return None
    p = Path(v).expanduser()
    return p if (p / "Engine").is_dir() else None


def _engine_from_disk_scan() -> Optional[Path]:
    """Slowest fallback. Picks the highest-versioned UE_X.Y under common roots."""
    candidates: list[Path] = []
    if sys.platform.startswith("win"):
        roots = [Path(f"{d}:/") for d in "CDEF"]
        prefixes = ["EpicGame", "Program Files/Epic Games", "UnrealEngine"]
    elif sys.platform == "darwin":
        roots = [Path("/Users/Shared/Epic Games"), Path.home() / "Epic Games"]
        prefixes = [""]
    else:
        roots = [Path.home() / "Epic Games", Path("/opt/Epic Games")]
        prefixes = [""]

    for r in roots:
        for pfx in prefixes:
            base = (r / pfx) if pfx else r
            if not base.is_dir():
                continue
            try:
                for child in base.iterdir():
                    if child.is_dir() and child.name.startswith("UE_") \
                            and (child / "Engine").is_dir():
                        candidates.append(child)
            except OSError:
                continue

    if not candidates:
        return None
    # Sort by trailing version number desc
    def _ver_key(p: Path):
        m = re.search(r"UE_(\d+)\.(\d+)", p.name)
        return (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    candidates.sort(key=_ver_key, reverse=True)
    return candidates[0]


def discover_engine_root(uproject: Optional[Path],
                         explicit: Optional[str] = None) -> tuple[Optional[Path], list[str]]:
    notes: list[str] = []

    # 1) explicit override
    if explicit:
        p = Path(explicit).expanduser()
        if (p / "Engine").is_dir():
            notes.append(f"engine: explicit → {p}")
            return p, notes
        notes.append(f"engine: explicit path invalid: {p}")

    # 2) registry via .uproject EngineAssociation
    if uproject:
        ea = _read_engine_association(uproject)
        if ea:
            notes.append(f"engine: EngineAssociation = {ea}")
            p = _engine_from_registry(ea)
            if p:
                notes.append(f"engine: registry → {p}")
                return p, notes

    # 3) .code-workspace folders
    if uproject:
        p = _engine_from_workspace_files(uproject.parent)
        if p:
            notes.append(f"engine: workspace folder → {p}")
            return p, notes

    # 4) env var
    p = _engine_from_env()
    if p:
        notes.append(f"engine: $UE_ENGINE_DIR → {p}")
        return p, notes

    # 5) disk scan
    p = _engine_from_disk_scan()
    if p:
        notes.append(f"engine: disk scan → {p}")
        return p, notes

    notes.append("engine: NOT FOUND — set engine_root in .uemcp/launcher.json")
    return None, notes


# ── orchestrator ───────────────────────────────────────────────────────────

def discover_all(project_root_hint: Optional[str] = None,
                 uproject_override: Optional[str] = None,
                 engine_root_override: Optional[str] = None) -> DiscoveryResult:
    """Run the full auto-detect pipeline. Always returns a result; missing
    fields stay None and notes explain why."""
    res = DiscoveryResult()

    up, n1 = discover_uproject(uproject_override, project_root_hint)
    res.notes.extend(n1)
    if up:
        res.uproject_path = up
        res.project_root = up.parent
        res.project_name = up.stem
        res.engine_association = _read_engine_association(up)

    eng, n2 = discover_engine_root(up, engine_root_override)
    res.notes.extend(n2)
    if eng:
        res.engine_root = eng

    return res
