"""Function Management action definitions."""

from __future__ import annotations

from .. import ActionDef


_FUNCTION_MGMT_ACTIONS = [
    ActionDef(
        id="function.create",
        command="create_blueprint_function",
        tags=("function", "create", "graph", "blueprint"),
        description="Create a new function graph in a Blueprint with inputs/outputs",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "function_name": {"type": "string", "description": "Name of the function"},
                "inputs": {"type": "array", "items": {"type": "object"}, "description": "Input parameters with 'name' and 'type' keys"},
                "outputs": {"type": "array", "items": {"type": "object"}, "description": "Output parameters with 'name' and 'type' keys"},
                "is_pure": {"type": "boolean", "description": "Create as pure function (no exec pins)"}
            },
            "required": ["blueprint_name", "function_name"]
        },
        examples=({"blueprint_name": "BP_Player", "function_name": "GetHealthPercent", "outputs": [{"name": "Percent", "type": "Float"}], "is_pure": True},),
    ),
    ActionDef(
        id="blueprint.add_override_function",
        command="add_blueprint_override_function",
        tags=("blueprint", "function", "override", "inheritance", "parent"),
        description="Add an override implementation graph for a function inherited from the Blueprint parent class",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "function_name": {"type": "string", "description": "Inherited function name to override"},
                "compile": {"type": "boolean", "description": "Compile the Blueprint after creating the override graph"}
            },
            "required": ["blueprint_name", "function_name"]
        },
        examples=(
            {"blueprint_name": "MeleeHit_NotifyState", "function_name": "Received_NotifyEnd", "compile": True},
        ),
    ),
    ActionDef(
        id="function.call",

        command="call_blueprint_function",
        tags=("function", "call", "invoke", "node"),
        description="Add a node that calls a custom Blueprint function",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Blueprint where to add the node"},
                "target_blueprint": {"type": "string", "description": "Blueprint containing the function"},
                "function_name": {"type": "string", "description": "Name of the function"},
                "node_position": {"type": "array", "items": {"type": "number"}, "description": "[X, Y] position"},
                "graph_name": {"type": "string", "description": "Optional graph name"}
            },
            "required": ["blueprint_name", "target_blueprint", "function_name"]
        },
    ),
    ActionDef(
        id="function.delete",
        command="delete_blueprint_function",
        tags=("function", "delete", "remove"),
        description="Delete a custom function from a Blueprint",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "function_name": {"type": "string", "description": "Name of the function to delete"}
            },
            "required": ["blueprint_name", "function_name"]
        },
        capabilities=("write", "destructive"),
        risk="moderate",
    ),
    ActionDef(
        id="function.rename",
        command="rename_blueprint_function",
        tags=("function", "rename", "refactor"),
        description="Rename a custom function graph in a Blueprint",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "function_name": {"type": "string", "description": "Current function name"},
                "new_name": {"type": "string", "description": "New function name"}
            },
            "required": ["blueprint_name", "function_name", "new_name"]
        },
    ),
    ActionDef(
        id="macro.rename",
        command="rename_blueprint_macro",
        tags=("macro", "rename", "refactor"),
        description="Rename a custom macro graph in a Blueprint",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "macro_name": {"type": "string", "description": "Current macro name"},
                "new_name": {"type": "string", "description": "New macro name"}
            },
            "required": ["blueprint_name", "macro_name", "new_name"]
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
