from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from typing import Any


def _ensure_mcp_import_stub() -> None:
    if "mcp.server" in sys.modules and "mcp.types" in sys.modules:
        return

    mcp_module = types.ModuleType("mcp")
    server_module = types.ModuleType("mcp.server")
    stdio_module = types.ModuleType("mcp.server.stdio")
    types_module = types.ModuleType("mcp.types")

    class Server:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def list_tools(self) -> Any:
            def decorator(func: Any) -> Any:
                return func

            return decorator

        def call_tool(self) -> Any:
            def decorator(func: Any) -> Any:
                return func

            return decorator

    class Tool:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    class TextContent:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    async def stdio_server() -> Any:
        raise RuntimeError("stdio_server is unavailable in tests")

    server_module.Server = Server
    stdio_module.stdio_server = stdio_server
    types_module.Tool = Tool
    types_module.TextContent = TextContent
    sys.modules.setdefault("mcp", mcp_module)
    sys.modules.setdefault("mcp.server", server_module)
    sys.modules.setdefault("mcp.server.stdio", stdio_module)
    sys.modules.setdefault("mcp.types", types_module)


_PKG_DIR = Path(__file__).resolve().parents[1]
if str(_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR))

_ensure_mcp_import_stub()

from ue_editor_mcp import dev_loop  # noqa: E402
from ue_editor_mcp import server_dev_loop  # noqa: E402


class DevLoopBoundaryTests(unittest.TestCase):
    def test_service_boundary_names_adjacent_services_without_owning_launcher_tools(self) -> None:
        description = dev_loop.describe_service()
        self.assertTrue(description["success"])
        self.assertEqual(description["service"], "ue-dev-loop-mcp")
        self.assertIn("building targets", description["does_not_own"])
        self.assertIn("launcher_run_automation", description["adjacent_services"]["ue-editor-mcp-launcher"])

        tool_names = {tool.name for tool in server_dev_loop.TOOLS}
        self.assertEqual(
            tool_names,
            {
                "dev_loop.describe",
                "dev_loop.plan_test_gate",
                "dev_loop.evaluate_test_gate",
                "dev_loop.classify_failure",
                "dev_loop.plan_self_loop",
            },
        )
        self.assertFalse(any(name.startswith("launcher_") for name in tool_names))

    def test_plan_test_gate_delegates_execution_to_launcher(self) -> None:
        plan = dev_loop.plan_test_gate(
            {
                "suite": "Project.Feature.Smoke+",
                "build": False,
                "required_steps": ["Boot", "FeatureReady"],
                "log_contains": "FEATURETEST",
            }
        )

        self.assertTrue(plan["success"])
        self.assertEqual(plan["execution"]["service"], "ue-editor-mcp-launcher")
        self.assertEqual(plan["execution"]["tool"], "launcher_run_automation")
        self.assertEqual(plan["execution"]["args"]["suite"], "Project.Feature.Smoke+")
        self.assertFalse(plan["execution"]["args"]["build"])
        self.assertEqual(plan["evidence"]["service"], "ue-editor-mcp-logs")
        self.assertEqual(plan["evidence"]["tool"], "unreal.logs.get")
        self.assertEqual(plan["required_steps"], ["Boot", "FeatureReady"])

    def test_plan_test_gate_rejects_shell_like_suite(self) -> None:
        result = dev_loop.plan_test_gate({"suite": "Project.Feature; Quit; open /Game/Map"})
        self.assertFalse(result["success"])
        self.assertIn("suite", result["error"])


class DevLoopEvaluationTests(unittest.TestCase):
    def test_evaluate_passes_when_launcher_done_and_steps_complete(self) -> None:
        result = dev_loop.evaluate_test_gate(
            {
                "launcher_status": {
                    "state": "done",
                    "result": {"outcome": {"passed": 2, "failed": 0, "failures": []}},
                },
                "required_steps": ["Boot", "FeatureReady"],
                "observed_steps": ["FeatureReady", "Boot"],
            }
        )

        self.assertEqual(result["result"], "passed")
        self.assertFalse(result["blocking_reasons"])
        self.assertTrue(result["required_steps"]["complete"])

    def test_evaluate_reports_missing_steps_and_log_errors(self) -> None:
        result = dev_loop.evaluate_test_gate(
            {
                "launcher_status": {"state": "done", "result": {"outcome": {"passed": 1, "failed": 0}}},
                "required_steps": ["Boot", "FeatureReady"],
                "observed_steps": ["Boot"],
                "log_summary": {"error_count": 1},
            }
        )

        self.assertEqual(result["result"], "failed")
        self.assertIn("FeatureReady", result["required_steps"]["missing"])
        self.assertGreaterEqual(len(result["blocking_reasons"]), 2)

    def test_classify_failure_is_project_neutral(self) -> None:
        classification = dev_loop.classify_failure(
            {
                "evaluation": {"blocking_reasons": ["automation reported 1 failed test(s)"]},
                "log_excerpt": "LogAutomationController: Error: failed test",
            }
        )

        self.assertTrue(classification["success"])
        self.assertEqual(classification["failure_class"], "automation_test_failure")
        self.assertTrue(classification["patch_allowed"])


class DevLoopSelfLoopTests(unittest.TestCase):
    def test_self_loop_composes_launcher_and_logs_without_executing(self) -> None:
        plan = dev_loop.plan_self_loop(
            {
                "suite": "Project.Feature.Smoke+",
                "target_files": ["Source/Game/Feature.cpp"],
                "action_sequence": ["run_tests", "collect_logs", "classify_failure", "stop"],
                "max_rounds": 2,
                "dry_run": True,
            }
        )

        self.assertTrue(plan["success"])
        self.assertEqual(plan["max_rounds"], 2)
        self.assertTrue(plan["dry_run"])
        round_actions = plan["rounds"][0]["actions"]
        self.assertEqual(round_actions[0]["service"], "ue-editor-mcp-launcher")
        self.assertEqual(round_actions[0]["tool"], "launcher_run_automation")
        self.assertEqual(round_actions[1]["service"], "ue-editor-mcp-logs")
        self.assertEqual(round_actions[2]["service"], "ue-dev-loop-mcp")
        self.assertIn("does not execute", plan["non_duplicate_boundary"])

    def test_self_loop_rejects_unsafe_action_and_absolute_target(self) -> None:
        bad_action = dev_loop.plan_self_loop(
            {"suite": "Project.Feature.Smoke+", "action_sequence": ["launcher_stop_editor"]}
        )
        self.assertFalse(bad_action["success"])
        self.assertIn("launcher_stop_editor", bad_action["unsafe_actions"])

        bad_target = dev_loop.plan_self_loop(
            {"suite": "Project.Feature.Smoke+", "target_files": ["C:/Project/Source/Game.cpp"]}
        )
        self.assertFalse(bad_target["success"])
        self.assertIn("target_files", bad_target["error"])


if __name__ == "__main__":
    unittest.main()
