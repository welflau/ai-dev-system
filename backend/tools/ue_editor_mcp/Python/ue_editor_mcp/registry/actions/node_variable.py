"""Node Variables action definitions."""

from __future__ import annotations

from .. import ActionDef


_NODE_VARIABLE_ACTIONS = [
    ActionDef(
        id="variable.create",
        command="add_blueprint_variable",
        tags=("variable", "create", "add", "member"),
        description="Add a member variable to a Blueprint (supports Boolean, Int, Float, Double, String, Vector, Rotator, Transform, and UObject types)",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "variable_name": {"type": "string", "description": "Name of the variable"},
                "variable_type": {"type": "string", "description": "Type (Boolean, Integer, Float, Vector, String, Rotator, Transform, etc.)"},
                "is_exposed": {"type": "boolean", "description": "Expose to editor"}
            },
            "required": ["blueprint_name", "variable_name", "variable_type"]
        },
        examples=({"blueprint_name": "BP_Player", "variable_name": "Health", "variable_type": "Float"},),
    ),
    ActionDef(
        id="variable.add_getter",
        command="add_blueprint_variable_get",
        tags=("variable", "get", "getter", "node"),
        description="Add a Variable Get node to a Blueprint graph",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "variable_name": {"type": "string", "description": "Name of the variable"},
                "node_position": {"type": "string", "description": "[X, Y] position"},
                "graph_name": {"type": "string", "description": "Optional graph name"}
            },
            "required": ["blueprint_name", "variable_name"]
        },
    ),
    ActionDef(
        id="variable.add_setter",
        command="add_blueprint_variable_set",
        tags=("variable", "set", "setter", "node"),
        description="Add a Variable Set node to a Blueprint graph",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "variable_name": {"type": "string", "description": "Name of the variable"},
                "node_position": {"type": "string", "description": "[X, Y] position"},
                "graph_name": {"type": "string", "description": "Optional graph name"}
            },
            "required": ["blueprint_name", "variable_name"]
        },
    ),
    ActionDef(
        id="variable.add_local",
        command="add_function_local_variable",
        tags=("variable", "local", "function", "add"),
        description="Add a local variable to a Blueprint function",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "function_name": {"type": "string", "description": "Function name"},
                "variable_name": {"type": "string", "description": "Variable name"},
                "variable_type": {"type": "string", "description": "Type (Boolean, Integer, Float, Vector, etc.)"},
                "default_value": {"type": "string", "description": "Optional default value"}
            },
            "required": ["blueprint_name", "function_name", "variable_name", "variable_type"]
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
