"""
launcher.config — load (or auto-generate) the per-project launcher config.

First-run UX:
  • If <ProjectRoot>/.uemcp/launcher.json does NOT exist, this module runs
    discovery.discover_all() and writes a fresh JSON with the auto-detected
    values. The file is committed to disk so users can later tweak fields
    (or check it into source control).
  • Subsequent runs read the JSON, but values left as null/missing are
    auto-filled by re-discovery (so adding a new optional knob in code never
    breaks an old config).

The schema is INTENTIONALLY small. Only fields a launcher *must* know about
the project (engine root, uproject, target name, suite prefix, GUI policy)
live here. Everything else uses validator/runner defaults.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from . import discovery as _disc
from ..plugin_config import load_bridge_config


CONFIG_DIRNAME = ".uemcp"
CONFIG_FILENAME = "launcher.json"
SCHEMA_VERSION = 1


# ── public schema ──────────────────────────────────────────────────────────

@dataclass
class ProjectInfo:
    project_root: str          # absolute, posix-style
    uproject_path: str         # absolute, posix-style
    project_name: str          # P111, MyGame, ...
    engine_root: Optional[str] # absolute or null when not yet discoverable
    engine_association: Optional[str] = None
    target_name: Optional[str] = None  # defaults to f"{project_name}{build_target_suffix}"


@dataclass
class LauncherConfig:
    schema_version: int = SCHEMA_VERSION
    project: ProjectInfo = None  # type: ignore[assignment]

    # Build defaults (overridable per-call but bounded by validator allowlist)
    build_target_suffix: str = "Editor"
    build_platform: str = "Win64"
    build_config: str = "Development"

    # Automation defaults
    test_suite_prefix: Optional[str] = None  # e.g. "P111." — None = no prefix policy
    process_timeout_sec: int = 1800
    log_tail_root: str = "Saved/Logs"
    report_root: str = "Saved/Automation/Reports"

    # Safety policy
    # DEPRECATED (2026-06-05): the previous "interactive launch is hard-gated"
    # policy has been removed. The field is kept for backward compatibility
    # with existing .uemcp/launcher.json files (so loading them does not
    # fail), and is reflected by launcher_get_config so external scripts
    # that read it still see a sane value, but it is NO LONGER consulted by
    # build_interactive_argv. Default is now True to match the new "GUI is a
    # normal capability" stance.
    allow_gui_launch: bool = True  # DEPRECATED: ignored by validator

    # Bridge (must match MCPBridge.cpp DefaultPort)
    bridge_host: str = "127.0.0.1"
    bridge_port: int = 55558

    # Provenance
    auto_generated: bool = False
    discovery_notes: list[str] = field(default_factory=list)


# ── (de)serialization helpers ──────────────────────────────────────────────

def _to_jsonable(cfg: LauncherConfig) -> dict:
    d = asdict(cfg)
    # ProjectInfo is also a dataclass → asdict already handled it
    return d


def _project_from_dict(d: dict) -> ProjectInfo:
    return ProjectInfo(
        project_root=d["project_root"],
        uproject_path=d["uproject_path"],
        project_name=d["project_name"],
        engine_root=d.get("engine_root"),
        engine_association=d.get("engine_association"),
        target_name=d.get("target_name"),
    )


def _apply_plugin_bridge_config(cfg: LauncherConfig) -> LauncherConfig:
    bridge = load_bridge_config()
    cfg.bridge_host = bridge.host
    cfg.bridge_port = bridge.port
    return cfg


def _config_from_dict(d: dict) -> LauncherConfig:
    proj = _project_from_dict(d["project"])
    cfg = LauncherConfig(
        schema_version=int(d.get("schema_version", SCHEMA_VERSION)),
        project=proj,
        build_target_suffix=str(d.get("build_target_suffix", "Editor")),
        build_platform=str(d.get("build_platform", "Win64")),
        build_config=str(d.get("build_config", "Development")),
        test_suite_prefix=d.get("test_suite_prefix"),
        process_timeout_sec=int(d.get("process_timeout_sec", 1800)),
        log_tail_root=str(d.get("log_tail_root", "Saved/Logs")),
        report_root=str(d.get("report_root", "Saved/Automation/Reports")),
        allow_gui_launch=bool(d.get("allow_gui_launch", True)),
        bridge_host=str(d.get("bridge_host", "127.0.0.1")),
        bridge_port=int(d.get("bridge_port", 55558)),
        auto_generated=bool(d.get("auto_generated", False)),
        discovery_notes=list(d.get("discovery_notes", [])),
    )
    if not cfg.project.target_name:
        cfg.project.target_name = f"{cfg.project.project_name}{cfg.build_target_suffix}"
    return _apply_plugin_bridge_config(cfg)


# ── auto-generate from discovery ───────────────────────────────────────────

def _build_default_from_discovery(project_root_hint: Optional[str]) -> tuple[Optional[LauncherConfig], list[str]]:
    """Run discovery and synthesize a LauncherConfig. Returns (cfg, notes).
    cfg is None if discovery couldn't even find a *.uproject — caller must
    surface the error to the human instead of writing a half-broken file."""
    res = _disc.discover_all(project_root_hint=project_root_hint)
    if not res.uproject_path or not res.project_root or not res.project_name:
        return None, res.notes

    proj = ProjectInfo(
        project_root=str(res.project_root.resolve()).replace("\\", "/"),
        uproject_path=str(res.uproject_path.resolve()).replace("\\", "/"),
        project_name=res.project_name,
        engine_root=str(res.engine_root.resolve()).replace("\\", "/") if res.engine_root else None,
        engine_association=res.engine_association,
        target_name=f"{res.project_name}Editor",
    )
    cfg = LauncherConfig(project=proj, auto_generated=True, discovery_notes=res.notes)
    return _apply_plugin_bridge_config(cfg), res.notes


# ── path helpers ───────────────────────────────────────────────────────────

def _config_path_for_root(project_root: Path) -> Path:
    return project_root / CONFIG_DIRNAME / CONFIG_FILENAME


def _resolve_project_root(project_root_hint: Optional[str]) -> Optional[Path]:
    """Find the project root either from the explicit hint or by walking up
    from CWD looking for *.uproject."""
    if project_root_hint:
        p = Path(project_root_hint).expanduser().resolve()
        if p.is_dir():
            return p

    # Use discovery's walk-up
    up, _ = _disc.discover_uproject(project_root_hint=None)
    if up:
        return up.parent
    return None


# ── public API ─────────────────────────────────────────────────────────────

def load_config(project_root_hint: Optional[str] = None,
                write_if_missing: bool = True) -> tuple[Optional[LauncherConfig], list[str]]:
    """Load (or auto-generate) launcher config for the project rooted at the
    given hint (or CWD-derived).

    Returns (config, notes). config is None when neither file nor discovery
    could nail down a project — caller MUST treat that as a hard error.
    """
    notes: list[str] = []
    project_root = _resolve_project_root(project_root_hint)

    # Try to read existing file even if we don't know the root yet — if hint
    # was given but no .uproject sits there, we skip silently.
    if project_root:
        cfg_path = _config_path_for_root(project_root)
        if cfg_path.is_file():
            try:
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                cfg = _config_from_dict(data)
                notes.append(f"config: loaded {cfg_path}")
                # Re-detect engine_root if it was null (e.g. user moved engine)
                if not cfg.project.engine_root:
                    eng, en_notes = _disc.discover_engine_root(
                        Path(cfg.project.uproject_path), explicit=None)
                    notes.extend(en_notes)
                    if eng:
                        cfg.project.engine_root = str(eng.resolve()).replace("\\", "/")
                        notes.append("config: engine_root auto-filled from discovery (not persisted)")
                return cfg, notes
            except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
                notes.append(f"config: existing file unreadable, regenerating ({exc})")

    # No file (or unreadable) → discover + optionally persist
    fresh, disc_notes = _build_default_from_discovery(
        project_root_hint=str(project_root) if project_root else None)
    notes.extend(disc_notes)

    if not fresh:
        notes.append("config: cannot auto-generate — no *.uproject found.")
        return None, notes

    if write_if_missing:
        try:
            target = _config_path_for_root(Path(fresh.project.project_root))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(_to_jsonable(fresh), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            notes.append(f"config: AUTO-GENERATED → {target}")
        except OSError as exc:
            notes.append(f"config: failed to persist auto-generated file: {exc}")

    return fresh, notes


def reset_config(project_root_hint: Optional[str] = None) -> bool:
    """Delete the persisted config so the next load_config rediscovers."""
    project_root = _resolve_project_root(project_root_hint)
    if not project_root:
        return False
    cfg_path = _config_path_for_root(project_root)
    try:
        if cfg_path.is_file():
            cfg_path.unlink()
            return True
    except OSError:
        return False
    return False
