"""Editor / Level Actors / Viewport action definitions."""

from __future__ import annotations

from .. import ActionDef


_EDITOR_ACTIONS = [
    ActionDef(
        id="editor.get_actors",
        command="get_actors_in_level",
        tags=("editor", "actors", "level", "list", "read"),
        description="Get a list of all actors in the current level",
        input_schema={"type": "object", "properties": {}},
        capabilities=("read",),
    ),
    ActionDef(
        id="editor.find_actors",
        command="find_actors_by_name",
        tags=("editor", "actors", "find", "search", "read"),
        description="Find actors by name pattern",
        input_schema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Actor object-name or label pattern to search for"},
                "world_scope": {
                    "type": "string",
                    "enum": ["editor", "pie", "auto"],
                    "description": "World to inspect. Defaults to editor; auto prefers an active PIE world."
                },
            },
            "required": ["pattern"]
        },
        capabilities=("read",),
        examples=(
            {"pattern": "Player"},
            {"pattern": "Boss", "world_scope": "pie"},
        ),
    ),
    ActionDef(
        id="editor.get_runtime_widgets",
        command="get_runtime_widgets",
        tags=("editor", "widget", "umg", "runtime", "pie", "visibility", "read"),
        description="Inspect live UserWidget instances and their bound target actors in an editor or PIE world",
        input_schema={
            "type": "object",
            "properties": {
                "world_scope": {
                    "type": "string",
                    "enum": ["editor", "pie", "auto"],
                    "description": "World to inspect. Defaults to auto, which prefers an active PIE world."
                },
                "class_pattern": {
                    "type": "string",
                    "description": "Optional case-insensitive Widget class-name/path filter."
                },
                "only_visible": {
                    "type": "boolean",
                    "description": "When true, omit widgets whose visibility or opacity hides them."
                },
            },
        },
        capabilities=("read",),
        examples=(
            {"world_scope": "pie", "class_pattern": "HealthBar"},
            {"world_scope": "pie", "only_visible": True},
        ),
    ),
    ActionDef(
        id="editor.spawn_actor",
        command="spawn_actor",
        tags=("editor", "actor", "spawn", "create"),
        description="Spawn a new actor in the current level",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name for the actor"},
                "type": {"type": "string", "description": "Type (StaticMeshActor, PointLight, etc.)"},
                "location": {"type": "array", "items": {"type": "number"}, "description": "[x, y, z]"},
                "rotation": {"type": "array", "items": {"type": "number"}, "description": "[pitch, yaw, roll]"}
            },
            "required": ["name", "type"]
        },
        examples=({"name": "MyLight", "type": "PointLight", "location": [0, 0, 200]},),
    ),
    ActionDef(
        id="editor.delete_actor",
        command="delete_actor",
        tags=("editor", "actor", "delete", "remove"),
        description="Delete an actor from the level by name",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the actor to delete"}
            },
            "required": ["name"]
        },
        capabilities=("write", "destructive"),
        risk="moderate",
    ),
    ActionDef(
        id="editor.set_actor_transform",
        command="set_actor_transform",
        tags=("editor", "actor", "transform", "position", "move"),
        description="Set the transform (location/rotation/scale) of an actor",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the actor"},
                "location": {"type": "array", "items": {"type": "number"}, "description": "[x, y, z]"},
                "rotation": {"type": "array", "items": {"type": "number"}, "description": "[pitch, yaw, roll]"},
                "scale": {"type": "array", "items": {"type": "number"}, "description": "[x, y, z]"}
            },
            "required": ["name"]
        },
        examples=({"name": "MyActor", "location": [100, 0, 50]},),
    ),
    ActionDef(
        id="editor.get_actor_properties",
        command="get_actor_properties",
        tags=("editor", "actor", "properties", "read"),
        description="Get all properties of an actor",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the actor"}
            },
            "required": ["name"]
        },
        capabilities=("read",),
    ),
    ActionDef(
        id="editor.set_actor_property",
        command="set_actor_property",
        tags=("editor", "actor", "property", "set"),
        description="Set a property on an actor in the level",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the actor"},
                "property_name": {"type": "string", "description": "Property name"},
                "property_value": {"type": "string", "description": "Value to set"}
            },
            "required": ["name", "property_name", "property_value"]
        },
    ),
    ActionDef(
        id="editor.focus_viewport",
        command="focus_viewport",
        tags=("editor", "viewport", "camera", "focus"),
        description="Focus the viewport on a specific actor or location",
        input_schema={
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Name of actor to focus on"},
                "location": {"type": "array", "items": {"type": "number"}, "description": "[x, y, z]"},
                "distance": {"type": "number", "description": "Distance from target"},
                "orientation": {"type": "array", "items": {"type": "number"}, "description": "[pitch, yaw, roll]"}
            }
        },
    ),
    ActionDef(
        id="editor.get_viewport_transform",
        command="get_viewport_transform",
        tags=("editor", "viewport", "camera", "read"),
        description="Get the current viewport camera location and rotation",
        input_schema={"type": "object", "properties": {}},
        capabilities=("read",),
    ),
    ActionDef(
        id="editor.set_viewport_transform",
        command="set_viewport_transform",
        tags=("editor", "viewport", "camera", "set"),
        description="Set the viewport camera location and/or rotation",
        input_schema={
            "type": "object",
            "properties": {
                "location": {"type": "array", "items": {"type": "number"}, "description": "[x, y, z]"},
                "rotation": {"type": "array", "items": {"type": "number"}, "description": "[pitch, yaw, roll]"}
            }
        },
    ),
    ActionDef(
        id="editor.save_all",
        command="save_all",
        tags=("editor", "save", "all"),
        description="Save all dirty packages (blueprints, levels, assets)",
        input_schema={"type": "object", "properties": {}},
    ),
    ActionDef(
        id="editor.save_loaded_asset",
        command="save_loaded_asset",
        tags=("editor", "asset", "save", "package", "write"),
        description="Save one loaded asset package by asset path without saving unrelated dirty levels or assets.",
        input_schema={
            "type": "object",
            "properties": {
                "asset_path": {"type": "string"},
                "only_if_dirty": {"type": "boolean", "description": "Only save when the package is dirty. Default false."},
            },
            "required": ["asset_path"],
        },
        capabilities=("write",),
        risk="safe",
        examples=({"asset_path": "/Game/FX/NS_Example", "only_if_dirty": True},),
    ),
    ActionDef(
        id="editor.set_world_settings_class",
        command="set_world_settings_class",
        tags=("editor", "world", "settings", "level", "gamemode", "class", "set"),
        description="Set a class-valued property on the current editor world's WorldSettings, such as DefaultGameMode (displayed as GameMode Override).",
        input_schema={
            "type": "object",
            "properties": {
                "property_name": {"type": "string", "description": "WorldSettings class property name, e.g. DefaultGameMode"},
                "class_path": {"type": "string", "description": "Class path/name, e.g. /Game/.../BP_Mode.BP_Mode_C"},
            },
            "required": ["property_name", "class_path"],
        },
        capabilities=("write",),
        risk="moderate",
        examples=(
            {
                "property_name": "DefaultGameMode",
                "class_path": "/Game/P110_2/TPS/Blueprints/BP_TPSQuickTestGameMode.BP_TPSQuickTestGameMode_C",
            },
        ),
    ),
    ActionDef(
        id="editor.list_assets",
        command="list_assets",
        tags=("editor", "assets", "list", "browse", "read"),
        description="List assets under a Content path with optional filtering",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Content path (e.g. /Game/Blueprints)"},
                "recursive": {"type": "boolean", "description": "Search sub-folders (default: true)"},
                "class_filter": {"type": "string", "description": "Filter by class (Blueprint, Material, Texture2D, etc.)"},
                "name_contains": {"type": "string", "description": "Filter by name substring"},
                "max_results": {"type": "integer", "description": "Max results (default: 500)"}
            },
            "required": ["path"]
        },
        capabilities=("read",),
        examples=({"path": "/Game/Blueprints", "class_filter": "Blueprint"},),
    ),
    ActionDef(
        id="editor.rename_assets",
        command="rename_assets",
        tags=("editor", "assets", "rename", "redirector", "fixup", "refactor"),
        description=(
            "Rename one or more assets and optionally fix redirectors automatically. "
            "Supports single-item params or batch items[] in one call. "
            "When allow_ui_prompts=false (default), runs non-interactive and silently auto-deletes only unreferenced redirectors."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "old_asset_path": {"type": "string", "description": "Single mode: source object path to rename (e.g. /Game/UI/WBP_Menu.WBP_Menu)"},
                "new_package_path": {"type": "string", "description": "Single mode: destination package path (e.g. /Game/UI/New)"},
                "new_name": {"type": "string", "description": "Single mode: destination asset name (without path)"},
                "items": {
                    "type": "array",
                    "description": "Batch mode: list of rename operations",
                    "items": {
                        "type": "object",
                        "properties": {
                            "old_asset_path": {"type": "string"},
                            "new_package_path": {"type": "string"},
                            "new_name": {"type": "string"},
                        },
                        "required": ["old_asset_path", "new_package_path", "new_name"],
                    },
                },
                "auto_fixup_redirectors": {"type": "boolean", "description": "Fix redirectors after rename (default: true)"},
                "allow_ui_prompts": {
                    "type": "boolean",
                    "description": "Allow UI dialogs during fixup (default: false). Keep false for unattended automation and batch runs.",
                },
                "fixup_mode": {
                    "type": "string",
                    "description": "Redirector handling mode: delete | leave | prompt (default: delete). If allow_ui_prompts=false, prompt is forced to delete.",
                    "enum": ["delete", "leave", "prompt"],
                },
                "checkout_dialog_prompt": {
                    "type": "boolean",
                    "description": "Show source-control checkout dialog during fixup (default: false). Only effective when allow_ui_prompts=true.",
                },
            },
        },
        capabilities=("write",),
        risk="moderate",
        examples=(
            {
                "old_asset_path": "/Game/P110_2/Blueprints/UI/WBP_Old.WBP_Old",
                "new_package_path": "/Game/P110_2/Blueprints/UI",
                "new_name": "WBP_New",
            },
            {
                "items": [
                    {
                        "old_asset_path": "/Game/P110_2/Blueprints/UI/WBP_A.WBP_A",
                        "new_package_path": "/Game/P110_2/Blueprints/UI",
                        "new_name": "WBP_A1",
                    },
                    {
                        "old_asset_path": "/Game/P110_2/Blueprints/UI/WBP_B.WBP_B",
                        "new_package_path": "/Game/P110_2/Blueprints/UI",
                        "new_name": "WBP_B1",
                    },
                ],
                "auto_fixup_redirectors": True,
                "allow_ui_prompts": False,
                "fixup_mode": "delete",
            },
        ),
    ),
    ActionDef(
        id="editor.plan_asset_renames",
        command="plan_asset_renames",
        tags=("editor", "assets", "rename", "plan", "dry-run", "preflight", "redirector", "reference", "cleanup"),
        description=(
            "Dry-run validation for one or more asset rename/move operations. "
            "Reports source existence, protected paths, destination conflicts, duplicate destinations, "
            "and external referencers before calling editor.rename_assets."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "old_asset_path": {"type": "string", "description": "Single mode: source object or package path"},
                "new_package_path": {"type": "string", "description": "Single mode: destination package folder (e.g. /Game/UI/New)"},
                "new_name": {"type": "string", "description": "Single mode: destination asset name"},
                "items": {
                    "type": "array",
                    "description": "Batch mode: list of rename operations",
                    "items": {
                        "type": "object",
                        "properties": {
                            "old_asset_path": {"type": "string"},
                            "new_package_path": {"type": "string"},
                            "new_name": {"type": "string"},
                        },
                        "required": ["old_asset_path", "new_package_path", "new_name"],
                    },
                },
                "include_referencers": {"type": "boolean", "description": "Include external referencer packages (default: true)"},
                "max_referencers_per_item": {"type": "integer", "description": "Maximum referencers reported per item (default: 20)"},
                "allow_protected_paths": {"type": "boolean", "description": "Allow protected paths such as /Game root or external actor folders (default: false)"},
            },
        },
        capabilities=("read",),
        risk="safe",
        examples=(
            {
                "old_asset_path": "/Game/P110_2/Blueprints/UI/WBP_Old.WBP_Old",
                "new_package_path": "/Game/P110_2/Blueprints/UI",
                "new_name": "WBP_New",
            },
        ),
    ),
    ActionDef(
        id="editor.delete_assets",
        command="delete_assets",
        tags=("editor", "assets", "delete", "cleanup", "reference", "dry-run", "destructive"),
        description=(
            "Delete assets with a safe dry-run default. "
            "Blocks protected paths, missing assets, maps unless explicitly allowed, and externally referenced assets unless force=true."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "asset_path": {"type": "string", "description": "Single object or package path to delete"},
                "asset_paths": {"type": "array", "items": {"type": "string"}, "description": "Batch asset paths to delete"},
                "dry_run": {"type": "boolean", "description": "Preview only without deleting (default: true)"},
                "require_unreferenced": {"type": "boolean", "description": "Block deletion when external referencers exist (default: true)"},
                "force": {"type": "boolean", "description": "Allow deletion despite external referencers when dry_run=false (default: false)"},
                "allow_map_assets": {"type": "boolean", "description": "Allow deleting World/Level assets (default: false)"},
                "allow_protected_paths": {"type": "boolean", "description": "Allow protected paths such as /Game root or external actor folders (default: false)"},
                "max_referencers_per_asset": {"type": "integer", "description": "Maximum referencers reported per asset (default: 20)"},
                "max_referencers_per_item": {"type": "integer", "description": "Alias for max_referencers_per_asset."},
            },
        },
        capabilities=("write", "destructive"),
        risk="high",
        examples=(
            {"asset_paths": ["/Game/P110_2/Temp/DA_Unused.DA_Unused"], "dry_run": True},
        ),
    ),
    ActionDef(
        id="editor.delete_empty_directories",
        command="delete_empty_directories",
        tags=("editor", "assets", "directories", "folders", "delete", "cleanup", "dry-run", "destructive"),
        description=(
            "Delete empty /Game directories with a safe dry-run default. "
            "A directory is considered empty only when the Asset Registry has no assets under it and its disk folder has no files."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Single /Game directory path"},
                "paths": {"type": "array", "items": {"type": "string"}, "description": "Batch /Game directory paths"},
                "dry_run": {"type": "boolean", "description": "Preview only without deleting (default: true)"},
                "recursive": {"type": "boolean", "description": "Include empty child directories (default: true)"},
                "allow_protected_paths": {"type": "boolean", "description": "Allow protected paths such as /Game root or external actor folders (default: false)"},
                "max_directories": {"type": "integer", "description": "Safety limit for discovered directories (default: 1000)"},
            },
        },
        capabilities=("write", "destructive"),
        risk="moderate",
        examples=(
            {"path": "/Game/P110_2/Temp", "dry_run": True, "recursive": True},
        ),
    ),
    ActionDef(
        id="editor.process_asset_maintenance_manifest",
        command="process_asset_maintenance_manifest",
        tags=(
            "editor",
            "assets",
            "manifest",
            "rename",
            "move",
            "cleanup",
            "redirector",
            "dry-run",
            "llm",
            "validation",
        ),
        description=(
            "Validate or apply an LLM-produced asset maintenance manifest. "
            "Plan mode returns normalized rename items, blockers, cleanup candidates, and a stable plan_hash; "
            "apply mode requires confirm_plan_hash to match before any asset mutation."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["plan", "dry_run", "apply"],
                    "description": "plan/dry_run previews only; apply requires confirm_plan_hash.",
                },
                "confirm_plan_hash": {
                    "type": "string",
                    "description": "Required in apply mode. Must equal the plan_hash returned by the same manifest.",
                },
                "manifest": {
                    "type": "object",
                    "description": "Versioned asset maintenance manifest generated by an LLM or deterministic planner.",
                    "properties": {
                        "schema": {
                            "type": "string",
                            "enum": ["ue.asset_maintenance_plan.v1", "ue.asset_rename_plan.v1"],
                        },
                        "project": {"type": "string"},
                        "defaults": {
                            "type": "object",
                            "properties": {
                                "auto_fixup_redirectors": {"type": "boolean"},
                                "fixup_mode": {"type": "string", "enum": ["delete", "leave", "prompt"]},
                                "delete_empty_dirs": {"type": "boolean"},
                                "allow_ui_prompts": {"type": "boolean"},
                            },
                        },
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "op": {
                                        "type": "string",
                                        "enum": [
                                            "rename_or_move_asset",
                                            "rename",
                                            "move",
                                            "rename_asset",
                                            "delete_empty_directory",
                                        ],
                                    },
                                    "source": {
                                        "type": "object",
                                        "properties": {
                                            "object_path": {"type": "string"},
                                            "asset_path": {"type": "string"},
                                            "package_path": {"type": "string"},
                                            "asset_name": {"type": "string"},
                                            "expected_class": {"type": "string"},
                                        },
                                    },
                                    "target": {
                                        "type": "object",
                                        "properties": {
                                            "directory": {"type": "string"},
                                            "new_package_path": {"type": "string"},
                                            "package_path": {"type": "string"},
                                            "object_path": {"type": "string"},
                                            "asset_name": {"type": "string"},
                                            "new_name": {"type": "string"},
                                        },
                                    },
                                    "path": {"type": "string", "description": "For delete_empty_directory items."},
                                    "rule_id": {"type": "string"},
                                    "reason": {"type": "string"},
                                    "confidence": {"type": "number"},
                                },
                            },
                        },
                        "cleanup": {
                            "type": "object",
                            "properties": {
                                "empty_directories": {
                                    "type": "array",
                                    "items": {
                                        "oneOf": [
                                            {"type": "string"},
                                            {
                                                "type": "object",
                                                "properties": {"path": {"type": "string"}},
                                                "required": ["path"],
                                            },
                                        ]
                                    },
                                }
                            },
                        },
                    },
                    "required": ["schema"],
                },
                "include_referencers": {"type": "boolean", "description": "Include external referencer summaries in plan mode (default: true)."},
                "max_referencers_per_item": {"type": "integer", "description": "Maximum referencers reported per item (default: 20)."},
                "allow_protected_paths": {"type": "boolean", "description": "Allow non-/Game, root, or World Partition external paths (default: false)."},
                "allow_case_only_renames": {"type": "boolean", "description": "Allow case-only renames; otherwise they are blocked for two-step temp handling."},
                "min_confidence": {"type": "number", "description": "Optional minimum LLM confidence required for each item."},
                "auto_fixup_redirectors": {"type": "boolean", "description": "Override manifest default for redirector fixup."},
                "fixup_mode": {"type": "string", "enum": ["delete", "leave", "prompt"], "description": "Override manifest default redirector fixup mode."},
                "delete_empty_directories": {"type": "boolean", "description": "Override manifest default for post-rename empty directory cleanup."},
                "apply_empty_directory_cleanup": {"type": "boolean", "description": "Alias for delete_empty_directories."},
                "max_directories": {"type": "integer", "description": "Safety cap for post-rename empty directory cleanup."},
            },
            "required": ["manifest"],
        },
        capabilities=("read", "write", "destructive"),
        risk="high",
        examples=(
            {
                "mode": "plan",
                "manifest": {
                    "schema": "ue.asset_maintenance_plan.v1",
                    "project": "p110_2",
                    "defaults": {
                        "auto_fixup_redirectors": True,
                        "fixup_mode": "delete",
                        "delete_empty_dirs": True,
                    },
                    "items": [
                        {
                            "id": "ren_0001",
                            "op": "rename_or_move_asset",
                            "source": {
                                "object_path": "/Game/P110_2/Blueprints/BP_Old.BP_Old",
                                "expected_class": "Blueprint",
                            },
                            "target": {
                                "directory": "/Game/P110_2/Blueprints",
                                "asset_name": "BP_New",
                            },
                            "rule_id": "blueprint_prefix",
                            "reason": "Normalize blueprint name.",
                            "confidence": 0.92,
                        }
                    ],
                    "cleanup": {"empty_directories": ["/Game/P110_2/Old"]},
                },
            },
        ),
    ),
    ActionDef(
        id="editor.capture_screenshot",
        command="capture_editor_screenshot",
        tags=("editor", "screenshot", "capture", "image", "base64", "viewport", "window", "visual", "read"),
        description=(
            "Capture the current UE editor UI as a PNG. Token-saving default scales output to max_width=512 with proportional height; "
            "only request higher resolution when you truly need visual detail by setting max_width/max_height, or use full_resolution=true for the captured source size. "
            "Defaults to the active Slate window; use target='active_viewport' for the Level Viewport."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "enum": ["active_window", "active_viewport"],
                    "description": "Capture target (default: active_window).",
                },
                "max_width": {
                    "type": "integer",
                    "description": "Maximum output width; default 512 to save tokens, clamp 64..1920. Increase only when higher detail is needed.",
                },
                "max_height": {
                    "type": "integer",
                    "description": "Maximum output height; default 1920 so the default is primarily width-limited, clamp 64..1920.",
                },
                "full_resolution": {
                    "type": "boolean",
                    "description": "Return captured source size and ignore max_width/max_height (default false). Use only when full detail is required.",
                },
                "include_base64": {
                    "type": "boolean",
                    "description": "Include image_base64 in the response (default: true).",
                },
            },
        },
        capabilities=("read",),
        examples=(
            {},
            {"target": "active_window", "max_width": 1024},
            {"target": "active_viewport", "full_resolution": True},
        ),
    ),
    ActionDef(
        id="editor.get_selected_asset_thumbnail",
        command="get_selected_asset_thumbnail",
        tags=("editor", "assets", "selection", "thumbnail", "image", "base64", "read"),
        description=(
            "Get base64-encoded PNG thumbnails for selected Content Browser assets, "
            "or for explicit asset path/id inputs. Supports batch output in one call."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "asset_path": {
                    "type": "string",
                    "description": "Optional single full asset path (e.g. /Game/P110_2/Art/T_Icon.T_Icon).",
                },
                "asset_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional multiple full asset paths.",
                },
                "asset_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional asset id/path list (alias of asset_paths).",
                },
                "ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional id list (alias of asset_paths).",
                },
                "size": {
                    "type": "integer",
                    "description": "Thumbnail target size in pixels (default 256, clamp 1..256)",
                },
            },
        },
        capabilities=("read",),
        examples=(
            {},
            {"size": 256},
            {"asset_paths": ["/Game/P110_2/Art/T_IconA.T_IconA", "/Game/P110_2/Art/T_IconB.T_IconB"]},
            {"asset_ids": ["/Game/P110_2/Art/T_Icon.T_Icon"], "size": 256},
        ),
    ),
    ActionDef(
        id="editor.get_selected_assets",
        command="get_selected_assets",
        tags=("editor", "assets", "selection", "list", "content-browser", "read"),
        description=(
            "List the assets currently selected in the Content Browser. "
            "Returns asset_name, asset_path, package_path, asset_class, and asset_class_path "
            "for each selected asset. No parameters required."
        ),
        input_schema={
            "type": "object",
            "properties": {},
        },
        capabilities=("read",),
        examples=(
            {},
        ),
    ),
    ActionDef(
        id="editor.diff_against_depot",
        command="diff_against_depot",
        tags=("editor", "diff", "source-control", "svn", "revision", "compare", "debug", "read"),
        description=(
            "Diff an asset against its latest source-control (SVN/Perforce/Git) depot revision. "
            "For Blueprints: returns per-graph node-level changes (added/removed/modified/moved nodes, pin changes). "
            "For generic assets: returns property-level differences. "
            "Requires Source Control to be connected in the editor."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "asset_path": {
                    "type": "string",
                    "description": "Full asset path (e.g. /Game/P110_2/Blueprints/BP_Foo)",
                },
                "revision": {
                    "type": "integer",
                    "description": "Optional specific revision number to diff against (default: latest)",
                },
            },
            "required": ["asset_path"],
        },
        capabilities=("read",),
        risk="safe",
        examples=(
            {"asset_path": "/Game/P110_2/Blueprints/Character/Player/BP_SideScrollingCharacter"},
            {"asset_path": "/Game/P110_2/Blueprints/BP_SideScrollingGameMode", "revision": 42},
        ),
    ),
    ActionDef(
        id="editor.get_asset_history",
        command="get_asset_history",
        tags=("editor", "source-control", "svn", "revision", "history", "read"),
        description=(
            "List source-control revision history for a given asset. "
            "Returns an array of revisions that actually modified the file "
            "(up to the SVN provider limit of 100). "
            "Use this to discover valid revision numbers before calling diff_against_depot."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "asset_path": {
                    "type": "string",
                    "description": "Full asset path (e.g. /Game/P110_2/Blueprints/BP_Foo)",
                },
                "max_count": {
                    "type": "integer",
                    "description": "Maximum number of revisions to return (default: all available, up to ~100)",
                },
            },
            "required": ["asset_path"],
        },
        capabilities=("read",),
        risk="safe",
        examples=(
            {"asset_path": "/Game/P110_2/Blueprints/Character/Player/BP_SideScrollingCharacter"},
            {"asset_path": "/Game/P110_2/Blueprints/BP_Foo", "max_count": 10},
        ),
    ),
    ActionDef(
        id="editor.get_logs",
        command="get_editor_logs",
        tags=("editor", "logs", "debug", "read"),
        description="Retrieve recent UE editor log entries from the in-memory ring buffer. Supports filtering by category and verbosity.",
        input_schema={
            "type": "object",
            "properties": {
                "count": {"type": "integer", "description": "Number of entries to return (default: 50, max: 500)"},
                "category": {"type": "string", "description": "Filter by log category (e.g. LogMCP, LogBlueprint)"},
                "min_verbosity": {"type": "string", "description": "Minimum verbosity: Fatal, Error, Warning, Display, Log, Verbose, VeryVerbose"}
            }
        },
        capabilities=("read",),
        examples=(
            {},
            {"count": 100, "category": "LogMCP"},
            {"count": 20, "min_verbosity": "Warning"},
        ),
    ),
    ActionDef(
        id="editor.is_ready",
        command="is_ready",
        tags=("editor", "status", "health", "ready", "read"),
        description="Check if the UE editor is fully initialized and ready for commands. Returns readiness of editor, world, and asset registry.",
        input_schema={"type": "object", "properties": {}},
        capabilities=("read",),
        risk="safe",
        examples=({},),
    ),
    ActionDef(
        id="editor.request_shutdown",
        command="request_shutdown",
        tags=("editor", "shutdown", "exit", "close"),
        description="Request the editor to shut down. Use force=true to skip save dialogs and exit immediately.",
        input_schema={
            "type": "object",
            "properties": {
                "force": {"type": "boolean", "description": "Force immediate exit without save prompts (default: false)"}
            }
        },
        risk="destructive",
        examples=(
            {},
            {"force": True},
        ),
    ),
    ActionDef(
        id="editor.exec_console_command",
        command="exec_console_command",
        tags=("editor", "console", "command", "exec", "automation", "test", "run", "stat", "log"),
        description=(
            "Execute a single UE console command inside the running editor (e.g. "
            "'Automation RunTests P111.LJC+', 'Stat Unit', 'log LogLJC Verbose'). "
            "STRICT allowlist: command must start with one of "
            "'Automation '/'Stat '/'log '/'viewmode '/'showflag.'/'r.'/'p.'/'t.'/'ai.'/'slomo '/'ke '. "
            "Multi-command separators (';' '&&' '||') and dangerous keywords "
            "('quit'/'exit'/'open '/'travel '/'restart'/'crash'/'rhi.'/abs paths) are rejected. "
            "Returns exec_succeeded (bool) and captured_logs from the editor log ring buffer "
            "for the duration of the command (capture_logs=true by default). "
            "Note: 'Automation RunTests X' is asynchronous — Exec returns true immediately and tests run "
            "over subsequent ticks; poll editor.assert_log / editor.get_logs to await completion."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Console command. Must match the allowlist (see description)."
                },
                "capture_logs": {
                    "type": "boolean",
                    "description": "Capture editor log entries emitted while Exec runs (default: true)."
                },
                "capture_lines": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 2000,
                    "description": "Max log lines to return when capture_logs=true (default: 200)."
                },
            },
            "required": ["command"],
        },
        capabilities=("write",),
        risk="moderate",
        examples=(
            {"command": "Automation RunTests P111.LJC.StructureGeometry+"},
            {"command": "Stat Unit"},
            {"command": "log LogLJC Verbose", "capture_logs": False},
        ),
    ),
    ActionDef(
        id="editor.live_coding_compile",
        command="live_coding_compile",
        tags=("editor", "live_coding", "hot_reload", "compile", "cpp"),
        description=(
            "Trigger UE Live Coding (Quick Compile) inside the running editor. "
            "Equivalent to clicking the Live Coding tray icon → Compile. Useful for "
            "agent-driven C++ iteration without restarting the editor. "
            "Set wait_for_completion=true to block until the compile finishes (or timeout)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "wait_for_completion": {
                    "type": "boolean",
                    "description": "Block until LC reports IsCompiling()==false (default: false)"
                },
                "timeout_seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1800,
                    "description": "Upper bound when wait_for_completion=true (default: 120)"
                },
            },
        },
        capabilities=("write",),
        risk="moderate",
        examples=(
            {},
            {"wait_for_completion": True, "timeout_seconds": 180},
        ),
    ),
    ActionDef(
        id="editor.live_coding_status",
        command="live_coding_status",
        tags=("editor", "live_coding", "status", "read"),
        description=(
            "Query Live Coding status: module_loaded, enabled, compile_in_progress, "
            "can_enable_for_session. Side-effect free; safe to poll."
        ),
        input_schema={"type": "object", "properties": {}},
        capabilities=("read",),
        risk="safe",
        examples=({},),
    ),
    # =========================================================================
    # P6: PIE Control Actions
    # =========================================================================
    ActionDef(
        id="editor.start_pie",
        command="start_pie",
        tags=("editor", "pie", "play", "start", "test", "run"),
        description=(
            "Start a Play In Editor (PIE) session. "
            "Mode: SelectedViewport (default), NewWindow, or Simulate. "
            "net_mode: Standalone (default), ListenServer, Client, DedicatedServer. "
            "player_count: 1..4. starting_map: optional level path to switch before launching. "
            "PIE starts asynchronously; use editor.get_pie_state to poll readiness."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["SelectedViewport", "NewWindow", "Simulate"],
                    "description": "PIE launch mode (default: SelectedViewport)",
                },
                "net_mode": {
                    "type": "string",
                    "enum": ["Standalone", "ListenServer", "Client", "DedicatedServer"],
                    "description": "Network mode (default: Standalone)",
                },
                "player_count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 4,
                    "description": "Number of clients (1..4). Used with ListenServer/Client/DedicatedServer.",
                },
                "starting_map": {
                    "type": "string",
                    "description": "Optional level path to load before PIE (e.g. '/Game/LJCTest/L_LJCTest')",
                },
            },
        },
        risk="moderate",
        examples=(
            {},
            {"mode": "SelectedViewport"},
            {"mode": "NewWindow"},
            {"mode": "Simulate"},
            {"mode": "NewWindow", "net_mode": "ListenServer", "player_count": 2},
            {
                "mode": "NewWindow",
                "net_mode": "ListenServer",
                "player_count": 2,
                "starting_map": "/Game/LJCTest/L_LJCTest",
            },
        ),
    ),
    ActionDef(
        id="editor.stop_pie",
        command="stop_pie",
        tags=("editor", "pie", "stop", "end", "test"),
        description="Stop the current PIE session without closing the editor. Safe to call when no session is running.",
        input_schema={"type": "object", "properties": {}},
        risk="safe",
        examples=({},),
    ),
    ActionDef(
        id="editor.get_pie_state",
        command="get_pie_state",
        tags=("editor", "pie", "state", "status", "query", "read"),
        description=(
            "Query the current PIE session state. Returns Running/Stopped, world name, "
            "pause state, and whether simulation mode is active."
        ),
        input_schema={"type": "object", "properties": {}},
        capabilities=("read",),
        risk="safe",
        examples=({},),
    ),
    # =========================================================================
    # P8: PIE Automation Test Actions（关卡切换 + 输入模拟）
    # =========================================================================
    ActionDef(
        id="editor.open_level",
        command="open_level",
        tags=("editor", "level", "map", "open", "load", "switch"),
        description=(
            "Switch the editor world to the specified level (must NOT be inside a PIE session). "
            "Accepts long package name or object path, e.g. '/Game/LJCTest/L_LJCTest'."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "level_path": {
                    "type": "string",
                    "description": "Level path, e.g. '/Game/LJCTest/L_LJCTest'",
                },
                "save_dirty": {
                    "type": "boolean",
                    "description": "Whether to save dirty packages before switching (default: false)",
                },
            },
            "required": ["level_path"],
        },
        risk="moderate",
        examples=(
            {"level_path": "/Game/LJCTest/L_LJCTest"},
            {"level_path": "/Game/LJCTest/L_LJCTest", "save_dirty": True},
        ),
    ),
    ActionDef(
        id="editor.create_level",
        command="create_level",
        tags=("editor", "level", "map", "create", "save", "asset"),
        description=(
            "Create and save a blank editor level package, optionally opening it after creation. "
            "Supports if_exists=error|overwrite|skip|reuse for repeatable automation."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "level_path": {
                    "type": "string",
                    "description": "Long package name or object path, e.g. '/Game/P110_2/TPS/Maps/L_TPS_Test'",
                },
                "if_exists": {
                    "type": "string",
                    "enum": ["error", "overwrite", "skip", "reuse"],
                    "description": "Existing asset behavior (default: error)",
                },
                "open_level": {
                    "type": "boolean",
                    "description": "Open the new/reused level in the editor after creation (default: true)",
                },
                "save_dirty": {
                    "type": "boolean",
                    "description": "Save dirty packages before replacing the current editor map (default: false)",
                },
            },
            "required": ["level_path"],
        },
        capabilities=("write",),
        risk="moderate",
        examples=(
            {"level_path": "/Game/P110_2/TPS/Maps/L_TPS_Test", "if_exists": "overwrite"},
        ),
    ),
    ActionDef(
        id="editor.duplicate_asset",
        command="duplicate_asset",
        tags=("editor", "asset", "duplicate", "copy", "clone", "blueprint", "map"),
        description=(
            "Duplicate an asset to a destination package path using EditorAssetSubsystem. "
            "Supports if_exists=error|overwrite|skip|reuse for repeatable automation."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "source_asset_path": {
                    "type": "string",
                    "description": "Source asset package or object path, e.g. '/Game/ThirdPerson/Blueprints/BP_ThirdPersonCharacter'",
                },
                "destination_asset_path": {
                    "type": "string",
                    "description": "Destination package or object path, e.g. '/Game/P110_2/TPS/BP_TPSCharacter_Test'",
                },
                "if_exists": {
                    "type": "string",
                    "enum": ["error", "overwrite", "skip", "reuse"],
                    "description": "Existing asset behavior (default: error)",
                },
                "save": {
                    "type": "boolean",
                    "description": "Save the duplicated package after creation (default: true)",
                },
            },
            "required": ["source_asset_path", "destination_asset_path"],
        },
        capabilities=("write",),
        risk="moderate",
        examples=(
            {
                "source_asset_path": "/Game/ThirdPerson/Blueprints/BP_ThirdPersonCharacter.BP_ThirdPersonCharacter",
                "destination_asset_path": "/Game/P110_2/TPS/BP_TPSCharacter_Test",
                "if_exists": "overwrite",
            },
        ),
    ),
    ActionDef(
        id="editor.simulate_input",
        command="simulate_input",
        tags=("editor", "pie", "input", "key", "mouse", "simulate", "test"),
        description=(
            "Simulate a key/mouse input inside an active PIE session, dispatched to the "
            "specified PIE client (0 = Listen Server / Standalone, 1+ = other clients). "
            "Supports Pressed / Released / Click. Common keys: 'W','A','S','D','SpaceBar', "
            "'Two' (digit '2'), 'LeftMouseButton', 'RightMouseButton'."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "client_index": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "PIE client index (default: 0)",
                },
                "key": {
                    "type": "string",
                    "description": "Key name (e.g. 'W', 'Two', 'LeftMouseButton')",
                },
                "event": {
                    "type": "string",
                    "enum": ["Pressed", "Released", "Click"],
                    "description": "Input event type (default: Pressed)",
                },
                "duration_ms": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5000,
                    "description": "Press → Release interval when event=Click (default: 50)",
                },
                "focus_viewport": {
                    "type": "boolean",
                    "description": "Force focus to game viewport before dispatch (default: true)",
                },
            },
            "required": ["key"],
        },
        risk="moderate",
        examples=(
            {"client_index": 0, "key": "W", "event": "Pressed"},
            {"client_index": 0, "key": "W", "event": "Released"},
            {"client_index": 0, "key": "LeftMouseButton", "event": "Click", "duration_ms": 80},
            {"client_index": 1, "key": "Two", "event": "Pressed"},
        ),
    ),
    # =========================================================================
    # P6: Log Enhancement Actions
    # =========================================================================
    ActionDef(
        id="editor.clear_logs",
        command="clear_logs",
        tags=("editor", "logs", "clear", "reset", "session"),
        description=(
            "Clear the MCP log capture ring buffer. Optionally insert a session tag marker "
            "before clearing for session segmentation. Returns the previous cursor for reference."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "tag": {
                    "type": "string",
                    "description": "Optional session tag to insert before clearing (e.g. 'test_run_01')",
                },
            },
        },
        risk="moderate",
        examples=(
            {},
            {"tag": "test_run_01"},
        ),
    ),
    ActionDef(
        id="editor.assert_log",
        command="assert_log",
        tags=("editor", "logs", "assert", "test", "validate", "verify", "pass", "fail"),
        description=(
            "Assertion-based log validation. Check log entries for keyword occurrences "
            "and return pass/fail for each assertion. Supports comparison operators "
            "(==, >=, <=, >, <) and optional cursor-based range filtering."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "assertions": {
                    "type": "array",
                    "description": "List of assertions to check",
                    "items": {
                        "type": "object",
                        "properties": {
                            "keyword": {"type": "string", "description": "Substring to search for in log messages"},
                            "expected_count": {"type": "integer", "description": "Expected number of occurrences"},
                            "comparison": {
                                "type": "string",
                                "enum": ["==", ">=", "<=", ">", "<"],
                                "description": "Comparison operator (default: >=)",
                            },
                            "category": {"type": "string", "description": "Optional log category filter"},
                        },
                        "required": ["keyword", "expected_count"],
                    },
                },
                "since_cursor": {
                    "type": "string",
                    "description": "Only check logs after this cursor (live:<seq> format)",
                },
            },
            "required": ["assertions"],
        },
        capabilities=("read",),
        risk="safe",
        examples=(
            {
                "assertions": [
                    {"keyword": "HelloWorld", "expected_count": 1, "comparison": ">="},
                    {"keyword": "ForLoop", "expected_count": 3, "comparison": "=="},
                ]
            },
            {
                "assertions": [{"keyword": "Error", "expected_count": 0, "comparison": "=="}],
                "since_cursor": "live:100",
            },
        ),
    ),
    # =========================================================================
    # P6: Outliner Management Actions
    # =========================================================================
    ActionDef(
        id="editor.rename_actor_label",
        command="rename_actor_label",
        tags=("editor", "actor", "rename", "label", "outliner"),
        description=(
            "Rename an actor's display label in the World Outliner. "
            "Supports single item (actor_name + new_label) or batch (items[])."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "actor_name": {"type": "string", "description": "Current actor name or label"},
                "new_label": {"type": "string", "description": "New display label"},
                "items": {
                    "type": "array",
                    "description": "Batch rename operations",
                    "items": {
                        "type": "object",
                        "properties": {
                            "actor_name": {"type": "string"},
                            "new_label": {"type": "string"},
                        },
                        "required": ["actor_name", "new_label"],
                    },
                },
            },
        },
        examples=(
            {"actor_name": "BP_Fly_C_0", "new_label": "Flying Enemy Alpha"},
            {
                "items": [
                    {"actor_name": "BP_Fly_C_0", "new_label": "Flyer 01"},
                    {"actor_name": "BP_Fly_C_1", "new_label": "Flyer 02"},
                ]
            },
        ),
    ),
    ActionDef(
        id="editor.set_actor_folder",
        command="set_actor_folder",
        tags=("editor", "actor", "folder", "outliner", "organize", "move"),
        description=(
            "Move actors into Outliner folders (auto-creates folders). "
            "Supports single item or batch items[]. Use empty folder_path to unfolder."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "actor_name": {"type": "string", "description": "Actor name or label"},
                "folder_path": {"type": "string", "description": "Target folder path (e.g. 'Enemies/Flying')"},
                "items": {
                    "type": "array",
                    "description": "Batch folder operations",
                    "items": {
                        "type": "object",
                        "properties": {
                            "actor_name": {"type": "string"},
                            "folder_path": {"type": "string"},
                        },
                        "required": ["actor_name", "folder_path"],
                    },
                },
            },
        },
        examples=(
            {"actor_name": "BP_Fly_C_0", "folder_path": "Enemies/Flying"},
            {
                "items": [
                    {"actor_name": "BP_Fly_C_0", "folder_path": "Enemies/Flying"},
                    {"actor_name": "BP_SideScrolling_NPC_C_0", "folder_path": "Enemies/Ground"},
                ]
            },
        ),
    ),
    ActionDef(
        id="editor.select_actors",
        command="select_actors",
        tags=("editor", "actor", "select", "selection", "outliner"),
        description=(
            "Select or deselect actors in the editor. "
            "Mode: set (replace selection), add, remove, toggle."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "actor_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Actor names or labels to select",
                },
                "mode": {
                    "type": "string",
                    "enum": ["set", "add", "remove", "toggle"],
                    "description": "Selection mode (default: set)",
                },
            },
            "required": ["actor_names"],
        },
        capabilities=("read",),
        risk="safe",
        examples=(
            {"actor_names": ["BP_Fly_C_0", "BP_Fly_C_1"]},
            {"actor_names": ["PlayerStart0"], "mode": "add"},
        ),
    ),
    ActionDef(
        id="editor.get_outliner_tree",
        command="get_outliner_tree",
        tags=("editor", "outliner", "tree", "hierarchy", "folder", "actors", "read"),
        description=(
            "Get the World Outliner actor hierarchy organized by folders. "
            "Returns folders with their actors and unfoldered actors separately. "
            "Supports class and folder prefix filtering."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "class_filter": {"type": "string", "description": "Filter actors by class name substring"},
                "folder_filter": {"type": "string", "description": "Filter by folder path prefix"},
            },
        },
        capabilities=("read",),
        risk="safe",
        examples=(
            {},
            {"class_filter": "BP_Fly"},
            {"folder_filter": "Enemies"},
        ),
    ),
    # =========================================================================
    # P7: Asset Editor Actions
    # =========================================================================
    ActionDef(
        id="editor.open_asset_editor",
        command="open_asset_editor",
        tags=("editor", "asset", "open", "focus", "window", "tab"),
        description=(
            "Open the asset editor for a given asset and optionally bring it to focus. "
            "Works for Blueprints, Materials, Widget Blueprints, Data Assets, etc."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "asset_path": {
                    "type": "string",
                    "description": "Full content path of the asset, e.g. '/Game/Characters/BP_Hero'",
                },
                "focus": {
                    "type": "boolean",
                    "description": "Whether to focus the editor window after opening (default: true)",
                },
            },
            "required": ["asset_path"],
        },
        capabilities=("write",),
        risk="safe",
        examples=(
            {"asset_path": "/Game/Characters/BP_Hero"},
            {"asset_path": "/Game/Materials/M_Base", "focus": False},
        ),
    ),
    ActionDef(
        id="batch.execute",
        command="batch_execute",
        tags=("batch", "execute", "multi", "pipeline"),
        description="Execute multiple actions in a single TCP round-trip. Non-atomic: already-succeeded commands are NOT rolled back on failure.",
        input_schema={
            "type": "object",
            "properties": {
                "commands": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "description": "Action command name"},
                            "params": {"type": "object", "description": "Action parameters"}
                        },
                        "required": ["type"]
                    },
                    "description": "Array of commands to execute sequentially"
                },
                "stop_on_error": {"type": "boolean", "description": "Stop on first error (default: true)"}
            },
            "required": ["commands"]
        },
        risk="moderate",
        examples=(
            {"commands": [{"type": "compile_blueprint", "params": {"blueprint_name": "BP_Player"}}]},
            {"commands": [
                {"type": "create_blueprint", "params": {"name": "BP_Test", "parent_class": "Actor"}},
                {"type": "compile_blueprint", "params": {"blueprint_name": "BP_Test"}},
            ], "stop_on_error": True},
        ),
    ),
    # =========================================================================
    # P9: Asset Property Editing — DataAsset 直读/直写
    # =========================================================================
    ActionDef(
        id="editor.configure_gameplay_effect_target_tags",
        command="configure_gameplay_effect_target_tags",
        tags=("editor", "asset", "gameplay-effect", "gameplay-tags", "cooldown", "write"),
        description=(
            "Add or update a TargetTagsGameplayEffectComponent on a GameplayEffect Blueprint and grant "
            "the specified tag to the target actor. Useful for UE 5.7 cooldown GameplayEffects."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "asset_path": {"type": "string", "description": "GameplayEffect Blueprint asset path"},
                "tag_name": {"type": "string", "description": "GameplayTag to grant while the effect is active"},
                "save": {"type": "boolean", "description": "Whether to save the asset after setting (default: true)"},
            },
            "required": ["asset_path", "tag_name"],
        },
        capabilities=("write",),
        risk="moderate",
        examples=(
            {
                "asset_path": "/Game/P111/Blueprints/Weapons/Tablet/GE/GE_TabletPrimaryAttack_CD",
                "tag_name": "System.Limit.Disable.PrimaryAttack",
            },
        ),
    ),
    ActionDef(
        id="editor.configure_gameplay_effect_ignore_tags",
        command="configure_gameplay_effect_ignore_tags",
        tags=("editor", "asset", "gameplay-effect", "gameplay-tags", "buff", "immunity", "write"),
        description=(
            "Add or update a TargetTagRequirementsGameplayEffectComponent on a GameplayEffect Blueprint, "
            "appending the given tag to ApplicationTagRequirements.IgnoreTags ('Must Not Have Tags'). "
            "Useful for data-driven immunity: if the target already has the tag, this GameplayEffect "
            "cannot be applied to it (no C++ if-branch needed)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "asset_path": {"type": "string", "description": "GameplayEffect Blueprint asset path"},
                "tag_name": {"type": "string", "description": "GameplayTag that blocks this effect from applying when present on the target"},
                "save": {"type": "boolean", "description": "Whether to save the asset after setting (default: true)"},
            },
            "required": ["asset_path", "tag_name"],
        },
        capabilities=("write",),
        risk="moderate",
        examples=(
            {
                "asset_path": "/Game/P111/Blueprints/Weapons/Hammer/GE/GE_HammerDamage",
                "tag_name": "Status.Buff.Invulnerable",
            },
        ),
    ),
    ActionDef(
        id="editor.set_gameplay_effect_modifier_scalable_float",
        command="set_gameplay_effect_modifier_scalable_float",
        tags=("editor", "asset", "gameplay-effect", "modifier", "scalable-float", "buff", "write"),
        description=(
            "Set every ScalableFloat modifier magnitude on one or more GameplayEffect Blueprints. "
            "Preserves attributes, modifier ops, curves, tag requirements, and other modifier settings."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "asset_path": {
                    "type": "string",
                    "description": "Single GameplayEffect Blueprint asset path",
                },
                "asset_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Multiple GameplayEffect Blueprint asset paths",
                },
                "new_value": {
                    "type": "number",
                    "description": "Value written to each ScalableFloat.Value (default: 1.0)",
                },
                "save": {
                    "type": "boolean",
                    "description": "Save changed assets after writing (default: true)",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Report matching modifiers without modifying or saving assets (default: false)",
                },
            },
            "anyOf": [
                {"required": ["asset_path"]},
                {"required": ["asset_paths"]},
            ],
        },
        capabilities=("write",),
        risk="moderate",
        examples=(
            {
                "asset_path": "/Game/P111/Data/BUFF/GE_Buff_DamageUp",
                "new_value": 1.0,
                "dry_run": True,
            },
            {
                "asset_paths": [
                    "/Game/P111/Data/BUFF/GE_Buff_AttackSpeedUp",
                    "/Game/P111/Data/BUFF/GE_Buff_InfiniteAttackSpeed",
                ],
                "new_value": 1.0,
                "save": True,
            },
        ),
    ),
    ActionDef(
        id="editor.create_data_asset",
        command="create_data_asset",
        tags=("editor", "asset", "dataasset", "create", "write"),
        description=(
            "Create a UDataAsset-derived asset. Supports C++ DataAsset classes and Blueprint-generated "
            "DataAsset classes exposed by the editor bridge."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "asset_name": {
                    "type": "string",
                    "description": "Asset name without path, e.g. 'DA_LJCReward_AddGold_Default'",
                },
                "package_path": {
                    "type": "string",
                    "description": "Content package path, e.g. '/Game/P111/Data/LJC'",
                },
                "asset_class": {
                    "type": "string",
                    "description": "DataAsset class path or short name, e.g. '/Script/P111.LJCRewardProfileSet'",
                },
                "save": {
                    "type": "boolean",
                    "description": "Whether to save the new asset immediately (default: true)",
                },
            },
            "required": ["asset_name", "package_path", "asset_class"],
        },
        capabilities=("write",),
        risk="moderate",
        examples=(
            {
                "asset_name": "DA_LJCReward_AddGold_Default",
                "package_path": "/Game/P111/Data/LJC/Rewards",
                "asset_class": "/Script/P111.LJCRewardProfileSet",
            },
        ),
    ),
    ActionDef(
        id="editor.get_data_asset_property",
        command="get_data_asset_property",
        tags=("editor", "asset", "dataasset", "property", "read", "get"),
        description=(
            "Read a single UPROPERTY value from any UObject asset (DataAsset, Blueprint CDO, etc.). "
            "Returns the property value as a UE text-format string."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "asset_path": {
                    "type": "string",
                    "description": "Full content path of the asset, e.g. '/Game/P111/Combat/Data/DA_HammerSwing'",
                },
                "property_name": {
                    "type": "string",
                    "description": "UPROPERTY name in C++ (lowercase with underscores, e.g. 'cue_timeline', 'hit_event_tag')",
                },
            },
            "required": ["asset_path", "property_name"],
        },
        capabilities=("read",),
        risk="safe",
        examples=(
            {"asset_path": "/Game/P111/Combat/Data/DA_HammerSwing", "property_name": "cue_timeline"},
            {"asset_path": "/Game/P111/Combat/Data/DA_HammerSwing", "property_name": "hit_event_tag"},
        ),
    ),
    ActionDef(
        id="editor.get_blueprint_cdo_gameplay_tags",
        command="get_blueprint_cdo_gameplay_tags",
        tags=("editor", "asset", "blueprint", "cdo", "gameplay-tags", "property", "read", "introspect"),
        description=(
            "Read all GameplayTag-related properties from a Blueprint generated class default object. "
            "Returns exact property_path -> tags mappings, including nested structs, arrays, sets, and maps."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "asset_path": {
                    "type": "string",
                    "description": "Blueprint asset path, e.g. '/Game/P111/Blueprints/Weapons/Welding/GA/GA_Welding_Attack'",
                },
                "include_empty": {
                    "type": "boolean",
                    "description": "Whether to include empty GameplayTag properties (default: false)",
                },
            },
            "required": ["asset_path"],
        },
        capabilities=("read",),
        risk="safe",
        examples=(
            {"asset_path": "/Game/P111/Blueprints/Weapons/Welding/GA/GA_Welding_Attack"},
        ),
    ),
    ActionDef(
        id="editor.set_data_asset_property",
        command="set_data_asset_property",
        tags=("editor", "asset", "dataasset", "property", "set", "write"),
        description=(
            "Set a single UPROPERTY value on any UObject asset. Supports scalars, structs, arrays, maps. "
            "Uses UE import-text format. FText values use INVTEXT(\"...\") wrapping."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "asset_path": {
                    "type": "string",
                    "description": "Full content path of the asset",
                },
                "property_name": {
                    "type": "string",
                    "description": "UPROPERTY name in C++",
                },
                "property_value": {
                    "type": "string",
                    "description": "Value in UE text-format, e.g. 'true', '1.5', '((TimeOffset=0.8,CueTag=...))'",
                },
                "save": {
                    "type": "boolean",
                    "description": "Whether to save the asset after setting (default: true)",
                },
            },
            "required": ["asset_path", "property_name", "property_value"],
        },
        capabilities=("write",),
        risk="moderate",
        examples=(
            {"asset_path": "/Game/P111/Combat/Data/DA_HammerSwing", "property_name": "play_rate", "property_value": "1.5"},
        ),
    ),
]
