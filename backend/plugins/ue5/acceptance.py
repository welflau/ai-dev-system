"""UE 套件的产品验收证据。

CLI 纯文本评审读不到 png。这里把 UBT、Automation、静态预检和少量头源文件摘要
交给 AcceptanceReviewAction，避免产品验收因为「工作目录里没有截图」打 0 分。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

logger = logging.getLogger("plugins.ue5.acceptance")

_SKIP_SNIPPET = ("Binaries/", "Intermediate/", "Saved/", "DerivedDataCache/")


def _parse_detail(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _snippet_paths(context: Dict[str, Any]) -> List[str]:
    existing = context.get("existing_code") or {}
    dev_result = context.get("dev_result") or {}
    ordered: List[str] = []
    files = dev_result.get("files") if isinstance(dev_result, dict) else None
    if isinstance(files, dict):
        ordered.extend(str(path) for path in files.keys())
    for path in existing.keys():
        if path not in ordered:
            ordered.append(str(path))
    kept: List[str] = []
    for path in ordered:
        norm = path.replace("\\", "/")
        if not norm.endswith((".h", ".cpp")):
            continue
        if any(part in norm for part in _SKIP_SNIPPET):
            continue
        kept.append(path)
    return kept[:3]


async def build_acceptance_evidence(context: Dict[str, Any]) -> Dict[str, Any]:
    """汇总编译、Playtest、自测和打包阶段的客观结果。"""
    ticket_id = str(context.get("ticket_id") or "")
    compile_detail: Dict[str, Any] = {}
    play_detail: Dict[str, Any] = {}
    self_test_detail: Dict[str, Any] = {}
    package_detail: Dict[str, Any] = {}

    if ticket_id:
        try:
            from database import db
            rows = await db.fetch_all(
                """SELECT action, to_status, message, detail
                   FROM ticket_logs
                   WHERE ticket_id = ? AND action IN ('complete', 'skill_step_done')
                   ORDER BY created_at DESC LIMIT 40""",
                (ticket_id,),
            )
            for row in rows or []:
                to_st = str(row.get("to_status") or "")
                msg = str(row.get("message") or "")
                det = _parse_detail(row.get("detail"))
                if not compile_detail and (
                    to_st == "engine_compile_passed" or "编译通过" in msg
                ):
                    compile_detail = det
                if not play_detail and (
                    to_st == "play_test_passed" or "Playtest 通过" in msg
                ):
                    play_detail = det
                if not self_test_detail and (
                    "self_test" in msg or det.get("ue_blocking_issues") is not None
                ):
                    self_test_detail = det
                if not package_detail and (to_st == "packaged" or "打包完成" in msg):
                    package_detail = det
        except Exception as exc:
            logger.debug("读取 UE 阶段日志异常（忽略）: %s", exc)

    sections: List[str] = ["## UE 插件自动化验收证据（真实运行报告）"]
    if compile_detail:
        errors = compile_detail.get("errors") or []
        warnings = compile_detail.get("warnings") or []
        sections.append(
            "- **UBT 编译 (`engine_compile`)**：已通过\n"
            f"  - exit_code=`{compile_detail.get('exit_code', 0)}`，"
            f"耗时 `{compile_detail.get('duration_ms', 0)}` ms，"
            f"errors=`{len(errors)}`，warnings=`{len(warnings)}`\n"
            f"  - 命令：`{compile_detail.get('command') or ''}`"
        )
    else:
        sections.append("- **UBT 编译**：本工单日志里没有 `engine_compile_passed` 记录。若本次没有 C++ 改动，可以不因此判失败。")

    if play_detail:
        summary = play_detail.get("summary") or {}
        shots = play_detail.get("screenshots") or []
        shot_text = "、".join(str(p) for p in shots[:5]) if shots else "（无截图路径）"
        sections.append(
            "- **UE Automation (`play_test`)**：已通过\n"
            f"  - passed=`{summary.get('passed', 0)}`，failed=`{summary.get('failed', 0)}`，"
            f"total=`{summary.get('total', 0)}`\n"
            f"  - 截图路径：{shot_text}\n"
            f"  - 命令：`{play_detail.get('command') or ''}`"
        )
    else:
        sections.append("- **UE Automation**：本工单日志里没有 `play_test_passed` 记录。")

    blocking = self_test_detail.get("ue_blocking_issues")
    if isinstance(blocking, list):
        if blocking:
            sections.append(f"- **静态预检**：{len(blocking)} 条 blocking issue。")
        else:
            sections.append("- **静态预检**：0 条 blocking issue，静态预检通过。")
    else:
        sections.append("- **静态预检**：日志里没有 blocking issue 计数。")

    if package_detail:
        sections.append(
            "- **打包**：已完成\n"
            f"  - 平台 `{package_detail.get('platform') or ''}`，"
            f"配置 `{package_detail.get('configuration') or ''}`，"
            f"耗时 `{package_detail.get('duration_ms', 0)}` ms"
        )
    else:
        sections.append("- **打包**：尚未打包。这不构成验收失败。")

    existing = context.get("existing_code") or {}
    snippets = _snippet_paths(context)
    if snippets:
        sections.append("\n## 核心 C++ 摘要")
        for rel in snippets:
            content = str(existing.get(rel) or "").strip()
            if not content:
                continue
            body = "\n".join(content.splitlines()[:80])
            sections.append(f"### `{rel}`\n```cpp\n{body}\n```")

    return {
        "evidence_markdown": "\n\n".join(sections),
        "extra_check_items": [
            "UBT 最近一次结果为通过，或本工单没有 C++ 改动因而未跑编译",
            "Automation 通过，或项目没有项目级测试且 Playtest 按 0 测试视为通过结束",
            "需要玩法验证的工单带有截图路径或预览说明",
            "改动的反射类型具备 GENERATED_BODY() 与对应的 .generated.h",
        ],
        "acceptance_rules": (
            "CLI 纯文本评审读不到 png 时，以本节的编译退出码、Automation 摘要和源码片段打分。"
            "不得因读不到截图判 0 分。截图路径只作为证据索引，不要求评审过程打开图片文件。"
            "尚未打包不构成失败。静态预检 0 条 blocking、编译 exit 为 0、测试 failed 为 0 时，"
            "应对照工单描述给通过分（score >= 7），而不是因为隔离目录里没有 png 拒绝验收。"
        ),
    }
