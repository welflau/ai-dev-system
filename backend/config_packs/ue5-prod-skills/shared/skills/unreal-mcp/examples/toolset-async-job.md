# Toolset Asynchronous Job

## Pattern

1. Call `list_toolsets` and select the exact official Toolset.
2. Call `describe_toolset(toolset_name=...)` and select a tool from the returned schema.
3. For a known long operation, call `call_tool(..., wait_seconds=0)`.
4. If the response returns `job_id`, poll `tool_job_status(job_id=...)` until `completed` or `failed`.
5. Consume and summarize the terminal result once; the job is in-memory and may no longer exist after retrieval or bridge restart.

Toolset states are not launcher states. Never poll a Toolset job with `launcher_task_status` or expect `done/cancelled/orphaned`.
