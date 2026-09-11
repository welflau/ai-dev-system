"""
Smoke tests for launcher.validator. Run with:

    python -m pytest Plugins/UEEditorMCP/Python/tests/test_launcher_validator.py

These are pure-logic tests; no UE / no filesystem mutation needed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest  # type: ignore[import-not-found]

# Make the package importable when invoked from the repo root
_PKG_DIR = Path(__file__).resolve().parents[1]
if str(_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR))

from ue_editor_mcp.launcher.validator import (  # noqa: E402
    ValidationError,
    validate_target,
    validate_platform,
    validate_config,
    validate_suite,
    validate_exec_cmds,
)


# ── target ─────────────────────────────────────────────────────────────────

class TestTarget:
    @pytest.mark.parametrize("name", ["P111Editor", "MyGameEditor", "Foo123Editor"])
    def test_valid(self, name):
        assert validate_target(name) == name

    @pytest.mark.parametrize("name", [
        "", "Editor", "P111", "P111-Editor", "1P111Editor",
        "P111Game", "P111Editor; rm -rf /", "P111Editor && evil",
    ])
    def test_invalid(self, name):
        with pytest.raises(ValidationError):
            validate_target(name)


# ── platform / config ─────────────────────────────────────────────────────

class TestPlatformConfig:
    def test_platform_ok(self):
        assert validate_platform("Win64") == "Win64"
        assert validate_platform("Mac") == "Mac"
        assert validate_platform("Linux") == "Linux"

    def test_platform_bad(self):
        with pytest.raises(ValidationError):
            validate_platform("Win32")

    def test_config_ok(self):
        for c in ("Debug", "DebugGame", "Development", "Shipping", "Test"):
            assert validate_config(c) == c

    def test_config_bad(self):
        with pytest.raises(ValidationError):
            validate_config("Release")


# ── suite ──────────────────────────────────────────────────────────────────

class TestSuite:
    @pytest.mark.parametrize("suite", [
        "P111.LJC+", "P111.Module.Sub.Case", "MyGame.Foo", "Foo+",
    ])
    def test_valid_no_prefix(self, suite):
        assert validate_suite(suite, required_prefix=None) == suite

    def test_required_prefix(self):
        assert validate_suite("P111.LJC+", required_prefix="P111.") == "P111.LJC+"
        with pytest.raises(ValidationError):
            validate_suite("Other.LJC+", required_prefix="P111.")

    @pytest.mark.parametrize("suite", [
        "", "P111.LJC; Quit", "P111.LJC && open evil",
        "P111.LJC|tail", "../etc/passwd", "P111.LJC restart",
    ])
    def test_rejects_bad_chars(self, suite):
        with pytest.raises(ValidationError):
            validate_suite(suite, required_prefix=None)


# ── exec_cmds template ────────────────────────────────────────────────────

class TestExecCmds:
    def test_canonical(self):
        s = "Automation RunTests P111.LJC+; Quit"
        assert validate_exec_cmds(s) == s

    @pytest.mark.parametrize("bad", [
        "Automation RunTests P111.LJC+; Quit; open Map",  # extra ;
        "Automation RunTests P111.LJC+; restart",          # forbidden token
        "RunTests P111.LJC+; Quit",                        # wrong prefix
        "Automation RunTests P111.LJC+",                   # missing Quit
        "Automation RunTests P111.LJC+ && evil; Quit",    # forbidden separator
    ])
    def test_rejects_malformed(self, bad):
        with pytest.raises(ValidationError):
            validate_exec_cmds(bad)
