"""UE 套件的失败反思信号与确定性快修。

SOP 打回 `engine_compile_failed` / `play_test_failed` / `self_test_failed` /
`ue_test_gen_failed` / `packaging_failed` / `ue_content_failed` 时，由
`plugins.registry` 分发到本模块，不再在宿主 `agents/dev.py` 与
`actions/reflection.py` 里按状态名分支。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

HANDLED_FAILURE_TYPES = frozenset({
    "engine_compile_failed",
    "play_test_failed",
    "self_test_failed",
    "ue_test_gen_failed",
    "packaging_failed",
    "ue_content_failed",
})

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_RE_UCLASS_DECL = re.compile(
    r"^\s*(UCLASS|USTRUCT|UINTERFACE)\s*(\(.*\))?\s*$"
)
_RE_GEN_BODY = re.compile(
    r"GENERATED_(BODY|UCLASS_BODY|USTRUCT_BODY|IINTERFACE_BODY|UINTERFACE_BODY)\s*\(\s*\)"
)
_RE_CLASS_LINE = re.compile(r"^\s*(class|struct)\b")
_TRUNC_MARK = "文件截断显示"

_UE_HINTS = (
    "\n⚠️ UE 常见坑：\n"
    "  - 同名头文件（UHT 禁止）\n"
    "  - 漏 UCLASS/UFUNCTION/UPROPERTY 宏\n"
    "  - Build.cs 缺模块依赖（Core/CoreUObject/Engine/InputCore/EnhancedInput 等）\n"
    "  - include 的头文件路径错误（.generated.h 要匹配 class 名）\n"
    "  - GENERATED_BODY() 遗漏 或位置错\n"
    "  - 在 .cpp 直接 new FClass() 但 class 没继承 UObject 走不了 GC\n"
    "\n🚫 重要：这是 Unreal Engine C++ 项目，修复时只能输出 .h/.cpp/.Build.cs 文件。\n"
    "  绝对不能输出 Python/JavaScript/HTML/Flask/FastAPI 代码。\n"
    "  如果你觉得需要写 Python——你理解错了编译错误，请重新分析上面的 error 列表。"
)

_PLAYTEST_HINTS = (
    "\n⚠️ UE Automation 常见失败原因：\n"
    "  - Functional Test actor 未正确 Register（需 PostRegisterAllComponents 注册）\n"
    "  - 资产引用路径过期（BP 重命名后 C++ 里的 SoftObjectPath 没更新）\n"
    "  - Enhanced Input mapping 缺失（IA / IMC 没在 BP 或 DefaultInput.ini 里绑）\n"
    "  - Tick 逻辑依赖某帧已初始化但未用 FTimerHandle/GameState 等待\n"
    "  - nullrhi 模式下 UMG/渲染相关断言（检查是否强依赖真 GPU）\n"
    "  - Spawn/Replication 依赖客户端世界，单机 playtest 跑不到"
)


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text or "").strip()


def _as_command(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return " ".join(str(part) for part in value)
    return str(value or "")


def _looks_like_unreal(context: Dict[str, Any]) -> bool:
    """编译失败信号是否像 UBT / MSVC。Godot、Unity 走同一状态名时不要套 UE 宏提示。"""
    blob = " ".join([
        str(context.get("compile_command") or ""),
        str(context.get("compile_raw_tail") or ""),
        str(context.get("compile_err_brief") or ""),
    ])
    if "UnrealBuildTool" in blob or "RunUAT" in blob or ".uproject" in blob:
        return True
    if re.search(r"\berror C\d+\b", blob) or re.search(r"\berror LNK\d+\b", blob):
        return True
    low = blob.lower()
    if "godot" in low or "unity" in low:
        return False
    for err in context.get("compile_errors") or []:
        code = str(err.get("code") or "")
        if code.startswith(("C", "LNK", "MSB")) or err.get("category") in (
            "msvc", "csharp", "ubt", "compile", "link", "uht",
        ):
            return True
        file_name = str(err.get("file") or "")
        if file_name.endswith((".h", ".cpp", ".Build.cs")):
            return True
    return False


def _issues_from_ticket_result(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = context.get("_ticket_result_json")
    if not raw:
        return []
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return []
    if not isinstance(parsed, dict):
        return []
    self_test = parsed.get("self_test") or {}
    issues = self_test.get("ue_blocking_issues") or []
    return list(issues) if isinstance(issues, list) else []


def _issues_as_errors(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for issue in issues:
        file_name = str(issue.get("file") or "")
        if not file_name:
            continue
        out.append({
            "file": file_name,
            "line": issue.get("line") or 0,
            "column": 0,
            "code": issue.get("rule") or "",
            "msg": issue.get("msg") or "",
            "suggest": issue.get("suggest") or "",
        })
    return out


def enrich_fix_context(
    failure_type: str,
    reject_detail: Dict[str, Any],
    context: Dict[str, Any],
) -> None:
    """从 reject detail（以及自测场景的工单 result）提取诊断字段。"""
    det = reject_detail or {}
    if failure_type == "play_test_failed":
        context["failed_tests"] = det.get("tests") or []
        context["playtest_summary"] = det.get("summary") or {}
        context["playtest_command"] = _as_command(det.get("command"))
        context["compile_raw_tail"] = det.get("raw_tail") or ""
        context["module_load_errors"] = det.get("module_load_errors") or []
        context["compile_err_brief"] = det.get("message") or det.get("err_brief") or ""
        return

    if failure_type == "self_test_failed":
        issues = det.get("ue_blocking_issues")
        if not issues:
            issues = _issues_from_ticket_result(context)
        issues = list(issues or [])
        context["ue_blocking_issues"] = issues
        if not context.get("compile_errors"):
            context["compile_errors"] = _issues_as_errors(issues)
        context["compile_raw_tail"] = det.get("raw_tail") or ""
        context["compile_err_brief"] = det.get("message") or det.get("err_brief") or ""
        return

    if failure_type == "ue_content_failed":
        context["compile_err_brief"] = det.get("err_brief") or det.get("message") or ""
        context["compile_raw_tail"] = det.get("raw_tail") or ""
        context["compile_command"] = _as_command(det.get("command"))
        return

    context["compile_errors"] = det.get("errors") or []
    context["compile_warnings"] = det.get("warnings") or []
    context["compile_command"] = _as_command(det.get("command"))
    context["compile_hints"] = det.get("hints") or []
    context["compile_raw_tail"] = det.get("raw_tail") or ""
    context["compile_err_brief"] = det.get("err_brief") or det.get("message") or ""


def _format_compile_errors(errors: List[Dict[str, Any]], limit: int = 15) -> List[str]:
    lines = ["\n具体错误列表（最多前 %d 条）：" % limit]
    for err in errors[:limit]:
        lines.append(
            f"  - [{err.get('category', '?')}] "
            f"{err.get('file', '?')}:{err.get('line', '?')}:{err.get('column', err.get('col', '?'))} "
            f"{err.get('code', '')} — {(err.get('msg') or '')[:200]}"
        )
    return lines


def _append_tail(lines: List[str], raw_tail: str, *, only_when_unparsed: bool) -> None:
    if not raw_tail:
        if only_when_unparsed:
            lines.append("\n未解析出结构化错误，且没有控制台尾部输出。")
        return
    limit = 1500 if only_when_unparsed else 800
    label = (
        "命令原始输出尾部（未解析出标准结构化错误，请直接根据原始输出定位）"
        if only_when_unparsed
        else "命令原始输出尾部"
    )
    lines.append(f"\n{label}：\n```\n{raw_tail[-limit:]}\n```")


def _env_override() -> Dict[str, Any]:
    return {
        "root_cause": (
            "编译失败但未捕获到任何结构化错误信息，疑似环境级问题"
            "（UBT 零输出 / UBA 子进程 / mutex / 引擎路径），而非代码语法错误。"
        ),
        "missed_requirements": [],
        "previous_attempt_issue": "上一次编译没有产生可解析的 error 输出，无法定位代码问题。",
        "strategy_change": (
            "先排查引擎/构建环境（确认 UBT 可正常启动、无残留 mutex、"
            "引擎版本与 .uproject 匹配），而非盲目改代码。建议人工介入检查。"
        ),
        "specific_changes": [
            "检查 UnrealBuildTool 是否能独立运行（手动执行编译命令看 stdout）",
            "确认无残留 UBA/编译进程占用 mutex",
            "核对引擎版本与 EngineAssociation 一致",
        ],
        "confidence": 0.2,
    }


def build_reflection_signal(
    failure_type: str,
    context: Dict[str, Any],
) -> str:
    """把 UE 门禁失败格式化成 ReflectionAction 的失败信号。"""
    compile_errors: List[Dict[str, Any]] = list(context.get("compile_errors") or [])
    compile_warnings: List[Dict[str, Any]] = list(context.get("compile_warnings") or [])
    compile_cmd = _as_command(context.get("compile_command"))
    raw_tail = _strip_ansi(str(context.get("compile_raw_tail") or ""))
    err_brief = _strip_ansi(str(context.get("compile_err_brief") or ""))

    if failure_type == "play_test_failed":
        return _playtest_signal(context, raw_tail, err_brief)

    if failure_type == "self_test_failed":
        return _self_test_signal(context, raw_tail)

    if failure_type == "engine_compile_failed" and not _looks_like_unreal(context):
        return _generic_engine_signal(
            compile_errors, compile_cmd, raw_tail, err_brief, context,
        )

    # 能认出是 UE、但又没有结构化错误：沿用原来的环境级反思，不调用 LLM。
    # 完全不像 UE 的空输出已在上面走通用文案。
    if failure_type == "engine_compile_failed" and not compile_errors:
        context["_reflection_override"] = _env_override()

    lines: List[str] = []
    if failure_type == "engine_compile_failed":
        lines.append(
            f"UnrealBuildTool 编译失败（{len(compile_errors)} errors, {len(compile_warnings)} warnings）。"
        )
    elif failure_type == "ue_test_gen_failed":
        lines.append(f"UE 测试生成后的单文件编译失败（{len(compile_errors)} errors）。")
    elif failure_type == "packaging_failed":
        lines.append(f"UE 打包（RunUAT）失败（{len(compile_errors)} errors）。")
    else:
        lines.append(f"UE 内容生成失败。")

    if compile_cmd:
        lines.append(f"执行命令: `{compile_cmd}`")
    if err_brief:
        lines.append(f"错误摘要: {err_brief}")
    if compile_errors:
        lines.extend(_format_compile_errors(compile_errors))
    if compile_warnings and failure_type == "engine_compile_failed":
        lines.append("\n部分警告（前 3 条）：")
        for warning in compile_warnings[:3]:
            lines.append(
                f"  - [{warning.get('category', '?')}] "
                f"{warning.get('file', '?')}:{warning.get('line', '?')} "
                f"{warning.get('code', '')} — {(warning.get('msg') or '')[:120]}"
            )
    if failure_type in ("engine_compile_failed", "ue_test_gen_failed"):
        lines.append(_UE_HINTS)
    elif failure_type == "packaging_failed":
        lines.append(
            "\n⚠️ 打包失败优先看 Cook / Stage 日志和缺失资产，不要先改玩法代码。"
            "环境级问题（缺 RunUAT、引擎路径不对）应走人工介入，而不是反复重写 C++。"
        )
    _append_tail(lines, raw_tail, only_when_unparsed=not compile_errors)
    return "\n".join(lines)


def _generic_engine_signal(
    errors: List[Dict[str, Any]],
    command: str,
    raw_tail: str,
    err_brief: str,
    context: Dict[str, Any],
) -> str:
    """同一 `engine_compile_failed` 状态也可能来自 Godot / Unity，此时不套 UE 宏提示。"""
    if not errors and not raw_tail:
        context["_reflection_override"] = _env_override()
    lines = [f"引擎编译失败（结构化错误 {len(errors)} 条）。"]
    if command:
        lines.append(f"执行命令: `{command}`")
    if err_brief:
        lines.append(f"错误摘要: {err_brief}")
    if errors:
        lines.extend(_format_compile_errors(errors))
    else:
        lines.append("未解析出结构化错误。")
    _append_tail(lines, raw_tail, only_when_unparsed=not errors)
    return "\n".join(lines)


def _playtest_signal(context: Dict[str, Any], raw_tail: str, err_brief: str) -> str:
    failed_tests = context.get("failed_tests") or []
    summary = context.get("playtest_summary") or {}
    command = _as_command(context.get("playtest_command"))
    lines = [
        f"UE Automation 测试失败 ({summary.get('failed', len(failed_tests))}/"
        f"{summary.get('total', 0)} failed)。"
    ]
    if command:
        lines.append(f"测试命令: `{command}`")
    if err_brief:
        lines.append(f"错误摘要: {err_brief}")
    lines.append("\n失败测试（最多前 5 个）：")
    if failed_tests:
        for test in failed_tests[:5]:
            name = test.get("name", "?")
            errs = "; ".join((test.get("errors") or [])[:2])[:200] or "(未捕获 error 行)"
            lines.append(f"  - {name}")
            lines.append(f"    → {errs}")
    else:
        lines.append("  - （没有解析到失败用例名）")
    modules = context.get("module_load_errors") or []
    if modules:
        lines.append("\n模块未加载：")
        for name in modules[:8]:
            lines.append(f"  - {name}")
    lines.append(_PLAYTEST_HINTS)
    _append_tail(lines, raw_tail, only_when_unparsed=not failed_tests)
    return "\n".join(lines)


def _self_test_signal(context: Dict[str, Any], raw_tail: str) -> str:
    issues = context.get("ue_blocking_issues") or []
    lines = [
        f"UE 自测失败（Layer 1 静态预检）：{len(issues)} 条 blocking issues。"
        "每条都是静态可发现的 UE C++ 常见错，请按 suggest 逐条修复。",
        "\n问题清单：",
    ]
    if issues:
        for idx, issue in enumerate(issues[:10], 1):
            msg = (issue.get("msg") or "").replace("\n", " ")[:220]
            lines.append(
                f"{idx}. [{issue.get('rule', '?')}] {issue.get('file', '?')}:"
                f"{issue.get('line') or '?'} — {msg}"
            )
            suggest = issue.get("suggest") or ""
            if suggest:
                lines.append(f"   → 建议: {suggest}")
    else:
        lines.append("  - （detail 与工单 result 都没有 blocking issue）")
    lines.append(
        "\n⚠️ 这些错在下游 UBT 编译会必然暴露（3-5 分钟后），"
        "但我们在开发阶段就用静态规则提前拦住。请严格按 suggest 修正，不要引入新的同类问题。\n"
        "\n🚫 提醒：这是 UE C++ 项目。修复时只输出 .h/.cpp/.Build.cs，绝对不能写 Python/JS/HTML！"
    )
    _append_tail(lines, raw_tail, only_when_unparsed=not issues)
    return "\n".join(lines)


def _read_fix_target(
    repo_path: str,
    rel_path: str,
    existing_code: Dict[str, str],
) -> Optional[str]:
    root = Path(repo_path) if repo_path else None
    if root and (root / rel_path).is_file():
        try:
            return (root / rel_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None
    raw = existing_code.get(rel_path)
    if raw and _TRUNC_MARK not in raw:
        return raw
    return None


def _insert_generated_body(content: str) -> Optional[str]:
    """在 UCLASS/USTRUCT/UINTERFACE 后 10 行内的类左花括号下一行补 GENERATED_BODY()。"""
    lines = content.splitlines()
    insert_after: List[int] = []
    for index, line in enumerate(lines):
        if not _RE_UCLASS_DECL.match(line):
            continue
        scan_end = min(index + 11, len(lines))
        block = lines[index:scan_end]
        if _RE_GEN_BODY.search("\n".join(block)):
            continue
        brace_at = None
        seen_class = False
        for offset, block_line in enumerate(block):
            if _RE_CLASS_LINE.match(block_line):
                seen_class = True
            if seen_class and "{" in block_line:
                brace_at = index + offset
                break
        if brace_at is not None:
            insert_after.append(brace_at)
    if not insert_after:
        return None
    for index in reversed(insert_after):
        lines.insert(index + 1, "    GENERATED_BODY()")
    newline = "\n" if content.endswith("\n") else ""
    return "\n".join(lines) + newline


def _insert_generated_include(content: str, header_path: str) -> Optional[str]:
    stem = Path(header_path.replace("\\", "/")).stem
    if not stem:
        return None
    include_line = f'#include "{stem}.generated.h"'
    if include_line in content:
        return None
    if not re.search(r"\b(UCLASS|USTRUCT|UINTERFACE)\b", content):
        return None
    lines = content.splitlines()
    last_include = -1
    for index, line in enumerate(lines):
        if line.strip().startswith("#include"):
            last_include = index
    lines.insert(last_include + 1, include_line)
    newline = "\n" if content.endswith("\n") else ""
    return "\n".join(lines) + newline


def _error_wants_genbody(err: Dict[str, Any]) -> bool:
    blob = " ".join([
        str(err.get("code") or ""),
        str(err.get("msg") or ""),
        str(err.get("suggest") or ""),
    ])
    return err.get("code") == "R1" or "GENERATED_BODY" in blob


def _error_wants_generated_include(err: Dict[str, Any]) -> bool:
    blob = " ".join([
        str(err.get("msg") or ""),
        str(err.get("suggest") or ""),
    ])
    return "generated.h" in blob.lower() or "Please define" in blob


def apply_deterministic_fixes(
    failure_type: str,
    repo_path: str,
    compile_errors: List[Dict[str, Any]],
    existing_code: Dict[str, str],
) -> Dict[str, str]:
    """补漏掉的 GENERATED_BODY() 与同名 `.generated.h`。只改报错点名的头文件。"""
    if failure_type not in (
        "engine_compile_failed", "self_test_failed", "ue_test_gen_failed",
    ):
        return {}
    if not compile_errors:
        return {}

    by_file: Dict[str, List[Dict[str, Any]]] = {}
    for err in compile_errors:
        rel = (err.get("file") or "").replace("\\", "/").lstrip("./")
        if rel:
            by_file.setdefault(rel, []).append(err)

    fixed: Dict[str, str] = {}
    for rel, errs in by_file.items():
        if not rel.endswith(".h"):
            continue
        content = _read_fix_target(repo_path, rel, existing_code)
        if not content:
            continue
        updated = content
        did_genbody = False
        did_include = False
        if any(_error_wants_genbody(err) for err in errs):
            patched = _insert_generated_body(updated)
            if patched and patched != updated:
                updated = patched
                did_genbody = True
        if any(_error_wants_generated_include(err) for err in errs):
            patched = _insert_generated_include(updated, rel)
            if patched and patched != updated:
                updated = patched
                did_include = True
        if updated == content:
            continue

        def _handled(err: Dict[str, Any]) -> bool:
            if did_genbody and _error_wants_genbody(err):
                return True
            if did_include and _error_wants_generated_include(err):
                return True
            return False

        if errs and all(_handled(err) for err in errs):
            fixed[rel] = updated
    return fixed
