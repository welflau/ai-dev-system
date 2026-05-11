#!/usr/bin/env python3
"""
编排器辅助工具 — 集中处理编排器中的确定性决策逻辑

跨平台：Python3 内置模块，零外部依赖。

子命令：
  1. check-phase-gate     — 检查 phase 完成状态
  2. should-launch-agent  — 根据 phase 状态决定是否启动 agent
  3. should-rerun-agent   — 检测 phase 更新，决定是否需要 re-run
  4. determine-trace-method — 根据工具可用性决定 traceMethod
  5. summarize-progress   — 汇总当前扫描进度
  6. detect-framework     — 检测项目框架/技术栈

设计原则：
  - 替代编排器 Agent 中的判断逻辑（if/else），确保确定性
  - 所有输出为 JSON，无 side effect（不写 DB，不修改文件）
  - 编排器只需读 stdout 中的 action 字段，做对应操作即可
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


# ─── 工具函数 ────────────────────────────────────────────────

def _connect_db(batch_dir, readonly=True):
    """连接 project-index.db，启用 WAL 模式和 busy_timeout，带重试机制"""
    db_path = str(Path(batch_dir) / "project-index.db")
    if not os.path.exists(db_path):
        return None
    max_retries = 3
    for attempt in range(max_retries):
        try:
            uri = f"file:{db_path}?mode=ro" if readonly else db_path
            conn = sqlite3.connect(uri if readonly else db_path, uri=readonly)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=15000")
            return conn
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and attempt < max_retries - 1:
                import time
                time.sleep(1 * (attempt + 1))
                continue
            raise


def _get_phase_status(conn):
    """获取所有 phase 的状态"""
    phases = {}
    for row in conn.execute("SELECT phase, status, completed_at FROM phase_status"):
        phases[row["phase"]] = {
            "status": row["status"],
            "completed_at": row["completed_at"],
        }
    return phases


def _get_table_counts(conn):
    """获取关键表的行数"""
    counts = {}
    for table in ["files", "sinks", "endpoints", "defenses", "call_graph",
                   "attack_surface", "indexer_findings", "ast_functions", "ast_refined_sinks"]:
        try:
            row = conn.execute(f"SELECT COUNT(*) as c FROM {table}").fetchone()
            counts[table] = row["c"]
        except sqlite3.OperationalError:
            counts[table] = 0
    return counts


# ─── Agent 依赖定义 ──────────────────────────────────────────

# 每个 agent 启动所需的最低 phase 和表依赖
AGENT_REQUIREMENTS = {
    "vuln-scan": {
        "min_phase": "phase1",
        "required_tables": ["sinks"],
        "optimal_phase": "phase2",
        "description": "Sink-Driven 漏洞扫描",
    },
    "logic-scan": {
        "min_phase": "phase2",
        "required_tables": ["endpoints"],
        "optimal_phase": "phase2",
        "description": "认证授权 + 业务逻辑审计",
    },
    "red-team": {
        "min_phase": "phase1",
        "required_tables": [],  # 可在空数据下运行（Grep-first）
        "optimal_phase": "phase2",
        "description": "红队对抗深度审计",
    },
}

# Phase 优先级排序（用于比较 phase 新旧）
PHASE_ORDER = {"phase1": 1, "phase1_5": 2, "phase2": 3}


# ─── 命令: check-phase-gate ──────────────────────────────────

def cmd_check_phase_gate(args):
    """检查指定 phase 是否已完成"""
    conn = _connect_db(args.batch_dir)
    if not conn:
        print(json.dumps({
            "phase": args.required_phase,
            "status": "unknown",
            "can_proceed": False,
            "reason": "database_not_found"
        }))
        return

    try:
        phases = _get_phase_status(conn)
        phase_info = phases.get(args.required_phase, {"status": "pending", "completed_at": None})

        can_proceed = phase_info["status"] == "completed"

        # 也检查当前最高已完成 phase
        completed_phases = [p for p, info in phases.items() if info["status"] == "completed"]
        highest_completed = max(completed_phases, key=lambda p: PHASE_ORDER.get(p, 0)) if completed_phases else None

        result = {
            "phase": args.required_phase,
            "status": phase_info["status"],
            "completed_at": phase_info["completed_at"],
            "can_proceed": can_proceed,
            "all_phases": {p: info["status"] for p, info in phases.items()},
            "highest_completed_phase": highest_completed,
        }
    finally:
        conn.close()

    print(json.dumps(result, ensure_ascii=False))


# ─── 命令: should-launch-agent ───────────────────────────────

def cmd_should_launch_agent(args):
    """根据 phase 状态和 agent 依赖决定是否启动 agent"""
    agent_name = args.agent
    req = AGENT_REQUIREMENTS.get(agent_name)

    if not req:
        print(json.dumps({
            "agent": agent_name,
            "action": "error",
            "reason": f"Unknown agent: {agent_name}. Known: {list(AGENT_REQUIREMENTS.keys())}"
        }))
        return

    conn = _connect_db(args.batch_dir)
    if not conn:
        print(json.dumps({
            "agent": agent_name,
            "action": "wait",
            "reason": "database_not_found"
        }))
        return

    try:
        phases = _get_phase_status(conn)
        counts = _get_table_counts(conn)

        # 检查最低 phase 是否已完成
        min_phase = req["min_phase"]
        min_phase_info = phases.get(min_phase, {"status": "pending"})
        phase_ready = min_phase_info["status"] == "completed"

        # 检查必需表是否有数据
        tables_ready = all(counts.get(t, 0) > 0 for t in req["required_tables"])

        # 检查 agent 是否已有输出
        agent_output = Path(args.batch_dir) / "agents" / f"{agent_name}.json"
        already_run = agent_output.exists()

        # 决定 action
        if already_run:
            action = "already_run"
            reason = f"Output exists: {agent_output}"
        elif phase_ready and tables_ready:
            action = "launch"
            reason = f"{min_phase} completed, required tables populated"
        elif phase_ready and not tables_ready:
            missing = [t for t in req["required_tables"] if counts.get(t, 0) == 0]
            action = "wait"
            reason = f"Phase ready but missing data in: {missing}"
        else:
            action = "wait"
            reason = f"Waiting for {min_phase} (current: {min_phase_info['status']})"

        # 判断当前 phase 是否已达最优
        optimal_phase = req["optimal_phase"]
        optimal_info = phases.get(optimal_phase, {"status": "pending"})
        at_optimal = optimal_info["status"] == "completed"

        result = {
            "agent": agent_name,
            "action": action,
            "reason": reason,
            "required_phase": min_phase,
            "optimal_phase": optimal_phase,
            "phase_ready": phase_ready,
            "at_optimal_phase": at_optimal,
            "tables_ready": tables_ready,
            "already_run": already_run,
            "table_counts": {t: counts.get(t, 0) for t in req["required_tables"]},
            "all_phases": {p: info["status"] for p, info in phases.items()},
        }

    finally:
        conn.close()

    print(json.dumps(result, ensure_ascii=False))


# ─── 命令: should-rerun-agent ────────────────────────────────

def cmd_should_rerun_agent(args):
    """检测 phase 更新，决定是否需要 re-run agent"""
    agent_name = args.agent
    req = AGENT_REQUIREMENTS.get(agent_name)

    if not req:
        print(json.dumps({
            "agent": agent_name,
            "action": "error",
            "reason": f"Unknown agent: {agent_name}"
        }))
        return

    agent_output = Path(args.batch_dir) / "agents" / f"{agent_name}.json"

    if not agent_output.exists():
        print(json.dumps({
            "agent": agent_name,
            "action": "not_applicable",
            "reason": "no_prior_run"
        }))
        return

    # 读取 agent 输出中的 metadata.index_phase
    try:
        with open(agent_output, "r", encoding="utf-8") as f:
            agent_data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(json.dumps({
            "agent": agent_name,
            "action": "error",
            "reason": f"Cannot read agent output: {e}"
        }))
        return

    prior_phase = agent_data.get("metadata", {}).get("index_phase", "unknown")
    agent_status = agent_data.get("status", "unknown")

    # 获取当前 DB 中的 phase 状态
    conn = _connect_db(args.batch_dir)
    if not conn:
        print(json.dumps({
            "agent": agent_name,
            "action": "error",
            "reason": "database_not_found"
        }))
        return

    try:
        phases = _get_phase_status(conn)
        completed_phases = [p for p, info in phases.items() if info["status"] == "completed"]
        latest_phase = max(completed_phases, key=lambda p: PHASE_ORDER.get(p, 0)) if completed_phases else None

        prior_order = PHASE_ORDER.get(prior_phase, 0)
        latest_order = PHASE_ORDER.get(latest_phase, 0) if latest_phase else 0

        # 检查 re-run 次数限制
        max_reruns = int(args.max_reruns) if args.max_reruns else 2
        rerun_count = agent_data.get("metadata", {}).get("rerun_count", 0)

        if rerun_count >= max_reruns:
            action = "skip"
            reason = f"Max reruns reached ({rerun_count}/{max_reruns})"
        elif latest_order > prior_order:
            action = "rerun"
            reason = f"New data available: {prior_phase} → {latest_phase}"
        elif agent_status == "partial":
            action = "continue"
            reason = "Agent reported partial completion, can continue"
        else:
            action = "no_action"
            reason = f"Phase unchanged ({prior_phase})"

        result = {
            "agent": agent_name,
            "action": action,
            "reason": reason,
            "prior_phase": prior_phase,
            "latest_phase": latest_phase,
            "agent_status": agent_status,
            "rerun_count": rerun_count,
            "max_reruns": max_reruns,
            "instruction": None,
        }

        if action == "rerun":
            result["instruction"] = (
                f"rm -f {agent_output} && relaunch {agent_name} "
                f"(new data from {latest_phase})"
            )
        elif action == "continue":
            pending = agent_data.get("metadata", {}).get("pendingSinks", [])
            result["instruction"] = (
                f"Resume {agent_name} with {len(pending)} pending items"
            )

    finally:
        conn.close()

    print(json.dumps(result, ensure_ascii=False))


# ─── 命令: determine-trace-method ────────────────────────────

def cmd_determine_trace_method(args):
    """根据工具可用性和 phase 状态决定 traceMethod"""
    conn = _connect_db(args.batch_dir)

    lsp_available = args.lsp_available == "true" if args.lsp_available else False
    has_ast = False
    has_call_graph = False

    if conn:
        try:
            counts = _get_table_counts(conn)
            has_ast = counts.get("ast_functions", 0) > 0
            has_call_graph = counts.get("call_graph", 0) > 0

            phases = _get_phase_status(conn)
            phase2_done = phases.get("phase2", {}).get("status") == "completed"

            # 如果 phase2 完成且 call_graph 有数据，LSP 数据已完整
            if phase2_done and has_call_graph:
                lsp_available = True
        finally:
            conn.close()

    if lsp_available and has_call_graph:
        trace_method = "LSP"
        confidence_cap = 100
        quality = "optimal"
    elif has_ast:
        trace_method = "Grep+AST"
        confidence_cap = 95
        quality = "good"
    else:
        trace_method = "Grep+Read"
        confidence_cap = 90
        quality = "baseline"

    result = {
        "traceMethod": trace_method,
        "confidence_cap": confidence_cap,
        "quality": quality,
        "lsp_available": lsp_available,
        "has_ast": has_ast,
        "has_call_graph": has_call_graph,
    }
    print(json.dumps(result, ensure_ascii=False))


# ─── 命令: summarize-progress ────────────────────────────────

def cmd_summarize_progress(args):
    """汇总当前扫描进度"""
    conn = _connect_db(args.batch_dir)
    if not conn:
        print(json.dumps({"error": "database_not_found"}))
        return

    try:
        phases = _get_phase_status(conn)
        counts = _get_table_counts(conn)

        # 检查各 agent 输出状态
        agents_dir = Path(args.batch_dir) / "agents"
        agent_statuses = {}
        for agent_name in ["vuln-scan", "logic-scan", "red-team"]:
            output_file = agents_dir / f"{agent_name}.json"
            if output_file.exists():
                try:
                    with open(output_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    agent_statuses[agent_name] = {
                        "status": data.get("status", "unknown"),
                        "findings": len(data.get("findings", [])),
                        "index_phase": data.get("metadata", {}).get("index_phase", "unknown"),
                    }
                except (json.JSONDecodeError, IOError):
                    agent_statuses[agent_name] = {"status": "error", "findings": 0}
            else:
                agent_statuses[agent_name] = {"status": "not_started", "findings": 0}

        # 检查验证状态
        verifier_statuses = {}
        for vname in ["verifier-vuln", "verifier-logic", "verifier-redteam"]:
            vfile = agents_dir / f"{vname}.json"
            if vfile.exists():
                try:
                    with open(vfile, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    verifier_statuses[vname] = {
                        "status": data.get("status", "unknown"),
                        "findings": len(data.get("findings", [])),
                    }
                except (json.JSONDecodeError, IOError):
                    verifier_statuses[vname] = {"status": "error"}
            else:
                verifier_statuses[vname] = {"status": "not_started"}

        # 检查 merged-scan.json
        merged_file = Path(args.batch_dir) / "merged-scan.json"
        merged_status = "completed" if merged_file.exists() else "not_started"

        # 检查报告
        report_file = Path(args.batch_dir) / "security-scan-report.html"
        report_status = "completed" if report_file.exists() else "not_started"

        # 计算总体进度
        total_steps = 8  # phase1 + phase1_5 + phase2 + 3 agents + merge + report
        completed_steps = 0
        completed_steps += sum(1 for p in phases.values() if p["status"] == "completed")
        completed_steps += sum(1 for a in agent_statuses.values() if a["status"] in ("completed", "partial"))
        if merged_status == "completed":
            completed_steps += 1
        if report_status == "completed":
            completed_steps += 1

        # 判断下一步操作
        next_actions = _determine_next_actions(phases, counts, agent_statuses)

        result = {
            "phases": {p: info["status"] for p, info in phases.items()},
            "table_counts": counts,
            "agents": agent_statuses,
            "verifiers": verifier_statuses,
            "merged_scan": merged_status,
            "report": report_status,
            "progress": f"{completed_steps}/{total_steps}",
            "progress_pct": round(completed_steps / total_steps * 100),
            "next_actions": next_actions,
        }
    finally:
        conn.close()

    print(json.dumps(result, ensure_ascii=False))


def _determine_next_actions(phases, counts, agent_statuses):
    """根据当前状态确定下一步操作"""
    actions = []

    phase_map = {p: info["status"] for p, info in phases.items()}

    # 如果 indexer 还在运行
    if phase_map.get("phase1") != "completed":
        actions.append({"action": "wait_indexer", "detail": "Waiting for indexer phase1"})
        return actions

    # Phase1 完成后的操作
    for agent_name in ["vuln-scan", "red-team"]:
        status = agent_statuses.get(agent_name, {}).get("status", "not_started")
        if status == "not_started":
            actions.append({"action": "launch_agent", "agent": agent_name, "phase": "phase1"})

    # Phase1_5 完成后的操作
    if phase_map.get("phase1_5") == "completed":
        for agent_name in ["vuln-scan", "red-team"]:
            status = agent_statuses.get(agent_name, {})
            if status.get("status") in ("completed", "partial") and status.get("index_phase") == "phase1":
                actions.append({"action": "rerun_agent", "agent": agent_name, "reason": "phase1_5 data available"})

    # Phase2 完成后的操作
    if phase_map.get("phase2") == "completed":
        logic_status = agent_statuses.get("logic-scan", {}).get("status", "not_started")
        if logic_status == "not_started":
            actions.append({"action": "launch_agent", "agent": "logic-scan", "phase": "phase2"})

        for agent_name in ["vuln-scan", "red-team"]:
            status = agent_statuses.get(agent_name, {})
            if status.get("index_phase") not in ("phase2", None):
                actions.append({"action": "rerun_agent", "agent": agent_name, "reason": "phase2 LSP data available"})

    # 所有 agent 完成后
    all_done = all(
        agent_statuses.get(a, {}).get("status") in ("completed", "partial")
        for a in ["vuln-scan", "logic-scan", "red-team"]
    )
    if all_done and phase_map.get("phase2") == "completed":
        actions.append({"action": "start_verification", "detail": "All agents completed, ready for verification"})

    if not actions:
        actions.append({"action": "wait", "detail": "Waiting for ongoing operations to complete"})

    return actions


# ─── 命令: detect-framework ──────────────────────────────────

FRAMEWORK_MARKERS = {
    "spring-boot": {
        "files": ["pom.xml", "build.gradle", "build.gradle.kts"],
        "content_patterns": ["spring-boot"],
        "language": "java",
    },
    "spring-mvc": {
        "files": ["pom.xml", "build.gradle"],
        "content_patterns": ["spring-webmvc", "spring-web"],
        "language": "java",
    },
    "spring-security": {
        "files": ["pom.xml", "build.gradle"],
        "content_patterns": ["spring-security"],
        "language": "java",
    },
    "ktor": {
        "files": ["build.gradle.kts", "build.gradle"],
        "content_patterns": ["io.ktor"],
        "language": "kotlin",
    },
    "spring-boot-kotlin": {
        "files": ["build.gradle.kts"],
        "content_patterns": ["kotlin-spring", "kotlin(\"spring\")", "kotlin(\"jpa\")"],
        "language": "kotlin",
    },
    "django": {
        "files": ["manage.py", "requirements.txt", "setup.py", "pyproject.toml"],
        "content_patterns": ["django"],
        "language": "python",
    },
    "flask": {
        "files": ["requirements.txt", "setup.py", "pyproject.toml"],
        "content_patterns": ["flask"],
        "language": "python",
    },
    "fastapi": {
        "files": ["requirements.txt", "setup.py", "pyproject.toml"],
        "content_patterns": ["fastapi"],
        "language": "python",
    },
    "express": {
        "files": ["package.json"],
        "content_patterns": ["express"],
        "language": "javascript",
    },
    "nestjs": {
        "files": ["package.json"],
        "content_patterns": ["@nestjs/core"],
        "language": "typescript",
    },
    "gin": {
        "files": ["go.mod"],
        "content_patterns": ["gin-gonic"],
        "language": "go",
    },
    "laravel": {
        "files": ["composer.json", "artisan"],
        "content_patterns": ["laravel"],
        "language": "php",
    },
}

BUILD_TOOL_MARKERS = {
    "maven": ["pom.xml"],
    "gradle": ["build.gradle", "build.gradle.kts"],
    "npm": ["package.json"],
    "pip": ["requirements.txt", "setup.py", "pyproject.toml"],
    "go-mod": ["go.mod"],
    "composer": ["composer.json"],
}

KNOWLEDGE_FILE_MAP = {
    "spring-boot": ["spring-security.yaml", "java-common.yaml"],
    "spring-mvc": ["spring-security.yaml", "java-common.yaml"],
    "spring-security": ["spring-security.yaml"],
    "ktor": ["kotlin-common.yaml"],
    "spring-boot-kotlin": ["spring-security.yaml", "kotlin-common.yaml"],
    "django": ["python-common.yaml"],
    "flask": ["python-common.yaml"],
    "fastapi": ["python-common.yaml"],
    "express": ["node-common.yaml"],
    "nestjs": ["node-common.yaml"],
    "gin": ["go-common.yaml"],
    "laravel": ["php-common.yaml"],
}


def cmd_detect_framework(args):
    """检测项目框架和技术栈"""
    project_path = Path(args.project_path).resolve()

    detected_frameworks = []
    detected_languages = set()
    detected_build_tools = []

    # 检测框架
    for framework, config in FRAMEWORK_MARKERS.items():
        for marker_file in config["files"]:
            marker_path = project_path / marker_file
            if marker_path.exists():
                # 检查文件内容是否包含特征模式
                try:
                    content = marker_path.read_text(encoding="utf-8", errors="ignore")
                    if any(p in content.lower() for p in config["content_patterns"]):
                        detected_frameworks.append(framework)
                        detected_languages.add(config["language"])
                        break
                except IOError:
                    continue

    # 检测构建工具
    for tool, markers in BUILD_TOOL_MARKERS.items():
        for marker in markers:
            if (project_path / marker).exists():
                detected_build_tools.append(tool)
                break

    # 推断 knowledge 文件
    knowledge_files = []
    for fw in detected_frameworks:
        for kf in KNOWLEDGE_FILE_MAP.get(fw, []):
            if kf not in knowledge_files:
                knowledge_files.append(kf)

    result = {
        "status": "completed",
        "frameworks": detected_frameworks,
        "primary_framework": detected_frameworks[0] if detected_frameworks else "unknown",
        "languages": sorted(detected_languages),
        "build_tools": detected_build_tools,
        "knowledge_files": knowledge_files,
        "project_path": str(project_path),
    }
    print(json.dumps(result, ensure_ascii=False))


# ─── CLI 入口 ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="编排器辅助工具 — 确定性编排决策",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 检查 phase 完成状态
  %(prog)s check-phase-gate \\
    --batch-dir security-scan-output/project-deep-xxx \\
    --required-phase phase1_5

  # 决定是否启动 vuln-scan
  %(prog)s should-launch-agent \\
    --batch-dir security-scan-output/project-deep-xxx \\
    --agent vuln-scan

  # 检查是否需要 re-run agent
  %(prog)s should-rerun-agent \\
    --batch-dir security-scan-output/project-deep-xxx \\
    --agent vuln-scan

  # 决定 traceMethod
  %(prog)s determine-trace-method \\
    --batch-dir security-scan-output/project-deep-xxx

  # 扫描进度汇总
  %(prog)s summarize-progress \\
    --batch-dir security-scan-output/project-deep-xxx

  # 检测项目框架
  %(prog)s detect-framework \\
    --project-path /path/to/project
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # check-phase-gate
    p_gate = subparsers.add_parser("check-phase-gate", help="检查 phase 完成状态")
    p_gate.add_argument("--batch-dir", required=True, help="扫描批次目录")
    p_gate.add_argument("--required-phase", required=True, help="需要检查的 phase")

    # should-launch-agent
    p_launch = subparsers.add_parser("should-launch-agent", help="决定是否启动 agent")
    p_launch.add_argument("--batch-dir", required=True, help="扫描批次目录")
    p_launch.add_argument("--agent", required=True, help="Agent 名称")

    # should-rerun-agent
    p_rerun = subparsers.add_parser("should-rerun-agent", help="决定是否 re-run agent")
    p_rerun.add_argument("--batch-dir", required=True, help="扫描批次目录")
    p_rerun.add_argument("--agent", required=True, help="Agent 名称")
    p_rerun.add_argument("--max-reruns", default="2", help="最大 re-run 次数 (默认 2)")

    # determine-trace-method
    p_trace = subparsers.add_parser("determine-trace-method", help="决定 traceMethod")
    p_trace.add_argument("--batch-dir", required=True, help="扫描批次目录")
    p_trace.add_argument("--lsp-available", help="LSP 是否可用 (true/false)")

    # summarize-progress
    p_progress = subparsers.add_parser("summarize-progress", help="扫描进度汇总")
    p_progress.add_argument("--batch-dir", required=True, help="扫描批次目录")

    # detect-framework
    p_detect = subparsers.add_parser("detect-framework", help="检测项目框架")
    p_detect.add_argument("--project-path", required=True, help="项目根目录")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "check-phase-gate": cmd_check_phase_gate,
        "should-launch-agent": cmd_should_launch_agent,
        "should-rerun-agent": cmd_should_rerun_agent,
        "determine-trace-method": cmd_determine_trace_method,
        "summarize-progress": cmd_summarize_progress,
        "detect-framework": cmd_detect_framework,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
