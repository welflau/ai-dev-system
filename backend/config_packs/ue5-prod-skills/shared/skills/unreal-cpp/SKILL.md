---
name: unreal-cpp
description: "Unreal Engine C++ workflow for modules, UHT/reflection, Build.cs, engine API verification, diagnostic logging, and build/test validation. Use for C++ code, reflected types, module dependencies, compile/link/UHT errors, or behavior bugs requiring native investigation."
---

# Unreal C++ Skill

## Context

- Repository rules: [`AGENTS.md`](../../../AGENTS.md)
- Related skills: [Editor workflows](../unreal-editor/SKILL.md), [UEEditorMCP](../unreal-mcp/SKILL.md), [Editor restart](../ue-editor-restart/SKILL.md), [Blueprint/Widget MCP](../unreal-blueprint/SKILL.md), [Material MCP](../unreal-material/SKILL.md), [Niagara MCP](../unreal-niagara/SKILL.md), [Python](../unreal-python/SKILL.md)

Use this skill for C++ implementation, reflected types, module dependencies, UHT/build/link failures, native editor extensions, replication, automation tests, or behavior bugs that need source-level diagnosis.

## Risk And Gate

Classify the touched surface before editing. The classification controls validation; it does not justify widening scope.

| Risk | Typical changes | Minimum gate |
|---|---|---|
| Low | `.cpp`-only local logic, null check, bounded algorithm, diagnostic repair | Focused build or test, then diff review |
| Medium | Header/API change without reflection, new native class in an existing module, minimal `.Build.cs` dependency | Full Editor target build, focused test, diff review |
| High | Reflection, UObject lifetime, replication/RPC, GAS, async/threading, serialization, module/plugin architecture, Blueprint-visible API | Full Editor target build, launcher restart when required, focused automation or PIE smoke, fresh review |

Never edit generated files or binary assets as C++ source. Do not modify `Binaries/`, `Intermediate/`, `Saved/`, `DerivedDataCache/`, `*.generated.h`, or `*.gen.cpp`.

## Default Workflow

1. Discover the project shape from `.uproject`, `Source/*/*.Build.cs`, `Plugins/*`, and existing naming. Do not assume module names or test prefixes.
2. Keep Runtime and Editor boundaries strict. Runtime modules must not depend on Editor-only modules; editor tools belong in Editor modules or plugins.
3. For every unfamiliar engine API, verify the symbol with LSP definition/hover first. If LSP is unavailable, resolve `<EngineRoot>/Engine/Source` from `.uproject` and search the engine source read-only.
4. Put reflected types in headers, include `*.generated.h` last, forward declare in headers where possible, and include concrete headers in `.cpp`.
5. Add the smallest needed `.Build.cs` dependency as soon as a cross-module type is used.
6. Build and test through the launcher workflow from `AGENTS.md`; use MCP log tools, not raw `Saved/Logs` reads.

## Engine Source Resolution

Resolve engine source from the target project, never from a hard-coded install path:

1. Read `EngineAssociation` from the workspace `.uproject`.
2. Prefer launcher/editor context or `UE_ENGINE_ROOT` / `UNREAL_ENGINE_ROOT` when present; verify `Engine/Source` exists.
3. On Windows, check `HKLM:\SOFTWARE\EpicGames\Unreal Engine\<EngineAssociation>` `InstalledDirectory`, then `HKCU:\SOFTWARE\Epic Games\Unreal Engine\Builds` for source/custom builds.
4. Fall back to conventional installs only after registry/context lookup.
5. If `<EngineRoot>/Engine/Source` is missing, say local engine source is unavailable and use public docs or reflected metadata instead.

## Coding Rules

- Follow Epic style: PascalCase, UE type prefixes, `b` bool fields, `Out` out params, `int32`/`uint8`, `TEXT()`, braces on all control blocks, tab indentation.
- Use `TObjectPtr` for reflected UObject references in UE5-era code unless local style differs.
- Avoid global `using`; UCLASS/USTRUCT/UENUM cannot live in namespaces.
- Prefer forward declarations and minimal includes; avoid adding umbrella headers to fix missing dependencies.
- Prefer enum/parameter structs over bool flag APIs.
- Reuse existing log categories where practical; Tick logs must be throttled.

## Unreal Lifetime And Execution Rules

- Create default subobjects with `CreateDefaultSubobject`, runtime UObjects with `NewObject`, and actors with `SpawnActor`; never use raw `new`/`delete` for UObjects.
- Keep owned UObject references visible to GC with the project-standard reflected pointer type. Use weak/soft references when ownership or loading semantics require them.
- Keep world-dependent work out of constructors. Use lifecycle hooks such as `BeginPlay`, `OnRegister`, `InitializeComponent`, or subsystem initialization.
- Do not access UObjects from worker threads unless the API explicitly permits it. Return UObject/world work to the game thread and guard delayed callbacks with weak lifetime checks.
- Clear timers, delegates, and subscriptions at the owning lifecycle boundary when callbacks can outlive the receiver.

