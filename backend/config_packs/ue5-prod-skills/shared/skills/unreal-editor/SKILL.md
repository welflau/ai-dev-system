---
name: unreal-editor
description: "Unreal Editor production workflow for live editor state, assets, levels, Blueprint validation, PIE smoke tests, dirty packages, source-control-visible changes, and intentional saving. Use for editor-facing work that spans asset types or needs safe readback and validation."
---

# Unreal Editor Workflow Skill

## Context

- Repository rules: [`AGENTS.md`](../../../AGENTS.md)
- Tool operation: [UEEditorMCP](../unreal-mcp/SKILL.md)
- Related skills: [C++](../unreal-cpp/SKILL.md), [Blueprint/UMG/Input](../unreal-blueprint/SKILL.md), [Material](../unreal-material/SKILL.md), [Niagara](../unreal-niagara/SKILL.md), [Python](../unreal-python/SKILL.md), [Restart](../ue-editor-restart/SKILL.md)

Use this skill for editor state, levels, actors, cross-asset workflows, asset validation, dirty-package discipline, PIE, editor smoke tests, project settings, plugins, references, redirectors, and save decisions. Use the specialized asset skill for graph-specific authoring rules.

## Operating Contract

Editor work must be state-aware, schema-backed, scoped, read back after mutation, compiled or validated where applicable, and saved intentionally.

Never edit `.uasset`, `.umap`, `.uexp`, `.ubulk`, or other Unreal binary packages through filesystem text/byte tools. Use UEEditorMCP, an approved editor API, or a project commandlet reached through the launcher.

## State Gate

Before mutation, inspect only the state relevant to the task:

1. Confirm bridge readiness with `ue_ping`.
2. Confirm project/editor context, current map/world, and PIE state.
3. Inspect the exact target assets, actors, classes, references, or settings.
4. Record unrelated dirty packages or pre-existing modified assets when the available tool exposes them.
5. For Blueprint work, follow the snapshot gate in `unreal-blueprint`.
6. If visual behavior matters, require an interactive editor; headless/NullRHI can validate structure and automation, not pixels.

Do not broadly enumerate the project when a target path or actor is already known.

## Mutation Classes

| Class | Examples | Rule |
|---|---|---|
| Read-only | describe assets, references, actors, current map, logs, source-control diff | Preferred for planning and verification |
| Scoped write | create one asset, set explicit properties, spawn/adjust named actors, compile Blueprint, save one package | Allowed after schema and target validation |
| High risk | delete, rename/move, redirector fixup, bulk edit, save all, project/plugin settings, level replacement | Require explicit scope, preflight/readback, rollback plan, and user approval when destructive |

Use dry-run or planning actions when available. Asset renames should use `editor.plan_asset_renames` or a manifest plan before the apply action. Never infer that a write is safe from an action's capability tag alone.

## Asset And Level Rules

- Use exact long package paths. Prefer `/Game/...`; modify plugin content only when explicitly in scope; never modify `/Engine/...` assets.
- Check existence before creation and use the action's `if_exists` policy deliberately. Do not overwrite production assets by default.
- Query references before rename/move/delete. Verify destination conflicts, redirectors, dependent Blueprints, and source-control state afterward.
- Before level changes, confirm current map, PIE state, World Partition/streaming/data-layer ownership, and the intended level.
- After actor changes, read back actor identity, world/level, transform, components, mobility, collision, visibility, and relevant properties.
- Preserve user selection and untouched graph/layout regions unless the operation requires changing them.

## Compile And Validation

After each meaningful mutation batch:

1. Read back through an independent query or fresh description.
2. Compile the touched Blueprint, Widget, Material, Niagara system, or other compilable asset.
3. Inspect structured diagnostics first; use filtered MCP logs for supporting evidence.
4. Run focused automation through `launcher_run_automation` when deterministic tests exist.
5. Use PIE for behavior that depends on runtime/editor world state. Poll `editor.get_pie_state`; stop PIE cleanly and check relevant logs.
6. Use screenshot or Slate inspection only when visual/UI state is part of acceptance. A screenshot is evidence, not a substitute for structural checks.

Do not claim a mutation succeeded solely because an MCP call returned `success=true`.

## Save Discipline

- Save only explicitly changed and validated packages. Prefer `editor.save_loaded_asset` for a known asset.
- `editor.save_all` is high risk because it includes unrelated dirty assets and levels. Use it only when the user explicitly requests that scope and the dirty set is understood.
- Do not save a Blueprint after failed compilation unless the user explicitly requests an intermediate broken state.
- Report created, modified, saved, unsaved, and pre-existing dirty assets separately.

## Plugin And Settings Changes

Treat plugin, module, project setting, GameplayTag source, packaging, and cook changes as high risk. Determine runtime/editor ownership, team and CI impact, restart requirement, config source, and rollback before mutation. Build and restart through launcher after module/plugin/reflection changes.

## Delivery

Report editor mode and map context, exact changed assets/actors/settings, readback and compile results, automation/PIE/visual evidence, save status, unrelated dirty state, and remaining risks.

## Examples

- [Examples index](./examples/00-examples-index.md)
- [Blueprint compile validation](./examples/blueprint-compile-validation.md)
- [Map and PIE smoke test](./examples/map-pie-smoke-test.md)
- [Asset rename and redirector preflight](./examples/asset-rename-preflight.md)
