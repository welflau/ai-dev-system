# Launcher Automation Task

## Pattern

1. Discover the exact project root and existing test suite/filter.
2. Submit `launcher_run_automation(project_root_hint=..., suite=..., build=true, ...)`.
3. Retain the returned launcher `task_id`.
4. Poll `launcher_task_status(task_id=...)` until `done`, `failed`, `cancelled`, or `orphaned`.
5. Read the structured launcher result and task log summary. On failure, use `unreal.logs.get` with a narrow category/keyword if editor logs are needed.

Do not treat submission as completion. Do not read Automation Reports or launcher task files directly. A cancellation request also requires polling to terminal state.
