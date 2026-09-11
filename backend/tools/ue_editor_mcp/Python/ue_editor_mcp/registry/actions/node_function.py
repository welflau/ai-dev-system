"""Node Functions action definitions."""

from __future__ import annotations

from .. import ActionDef


_NODE_FUNCTION_ACTIONS = [
    ActionDef(
        id="node.add_function_call",
        command="add_blueprint_function_node",
        tags=("node", "function", "call", "method"),
        description="Add a function call node to a Blueprint graph",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "target": {"type": "string", "description": "Target object (component name or self)"},
                "function_name": {"type": "string", "description": "Name of the function to call"},
                "params": {"type": "string", "description": "Parameters as JSON string"},
                "node_position": {"type": "string", "description": "[X, Y] position"},
                "graph_name": {"type": "string", "description": "Optional graph name"}
            },
            "required": ["blueprint_name", "target", "function_name"]
        },
        examples=({"blueprint_name": "BP_Player", "target": "self", "function_name": "PrintString"},),
    ),
    ActionDef(
        id="node.add_spawn_actor",
        command="add_spawn_actor_from_class_node",
        tags=("node", "spawn", "actor", "class"),
        description="Add a SpawnActorFromClass node for runtime actor spawning",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "class_to_spawn": {"type": "string", "description": "Class to spawn (e.g., BP_Enemy)"},
                "node_position": {"type": "array", "items": {"type": "number"}, "description": "[X, Y] position"},
                "graph_name": {"type": "string", "description": "Optional graph name"}
            },
            "required": ["blueprint_name", "class_to_spawn"]
        },
    ),
    ActionDef(
        id="node.set_pin_default",
        command="set_node_pin_default",
        tags=("node", "pin", "default", "value", "set"),
        description="Set the default value of a pin on an existing node",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "node_id": {"type": "string", "description": "GUID of the node"},
                "pin_name": {"type": "string", "description": "Name of the pin"},
                "default_value": {"type": "string", "description": "Default value as string"},
                "graph_name": {"type": "string", "description": "Optional graph name"}
            },
            "required": ["blueprint_name", "node_id", "pin_name", "default_value"]
        },
    ),
    ActionDef(
        id="node.set_object_property",
        command="set_object_property",
        tags=("node", "property", "set", "external", "object"),
        description="Create a Set Property node for an external object (e.g., bShowMouseCursor on PlayerController)",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "owner_class": {"type": "string", "description": "Class that owns the property"},
                "property_name": {"type": "string", "description": "Property to set"},
                "node_position": {"type": "array", "items": {"type": "number"}, "description": "[X, Y] position"},
                "graph_name": {"type": "string", "description": "Optional graph name"}
            },
            "required": ["blueprint_name", "owner_class", "property_name"]
        },
    ),
    ActionDef(
        id="node.add_get_subsystem",
        command="add_blueprint_get_subsystem_node",
        tags=("node", "subsystem", "get", "reference"),
        description="Add a GetSubsystem node to get a reference to a subsystem",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "subsystem_class": {"type": "string", "description": "Class name of the subsystem"},
                "node_position": {"type": "array", "items": {"type": "number"}, "description": "[X, Y] position"},
                "graph_name": {"type": "string", "description": "Optional graph name"}
            },
            "required": ["blueprint_name", "subsystem_class"]
        },
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