## Networking And Data Rules

- For replication, state the authority and ownership model before editing. Verify actor/component replication, property registration, `OnRep` signatures, RPC ownership, and dedicated-server behavior.
- Treat GAS owner/avatar selection, prediction, replication mode, attribute replication, and ability-task lifetime as explicit design decisions.
- For SaveGame or serialized data, preserve stable identifiers and version/migration behavior. Do not serialize transient UObject pointers as durable state.
- For GameplayTags, discover the project's real tag source and usages; do not parse `.uasset` files or invent tags from stale examples.

## Diagnostic Logging Loop

Use temporary logs only when static reading cannot establish the runtime cause.

1. Add short `[DIAG-<TaskTag>]` logs at the write/read/fallback points that can explain the mismatch.
2. Reproduce with launcher automation or PIE, then fetch filtered logs with `unreal.logs.get(filter.contains="DIAG-<TaskTag>", filter.minVerbosity="Warning")`.
3. Identify the exact bad state or call site before changing behavior.
4. Fix the root cause, rerun the smallest validation, and remove all `[DIAG-<TaskTag>]` logs before delivery unless the user explicitly wants them kept.

## Root-Cause Guard

Before a bug fix, answer these briefly in your own reasoning:

- Am I changing the source of the behavior rather than masking the symptom?
- Have I checked every write path, read path, and fallback branch involved?
- Which callers/tests can regress?
- Are temporary logs, TODOs, or stopgap branches being cleaned up?

Patch-style mitigation is acceptable only for urgent breakage or third-party/engine bugs the repo cannot fix directly; mark it with `PATCH(<reason>)` and the relevant engine/plugin version.

## Reflection And Restart

Full rebuild + editor restart is required after:

- USTRUCT/UCLASS/UENUM field or metadata changes.
- UFUNCTION/UPROPERTY signature or reflection metadata changes.
- `.Build.cs` dependency changes.
- Adding/removing `.cpp` files or modules.

Live Coding is suitable only for implementation body changes that do not alter reflected layout or module graph.

## Automation Tests

- Put tests in the owning module's `Tests/` directory and guard them with `#if WITH_DEV_AUTOMATION_TESTS`.
- Use project-local naming discovered from existing tests, commonly `<Project>.<Module>.<Subsystem>.<Case>`.
- Prefer in-memory objects; do not read/write production `Content/` assets unless the task is explicitly asset-level.

## Common Failures

| Symptom | First checks |
|---|---|
| Missing `*.generated.h` | Header included by target, generated include is last, reflected macro/body exist. |
| UHT unknown type | Add real include or forward declaration; avoid unsupported template types in reflected signatures. |
| Linker unresolved external | Implementation compiled, module dependency present, symbol exported if cross-module. |
| Runtime object GC issue | Reflected owner uses `UPROPERTY` / `TObjectPtr`; async references are guarded. |
| API guessed wrong | Re-check LSP or engine source and cite the actual declaration. |

## Examples

Load only the matching card. Every example is a pattern, not project truth: replace module names, API paths, ownership choices, and test suites with discovered local values. The build/test commands in examples are subordinate to `AGENTS.md` and the launcher workflow.

Existing project examples:

- [Adding a reflected UObject type](./examples/add-reflected-uobject.md)
- [Simple AActor-derived class](./examples/simple-actor-example.md)
- [USTRUCT and UENUM](./examples/ustruct-and-uenum.md)
- [Delegates and events](./examples/delegates-events.md)
- [Network replication](./examples/network-replication.md)
- [Logging and debugging](./examples/logging-and-debug.md)
- [MVVM status HUD](./examples/mvvm-status-hud.md)
- [Preset + CVar + bounded BFS](./examples/preset-cvar-bounded-bfs.md)

Imported production patterns:

- [Examples index and routing](./examples/00-examples-index.md)
- [Actor component health](./examples/actor-component-health.md)
- [UINTERFACE interaction](./examples/interactable-interface.md)
- [DataAsset-driven weapon configuration](./examples/dataasset-driven-weapon.md)
- [C++ UMG BindWidget](./examples/umg-userwidget.md)
- [PlayerController-owned HUD](./examples/hud-widget-controller.md)
- [Enhanced Input binding](./examples/enhanced-input-binding.md)
- [AIController and Behavior Tree](./examples/ai-controller-behavior.md)
- [Async and timer lifetime](./examples/async-timer-lifetime.md)
- [Build.cs dependency ownership](./examples/buildcs-dependencies.md)
- [Automation test skeleton](./examples/automation-test.md)
- [Animation instance boundary](./examples/animation-instance-boundary.md)
- [CommonUI activatable widget](./examples/commonui-activatable-widget.md)

## Delivery

Report changed files/symbols, Build.cs impact, whether reflection restart is needed, validation run or recommended launcher suite, temporary log status, and any engine API source references used.
