---
name: unreal-niagara
description: "Workflow for authoring, tuning, diagnosing, and validating Unreal Engine Niagara VFX through UEEditorMCP. Use for Niagara systems, emitters, renderers, module inputs, static switches, Data Channels, compile diagnostics, and visual preview validation."
---

# Unreal Niagara MCP Skill

## Context

- Repository rules: [`AGENTS.md`](../../../AGENTS.md)
- Related skills: [Editor workflows](../unreal-editor/SKILL.md), [UEEditorMCP](../unreal-mcp/SKILL.md), [Blueprint/Widget](../unreal-blueprint/SKILL.md), [Material](../unreal-material/SKILL.md), [C++](../unreal-cpp/SKILL.md)
- Examples load on demand: [paper-dust-falling](./examples/paper-dust-falling.md), [ndc-gameplayburst-damage-text](./examples/ndc-gameplayburst-damage-text.md)

Use this skill for creating, duplicating, repairing, tuning, previewing, and saving Niagara systems. Do not use it for gameplay-side spawning code, Blueprint graph logic, UMG, or Material graph authoring.

## Preconditions

1. Confirm editor connectivity with `ue_ping`.
2. Use an interactive editor session for visual VFX validation; headless `-nullrhi` cannot validate real rendering, GPU collision, or viewport behavior.
3. For unknown actions, run `ue_actions_search("niagara")` then `ue_actions_schema(action_id=...)`.
4. Use `ue_batch` for dependent edits and compact results unless diagnosing failures.
5. Resolve engine source from `.uproject` before investigating native Niagara implementation details.

## Safe Workflow

1. Inspect: `niagara.get_system_summary`, `niagara.get_module_inputs`, `niagara.find_scripts`, and renderer summaries when available.
2. Scope: preserve user-named existing systems and patch in place. Create/duplicate only for new assets, probes, or explicit replacement.
3. Render: set mesh/material/bindings before fine tuning.
4. Tune: edit module inputs, emitter properties, static switches, and renderer properties.
5. Validate: `niagara.get_compile_diagnostics(refresh_compile=true, wait=true)`.
6. Preview: use Niagara preview timeline for visual checks; spawn into a level only when requested, then clean up temporary actors.
7. Save: call `editor.save_loaded_asset` for the explicit validated system. Use `editor.save_all` only with user-approved all-dirty-package scope.

## Core Read Actions

| Action | Use |
|---|---|
| `niagara.get_compile_diagnostics` | Authoritative compile status; inspect `events[]` and `stack_issues[]`. |
| `niagara.get_module_inputs` | Real module/input names, hidden inputs, override pins, bindings, stale overrides. |
| `niagara.get_system_summary` | System path, emitters, parameters, quick inventory. |
| `niagara.find_scripts` | Resolve module scripts with narrow `path` / `name_filter`. |
| `niagara.get_script_digest` | Script metadata when usage or module path is uncertain. |

## Core Write Actions

| Action | Use |
|---|---|
| `niagara.create_system` | Create/duplicate systems; use `template_system_path` and explicit `if_exists`. |
| `niagara.set_module_input` | Scalar/vector/bool rapid-iteration values. |
| `niagara.set_module_input_binding` | Bind inputs to parameters, particle attributes, engine values, or dynamic expressions. |
| `niagara.set_module_enabled` | Toggle modules; prefer tuning to near-zero when disabling risks stage imbalance. |
| `niagara.set_module_static_int` | Static switches and enum-like settings such as GPU collision type. |
| `niagara.set_emitter_property` | `SimTarget`, local space, determinism, persistent IDs, and other reflected properties. |
| `niagara.set_renderer_mesh/material/binding` | Renderer assets, overrides, attribute bindings. |
| `niagara.add_module/add_renderer/add_emitter` | Add only after proving the target is absent or composition is intended. |

## Parameter Conventions

- `stage`: `system_spawn`, `system_update`, `emitter_spawn`, `emitter_update`, `particle_spawn`, `particle_update`.
- `module_name`: stack display name, e.g. `SpawnRate`, `Collision`, `GravityForce`.
- `input_name`: module input display name, e.g. `SpawnRate`, `Box Size`.
- `value_type`: `float`, `int`, `bool`, `vec2`, `vec3`, `vec4`, `color`; vectors/colors use numeric arrays.

## Production Rules

- Never duplicate a Collision module just to change collision behavior; inspect and tune the existing module.
- Collision must run before the solver that consumes collision response in the same effective simulation step.
- CPU collision uses trace channels; GPU collision depends on scene depth or mesh distance fields and project settings.
- Many templates contain multiple shape modules; inspect all shape modules before changing emission area.
- Unexpected `has_override_pin=true` or `override_unlinked` means inspect pins/order before resetting or replacing anything.
- Data Channel systems require runtime proof beyond compile success. Preserve reader modules, current-frame flags, auto-link behavior, and emitter-id bindings unless a before/after probe proves they are wrong.

## Validation Contract

- Always run `niagara.get_compile_diagnostics(refresh_compile=true, wait=true)` after a meaningful edit batch.
- Read error display text instead of guessing.
- If diagnostics pass but viewport behavior is wrong, inspect module inputs and run interactive preview.
- For logs, use `unreal.logs.get(filter.category="LogNiagara", filter.minVerbosity="Warning")`.

## Extending MCP

Niagara handlers, when this plugin exists, usually live under `Plugins/UEEditorMCP/Source/UEEditorMCP/{Public,Private}/Actions/` and registry schemas under `Plugins/UEEditorMCP/Python/ue_editor_mcp/registry/actions/`. Verify paths in the current repository before editing.

Add/adjust schema, implement the C++ handler if needed, register it, rebuild/restart through launcher MCP, then use the new action.

## Delivery

Report changed system path, emitters/modules/renderers touched, compile diagnostics, preview method, saved status, and any manual visual validation that remains.
