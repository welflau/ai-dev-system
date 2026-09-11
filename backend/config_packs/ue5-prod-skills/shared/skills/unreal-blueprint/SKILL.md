---
name: unreal-blueprint
description: "Workflow for generating and editing Unreal Engine Blueprint, Widget, Input, and related editor assets through UEEditorMCP. Use for asset creation, graph edits, UMG/MVVM setup, layout/comment cleanup, compile diagnostics, and MCP action extension decisions."
---

# Unreal Blueprint And Asset MCP Skill

## Context

- Repository rules: [`AGENTS.md`](../../../AGENTS.md)
- Related skills: [Editor workflows](../unreal-editor/SKILL.md), [UEEditorMCP](../unreal-mcp/SKILL.md), [C++](../unreal-cpp/SKILL.md), [Material](../unreal-material/SKILL.md), [Niagara](../unreal-niagara/SKILL.md), [Python](../unreal-python/SKILL.md)

Use this skill for Blueprint, Widget Blueprint, Enhanced Input assets, editor asset wiring, UMG/MVVM setup, and graph refactoring through UEEditorMCP.

Use the specialized skill instead when the task is primarily Material, Niagara, or native C++.

## Preconditions

1. Confirm editor connectivity with `ue_ping`.
2. If editor state matters, call `ue_actions_run("editor.is_ready", {})`.
3. Follow `unreal-mcp` routing: use known typed Actions directly; for unknown Actions use search then schema; consider official Toolsets when no matching Action exists.
4. If native behavior is unclear, resolve engine source from `.uproject` as described in `AGENTS.md` and cite the actual source line.

## Required Workflow

1. Decompose the request into assets, components, variables, graphs, widgets, input bindings, dependencies, and validation steps.
2. Check capability. If a required MCP action is missing, describe the gap and ask before extending the MCP.
3. Create or modify assets in dependency order: assets -> components/widgets -> variables -> nodes -> wires -> defaults -> layout/comment -> compile.
4. Validate after each meaningful graph batch with scoped layout, comments, compile, and targeted introspection.
5. Save only when compile/validation results are acceptable or the user explicitly wants an intermediate asset saved.

## Blueprint Snapshot Gate

- Existing Blueprint: call `blueprint.describe_full` once before the first edit.
- New Blueprint: create, compile once, then call `blueprint.describe_full` as the baseline.
- Re-run the snapshot only when switching target Blueprint or when a failed action indicates state drift.

This prevents editing against stale graph IDs, pins, components, or function signatures.

## Token And Request Discipline

- Prefer `ue_batch` with compact results and cross-step `$ref` values for dependent edits.
- Prefer `graph.validate_patch` + `graph.apply_patch` for multi-node graph edits.
- Use narrow `editor.list_assets` filters and bounded `max_results`.
- Prefer targeted reads (`graph.get_node_pins`, `graph.find_nodes`, `widget.get_tree`, `blueprint.get_summary`) over broad graph dumps.
- Retry a failed action at most twice with new information; then switch strategy or report the missing capability.

## Idempotent Asset Creation

Actions such as `blueprint.create`, `material.create`, and `niagara.create_system` may support `if_exists`:

- `error`: fail if the asset exists.
- `overwrite`: recreate cleanly for deterministic reruns.
- `skip` / `reuse`: keep the existing asset and continue.

Use `overwrite` for disposable generated assets, and `reuse` only when preserving existing work is intentional.

## Layout And Comments

- Use the smallest valid layout scope: selected nodes or affected subtree first; graph/all only for explicit graph-wide edits.
- Layout before comments. Comment nodes do not reliably follow later auto-layout.
- Prefer `graph.auto_comment` with node IDs; use `graph.add_comment` only when exact manual placement is required.
- Keep generated comment labels concise. Match the repository language/style; if no local convention exists, Chinese labels are acceptable for this workspace.
- Do not disturb untouched graph regions just to make the whole graph look uniform.

