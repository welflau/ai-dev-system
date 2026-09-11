"""Blueprint Management action definitions."""

from __future__ import annotations

from .. import ActionDef


_BLUEPRINT_ACTIONS = [
    ActionDef(
        id="blueprint.create",
        command="create_blueprint",
        tags=("blueprint", "create", "asset"),
        description="Create a new Blueprint class",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the Blueprint"},
                "parent_class": {"type": "string", "description": "Parent class (Actor, Pawn, Character, GameModeBase, etc.)"},
                "path": {"type": "string", "description": "Content path (default: /Game/Blueprints)"},
                "if_exists": {"type": "string", "enum": ["error", "overwrite", "skip", "reuse"], "description": "Existing asset policy. Default error; use overwrite for clean retry, skip/reuse to continue with existing asset."}
            },
            "required": ["name", "parent_class"]
        },
        examples=(
            {"name": "BP_Player", "parent_class": "Character"},
            {"name": "BP_Projectile", "parent_class": "Actor", "path": "/Game/Weapons"},
        ),
    ),
    ActionDef(
        id="blueprint.compile",
        command="compile_blueprint",
        tags=("blueprint", "compile", "validate"),
        description="Compile a Blueprint and check for errors",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint to compile"}
            },
            "required": ["blueprint_name"]
        },
        examples=({"blueprint_name": "BP_Player"},),
    ),
    ActionDef(
        id="blueprint.refresh_all_nodes",
        command="refresh_blueprint_nodes",
        tags=("blueprint", "refresh", "reconstruct", "repair", "nodes"),
        description=(
            "Refresh and reconstruct every node in a Blueprint using Unreal's native "
            "Refresh All Nodes flow while preserving compatible links and defaults"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {
                    "type": "string",
                    "description": "Name of the Blueprint to refresh",
                }
            },
            "required": ["blueprint_name"],
        },
        examples=({"blueprint_name": "BP_Player"},),
    ),
    ActionDef(
        id="blueprint.repair_component_references",
        command="repair_blueprint_component_references",
        tags=("blueprint", "component", "repair", "references", "nodes"),
        description=(
            "Rebind stale Get/Set and component-bound event nodes to the current "
            "SCS component variable GUID after a component was deleted and recreated"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {
                    "type": "string",
                    "description": "Name of the Blueprint to repair",
                },
                "component_name": {
                    "type": "string",
                    "description": "SCS component variable name to rebind",
                },
            },
            "required": ["blueprint_name", "component_name"],
        },
        examples=(
            {
                "blueprint_name": "BP_Player",
                "component_name": "AIPort",
            },
        ),
        risk="moderate",
    ),
    ActionDef(
        id="blueprint.set_property",
        command="set_blueprint_property",
        tags=("blueprint", "property", "set", "default"),
        description="Set a property on a Blueprint class default object",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "property_name": {"type": "string", "description": "Name of the property"},
                "property_value": {"type": "string", "description": "Value to set"}
            },
            "required": ["blueprint_name", "property_name", "property_value"]
        },
        examples=({"blueprint_name": "BP_Player", "property_name": "MaxHealth", "property_value": "100.0"},),
    ),
    ActionDef(
        id="blueprint.spawn_actor",
        command="spawn_blueprint_actor",
        tags=("blueprint", "spawn", "actor", "level"),
        description="Spawn an instance of a Blueprint in the level",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint to spawn"},
                "actor_name": {"type": "string", "description": "Name for the spawned actor"},
                "location": {"type": "array", "items": {"type": "number"}, "description": "[x, y, z]"},
                "rotation": {"type": "array", "items": {"type": "number"}, "description": "[pitch, yaw, roll]"}
            },
            "required": ["blueprint_name", "actor_name"]
        },
        examples=({"blueprint_name": "BP_Enemy", "actor_name": "Enemy1", "location": [100, 0, 50]},),
    ),
    ActionDef(
        id="blueprint.set_parent_class",
        command="set_blueprint_parent_class",
        tags=("blueprint", "parent", "reparent", "inherit"),
        description="Change the parent class of a Blueprint (reparent)",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "parent_class": {"type": "string", "description": "New parent class name or full path"}
            },
            "required": ["blueprint_name", "parent_class"]
        },
        examples=({"blueprint_name": "BP_Player", "parent_class": "Character"},),
    ),
    ActionDef(
        id="blueprint.add_interface",
        command="add_blueprint_interface",
        tags=("blueprint", "interface", "add", "implement"),
        description="Add an interface implementation to a Blueprint",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "interface_name": {"type": "string", "description": "Interface class name or full path"}
            },
            "required": ["blueprint_name", "interface_name"]
        },
        examples=({"blueprint_name": "BP_Chest", "interface_name": "BPI_Interactable"},),
    ),
    ActionDef(
        id="blueprint.remove_interface",
        command="remove_blueprint_interface",
        tags=("blueprint", "interface", "remove"),
        description="Remove an implemented interface from a Blueprint",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "interface_name": {"type": "string", "description": "Interface class name or path to remove"}
            },
            "required": ["blueprint_name", "interface_name"]
        },
        capabilities=("write", "destructive"),
        risk="moderate",
        examples=({"blueprint_name": "BP_Chest", "interface_name": "BPI_Interactable"},),
    ),
    ActionDef(
        id="blueprint.add_component",
        command="add_component_to_blueprint",
        tags=("blueprint", "component", "add"),
        description="Add a component to a Blueprint",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "component_type": {"type": "string", "description": "Type of component (StaticMeshComponent, BoxComponent, etc.)"},
                "component_name": {"type": "string", "description": "Name for the component"},
                "location": {"type": "array", "items": {"type": "number"}, "description": "[x, y, z]"},
                "rotation": {"type": "array", "items": {"type": "number"}, "description": "[pitch, yaw, roll]"},
                "scale": {"type": "array", "items": {"type": "number"}, "description": "[x, y, z]"},
                "parent_component": {"type": "string", "description": "Optional SCS parent component name; preserves the component tree attachment."},
                "niagara_system": {"type": "string", "description": "Optional Niagara system asset path when component_type is NiagaraComponent."}
            },
            "required": ["blueprint_name", "component_type", "component_name"]
        },
        examples=(
            {"blueprint_name": "BP_Player", "component_type": "CapsuleComponent", "component_name": "Capsule"},
            {"blueprint_name": "BP_Lamp", "component_type": "PointLightComponent", "component_name": "Light", "location": [0, 0, 100]},
        ),
    ),
    ActionDef(
        id="blueprint.remove_component",
        command="remove_component_from_blueprint",
        tags=("blueprint", "component", "remove", "delete"),
        description="Remove an SCS component owned by a Blueprint",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "component_name": {"type": "string", "description": "Name of the component to remove"}
            },
            "required": ["blueprint_name", "component_name"]
        },
        capabilities=("write", "destructive"),
        risk="moderate",
        examples=(
            {"blueprint_name": "BP_Player", "component_name": "UnusedCollision"},
        ),
    ),
    ActionDef(
        id="blueprint.get_summary",
        command="get_blueprint_summary",
        tags=("blueprint", "summary", "introspect", "info", "read"),
        description="Get a comprehensive summary of a Blueprint: variables, functions, event graphs, components, parent class, compile status, and interfaces",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint (e.g. BP_Player)"},
                "asset_path": {"type": "string", "description": "Full asset path if name is ambiguous"}
            }
        },
        capabilities=("read",),
        examples=({"blueprint_name": "BP_Player"},),
    ),
    ActionDef(
        id="blueprint.describe_full",
        command="describe_blueprint_full",
        tags=("blueprint", "describe", "full", "snapshot", "introspect", "topology", "graphs", "variables", "components", "read"),
        description=(
            "Single-call comprehensive Blueprint snapshot: summary (variables, components, interfaces, compile status) "
            "+ ALL graph topologies (EventGraph, function graphs, macro graphs) with nodes, pins, edges. "
            "Replaces: 1x blueprint.get_summary + Nx graph.describe. Default compact pin serialization; "
            "use include_pin_details=true for full FEdGraphPinType."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint (e.g. BP_Player)"},
                "asset_path": {"type": "string", "description": "Full asset path if name is ambiguous"},
                "include_pin_details": {
                    "type": "boolean",
                    "description": "If true, serialize full PinType details (sub_category_object, is_array, etc.). Default: false (compact mode).",
                    "default": False
                },
                "include_function_signatures": {
                    "type": "boolean",
                    "description": "If true, inline function signatures for CallFunction nodes. Default: false.",
                    "default": False
                }
            }
        },
        capabilities=("read",),
        examples=(
            {"blueprint_name": "BP_Player"},
            {"blueprint_name": "BP_Enemy", "include_pin_details": True, "include_function_signatures": True},
        ),
    ),
    ActionDef(
        id="blueprint.create_colored_material",
        command="create_colored_material",
        tags=("material", "color", "create", "simple"),
        description="Create a simple colored material asset",
        input_schema={
            "type": "object",
            "properties": {
                "material_name": {"type": "string", "description": "Name for the material"},
                "color": {"type": "array", "items": {"type": "number"}, "description": "[R, G, B] values 0.0-1.0"},
                "path": {"type": "string", "description": "Content path (default: /Game/Materials)"}
            },
            "required": ["material_name"]
        },
        examples=({"material_name": "M_Red", "color": [1.0, 0.0, 0.0]},),
    ),
    # =========================================================================
    # P9: Asset Property Editing — DataAsset 直读/直写
    # =========================================================================
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
