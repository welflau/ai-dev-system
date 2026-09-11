---
name: unreal-mcp
description: "Current UEEditorMCP interface workflow for Actions Registry, official ToolsetRegistry, ue_batch, launcher tasks, logs, asset context, schemas, asynchronous jobs, and mutation verification. Use whenever operating Unreal through MCP or extending the UEEditorMCP bridge."
---

# UEEditorMCP Skill

## Context

- Repository rules: [`AGENTS.md`](../../../AGENTS.md)
- Editor production rules: [Unreal Editor](../unreal-editor/SKILL.md)
- Specialized workflows: [Blueprint](../unreal-blueprint/SKILL.md), [Material](../unreal-material/SKILL.md), [Niagara](../unreal-niagara/SKILL.md), [Python](../unreal-python/SKILL.md), [Restart](../ue-editor-restart/SKILL.md)

This skill defines how to operate the current project bridge. Discover schemas at runtime; action and toolset counts are dynamic and must never be hard-coded as a compatibility claim.

## Capability Model

### Unified bridge

The unified server exposes these stable entry points:

- Health and resources: `ue_ping`, `ue_resources_read`
- Actions Registry: `ue_actions_search`, `ue_actions_schema`, `ue_actions_run`, `ue_batch`
- Official ToolsetRegistry: `list_toolsets`, `describe_toolset`, `call_tool`, `tool_job_status`
- Live ring-buffer logs: `ue_logs_tail`

### Launcher service

- `launcher_start_editor`
- `launcher_run_automation`
- `launcher_stop_editor`
- `launcher_task_status`
- `launcher_task_cancel`

### Asset/log context service

- `unreal.logs.get`
- `unreal.asset_thumbnail.get`
- `unreal.asset_diff.get`
- `unreal.asset_history.get`

These are separate APIs with different schemas. Do not mix `unreal.logs.get` camelCase fields such as `tailLines`, `maxBytes`, `workspaceRoot`, and `minVerbosity` with `ue_logs_tail` fields `n`, `source`, `category`, and `min_verbosity`.

## Routing Decision

1. Use a known typed Action directly when its ID and schema are current.
2. For an unknown Action, call `ue_actions_search`, then `ue_actions_schema`, then execute.
3. Use `ue_batch` for multiple Actions that benefit from one TCP round-trip or cross-step references.
4. Use official ToolsetRegistry for capabilities exposed by UE toolsets rather than the Actions Registry: `list_toolsets` -> `describe_toolset` -> `call_tool`.
5. Use launcher tools for build/start/stop/automation lifecycle. Do not replace them with console commands or shell commands.
6. Use typed Action or typed Toolset before console commands, generic property writes, programmatic orchestration, or Python.

Actions Registry and ToolsetRegistry are independent discovery surfaces. Finding no Action does not prove no Toolset exists, and vice versa.

## Discovery Budget

- If an exact known action is already established, do not search again unless its call fails with a schema/capability error.
- Search with task-specific terms and a bounded result count. Read schemas only for the chosen candidates.
- Toolsets must be listed before description unless a toolset name was returned in the current session. Describe only the relevant toolset.
- Never invent action IDs, tool names, parameters, object paths, node IDs, or pin names.

## Actions And Batch

`ue_actions_run` accepts schema parameters under `params` and returns the Action result. Verify mutations independently.

`ue_batch` rules:

- Maximum 50 Actions; prefer smaller semantic batches.
- Execution is sequential on the editor/game-thread path and is non-atomic. Completed steps are not rolled back when a later step fails.
- Default `continue_on_error=true`; set false when later steps would be unsafe after a failure.
- Default `result_verbosity="compact"`; request full only when diagnosis requires it.
- Cross-step refs may use `{"$ref":"steps[0].field"}` or `$ref:steps[0].field`.
- Top-level protocol success does not mean every sub-action succeeded. Inspect `has_failures`, failed counts, per-step results, and `failures[]`.

Before a write batch, establish exact targets and a readback query. For risky multi-step changes, use one reversible mutation first before batching.

