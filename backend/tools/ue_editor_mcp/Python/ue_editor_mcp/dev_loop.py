from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any


CONTRACT_VERSION = "UE_DEV_LOOP_V1"
SERVICE_NAME = "ue-dev-loop-mcp"
LAUNCHER_SERVICE = "ue-editor-mcp-launcher"
LOGS_SERVICE = "ue-editor-mcp-logs"
EDITOR_SERVICE = "ue-editor-mcp"

SAFE_SELF_LOOP_ACTIONS = {
    "collect_context",
    "classify_failure",
    "plan_fix",
    "run_tests",
    "collect_logs",
    "observe_editor",
    "stop",
}
DEFAULT_SELF_LOOP_ACTIONS = [
    "collect_context",
    "classify_failure",
    "plan_fix",
    "run_tests",
    "collect_logs",
]
MAX_SELF_LOOP_ROUNDS = 8

_SUITE_RE = re.compile(r"^[A-Za-z0-9_.+:-]+$")
_FORBIDDEN_SUITE_TOKENS = (";", "&", "|", "\n", "\r", "..", "/", "\\", " open ", " travel ", " restart ", " exit ")


def _clamp_int(value: Any, default_value: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default_value
    return max(min_value, min(max_value, parsed))


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _as_string_list(value: Any) -> list[str]:
    result: list[str] = []
    for item in _as_list(value):
        text = str(item).strip()
        if text:
            result.append(text)
    return result


def _validate_suite(suite: str) -> tuple[bool, str | None]:
    if not suite:
        return False, "suite is required"
    lowered = f" {suite.lower()} "
    if any(token in lowered for token in _FORBIDDEN_SUITE_TOKENS):
        return False, "suite contains forbidden command/path token"
    if not _SUITE_RE.match(suite):
        return False, "suite contains characters outside the Automation suite allowlist"
    return True, None


def _normalize_target_file(path: str) -> str | None:
    text = path.replace("\\", "/").strip()
    if not text:
        return None
    if text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        return None
    pure = PurePosixPath(text)
    if any(part in {"", ".", ".."} for part in pure.parts):
        return None
    return pure.as_posix()


def describe_service() -> dict[str, Any]:
    return {
        "success": True,
        "service": SERVICE_NAME,
        "contract": CONTRACT_VERSION,
        "purpose": "Plan and evaluate generic Unreal development test loops without executing launcher/editor operations.",
        "owns": [
            "dev-loop planning",
            "test gate evaluation",
            "generic failure classification",
            "bounded self-loop contracts",
        ],
        "does_not_own": [
            "building targets",
            "starting or stopping Unreal Editor",
            "submitting or polling Automation tasks",
            "reading raw Unreal logs",
            "mutating project files or assets",
        ],
        "adjacent_services": {
            LAUNCHER_SERVICE: [
                "launcher_start_editor",
                "launcher_run_automation",
                "launcher_task_status",
                "launcher_task_cancel",
                "launcher_stop_editor",
            ],
            LOGS_SERVICE: ["unreal.logs.get", "unreal.asset_thumbnail.get", "unreal.asset_diff.get", "unreal.asset_history.get"],
            EDITOR_SERVICE: ["ue_ping", "ue_actions_search", "ue_actions_schema", "ue_actions_run", "ue_batch"],
        },
        "tool_policy": "This service returns plans, contracts, and evaluations. Execute returned launcher/log/editor calls through their owning MCP services.",
    }


def plan_test_gate(args: dict[str, Any]) -> dict[str, Any]:
    suite = str(args.get("suite") or "").strip()
    ok, error = _validate_suite(suite)
    if not ok:
        return {"success": False, "contract": CONTRACT_VERSION, "error": error}

    launcher_args: dict[str, Any] = {
        "suite": suite,
        "build": bool(args.get("build", True)),
    }
    for key in ("timeout_sec", "build_timeout_sec", "project_root_hint"):
        value = args.get(key)
        if value is not None:
            launcher_args[key] = value

    required_steps = _as_string_list(args.get("required_steps"))
    log_contains = args.get("log_contains")
    log_filter: dict[str, Any] = {}
    if isinstance(log_contains, str) and log_contains.strip():
        log_filter["contains"] = log_contains.strip()
    min_verbosity = args.get("min_verbosity")
    if isinstance(min_verbosity, str) and min_verbosity.strip():
        log_filter["minVerbosity"] = min_verbosity.strip()

    return {
        "success": True,
        "contract": CONTRACT_VERSION,
        "gate": "automation_test",
        "suite": suite,
        "required_steps": required_steps,
        "execution": {
            "service": LAUNCHER_SERVICE,
            "tool": "launcher_run_automation",
            "args": launcher_args,
        },
        "polling": {
            "service": LAUNCHER_SERVICE,
            "tool": "launcher_task_status",
            "cadence_seconds": "15-30",
            "args_template": {"task_id": "<task_id from launcher_run_automation>", "log_tail_lines": 40},
        },
        "evidence": {
            "service": LOGS_SERVICE,
            "tool": "unreal.logs.get",
            "args_template": {
                "mode": "auto",
                "tailLines": 200,
                "maxBytes": 65536,
                "filter": log_filter or {"minVerbosity": "Warning"},
            },
        },
        "evaluation": {
            "service": SERVICE_NAME,
            "tool": "dev_loop.evaluate_test_gate",
            "inputs": ["launcher_status", "required_steps", "observed_steps", "log_summary"],
        },
        "non_duplicate_boundary": "Execution belongs to ue-editor-mcp-launcher; this service only describes the gate and later evaluates evidence.",
    }


def _extract_outcome(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    candidates = [
        payload.get("outcome"),
        (payload.get("result") or {}).get("outcome") if isinstance(payload.get("result"), dict) else None,
        payload.get("launcher_result", {}).get("outcome") if isinstance(payload.get("launcher_result"), dict) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return {}


def _extract_state(payload: dict[str, Any]) -> str | None:
    if not isinstance(payload, dict):
        return None
    state = payload.get("state")
    if isinstance(state, str):
        return state
    result = payload.get("result")
    if isinstance(result, dict) and isinstance(result.get("state"), str):
        return result["state"]
    return None


def _failed_count(outcome: dict[str, Any]) -> int:
    failed = outcome.get("failed")
    if isinstance(failed, int):
        return failed
    failures = outcome.get("failures")
    if isinstance(failures, list):
        return len(failures)
    return 0


def evaluate_test_gate(args: dict[str, Any]) -> dict[str, Any]:
    launcher_status = args.get("launcher_status") if isinstance(args.get("launcher_status"), dict) else {}
    launcher_result = args.get("launcher_result") if isinstance(args.get("launcher_result"), dict) else {}
    payload = launcher_status or launcher_result
    outcome = _extract_outcome(payload)
    state = _extract_state(payload)
    required_steps = _as_string_list(args.get("required_steps"))
    observed_steps = set(_as_string_list(args.get("observed_steps")))
    missing_steps = [step for step in required_steps if step not in observed_steps]
    log_summary = args.get("log_summary") if isinstance(args.get("log_summary"), dict) else {}

    blocking_reasons: list[str] = []
    if state in {"failed", "cancelled", "orphaned"}:
        blocking_reasons.append(f"launcher task ended with state={state}")
    if outcome:
        failed = _failed_count(outcome)
        if failed > 0:
            blocking_reasons.append(f"automation reported {failed} failed test(s)")
    elif state not in {"done", None}:
        blocking_reasons.append("launcher task is not terminal done yet")

    if required_steps and not observed_steps:
        blocking_reasons.append("required_steps were provided but observed_steps is empty")
    elif missing_steps:
        blocking_reasons.append("missing required observed steps: " + ", ".join(missing_steps))

    error_count = log_summary.get("error_count")
    if isinstance(error_count, int) and error_count > 0:
        blocking_reasons.append(f"log_summary reports {error_count} error(s)")

    screenshot_summary = args.get("screenshot_summary") if isinstance(args.get("screenshot_summary"), dict) else {}
    if bool(args.get("require_visual")) and not screenshot_summary.get("passed"):
        blocking_reasons.append("visual evidence was required but screenshot_summary did not pass")

    result = "passed"
    if blocking_reasons:
        result = "failed"
    elif not outcome and state is None:
        result = "incomplete"

    return {
        "success": True,
        "contract": CONTRACT_VERSION,
        "result": result,
        "state": state,
        "automation_outcome": outcome or None,
        "required_steps": {
            "required": required_steps,
            "observed": sorted(observed_steps),
            "missing": missing_steps,
            "complete": bool(required_steps) and not missing_steps or not required_steps,
        },
        "blocking_reasons": blocking_reasons,
        "next_action": _next_action_for_result(result, blocking_reasons),
    }


def _text_blob(*items: Any) -> str:
    chunks: list[str] = []
    for item in items:
        if isinstance(item, str):
            chunks.append(item)
        elif isinstance(item, dict):
            chunks.append(str(item))
        elif isinstance(item, list):
            chunks.extend(str(x) for x in item)
    return "\n".join(chunks).lower()


def classify_failure(args: dict[str, Any]) -> dict[str, Any]:
    evaluation = args.get("evaluation") if isinstance(args.get("evaluation"), dict) else {}
    launcher_status = args.get("launcher_status") if isinstance(args.get("launcher_status"), dict) else {}
    log_summary = args.get("log_summary") if isinstance(args.get("log_summary"), dict) else {}
    text = _text_blob(evaluation, launcher_status, log_summary, args.get("log_excerpt"))

    category = "unknown"
    if "build_failed" in text or "ubt" in text or "compile" in text:
        category = "build_or_compile"
    elif "uht" in text or "generated.h" in text:
        category = "reflection_uht"
    elif "link" in text or "unresolved external" in text:
        category = "linker"
    elif "missing required" in text or "observed_steps is empty" in text:
        category = "missing_evidence_or_steps"
    elif "automation reported" in text or "failed test" in text:
        category = "automation_test_failure"
    elif "timeout" in text or "cancelled" in text or "orphaned" in text:
        category = "launcher_lifecycle"
    elif "visual" in text or "screenshot" in text or "black frame" in text:
        category = "visual_evidence"
    elif "error_count" in text or " fatal" in text or " error" in text:
        category = "runtime_log_error"

    return {
        "success": True,
        "contract": CONTRACT_VERSION,
        "failure_class": category,
        "patch_allowed": category in {"build_or_compile", "reflection_uht", "linker", "automation_test_failure", "runtime_log_error"},
        "recommended_next_actions": _recommended_actions(category),
        "notes": [
            "Classification is heuristic and project-neutral.",
            "Use project-specific MCP/services for semantic assertions or custom log token parsing.",
        ],
    }


def plan_self_loop(args: dict[str, Any]) -> dict[str, Any]:
    suite = str(args.get("suite") or "").strip()
    ok, error = _validate_suite(suite)
    if not ok:
        return {"success": False, "contract": CONTRACT_VERSION, "error": error}

    action_sequence = _as_string_list(args.get("action_sequence")) or list(DEFAULT_SELF_LOOP_ACTIONS)
    unsafe_actions = [item for item in action_sequence if item not in SAFE_SELF_LOOP_ACTIONS]
    if unsafe_actions:
        return {
            "success": False,
            "contract": CONTRACT_VERSION,
            "error": "self-loop action_sequence contains unsupported actions",
            "unsafe_actions": unsafe_actions,
            "safe_actions": sorted(SAFE_SELF_LOOP_ACTIONS),
        }

    raw_targets = _as_string_list(args.get("target_files"))
    target_files: list[str] = []
    unsafe_targets: list[str] = []
    for path in raw_targets:
        normalized = _normalize_target_file(path)
        if normalized:
            target_files.append(normalized)
        else:
            unsafe_targets.append(path)
    if unsafe_targets:
        return {
            "success": False,
            "contract": CONTRACT_VERSION,
            "error": "target_files must be project-relative paths without '..' or drive roots",
            "unsafe_targets": unsafe_targets,
        }

    max_rounds = _clamp_int(args.get("max_rounds"), 3, 1, MAX_SELF_LOOP_ROUNDS)
    max_failed_gates = _clamp_int(args.get("max_failed_gates"), 1, 0, max_rounds)
    dry_run = bool(args.get("dry_run", True))

    rounds: list[dict[str, Any]] = []
    for round_index in range(1, max_rounds + 1):
        rounds.append(
            {
                "round": round_index,
                "actions": [_self_loop_action_plan(action_id, suite, args) for action_id in action_sequence],
                "stop_conditions": [
                    "test gate passes and stop_on_success=true",
                    f"failed gate count exceeds {max_failed_gates}",
                    "manual stop action is selected",
                ],
            }
        )

    return {
        "success": True,
        "contract": CONTRACT_VERSION,
        "suite": suite,
        "target_files": target_files,
        "dry_run": dry_run,
        "max_rounds": max_rounds,
        "max_failed_gates": max_failed_gates,
        "stop_on_success": bool(args.get("stop_on_success", True)),
        "action_sequence": action_sequence,
        "rounds": rounds,
        "boundaries": describe_service()["does_not_own"],
        "non_duplicate_boundary": "Self-loop execution is decomposed into calls to launcher/logs/editor services; ue-dev-loop-mcp does not execute those calls itself.",
    }


def _self_loop_action_plan(action_id: str, suite: str, args: dict[str, Any]) -> dict[str, Any]:
    if action_id == "run_tests":
        return {
            "action_id": action_id,
            "service": LAUNCHER_SERVICE,
            "tool": "launcher_run_automation",
            "args": plan_test_gate({**args, "suite": suite})["execution"]["args"],
        }
    if action_id == "collect_logs":
        return {
            "action_id": action_id,
            "service": LOGS_SERVICE,
            "tool": "unreal.logs.get",
            "args": {"mode": "auto", "tailLines": 200, "filter": {"minVerbosity": "Warning"}},
        }
    if action_id == "observe_editor":
        return {
            "action_id": action_id,
            "service": EDITOR_SERVICE,
            "tool": "ue_actions_search",
            "args": {"query": "state ready context", "top_k": 5},
        }
    if action_id == "classify_failure":
        return {"action_id": action_id, "service": SERVICE_NAME, "tool": "dev_loop.classify_failure"}
    if action_id == "collect_context":
        return {"action_id": action_id, "service": SERVICE_NAME, "tool": "dev_loop.evaluate_test_gate"}
    if action_id == "plan_fix":
        return {
            "action_id": action_id,
            "service": "agent",
            "tool": "workspace_edit",
            "notes": "The agent or user applies code changes; this MCP service does not mutate files.",
        }
    return {"action_id": action_id, "service": SERVICE_NAME, "tool": "stop"}


def _next_action_for_result(result: str, blocking_reasons: list[str]) -> str:
    if result == "passed":
        return "Continue to the next development task or tighten project-specific assertions."
    if result == "incomplete":
        return "Poll launcher_task_status or collect logs/evidence before making code changes."
    if blocking_reasons:
        return "Classify the first blocking reason, apply the smallest project change, then rerun the planned test gate."
    return "Collect launcher status and logs, then evaluate again."


def _recommended_actions(category: str) -> list[str]:
    if category in {"build_or_compile", "reflection_uht", "linker"}:
        return ["inspect compiler output", "edit code", "rerun launcher_run_automation with build=true"]
    if category == "missing_evidence_or_steps":
        return ["collect logs with a narrower filter", "confirm required_steps are project-appropriate"]
    if category == "automation_test_failure":
        return ["inspect failed automation test", "fix root cause", "rerun the same suite"]
    if category == "launcher_lifecycle":
        return ["poll launcher_task_status", "cancel or restart only through launcher"]
    if category == "visual_evidence":
        return ["rerun with an interactive/RHI visual gate", "collect screenshots through the owning service"]
    if category == "runtime_log_error":
        return ["query logs by Error/Fatal", "fix the first root-cause runtime error"]
    return ["collect launcher status", "collect warning/error logs", "evaluate test gate again"]
