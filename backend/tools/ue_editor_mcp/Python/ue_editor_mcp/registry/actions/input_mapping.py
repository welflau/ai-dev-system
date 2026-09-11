"""Input Mappings action definitions."""

from __future__ import annotations

from .. import ActionDef


_INPUT_ACTIONS = [
    ActionDef(
        id="input.create_mapping",
        command="create_input_mapping",
        tags=("input", "mapping", "legacy", "key", "bind"),
        description="Create a legacy input mapping (Action or Axis)",
        input_schema={
            "type": "object",
            "properties": {
                "action_name": {"type": "string", "description": "Input action name"},
                "key": {"type": "string", "description": "Key (SpaceBar, W, LeftMouseButton, etc.)"},
                "input_type": {"type": "string", "description": "Type: Action or Axis"},
                "scale": {"type": "number", "description": "Scale for Axis (1.0 or -1.0)"}
            },
            "required": ["action_name", "key"]
        },
    ),
    ActionDef(
        id="input.create_action",
        command="create_input_action",
        tags=("input", "action", "enhanced", "create"),
        description="Create an Enhanced Input Action asset",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name (e.g., IA_Move)"},
                "value_type": {"type": "string", "description": "Boolean, Axis1D/Float, Axis2D/Vector2D, Axis3D/Vector"},
                "path": {"type": "string", "description": "Content path (default: /Game/Input)"}
            },
            "required": ["name"]
        },
        examples=({"name": "IA_Move", "value_type": "Axis2D"},),
    ),
    ActionDef(
        id="input.create_mapping_context",
        command="create_input_mapping_context",
        tags=("input", "mapping", "context", "enhanced", "create"),
        description="Create an Enhanced Input Mapping Context asset",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name (e.g., IMC_Default)"},
                "path": {"type": "string", "description": "Content path (default: /Game/Input)"}
            },
            "required": ["name"]
        },
        examples=({"name": "IMC_Default"},),
    ),
    ActionDef(
        id="input.add_key_mapping",
        command="add_key_mapping_to_context",
        tags=("input", "key", "mapping", "bind", "modifier"),
        description="Add a key mapping to an Input Mapping Context with optional modifiers",
        input_schema={
            "type": "object",
            "properties": {
                "context_name": {"type": "string", "description": "IMC asset name"},
                "action_name": {"type": "string", "description": "Input Action asset name"},
                "key": {"type": "string", "description": "Key (W, A, SpaceBar, etc.)"},
                "modifiers": {"type": "array", "items": {"type": "string"}, "description": "Modifiers: Negate, SwizzleYXZ, etc."},
                "context_path": {"type": "string", "description": "Content folder containing the IMC asset, e.g. /Game/Input; do not include Asset.Asset"},
                "action_path": {"type": "string", "description": "Content folder containing the IA asset, e.g. /Game/Input/Actions; do not include Asset.Asset"}
            },
            "required": ["context_name", "action_name", "key"]
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
