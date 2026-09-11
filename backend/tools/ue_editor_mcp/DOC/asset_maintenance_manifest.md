# Asset Maintenance Manifest

`editor.process_asset_maintenance_manifest` is the safe high-level entry point
for LLM-produced asset rename/move plans.

The action is intentionally two-phase:

1. `mode: "plan"` normalizes the manifest, runs deterministic preflight checks,
   returns blockers/warnings, and emits a stable `plan_hash`.
2. `mode: "apply"` requires `confirm_plan_hash` to exactly match the plan hash
   from the same manifest before any asset mutation is attempted.

The action reuses the lower-level UEEditorMCP actions:

- `editor.plan_asset_renames`
- `editor.rename_assets`
- `editor.delete_empty_directories`

It does not support asset deletion inside the manifest. Use
`editor.delete_assets` as a separate dry-run-first operation.

## Schema

```json
{
  "mode": "plan",
  "manifest": {
    "schema": "ue.asset_maintenance_plan.v1",
    "project": "p110_2",
    "defaults": {
      "auto_fixup_redirectors": true,
      "fixup_mode": "delete",
      "delete_empty_dirs": true,
      "allow_ui_prompts": false
    },
    "items": [
      {
        "id": "ren_0001",
        "op": "rename_or_move_asset",
        "source": {
          "object_path": "/Game/Old/BP_Door.BP_Door",
          "expected_class": "Blueprint"
        },
        "target": {
          "directory": "/Game/Props/Doors",
          "asset_name": "BP_Door_A"
        },
        "rule_id": "blueprint_prefix_and_category",
        "reason": "Normalize blueprint name and folder.",
        "confidence": 0.92
      }
    ],
    "cleanup": {
      "empty_directories": ["/Game/Old"]
    }
  }
}
```

`schema` may be `ue.asset_maintenance_plan.v1` or
`ue.asset_rename_plan.v1`.

## Safety Rules

- Plan mode is read-only.
- Apply mode refuses to run without `confirm_plan_hash`.
- Apply mode refuses when any blocker is present.
- Protected paths are blocked by default, including non-`/Game` paths and World
  Partition external actor/object folders.
- Case-only renames are blocked by default because they may require a two-step
  temporary name on Windows/source control.
- Rename cycles such as `A -> B` while `B` is also a source in the same manifest
  are blocked and must be split through temporary names.
- `delete_asset` operations are rejected in this manifest format.
- Empty directory cleanup runs only after successful renames and only if the
  directory is still empty when the lower-level cleanup action executes.

## Apply

```json
{
  "mode": "apply",
  "confirm_plan_hash": "<hash returned by plan>",
  "manifest": {
    "schema": "ue.asset_maintenance_plan.v1",
    "items": []
  }
}
```

Keep the manifest byte-for-byte equivalent at the semantic level between plan
and apply. If any operation, target, option, or cleanup directory changes, the
plan hash changes and apply is refused.
