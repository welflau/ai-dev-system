"""Struct & Switch Nodes action definitions."""

from __future__ import annotations

from .. import ActionDef


_STRUCT_SWITCH_ACTIONS = [
    ActionDef(
        id="node.add_make_struct",
        command="add_make_struct_node",
        tags=("node", "struct", "make", "construct"),
        description="Add a Make Struct node (Make Vector, Make IntPoint, Make LinearColor, etc.)",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "struct_type": {"type": "string", "description": "Struct type: IntPoint, Vector, Vector2D, Rotator, Transform, LinearColor, Color"},
                "pin_defaults": {"type": "object", "description": "Default pin values (e.g., {'X': '1920', 'Y': '1080'})"},
                "node_position": {"type": "array", "items": {"type": "number"}, "description": "[X, Y] position"},
                "graph_name": {"type": "string", "description": "Optional graph name"}
            },
            "required": ["blueprint_name", "struct_type"]
        },
    ),
    ActionDef(
        id="node.add_break_struct",
        command="add_break_struct_node",
        tags=("node", "struct", "break", "decompose"),
        description="Add a Break Struct node (Break Vector, Break IntPoint, etc.)",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "struct_type": {"type": "string", "description": "Struct type: IntPoint, Vector, Vector2D, Rotator, Transform, LinearColor, Color"},
                "node_position": {"type": "array", "items": {"type": "number"}, "description": "[X, Y] position"},
                "graph_name": {"type": "string", "description": "Optional graph name"}
            },
            "required": ["blueprint_name", "struct_type"]
        },
    ),
    ActionDef(
        id="node.add_switch_string",
        command="add_switch_on_string_node",
        tags=("node", "switch", "string", "case", "flow"),
        description="Add a Switch on String node with case options",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "cases": {"type": "array", "items": {"type": "string"}, "description": "String case values"},
                "node_position": {"type": "array", "items": {"type": "number"}, "description": "[X, Y] position"},
                "graph_name": {"type": "string", "description": "Optional graph name"}
            },
            "required": ["blueprint_name"]
        },
    ),
    ActionDef(
        id="node.add_switch_int",
        command="add_switch_on_int_node",
        tags=("node", "switch", "int", "case", "flow"),
        description="Add a Switch on Int node with case options",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "start_index": {"type": "integer", "description": "Starting index (default: 0)"},
                "cases": {"type": "array", "items": {"type": "integer"}, "description": "Number of cases"},
                "node_position": {"type": "array", "items": {"type": "number"}, "description": "[X, Y] position"},
                "graph_name": {"type": "string", "description": "Optional graph name"}
            },
            "required": ["blueprint_name"]
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
