"""Node Events action definitions."""

from __future__ import annotations

from .. import ActionDef


_NODE_EVENT_ACTIONS = [
    ActionDef(
        id="node.add_event",
        command="add_blueprint_event_node",
        tags=("node", "event", "beginplay", "tick", "graph"),
        description="Add an event node (ReceiveBeginPlay, ReceiveTick, etc.) to a Blueprint event graph",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "event_name": {"type": "string", "description": "Event name (ReceiveBeginPlay, ReceiveTick, etc.)"},
                "node_position": {"type": "string", "description": "[X, Y] position"}
            },
            "required": ["blueprint_name", "event_name"]
        },
        examples=({"blueprint_name": "BP_Player", "event_name": "ReceiveBeginPlay"},),
    ),
    ActionDef(
        id="node.add_custom_event",
        command="add_blueprint_custom_event",
        tags=("node", "event", "custom", "delegate"),
        description="Add a Custom Event node with optional parameters",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "event_name": {"type": "string", "description": "Name for the custom event"},
                "node_position": {"type": "string", "description": "[X, Y] position"},
                "parameters": {"type": "array", "items": {"type": "object"}, "description": "Parameters with 'name' and 'type' keys"}
            },
            "required": ["blueprint_name", "event_name"]
        },
        examples=({"blueprint_name": "BP_Player", "event_name": "OnDamaged", "parameters": [{"name": "Damage", "type": "Float"}]},),
    ),
    ActionDef(
        id="node.add_custom_event_for_delegate",
        command="add_custom_event_for_delegate",
        tags=("node", "event", "custom", "delegate", "signature", "bind"),
        description=(
            "Add a Custom Event node whose signature automatically matches a delegate. "
            "Supports two modes: (1) Class property mode: delegate_class + delegate_name, "
            "(2) Node pin mode: source_node_id + source_pin_name. "
            "The resulting event's pins are locked to the delegate signature and can be "
            "directly connected to the delegate pin."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "event_name": {"type": "string", "description": "Name for the custom event"},
                "delegate_class": {
                    "type": "string",
                    "description": "Class that owns the delegate (e.g., 'PrimitiveComponent', 'Actor'). Used with delegate_name."
                },
                "delegate_name": {
                    "type": "string",
                    "description": "Delegate property name (e.g., 'OnComponentBeginOverlap'). If delegate_class is omitted, searches the Blueprint's own class."
                },
                "source_node_id": {
                    "type": "string",
                    "description": "Node GUID to resolve delegate signature from and optionally connect to"
                },
                "source_pin_name": {
                    "type": "string",
                    "description": "Pin name on source node (defaults to first unconnected delegate input pin)"
                },
                "auto_connect": {
                    "type": "boolean",
                    "description": "Connect delegate output to source pin (default: true, only for source_node_id mode)"
                },
                "node_position": {"type": "string", "description": "[X, Y] position"},
                "graph_name": {"type": "string", "description": "Optional target graph name"}
            },
            "required": ["blueprint_name", "event_name"]
        },
        examples=(
            {
                "blueprint_name": "BP_Player",
                "event_name": "OnOverlap",
                "delegate_class": "PrimitiveComponent",
                "delegate_name": "OnComponentBeginOverlap"
            },
            {
                "blueprint_name": "BP_Player",
                "event_name": "OnMyDispatcher",
                "delegate_name": "MyEventDispatcher"
            },
            {
                "blueprint_name": "BP_Player",
                "event_name": "OnDelegateEvent",
                "source_node_id": "<node-guid>",
                "source_pin_name": "Event"
            },
        ),
    ),
    ActionDef(
        id="node.add_input_action",
        command="add_blueprint_input_action_node",
        tags=("node", "input", "action", "legacy"),
        description="Add an input action event node (legacy input system)",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "action_name": {"type": "string", "description": "Name of the input action"},
                "node_position": {"type": "string", "description": "[X, Y] position"}
            },
            "required": ["blueprint_name", "action_name"]
        },
    ),
    ActionDef(
        id="node.add_enhanced_input_action",
        command="add_enhanced_input_action_node",
        tags=("node", "input", "enhanced", "action", "started", "triggered"),
        description="Add an Enhanced Input Action event node with Started/Triggered/Completed exec pins",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "action_name": {"type": "string", "description": "Name of the Input Action asset (e.g., IA_Move)"},
                "action_path": {"type": "string", "description": "Content path to asset (default: /Game/Input)"},
                "node_position": {"type": "string", "description": "[X, Y] position"}
            },
            "required": ["blueprint_name", "action_name"]
        },
        examples=({"blueprint_name": "BP_Player", "action_name": "IA_Move"},),
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
