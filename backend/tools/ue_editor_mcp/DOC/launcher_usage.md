# UEEditorMCP — Launcher Server

> **What it is**: a third MCP server (`ue-editor-mcp-launcher`) shipped together with
> UEEditorMCP. Unlike the other two servers, the launcher operates **outside** the
> running editor — it can build, spawn, kill, and run-tests against UE while the
> editor is **not** alive (or while it is, with appropriate guards).

This document is **project-agnostic**. Any UE 5.x project that drops UEEditorMCP into
`Plugins/` gets the launcher capabilities for free.

---

## 1. Zero-config first run

After cloning a project that ships UEEditorMCP, the user only needs to run the
existing one-shot setup:

```powershell
cd <ProjectRoot>/Plugins/UEEditorMCP
./setup_mcp.ps1
```

This will:

1. Locate the engine python (5-tier probe: `-EngineRoot` arg → `.uproject`
   `EngineAssociation` registry → `.code-workspace` folders → `UE_ENGINE_DIR` env
   → disk scan).
2. Create a venv under `Plugins/UEEditorMCP/Python/.venv`.
3. Install `mcp` + `psutil` (online or vendored offline).
4. Generate `<ProjectRoot>/.vscode/mcp.json` with **three** servers:
   - `ue-editor-mcp` (in-editor actions, port 55558)
   - `ue-editor-mcp-logs` (offline log reader)
   - `ue-editor-mcp-launcher` *(new)*

That's it. **No fields to fill in.** The first time any `launcher_*` tool is
called, the launcher's `load_config()` auto-detects the project and writes
`<ProjectRoot>/.uemcp/launcher.json`. From that point on every member of the team
gets the same behaviour without manual edits.

The auto-generated file looks like this for a project named `MyGame`:

```jsonc
{
  "schema_version": 1,
  "project": {
    "project_root":   "D:/Git/MyGame",
    "uproject_path":  "D:/Git/MyGame/MyGame.uproject",
    "project_name":   "MyGame",
    "engine_root":    "E:/EpicGame/UE_5.7",
    "engine_association": "5.7",
    "target_name":    "MyGameEditor"
  },
  "build_target_suffix": "Editor",
  "build_platform": "Win64",
  "build_config": "Development",
  "test_suite_prefix": null,        // set to e.g. "MyGame." to harden RunTests
  "process_timeout_sec": 1800,
  "log_tail_root": "Saved/Logs",
  "report_root": "Saved/Automation/Reports",
  "allow_gui_launch": true,         // DEPRECATED (2026-06-05): kept for back-compat, no longer enforced
  "bridge_host": "127.0.0.1",
  "bridge_port": 55558,
  "auto_generated": true,
  "discovery_notes": [ ... ]
}
```

Editing the file is optional. Recommended tweaks:

- `test_suite_prefix`: lock automation to your project's namespace (e.g. `"P111."`).
- `allow_gui_launch`: **DEPRECATED** (2026-06-05). Previously gated `mode="interactive"`; the launcher now treats GUI launch as a normal capability and the field is ignored. Kept in the schema only so existing `.uemcp/launcher.json` files keep loading.

To force a fresh re-detect, delete `.uemcp/launcher.json` (or call the hidden helper `launcher_reset_config` directly via `handle_tool(...)`).

> The launcher **does not** persist absolute paths into source control — `.uemcp/`
> is added to the project's `.gitignore` so each developer keeps their own
> machine-local config.

---

## 2. Tool catalogue

### 2.1 LLM-visible tools (3, all prefixed `launcher_`)

> 2026-06-05 simplification: the LLM-visible surface deliberately collapsed from 8 tools
> to 3. Build, process self-check, and bridge-readiness wait are now folded into the
> 3 action tools so an agent never has to chain 4 calls to do one logical thing.

