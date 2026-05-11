#!/usr/bin/env python3
"""
Stop Hook: 兜底上报技能使用数据。

触发方式: hooks/hooks.json > Stop Hook
输入: stdin JSON (包含 cwd 等)
输出: 无（完全静默，不输出任何 stdout/stderr）

本脚本始终 exit 0，绝不阻止 Agent 停止。
作为 SKILL.md 中 AI 主动上报的兜底补充——
即使 AI 在推理过程中跳过了上报命令，Stop Hook 也会在会话结束时触发。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    # 解析 stdin
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    cwd = hook_input.get("cwd", "")

    # 延迟导入上报模块
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    try:
        from report import report_event
    except ImportError:
        sys.exit(0)

    # 兜底上报一次 load 事件
    # 使用 "hook_fallback" 标记，方便后端区分是 AI 主动上报还是 Hook 兜底
    try:
        report_event(
            action="hook_fallback",
            language="unknown",
            rules_triggered=[],
            safe_functions_triggered=[],
            rule_count=0,
            code_lines_generated=0,
            path=cwd or None
        )
    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)  # 始终 exit 0
