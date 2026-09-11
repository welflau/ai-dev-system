---
name: unreal-material
description: "Focused workflow for creating, editing, validating, and applying Unreal Engine Material assets through UEEditorMCP. Use for Material graphs, Material Instances, Custom HLSL nodes, material compiler diagnostics, and material assignment to actors/components."
---

# Unreal Material MCP Skill

## Context

- Repository rules: [`AGENTS.md`](../../../AGENTS.md)
- Related skills: [Editor workflows](../unreal-editor/SKILL.md), [UEEditorMCP](../unreal-mcp/SKILL.md), [Blueprint/Widget](../unreal-blueprint/SKILL.md), [Niagara](../unreal-niagara/SKILL.md), [C++](../unreal-cpp/SKILL.md)
- Custom HLSL reference: [references/custom-hlsl.md](./references/custom-hlsl.md)

Use this skill for Material asset creation, graph edits, parameter setup, Custom nodes, Material Instances, post-process materials, compile diagnostics, and applying materials to actors/components.

## Preconditions

1. Confirm editor connectivity with `ue_ping`.
2. For unknown material actions, run `ue_actions_search("material")` and `ue_actions_schema(action_id=...)`.
3. When renderer/compiler behavior is unclear, resolve engine source from `.uproject` and search `<EngineRoot>/Engine/Source` read-only.

## Standard Workflow

1. Plan material domain, blend mode, shading model, parameters, expressions, and target outputs.
2. Create or reuse the asset. Use `if_exists="overwrite"` only for deterministic regeneration; use `reuse` when preserving edits.
3. Add expressions with stable explicit `node_name` values. Never use empty names or `None`/`NAME_None` for parameter keys.
4. Wire expressions to each other, then to material outputs.
5. Set expression and material properties.
6. Run `material.auto_layout`, then `material.auto_comment` if comments are useful.
7. Compile with `material.compile` and inspect structured diagnostics.
8. Refresh the editor if the Material Editor is open, inspect with `material.get_summary`, apply to actors/components if needed, then save.

## Core Actions

| Area | Actions |
|---|---|
| Asset | `material.create`, `material.create_instance`, `material.set_property`, `editor.save_loaded_asset` |
| Graph | `material.add_expression`, `material.connect_expressions`, `material.connect_to_output`, `material.remove_expression` |
| Properties | `material.set_expression_property`, `material.apply_to_component`, `material.apply_to_actor` |
| Validation | `material.compile`, `material.get_summary`, `material.refresh_editor`, `material.auto_layout`, `material.auto_comment` |

## Expression And Output Notes

- Common expression classes: constants, scalar/vector/texture parameters, math ops, `TextureSample`, `TextureObjectParameter`, `StaticSwitchParameter`, `MaterialFunctionCall`, `SceneTexture`, `Custom`.
- Common input pins: `A/B`, `Input`, `Alpha`, `Base/Exponent`, `Min/Max`, and Custom-node dynamic input names.
- Common outputs: `BaseColor`, `EmissiveColor`, `Metallic`, `Roughness`, `Specular`, `Normal`, `Opacity`, `OpacityMask`, `WorldPositionOffset`.
- For placeholder texture sampling, prefer a visually distinct built-in texture such as `/Engine/EditorShellMaterials/T_BaseButton.T_BaseButton` after verifying it exists.

## Custom HLSL

When the task involves a `Custom` node:

1. Read [references/custom-hlsl.md](./references/custom-hlsl.md).
2. Choose the correct pipeline before writing nodes: math-only, regular texture sampling, translucent scene sampling, post-process scene sampling, or post-process texture sampling.
3. Add required graph-side nodes before compiling; do not silently move user-requested sampling out of the Custom node.
4. Deliver the chosen pipeline, sampling budget if applicable, generated inputs, and compile result.

## Diagnostics

- `material.compile` should return `compiled`, `error_count`, `warning_count`, and `errors[]`.
- On failure, inspect structured errors before reading logs.
- If output looks wrong but compile succeeds, verify material domain/blend/shading model, graph connections, and Custom node return type.
- For log fallback, use MCP logs filtered to material/shader categories; never raw-read `Saved/Logs`.
- Save only the explicit validated material or instance. Use `editor.save_all` only with user-approved all-dirty-package scope.

## Delivery

Report material path, expressions/parameters created, output connections, compile warnings/errors, any actor/component assignments, and remaining manual validation needs.