## Toolset Jobs

Call flow: `list_toolsets` -> `describe_toolset` -> `call_tool`.

- `call_tool` requires `toolset_name` and `tool_name`; do not attempt top-level self-dispatch.
- Short calls may return inline. Long calls return a `job_id`; use `tool_job_status` until `completed` or `failed`.
- Use `wait_seconds=0` for known long calls. The default inline wait budget is short and not a completion guarantee.
- Toolset job states are `running|completed|failed`.
- Toolset jobs are in-memory and can disappear after result retrieval or editor/bridge restart. Consume the terminal result once and retain the needed summary in task context.

Do not confuse Toolset jobs with launcher tasks.

## Launcher Tasks

`launcher_start_editor` and `launcher_run_automation` return a task ID immediately. Poll `launcher_task_status` until `done`, `failed`, `cancelled`, or `orphaned`; queued/running are non-terminal.

- Launcher tasks persist under launcher management and may become `orphaned` after service interruption.
- `launcher_task_cancel` requests cancellation. Continue polling until terminal state.
- Cancellation can stop a subprocess but does not undo a partial compile.
- `launcher_stop_editor` is the normal stop path and must not kill an external, non-launcher-managed editor.
- Resolve mode mismatch by stopping the managed editor before starting the requested mode.
- Use interactive mode for Slate, viewport, PIE, RHI, or visual work. Use headless only for non-visual automation.
- Do not call editor-dependent bridge tools until launcher status confirms bridge readiness.

## Logs And Evidence

- Prefer `unreal.logs.get(mode="auto")` for live/saved/offline context and cursor-based incremental reads. Reuse the returned cursor.
- Use `ue_logs_tail` when the connected editor ring buffer is sufficient or Python/bridge logs are needed.
- Use `launcher_task_status` for launcher task logs. Do not directly read `Saved/Logs`, Automation Reports, or `.uemcp/tasks` files.
- Start with category, keyword, verbosity, and bounded lines; widen only if the first query cannot discriminate the cause.
- An Action return, log line, screenshot, compile result, and state readback answer different questions. Use the smallest independent evidence set that proves acceptance.

## Mutation Safety

- Read target state before mutation and read it back afterward through a fresh query.
- Use exact package/object paths and stable IDs returned by discovery.
- Prefer explicit one-package save actions. `editor.save_all`, deletion, rename/move, redirector fixup, bulk edits, project/plugin settings, and arbitrary commands are high risk.
- Use dry-run/plan actions where available and require plan hash/confirmation when the schema provides them.
- Do not directly edit Unreal binary assets or use Python/filesystem access to bypass Action safety boundaries.
- Treat Action capability/risk metadata as hints; repository rules and user approval remain authoritative.

## Extending The Bridge

When no typed Action or Toolset can satisfy the task:

1. Prove the capability gap with bounded search and schema discovery.
2. Choose ownership: project-specific typed Actions belong under the current `Plugins/UEEditorMCP/Python/ue_editor_mcp/registry/actions/` packages with C++ handlers under the plugin Actions directories; official/general UE capabilities may belong in a Toolset plugin.
3. Define a narrow schema, validation, diagnostic errors, readback support, risk/capability metadata, and idempotency behavior before implementation.
4. Add focused C++/Python registry tests as appropriate.
5. Build and restart through launcher before invoking the new capability.

Do not assume legacy single-file registry paths or fixed action counts are current.

## Delivery

Report the exact Action IDs or Toolset tools used, schemas discovered, launcher/toolset job terminal states, batch partial failures, readback evidence, logs/test result, save status, and any capability gap or high-risk operation not performed.

## Examples

- [Examples index](./examples/00-examples-index.md)
- [Discover Actions and Toolsets](./examples/discover-capabilities.md)
- [Non-atomic batch with cross-step refs](./examples/batch-and-readback.md)
- [Launcher automation task](./examples/launcher-automation-task.md)
- [Toolset asynchronous job](./examples/toolset-async-job.md)
- [Cursor-based log diagnosis](./examples/log-cursor-workflow.md)
