"""Self-Evolution Actions action definitions."""

from __future__ import annotations

from .. import ActionDef


_SELF_EVOLUTION_ACTIONS = [
    ActionDef(
        id="node.search_catalog",
        command="search_catalog",
        tags=("node", "search", "catalog", "discover", "browse", "action", "database", "self-evolution"),
        description=(
            "Search the Blueprint action catalog for available nodes. "
            "Queries UE's FBlueprintActionDatabase to discover ALL registered Blueprint actions "
            "(engine functions, third-party plugins, project functions, etc.). "
            "Returns spawner_id that can be used with node.add_generic to create any node."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "Search term (min 2 chars). Matches against action name, category, and keywords.",
                },
                "category": {
                    "type": "string",
                    "description": "Optional category filter to narrow results (e.g. 'Math', 'String', 'HTTP').",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max results to return (default: 50, max: 200).",
                },
            },
            "required": ["keyword"],
        },
        examples=(
            {"keyword": "Print String"},
            {"keyword": "HTTP", "max_results": 20},
            {"keyword": "Get", "category": "Math", "max_results": 10},
            {"keyword": "TryGet", "max_results": 30},
        ),
    ),
    ActionDef(
        id="node.add_generic",
        command="add_generic_node",
        tags=("node", "add", "generic", "create", "spawn", "universal", "self-evolution"),
        description=(
            "Create ANY Blueprint node using a spawner_id from node.search_catalog or node.suggest_next. "
            "This is the universal node creator — can spawn function calls, events, macros, "
            "async actions, struct operations, and any third-party plugin node."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {
                    "type": "string",
                    "description": "Name of the target Blueprint",
                },
                "spawner_id": {
                    "type": "string",
                    "description": "Spawner ID obtained from node.search_catalog or node.suggest_next",
                },
                "node_position": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "[X, Y] position in the graph",
                },
                "graph_name": {
                    "type": "string",
                    "description": "Target graph (default: EventGraph)",
                },
                "pin_defaults": {
                    "type": "object",
                    "description": "Object mapping pin_name -> default_value string",
                },
            },
            "required": ["blueprint_name", "spawner_id"],
        },
        examples=(
            {"blueprint_name": "BP_Player", "spawner_id": "sp_42", "node_position": [300, 0]},
            {
                "blueprint_name": "WBP_Weather",
                "spawner_id": "sp_7",
                "node_position": [500, 100],
                "pin_defaults": {"URL": "https://api.example.com"},
            },
        ),
    ),
    ActionDef(
        id="node.add_level_actor_reference",
        command="add_level_actor_reference_node",
        tags=("node", "add", "level", "actor", "reference", "literal", "blueprint"),
        description=(
            "Create a direct reference node for an Actor placed in the current level. "
            "This mirrors dragging an Actor from the World Outliner into the Level Blueprint "
            "and is only valid for actors owned by that Level Blueprint's level."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "actor_name": {
                    "type": "string",
                    "description": "Exact actor object name or unique actor label in the current persistent level",
                },
                "node_position": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "[X, Y] position in the Level Blueprint graph",
                },
                "graph_name": {
                    "type": "string",
                    "description": "Target Level Blueprint graph (default: EventGraph)",
                },
            },
            "required": ["actor_name"],
        },
        examples=(
            {
                "actor_name": "BP_Door_C_0",
                "node_position": [300, 0],
                "graph_name": "EventGraph",
            },
        ),
    ),
    ActionDef(
        id="node.suggest_next",
        command="suggest_next",
        tags=("node", "suggest", "context", "pin", "compatible", "next", "self-evolution"),
        description=(
            "Given a node pin, suggest compatible nodes that can connect to it. "
            "Uses UE's native context-sensitive menu system (same as right-click drag from pin). "
            "Returns spawner_id for each suggestion, usable with node.add_generic."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {
                    "type": "string",
                    "description": "Name of the target Blueprint",
                },
                "node_id": {
                    "type": "string",
                    "description": "GUID of the source node",
                },
                "pin_name": {
                    "type": "string",
                    "description": "Name of the pin to find compatible connections for",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max results (default: 30, max: 100)",
                },
                "graph_name": {
                    "type": "string",
                    "description": "Target graph (default: EventGraph)",
                },
            },
            "required": ["blueprint_name", "node_id", "pin_name"],
        },
        examples=(
            {
                "blueprint_name": "BP_Player",
                "node_id": "A1B2C3D4-...",
                "pin_name": "ReturnValue",
            },
            {
                "blueprint_name": "WBP_Weather",
                "node_id": "E5F6A7B8-...",
                "pin_name": "OnSuccess",
                "max_results": 20,
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
