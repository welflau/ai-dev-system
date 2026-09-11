from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from . import dev_loop

logger = logging.getLogger(__name__)


TOOLS = [
    Tool(
        name="dev_loop.describe",
        description=(
            "Describe the ue-dev-loop-mcp boundary and show which adjacent MCP service owns "
            "launcher, log, and editor execution. Use this before wiring a self-loop so tools "
            "do not duplicate ue-editor-mcp-launcher."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="dev_loop.plan_test_gate",
        description=(
            "Create a project-neutral Automation test gate plan. This does not run tests; "
            "it returns the exact ue-editor-mcp-launcher and logs service calls to make."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "suite": {"type": "string", "description": "UE Automation suite name, e.g. P111.LJC+ or Project.Module.Case"},
                "build": {"type": "boolean", "description": "Whether launcher_run_automation should build first (default true)."},
                "timeout_sec": {"type": "integer"},
                "build_timeout_sec": {"type": "integer"},
                "project_root_hint": {"type": "string"},
                "required_steps": {"type": "array", "items": {"type": "string"}},
                "log_contains": {"type": "string", "description": "Optional token/filter hint for unreal.logs.get."},
                "min_verbosity": {"type": "string", "enum": ["Verbose", "Log", "Warning", "Error", "Fatal"]},
            },
            "required": ["suite"],
        },
    ),
    Tool(
        name="dev_loop.evaluate_test_gate",
        description=(
            "Evaluate launcher/log/evidence summaries for a planned test gate and return "
            "passed/failed/incomplete plus blocking reasons. This does not read logs itself."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "launcher_status": {"type": "object", "additionalProperties": True},
                "launcher_result": {"type": "object", "additionalProperties": True},
                "required_steps": {"type": "array", "items": {"type": "string"}},
                "observed_steps": {"type": "array", "items": {"type": "string"}},
                "log_summary": {"type": "object", "additionalProperties": True},
                "screenshot_summary": {"type": "object", "additionalProperties": True},
                "require_visual": {"type": "boolean"},
            },
        },
    ),
    Tool(
        name="dev_loop.classify_failure",
        description=(
            "Classify a generic dev-loop failure from evaluation, launcher status, and log "
            "summaries. Classification is heuristic and project-neutral."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "evaluation": {"type": "object", "additionalProperties": True},
                "launcher_status": {"type": "object", "additionalProperties": True},
                "log_summary": {"type": "object", "additionalProperties": True},
                "log_excerpt": {"type": "string"},
            },
        },
    ),
    Tool(
        name="dev_loop.plan_self_loop",
        description=(
            "Create a bounded project-neutral self-loop contract that composes existing "
            "launcher/log/editor MCP tools. This service does not execute or mutate files."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "suite": {"type": "string"},
                "target_files": {"type": "array", "items": {"type": "string"}},
                "action_sequence": {"type": "array", "items": {"type": "string"}},
                "max_rounds": {"type": "integer", "minimum": 1, "maximum": dev_loop.MAX_SELF_LOOP_ROUNDS},
                "max_failed_gates": {"type": "integer", "minimum": 0},
                "dry_run": {"type": "boolean", "default": True},
                "stop_on_success": {"type": "boolean", "default": True},
                "build": {"type": "boolean", "default": True},
                "timeout_sec": {"type": "integer"},
                "build_timeout_sec": {"type": "integer"},
                "project_root_hint": {"type": "string"},
            },
            "required": ["suite"],
        },
    ),
]


_HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "dev_loop.describe": lambda _args: dev_loop.describe_service(),
    "dev_loop.plan_test_gate": dev_loop.plan_test_gate,
    "dev_loop.evaluate_test_gate": dev_loop.evaluate_test_gate,
    "dev_loop.classify_failure": dev_loop.classify_failure,
    "dev_loop.plan_self_loop": dev_loop.plan_self_loop,
}

server = Server(dev_loop.SERVICE_NAME)


def _json_text(data: dict[str, Any]) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name == "dev_loop.ping":
        return _json_text({"success": True, "pong": True, "service": dev_loop.SERVICE_NAME})

    handler = _HANDLERS.get(name)
    if handler is None:
        return _json_text({"success": False, "error": f"Unknown tool: {name}"})

    try:
        return _json_text(handler(arguments or {}))
    except Exception as exc:
        logger.exception("%s failed", name)
        return _json_text({"success": False, "error": str(exc), "tool": name})


async def _run() -> None:
    logger.info("Starting %s (planner/evaluator only; no UE connection required)", dev_loop.SERVICE_NAME)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        logger.info("%s stopped by user", dev_loop.SERVICE_NAME)


if __name__ == "__main__":
    main()
