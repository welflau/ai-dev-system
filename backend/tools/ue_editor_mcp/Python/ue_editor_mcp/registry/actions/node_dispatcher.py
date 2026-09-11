"""Node Event Dispatchers action definitions."""

from __future__ import annotations

from .. import ActionDef


_NODE_DISPATCHER_ACTIONS = [
    ActionDef(
        id="dispatcher.create",
        command="add_event_dispatcher",
        tags=("dispatcher", "event", "multicast", "delegate", "create"),
        description="Add an Event Dispatcher (multicast delegate) to a Blueprint",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "dispatcher_name": {"type": "string", "description": "Name for the dispatcher"},
                "parameters": {"type": "array", "items": {"type": "object"}, "description": "Parameters with 'name' and 'type' keys"}
            },
            "required": ["blueprint_name", "dispatcher_name"]
        },
        examples=({"blueprint_name": "BP_Door", "dispatcher_name": "OnDoorOpened"},),
    ),
    ActionDef(
        id="dispatcher.call",
        command="call_event_dispatcher",
        tags=("dispatcher", "event", "call", "broadcast"),
        description="Add a Call node for an Event Dispatcher (broadcasts the event)",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "dispatcher_name": {"type": "string", "description": "Name of the dispatcher"},
                "node_position": {"type": "array", "items": {"type": "number"}, "description": "[X, Y] position"},
                "graph_name": {"type": "string", "description": "Optional graph name"}
            },
            "required": ["blueprint_name", "dispatcher_name"]
        },
    ),
    ActionDef(
        id="dispatcher.bind",
        command="bind_event_dispatcher",
        tags=("dispatcher", "event", "bind", "listen"),
        description="Add a Bind node for an Event Dispatcher (creates bind node + matching custom event)",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Blueprint where to add the bind node"},
                "dispatcher_name": {"type": "string", "description": "Name of the dispatcher to bind"},
                "target_blueprint": {"type": "string", "description": "Blueprint that owns the dispatcher"},
                "node_position": {"type": "array", "items": {"type": "number"}, "description": "[X, Y] position"},
                "graph_name": {"type": "string", "description": "Optional graph name"}
            },
            "required": ["blueprint_name", "dispatcher_name"]
        },
    ),
    ActionDef(
        id="dispatcher.create_event",
        command="create_event_delegate",
        tags=("dispatcher", "delegate", "event", "create", "function", "bind"),
        description="Create a 'Create Event' (K2Node_CreateDelegate) node that binds a function to a delegate pin. Works inside function graphs where CustomEvent is unavailable.",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "function_name": {"type": "string", "description": "Name of the function to bind as delegate"},
                "connect_to_node_id": {"type": "string", "description": "Node GUID to auto-connect delegate output to"},
                "connect_to_pin": {"type": "string", "description": "Target delegate pin name (default: 'Event')"},
                "node_position": {"type": "array", "items": {"type": "number"}, "description": "[X, Y] position"},
                "graph_name": {"type": "string", "description": "Optional function graph name"}
            },
            "required": ["blueprint_name", "function_name"]
        },
        examples=({"blueprint_name": "BP_Player", "function_name": "OnTTSEnvelope", "graph_name": "SetupTTS"},),
    ),
    ActionDef(
        id="component.bind_event",
        command="bind_component_event",
        tags=("component", "delegate", "event", "bind", "actor", "signal"),
        description=(
            "Bind a component delegate event (e.g., OnComponentBeginOverlap, OnTTSEnvelope). "
            "Creates a UK2Node_ComponentBoundEvent in the Blueprint event graph. "
            "The component must exist as a UPROPERTY on the Blueprint's GeneratedClass "
            "(added via SCS in editor or declared in C++ parent)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "component_name": {"type": "string", "description": "Component variable name on the Blueprint (e.g., 'AIPortComponent', 'CapsuleComponent')"},
                "event_name": {"type": "string", "description": "Delegate name on the component class (e.g., 'OnTTSEnvelope', 'OnComponentBeginOverlap')"},
                "node_position": {"type": "array", "items": {"type": "number"}, "description": "[X, Y] position"},
                "graph_name": {"type": "string", "description": "Optional graph name (defaults to EventGraph)"}
            },
            "required": ["blueprint_name", "component_name", "event_name"]
        },
        examples=(
            {"blueprint_name": "BP_SideScrollingCharacter", "component_name": "AIPortComponent", "event_name": "OnTTSEnvelope"},
            {"blueprint_name": "BP_Player", "component_name": "CapsuleComponent", "event_name": "OnComponentBeginOverlap"},
        ),
    ),
    ActionDef(
        id="node.bind_uobject_delegate",
        command="bind_uobject_delegate",
        tags=("node", "uobject", "delegate", "event", "bind", "async", "callback"),
        description=(
            "Bind a BlueprintAssignable multicast delegate on a UObject reference pin. "
            "Creates a Bind Event node plus a signature-matched Custom Event, then connects "
            "the source object pin and delegate event pin automatically."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint to edit"},
                "target_node_id": {"type": "string", "description": "GUID of the node that outputs the target UObject reference"},
                "target_pin_name": {"type": "string", "description": "Output pin name containing the UObject reference (e.g., 'ReturnValue')"},
                "delegate_name": {"type": "string", "description": "BlueprintAssignable delegate name on the UObject class (e.g., 'OnCreateResult')"},
                "event_name": {"type": "string", "description": "Optional custom event name to create (defaults to 'On' + delegate_name)"},
                "node_position": {"type": "array", "items": {"type": "number"}, "description": "[X, Y] position for the bind node"},
                "graph_name": {"type": "string", "description": "Optional graph name (defaults to EventGraph)"}
            },
            "required": ["blueprint_name", "target_node_id", "target_pin_name", "delegate_name"]
        },
        examples=(
            {
                "blueprint_name": "WB_HostGameMenu",
                "target_node_id": "<GetSession node GUID>",
                "target_pin_name": "ReturnValue",
                "delegate_name": "OnCreateResult",
                "event_name": "OnCreateSessionResult",
                "node_position": [1200, -600],
                "graph_name": "EventGraph",
            },
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