## Core Action Groups

Discover exact schemas at runtime. Common action families include:

| Area | Actions |
|---|---|
| Blueprint | `blueprint.create`, `blueprint.compile`, `blueprint.describe_full`, `blueprint.add_component`, `blueprint.set_parent_class`, `blueprint.add_interface` |
| Variables | `variable.create`, `variable.set_default`, `variable.rename`, `variable.delete`, `variable.add_getter`, `variable.add_setter`, `variable.add_local` |
| Nodes | `node.add_event`, `node.add_custom_event`, `node.add_function_call`, `node.add_branch`, `node.add_macro`, `node.add_cast`, `node.set_pin_default` |
| Graph | `graph.connect_nodes`, `graph.find_nodes`, `graph.get_node_pins`, `graph.apply_patch`, `graph.validate_patch`, `graph.auto_comment`, `layout.auto_selected`, `layout.auto_subtree` |
| Refactor | `graph.set_selected_nodes`, `graph.collapse_selection_to_function`, `graph.collapse_selection_to_macro`, `function.rename`, `macro.rename`, `graph.export_nodes`, `graph.import_nodes` |
| UMG/MVVM | `widget.create`, `widget.add_component`, `widget.reparent`, `widget.set_properties`, `widget.get_tree`, `widget.mvvm_add_viewmodel`, `widget.mvvm_add_binding` |
| Input | `input.create_action`, `input.create_mapping_context`, `input.add_key_mapping` |
| Editor | `editor.list_assets`, `editor.save_loaded_asset`, `editor.get_actors`, `editor.spawn_actor`, `editor.focus_viewport` |

## Pin And Class Checks

- Do not guess exact pin names after failures; inspect with `graph.get_node_pins`.
- Use fully-qualified `/Script/...` class paths when simple names fail or ambiguity exists.
- Object default values should use full asset object paths such as `/Game/Path/Asset.Asset`.
- For UE5 math nodes, verify function names against the current engine/source or action schema instead of relying on older `_FloatFloat` names.

## UMG And MVVM Notes

- Build the widget tree before binding events or MVVM destinations.
- Compile the ViewModel C++ class before associating it with a Widget Blueprint.
- For runtime widgets, store created widget references in reflected variables when lifetime matters.
- Validate with `widget.get_tree`, compile results, and Blueprint log diagnostics.

## Cross-Graph Refactor Pattern

When moving event-graph logic into a function:

1. `blueprint.describe_full`
2. Locate downstream nodes with `graph.describe_enhanced` or targeted find calls.
3. Prefer `graph.collapse_selection_to_function` for a contiguous chain.
4. Use `graph.export_nodes` / `graph.import_nodes` only when a custom target graph or signature is required.
5. Rename the function/macro to its final intent-driven name.
6. Rewire delegates or callers, then layout/comment/compile.

## Validation

- Compile every touched Blueprint or Widget.
- On compile errors, read structured result first; then fetch filtered Blueprint logs through MCP logs.
- Check no intended exec/data wires are dangling.
- Check widget hierarchy and visibility/state where relevant.
- Save each explicit validated asset through `editor.save_loaded_asset`. Treat `editor.save_all` as high risk and use it only when the user requests that scope and the dirty set is understood.

## Extending MCP

If the user approves a missing capability:

1. Add or update the action schema in the plugin registry, commonly under `Plugins/UEEditorMCP/Python/ue_editor_mcp/registry/actions/`.
2. Implement/adjust the C++ action handler under `Plugins/UEEditorMCP/Source/UEEditorMCP/{Public,Private}/Actions/`.
3. Register the handler in the bridge.
4. Rebuild/restart through launcher MCP before using the new action.

Validate exact paths against the current repository before editing; do not assume this plugin exists in every Unreal project.

## Delivery

Report created/modified asset paths, important components/variables/functions, compile result, validation method, saved status, and any manual/editor-only follow-up.
