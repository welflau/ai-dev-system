"""Async Action Nodes action definitions."""

from __future__ import annotations

from .. import ActionDef


_ASYNC_ACTION_ACTIONS = [
    ActionDef(
        id="node.add_async_action",
        command="add_async_action_node",
        tags=("node", "async", "action", "latent", "third-party", "uforge", "http"),
        description="Add an async action node (UK2Node_AsyncAction) by class name. Supports any UBlueprintAsyncActionBase subclass including third-party plugins like UForge HTTP & JSON Utility.",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the target Blueprint"},
                "class_name": {"type": "string", "description": "C++ class name of the async action (e.g. 'HTTPProxyAsync', 'DownloadImage'). Supports fuzzy matching."},
                "factory_function": {"type": "string", "description": "Factory function name (auto-detected if omitted)"},
                "node_position": {"type": "array", "items": {"type": "number"}, "description": "[X, Y] position"},
                "graph_name": {"type": "string", "description": "Target graph (default: EventGraph)"},
                "pin_defaults": {"type": "object", "description": "Object mapping pin_name -> default_value string"}
            },
            "required": ["blueprint_name", "class_name"]
        },
        examples=(
            {"blueprint_name": "WBP_Weather", "class_name": "HTTPProxyAsync", "node_position": [500, 0]},
            {"blueprint_name": "BP_Player", "class_name": "DownloadImage", "node_position": [300, 0]},
        ),
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
