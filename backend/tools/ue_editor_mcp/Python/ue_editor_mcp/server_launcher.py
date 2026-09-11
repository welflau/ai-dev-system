"""
UE Editor MCP — Launcher sub-server.

This MCP server is INTENTIONALLY decoupled from the running editor: it must
keep working even when no UnrealEditor process is alive (in fact, that is its
whole reason to exist). So unlike server_unified / server_unreal_logs, this
file does NOT connect to MCPBridge on startup.

LLM-visible tool surface (5 tools, 2026-06-05 async refactor):
    launcher_start_editor      — submits async build+spawn+wait task
    launcher_run_automation    — submits async build+headless-runtests task
    launcher_stop_editor       — synchronous stop (fast, < 5s)
    launcher_task_status       — poll a task by id (state/stages/log_tail)
    launcher_task_cancel       — request cancel of a running task

Hidden helpers still reachable via call_tool() (used by setup scripts and
regression tests; intentionally NOT in list_tools()):
    launcher_ping / launcher_get_config / launcher_reset_config /
    launcher_is_editor_running / launcher_build_editor / launcher_wait_until_ready /
    launcher_run_automation_sync (legacy synchronous variant)

First-run UX: when ANY tool is invoked for the first time inside a fresh
checkout, load_config() auto-discovers project_root + uproject + engine_root
and writes <ProjectRoot>/.uemcp/launcher.json so subsequent runs are zero-conf.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from ue_editor_mcp.launcher import tools as launcher_tools
from ue_editor_mcp.launcher.config import load_config

logger = logging.getLogger(__name__)

server = Server("ue-editor-mcp-launcher")


@server.list_tools()
async def list_tools() -> list[Tool]:
    # LLM-visible surface (5 tools): the 3 action submitters
    # (start_editor / stop_editor / run_automation) plus the 2 task-pool
    # helpers (task_status / task_cancel). launcher_ping stays reachable
    # via call_tool() as a liveness probe for setup scripts and IDE
    # wiring tests, but is not advertised in the tool list to keep the
    # agent surface focused.
    return list(launcher_tools.get_tools())


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name == "launcher_ping":
        return [TextContent(type="text", text=json.dumps({"success": True, "pong": True}))]
    return await launcher_tools.handle_tool(name, arguments or {})


async def _run() -> None:
    logger.info("Starting ue-editor-mcp-launcher (no UE connection required)…")

    # Best-effort warm load: surface auto-detect notes immediately in the
    # server log on first run, so users see what was generated without
    # needing to call launcher_get_config.
    project_root: "Path | None" = None
    try:
        cfg, notes = load_config()
        for n in notes:
            logger.info("[launcher.config] %s", n)
        if cfg:
            logger.info("[launcher.config] project=%s engine_root=%s",
                        cfg.project.project_name, cfg.project.engine_root)
            from pathlib import Path  # local import to keep top section minimal
            project_root = Path(cfg.project.project_root)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[launcher.config] warm-load failed: %s", exc)

    # ── Async task store: recover any orphaned tasks from the previous
    #    server process. Persistence layout:
    #    <project_root>/.uemcp/tasks/<task_id>.json (+ .log)
    if project_root is not None:
        try:
            from ue_editor_mcp.launcher.tasks import get_store
            store = get_store(project_root)
            recovered = store.recover_orphans()
            if recovered:
                logger.warning(
                    "[launcher.tasks] recovered %d orphaned task(s) from previous "
                    "session: %s", len(recovered), ", ".join(recovered),
                )
            # opportunistic GC of terminal tasks older than retention window
            deleted = store.gc()
            if deleted:
                logger.info("[launcher.tasks] gc'd %d expired terminal task(s)", deleted)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[launcher.tasks] recovery failed: %s", exc)

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
        logger.info("ue-editor-mcp-launcher stopped by user")


if __name__ == "__main__":
    main()