| Tool | Purpose | Internally |
|------|---------|-----------|
| `launcher_start_editor` | Launch UE and block until it can take MCP calls | (1) optional UBT build (`build=true` by default) → (2) process self-check (managed-same-mode reuse / managed-different-mode → `error=mode_mismatch` / external-only → `status=already_running_external` no-op) → (3) spawn `-Cmd` (headless, default) or `UnrealEditor.exe` (interactive) → (4) optional MCPBridge readiness wait (`wait_ready=true`, default 120 s) |
| `launcher_stop_editor` | Stop launcher-managed editors | Auto-detect: no editor → `status=already_stopped`; only external editors and `force_kill_external` not set → `status=external_only` (no-op); otherwise terminate every managed PID. |
| `launcher_run_automation` | Headless RunTests + report parse | (1) optional UBT build (`build=true` by default) → (2) preflight refuses to run while any UE is alive (`.uproject` mutex protection) → (3) spawn `UnrealEditor-Cmd` with the validated `Automation RunTests <suite>; Quit` template → (4) parse `index.json` and return `{passed, failed, skipped, failures[]}`. |

### 2.2 Hidden helpers (still callable via `handle_tool(...)`, not in `list_tools()`)

These exist for setup scripts, regression tests, and human troubleshooting. They
are intentionally NOT advertised to the LLM so the agent surface stays focused
on the 3 action tools above.

| Helper | What it does |
|--------|--------------|
| `launcher_ping`              | Liveness probe for the launcher server itself. |
| `launcher_get_config`        | Inspect detected/persisted config. |
| `launcher_reset_config`      | Delete `.uemcp/launcher.json` to force a fresh re-detect. |
| `launcher_is_editor_running` | Probe for any UnrealEditor* process on the box. |
| `launcher_build_editor`      | Run UBT directly (folded into `launcher_start_editor` / `launcher_run_automation` for the LLM). |
| `launcher_wait_until_ready`  | Poll the MCPBridge TCP port (folded into `launcher_start_editor`). |

### Safety model (the launcher cannot be talked into doing more than this)

1. **Binary allowlist** — only `Build.bat`/`Build.sh`, `UnrealEditor-Cmd[.exe]`,
   and `UnrealEditor[.exe]` may ever be spawned.
2. **Argument allowlist** — `target` matches `^[A-Za-z][\w]*Editor$`,
   `platform ∈ {Win64,Mac,Linux}`, `config ∈ {Debug,DebugGame,Development,Shipping,Test}`.
3. **`-ExecCmds` template** — exactly `Automation RunTests <suite>; Quit`. Anything
   else (extra `;`, `open`, `travel`, `restart`, `quit`, `..\\`, …) is rejected
   before the process is even forked.
4. **Suite prefix policy** — when `test_suite_prefix` is set, every suite name
   must start with it. Otherwise no project-namespace constraint.
5. **GUI launch** — `mode="interactive"` is freely available; pick it when the
   scenario truly needs Slate/RHI/PIE (the LLM/user judges per case). The old
   `allow_gui_launch` hard-gate has been removed (2026-06-05).
6. **Process registry** — `launcher_stop_editor` only kills processes this server
   started, unless `force_kill_external=true` is explicitly supplied by the caller.
7. **Mode tagging** — every spawned editor PID is tagged with its launch mode
   (`headless` / `interactive`); `launcher_start_editor` uses the tag to decide
   between reuse, `already_running_managed`, and `error=mode_mismatch`.

---

## 3. Typical end-to-end loops

### A. Auto-test loop (UE NOT running)

```text
1. launcher_run_automation suite="P111.LJC+"
   - internally: build (if build=true, default) → preflight → headless RunTests → parse index.json
   - returns {success, outcome:{passed, failed, skipped, failures[]}, build:{...}}
2. (failed) ue-editor-mcp-logs.unreal.logs.get
   → grep for the suite name + "FAIL"
3. agent edits code → loop back to step 1.
```

### B. GUI / Slate-dependent loop

```text
1. launcher_start_editor mode="interactive"
   - internally: build → process self-check → spawn GUI → wait for MCPBridge
   - returns {status:"started"|"already_running_managed"|"already_running_external", pid, bridge_ready}
   - if status=="already_running_external" the editor was started outside this server
     (e.g. an IDE F5 debug session). DO NOT force-stop it; ask the user instead.
2. ue_ping → ue_actions_run editor.is_ready → ... business actions ...
3. launcher_stop_editor
   - returns {status:"stopped"|"already_stopped"|"external_only"}
```

