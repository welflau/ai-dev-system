"""UE 套件对照 H5 准入约束：反思、确定性快修、验收证据、命令记录、看板列。"""
import json

import pytest

from plugins.registry import is_plugin_failure_type
from plugins.ue5.reflection import (
    HANDLED_FAILURE_TYPES,
    apply_deterministic_fixes,
    build_reflection_signal,
    enrich_fix_context,
)


_GATES = {
    "engine_compile_failed",
    "play_test_failed",
    "self_test_failed",
    "ue_test_gen_failed",
    "packaging_failed",
    "ue_content_failed",
}


def test_handled_failure_types_cover_ue_gates():
    assert _GATES <= set(HANDLED_FAILURE_TYPES)
    assert is_plugin_failure_type("engine_compile_failed") is True


def test_enrich_fix_context_coerces_command_to_str():
    ctx: dict = {}
    enrich_fix_context(
        "engine_compile_failed",
        {
            "errors": [{"file": "Source/Foo.h", "line": 4, "code": "C2065", "msg": "ident"}],
            "raw_tail": "UBT tail",
            "command": ["UnrealBuildTool.exe", "FooEditor"],
        },
        ctx,
    )
    assert ctx["compile_errors"][0]["file"] == "Source/Foo.h"
    assert ctx["compile_raw_tail"] == "UBT tail"
    assert ctx["compile_command"] == "UnrealBuildTool.exe FooEditor"
    assert isinstance(ctx["compile_command"], str)


def test_reflection_signal_includes_file_line_and_code():
    ctx = {
        "compile_errors": [{
            "file": "Source/Foo.h",
            "line": 12,
            "column": 3,
            "code": "C2065",
            "msg": "ident",
            "category": "compile",
        }],
        "compile_command": "UnrealBuildTool.exe FooEditor",
        "compile_raw_tail": "error C2065: ident",
    }
    signal = build_reflection_signal("engine_compile_failed", ctx)
    assert "Source/Foo.h:12:3" in signal
    assert "C2065" in signal
    assert "_reflection_override" not in ctx


def test_reflection_signal_empty_errors_keeps_raw_tail_and_override():
    ctx = {
        "compile_errors": [],
        "compile_raw_tail": "UnrealBuildTool mutex busy",
    }
    signal = build_reflection_signal("engine_compile_failed", ctx)
    assert "mutex busy" in signal
    assert ctx["_reflection_override"]["confidence"] == 0.2


def test_non_unreal_compile_signal_skips_ue_macro_hints():
    ctx = {
        "compile_errors": [],
        "compile_raw_tail": "godot script error at line 1",
    }
    signal = build_reflection_signal("engine_compile_failed", ctx)
    assert "引擎编译失败" in signal
    assert "GENERATED_BODY" not in signal
    assert "_reflection_override" not in ctx


def test_deterministic_fix_inserts_generated_body_only_for_named_files(tmp_path):
    header = tmp_path / "Source"
    header.mkdir()
    foo = header / "Foo.h"
    foo.write_text(
        "#pragma once\n#include \"GameFramework/Actor.h\"\n"
        "UCLASS()\nclass AFoo : public AActor {\n};\n",
        encoding="utf-8",
    )
    bar = header / "Bar.h"
    original_bar = "UCLASS()\nclass ABar : public AActor {\n};\n"
    bar.write_text(original_bar, encoding="utf-8")
    fixed = apply_deterministic_fixes(
        "self_test_failed",
        str(tmp_path),
        [{
            "file": "Source/Foo.h",
            "line": 3,
            "code": "R1",
            "msg": "未见 GENERATED_BODY()",
        }],
        {},
    )
    assert "GENERATED_BODY()" in fixed["Source/Foo.h"]
    assert "Source/Bar.h" not in fixed
    assert bar.read_text(encoding="utf-8") == original_bar


def test_classify_board_column_for_ue_package_and_content():
    from api.tickets import _classify_board_column

    assert _classify_board_column("packaged", {}) == "in_review"
    assert _classify_board_column("packaging_failed", {}) == "blocked"
    assert _classify_board_column("ue_content_done", {}) == "in_review"
    assert _classify_board_column("ue_content_pending", {}) == "in_progress"


@pytest.mark.asyncio
async def test_ue_acceptance_evidence_uses_gate_logs(monkeypatch):
    rows = [
        {
            "action": "complete",
            "to_status": "engine_compile_passed",
            "message": "编译通过",
            "detail": json.dumps({
                "exit_code": 0,
                "duration_ms": 12000,
                "errors": [],
                "warnings": [],
                "command": "UnrealBuildTool.exe FooEditor",
            }),
        },
        {
            "action": "complete",
            "to_status": "play_test_passed",
            "message": "Playtest 通过",
            "detail": json.dumps({
                "summary": {"passed": 2, "failed": 0, "total": 2},
                "tests": [],
                "screenshots": ["Saved/AutoScreenshot.png"],
                "command": "UnrealEditor-Cmd.exe",
            }),
        },
    ]

    async def _fetch_all(sql, params):
        return rows

    import database
    monkeypatch.setattr(database.db, "fetch_all", _fetch_all)

    from plugins.ue5.acceptance import build_acceptance_evidence

    evidence = await build_acceptance_evidence({
        "ticket_id": "TK-UE-1",
        "project_traits": ["engine:ue5"],
        "existing_code": {
            "Source/Foo.h": "UCLASS()\nclass AFoo {\n    GENERATED_BODY()\n};\n",
            "Binaries/Foo.h": "should not appear",
        },
        "dev_result": {"files": {"Source/Foo.h": "x"}},
    })
    text = evidence["evidence_markdown"]
    assert "UBT" in text
    assert "Automation" in text
    assert "Source/Foo.h" in text
    assert "Binaries/Foo.h" not in text
    assert "不得因读不到截图判 0 分" in evidence["acceptance_rules"]


@pytest.mark.asyncio
async def test_trace_ue_command_records_str(monkeypatch):
    captured = {}

    async def _fake_record(**kwargs):
        captured.update(kwargs)
        return "TCMD-UE-1"

    import command_log
    monkeypatch.setattr(command_log, "record_traced_command", _fake_record)

    from plugins.ue5.command_trace import trace_ue_command

    record_id = await trace_ue_command(
        source="ue_compile_check",
        tool="ubt",
        command=["UnrealBuildTool.exe", "FooEditor"],
        cwd="F:/game",
        exit_code=0,
        status="success",
        duration_ms=10,
        output="ok",
        ticket_id="TK-UE-1",
        project_id="PRJ-1",
    )
    assert record_id == "TCMD-UE-1"
    assert captured["command"] == "UnrealBuildTool.exe FooEditor"
    assert isinstance(captured["command"], str)
