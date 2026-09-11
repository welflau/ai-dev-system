"""
ue_editor_mcp.launcher — Headless build/launch sub-package for UEEditorMCP.

This package provides MCP tools that operate OUTSIDE the running UE Editor:
  • build_editor      — invoke UBT's Build.bat to (re)compile a target
  • start_editor      — spawn UnrealEditor[-Cmd].exe (headless by default)
  • stop_editor       — terminate processes spawned by THIS server
  • is_editor_running — psutil-based existence probe
  • run_automation    — headless Automation RunTests + report parsing
  • wait_until_ready  — poll TCP 55558 + editor.is_ready until ready

Design goals:
  1. Project-agnostic — zero hard-coded project names. Per-project overrides
     live in <ProjectRoot>/.uemcp/launcher.json (auto-generated on first run).
  2. Same deployment as the main MCP server — re-uses the venv created by
     setup_mcp.ps1; nothing extra to install.
  3. Strict safety — validator.py enforces a binary/argument allowlist; no
     free-form shell strings can reach Build.bat or UnrealEditor*.exe.
"""

from .config import load_config, ProjectInfo, LauncherConfig

__all__ = ["load_config", "ProjectInfo", "LauncherConfig"]
