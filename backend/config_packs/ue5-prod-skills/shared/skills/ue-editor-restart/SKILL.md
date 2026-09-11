---
name: ue-editor-restart
description: "Generic Unreal editor build/restart workflow using UEEditorMCP launcher tools. Use when reflected C++ changes, module dependency changes, plugin changes, or editor automation require a clean close-build-start-ready loop."
---

# UE Editor Restart Skill

## Context

- Repository rules: [`AGENTS.md`](../../../AGENTS.md)
- Related skills: [C++](../unreal-cpp/SKILL.md), [UEEditorMCP](../unreal-mcp/SKILL.md), [Editor workflows](../unreal-editor/SKILL.md)

Use this skill when a task needs the editor fully restarted after C++ reflection, module, plugin, or generated-code changes.

## Preferred Workflow

1. Discover the project root and `.uproject`; do not hard-code project names, targets, or paths.
2. Stop the editor with `launcher_stop_editor` when a launcher-managed editor is running. Never terminate an external editor through this workflow.
3. Start the editor with `launcher_start_editor(mode="interactive")` for visual/editor work, or `mode="headless"` only for non-visual automation.
4. Poll `launcher_task_status(task_id)` until `done`, `failed`, `cancelled`, or `orphaned`. `queued` and `running` are non-terminal.
5. Proceed with UE MCP calls only when the result indicates the bridge/editor is ready.

`launcher_start_editor` and `launcher_run_automation` return task IDs immediately. `launcher_task_cancel` only requests cancellation; continue polling until terminal state. Cancellation does not roll back a partial build.

## When Restart Is Required

- UCLASS/USTRUCT/UENUM changes.
- UPROPERTY/UFUNCTION type, metadata, or signature changes.
- `.Build.cs`, module, plugin, or target changes.
- New/deleted `.cpp` files.
- Live Coding shadow types or stale reflected fields/functions.

## Automation Gate

For test runs, use `launcher_run_automation(suite="<discovered-suite>+", build=true)` and poll with `launcher_task_status`. Derive suite names from existing tests and project conventions.

## Fallback

Only if launcher tools are unavailable and the user authorizes fallback:

1. Resolve `.uproject`, editor target, engine root, platform, and config from the current workspace.
2. Run the minimal `Build.bat <EditorTarget> Win64 Development <Project.uproject> -waitmutex`.
3. Launch `UnrealEditor.exe <Project.uproject>`.
4. Wait for MCP/editor readiness before continuing.

Do not use fixed paths, fixed project names, or Live Coding as a substitute for a required restart.

## Delivery

Report task id, final launcher state, bridge readiness, build/test result, and any follow-up command that still needs the user's interactive editor.
