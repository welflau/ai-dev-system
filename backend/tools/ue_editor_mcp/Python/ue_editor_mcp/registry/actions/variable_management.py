"""Variable Management action definitions."""

from __future__ import annotations

from .. import ActionDef


_VARIABLE_MGMT_ACTIONS = [
    ActionDef(
        id="variable.set_default",
        command="set_blueprint_variable_default",
        tags=("variable", "default", "value", "set"),
        description="Set the default value of a Blueprint member variable",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "variable_name": {"type": "string", "description": "Name of the variable"},
                "default_value": {"type": "string", "description": "Default value as string"}
            },
            "required": ["blueprint_name", "variable_name", "default_value"]
        },
    ),
    ActionDef(
        id="variable.delete",
        command="delete_blueprint_variable",
        tags=("variable", "delete", "remove"),
        description="Delete a member variable from a Blueprint",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "variable_name": {"type": "string", "description": "Name of the variable to delete"}
            },
            "required": ["blueprint_name", "variable_name"]
        },
        capabilities=("write", "destructive"),
        risk="moderate",
    ),
    ActionDef(
        id="variable.rename",
        command="rename_blueprint_variable",
        tags=("variable", "rename", "refactor"),
        description="Rename a member variable in a Blueprint (updates all getter/setter references)",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "old_name": {"type": "string", "description": "Current variable name"},
                "new_name": {"type": "string", "description": "New variable name"}
            },
            "required": ["blueprint_name", "old_name", "new_name"]
        },
    ),
    ActionDef(
        id="variable.set_metadata",
        command="set_variable_metadata",
        tags=("variable", "metadata", "category", "tooltip", "replicated"),
        description="Set metadata on a Blueprint variable: category, tooltip, instance_editable, replicated, private, etc.",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "variable_name": {"type": "string", "description": "Name of the variable"},
                "category": {"type": "string", "description": "Variable category"},
                "tooltip": {"type": "string", "description": "Tooltip description"},
                "instance_editable": {"type": "boolean", "description": "Expose to details panel"},
                "blueprint_read_only": {"type": "boolean", "description": "Read-only in graph"},
                "expose_on_spawn": {"type": "boolean", "description": "Expose on SpawnActor node"},
                "replicated": {"type": "boolean", "description": "Enable network replication"},
                "private": {"type": "boolean", "description": "Accessible only within this Blueprint"}
            },
            "required": ["blueprint_name", "variable_name"]
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
