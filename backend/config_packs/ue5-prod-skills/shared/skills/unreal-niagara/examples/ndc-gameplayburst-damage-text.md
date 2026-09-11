# Example: NDC GameplayBurst Damage Text

Load this example only when a Niagara effect is driven by a Niagara Data Channel, GameplayBurst spawning, damage numbers, or scratch-pad modules that read NDC rows.

## Goal

Keep the NDC publish -> GameplayBurst spawn -> listener reader path intact while tuning or repairing a damage-text Niagara system. The key lesson: a clean compile can still hide a broken runtime NDC chain.

## Preserve first

Before deleting or disabling anything, inspect the full stack and reader state:

```json
{"action_id":"niagara.get_module_inputs","params":{"system_path":"/Game/FX/NS_DamageText_NDC","emitter_name":"DamageTextDigits","include_hidden":true}}
```

Treat these as runtime-critical until proven otherwise:

- Scratch-pad modules that initialize Data Channel readers.
- Spawn modules that read an integer count from NDC rows.
- Particle init modules that read row payloads into `Particles.*`.
- Reader flags such as `bReadCurrentFrame`, `bAutoLinkToSpawningNDC`, and emitter-id bindings.

## Damage-text topology reference

For a typical NDC-backed damage-text system:

- The current-frame bootstrap reader, if present, must keep `bReadCurrentFrame=true`.
- The active spawn reader setup must keep its NDC asset, auto-link, and spawn-count variable intact.
- The spawn module that reads from NDC should keep `Emitter ID` linked to `Engine.Emitter.ID` when the script uses emitter-specific rows.
- The particle init/read module should keep the same `Emitter ID` binding when it reads the spawned row payload.
- Multiple Mesh Renderers are intentional digit/visibility renderers, not duplicate leftovers.

Prefer one NDC row per visible text group. The row should carry the group payload, such as position, value, digit count, spacing, style, lifetime, and movement parameters. Spawn one particle per digit/part inside Niagara and use `DigitIndex` only to extract the digit and apply a centered local offset. Avoid turning one number into multiple NDC rows unless the publisher, reader, and dedupe contract were designed for row-per-digit behavior.

## Group-facing layout

When a multi-digit value is rendered by separate digit meshes, make layout a group decision, not a per-character decision:

- Derive one group-facing vector from the same camera reference for the whole text group.
- Write that vector, or the resulting right-axis such as `Particles.DigitRight`, before the module that computes final digit position.
- A common camera-facing basis is `DigitRight = normalize(cross(GroupToCamera, WorldUp))`; flip the sign only when high-order digits appear on the wrong screen side.
- Keep the existing final positioning expression responsible for centered offsets, easing, vertical motion, scale, and fade. Change the upstream basis variable rather than duplicating the full movement expression.
- If MCP cannot author the needed ordered assignment or dynamic-input binding, extend the Niagara MCP action first, rebuild/restart the editor, then apply the repeatable asset edit.

## Runtime probe

After any meaningful NDC edit, compile diagnostics are necessary but not sufficient. Also write and flush one NDC row, then confirm a component and reader data exist:

```json
{
  "action_id": "niagara.write_data_channel_test",
  "params": {
    "asset_path": "/Game/FX/NDC/NDC_DamageText",
    "values": {
      "Position": [0, 0, 200],
      "SpawnCount": 3,
      "Value": 123,
      "DigitCount": 3
    },
    "system_to_spawn": "/Game/FX/NS_DamageText_NDC",
    "override_default_system_to_spawn": true,
    "flush_publish_requests": true,
    "advance_spawned_components": true,
    "advance_matching_components": true,
    "activate_advanced_components": true,
    "reset_advanced_components": true,
    "tick_count": 4,
    "tick_delta_seconds": 0.016
  }
}
```

Look for `rows_written > 0`, `flushed_publish_requests > 0`, a spawned or matching active component, and a reader with `compiled_spawns_particles=true`, `has_channel_handler=true`, and `reader_has_data=true`.

In isolated editor-world probes, `total_particles` can be zero even when rows, handler, and reader state are valid if the probe does not reproduce the real GameplayBurst tick order or viewport context. Treat that as a reason to inspect reader state and test the real publish path, not as a reason to rewrite unrelated renderers/materials.

## Cleanup rule

Do not remove scratch/internal NDC modules just because they look unused or compile without warnings. Only remove them after a before/after runtime probe shows equivalent spawned components, reader data, and visible gameplay behavior.