### C. Hot-reload loop (UE already running, our managed instance)

```text
1. launcher_start_editor mode="headless" (or "interactive")
   - returns status="already_running_managed" if an instance with the same mode
     is already alive; pid is reused without spawning a second one.
2. ue_actions_run editor.live_coding_compile {}
     - Fire-and-forget: returns immediately with compile_started=true.
     - DO NOT pass wait_for_completion=true — it is now ignored (was a
       GameThread self-deadlock; see Troubleshooting).
3. Poll until done:
     loop every 1–2s:
         ue_actions_run editor.live_coding_status {}
         break when compile_in_progress == false
4. business actions ...
```

---

## 4. New companion C++ actions (Live Coding)

| Action ID                      | Description |
|-------------------------------|-------------|
| `editor.live_coding_compile`  | Trigger Quick Compile via `ILiveCodingModule::Compile()`. **Fire-and-forget** — always returns immediately. The legacy `wait_for_completion` / `timeout_seconds` parameters are accepted for backward compatibility but ignored (and a `deprecation_warning` is included in the response when set). Poll `editor.live_coding_status` until `compile_in_progress=false` instead. |
| `editor.live_coding_status`   | Read-only: `module_loaded` / `enabled` / `compile_in_progress` / `can_enable_for_session`. Cheap; safe to poll at 1–2 Hz. |

These live in the regular `ue-editor-mcp` server (they need to run inside the
editor). The launcher complements them by handling the cases LiveCoding can't:
full rebuilds, restarts, and headless test runs.

---

## 5. Troubleshooting

| Symptom | Diagnosis |
|---------|-----------|
| `launcher_start_editor` returns `status="already_running_external"` | An UnrealEditor process is alive but was NOT spawned by this launcher (typical: user pressed F5 in their IDE). The launcher refuses to touch it. Tell the user, do **not** force-stop. |
| `launcher_start_editor` returns `error="mode_mismatch"` | A managed editor with the **other** mode is alive (e.g. headless running but you asked for interactive). Call `launcher_stop_editor` first, then retry. |
| `launcher_start_editor` returns `status="build_failed"` | UBT compile failed before the spawn step. Inspect `build.errors[]` in the response, fix the code, retry. To skip rebuild on the next call use `build=false`. |
| `launcher_start_editor` returns `bridge_ready=false` with a warning | Editor process spawned but MCPBridge did not accept TCP within `wait_timeout_sec`. Check `Saved/Logs/<Project>.log`; the editor may still be cooking shaders / loading plugins. |
| `handle_tool("launcher_get_config", ...)` returns `success:false, error:"could not auto-detect project"` | No `*.uproject` reachable from the launcher's CWD. Pass `project_root_hint` explicitly or run the server with the project root as CWD. |
| `engine_root: null` in the config | None of the 5 probes hit. Edit `.uemcp/launcher.json` and set `engine_root` to your UE install (the dir containing `Engine/`). |
| `launcher_run_automation` errors with `Cannot run headless tests while UnrealEditor is running` | Close the IDE-launched editor or call `launcher_stop_editor` first. Do **not** `force_kill_external=true` casually — it will SIGKILL any editor you started elsewhere. |
| `editor.live_coding_compile` returns `live_coding_unavailable` | The editor was launched without Live Coding support, or the LiveCoding module failed to load. Pass `build=true` to `launcher_start_editor` for a clean full rebuild path. |
| `editor.live_coding_compile` response carries `deprecation_warning` about `wait_for_completion` | Caller still passes the legacy `wait_for_completion=true`. The action is now strictly fire-and-forget (waiting on GameThread would deadlock LiveCoding). Drop the parameter and poll `editor.live_coding_status` until `compile_in_progress=false`. |
| Editor UI freezes for ~120s right after `editor.live_coding_compile` | You are on an old build that still had the GameThread spin-wait. Rebuild the `UEEditorMCP` plugin with the 2026-06-05 fix; the action now never blocks. |
