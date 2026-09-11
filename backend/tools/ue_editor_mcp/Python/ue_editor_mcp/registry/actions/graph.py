"""Graph Operations action definitions."""

from __future__ import annotations

from .. import ActionDef


_GRAPH_ACTIONS = [
    ActionDef(
        id="graph.connect_nodes",
        command="connect_blueprint_nodes",
        tags=("graph", "connect", "wire", "link", "pin"),
        description="Connect two nodes in a Blueprint graph",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "source_node_id": {"type": "string", "description": "GUID of the source node"},
                "source_pin": {"type": "string", "description": "Name of the output pin"},
                "target_node_id": {"type": "string", "description": "GUID of the target node"},
                "target_pin": {"type": "string", "description": "Name of the input pin"},
                "graph_name": {"type": "string", "description": "Optional graph name"}
            },
            "required": ["blueprint_name", "source_node_id", "source_pin", "target_node_id", "target_pin"]
        },
    ),
    ActionDef(
        id="graph.find_nodes",
        command="find_blueprint_nodes",
        tags=("graph", "find", "search", "nodes", "read"),
        description="Find nodes in a Blueprint graph by type or event type",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "graph_name": {"type": "string", "description": "Optional graph name"},
                "node_type": {"type": "string", "description": "Type of node (Event, Function, Variable, etc.)"},
                "event_type": {"type": "string", "description": "Specific event type (BeginPlay, Tick, etc.)"}
            },
            "required": ["blueprint_name"]
        },
        capabilities=("read",),
    ),
    ActionDef(
        id="graph.delete_node",
        command="delete_blueprint_node",
        tags=("graph", "delete", "remove", "node"),
        description="Delete a node from a Blueprint graph",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "node_id": {"type": "string", "description": "GUID of the node to delete"},
                "graph_name": {"type": "string", "description": "Optional graph name"}
            },
            "required": ["blueprint_name", "node_id"]
        },
        capabilities=("write", "destructive"),
        risk="moderate",
    ),
    ActionDef(
        id="graph.get_node_pins",
        command="get_node_pins",
        tags=("graph", "node", "pins", "debug", "read"),
        description="Get all pins on a node for debugging connection issues",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "node_id": {"type": "string", "description": "GUID of the node"},
                "graph_name": {"type": "string", "description": "Optional graph name"}
            },
            "required": ["blueprint_name", "node_id"]
        },
        capabilities=("read",),
    ),
    ActionDef(
        id="graph.get_selected_nodes",
        command="get_selected_nodes",
        tags=("graph", "selected", "nodes", "editor", "read", "introspect"),
        description="Get information about the currently selected nodes in the focused Blueprint graph editor. Returns node GUID/class/title/position/pins/edges for each selected node. Falls back to the active editor when blueprint_name is omitted.",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Optional Blueprint name — if omitted, uses the currently focused editor"},
                "graph_name": {"type": "string", "description": "Optional graph name — if omitted, uses the focused graph"},
                "include_hidden_pins": {"type": "boolean", "description": "Include hidden pins (default: false)"}
            }
        },
        capabilities=("read",),
        examples=(
            {},
            {"blueprint_name": "BP_Player"},
            {"blueprint_name": "BP_Player", "graph_name": "EventGraph", "include_hidden_pins": True},
        ),
    ),
    ActionDef(
        id="graph.collapse_selection_to_function",
        command="collapse_selection_to_function",
        tags=("graph", "collapse", "selection", "function", "refactor", "editor"),
        description="Collapse currently selected nodes in the focused Blueprint graph into a new function using Unreal's native collapse-to-function flow.",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Optional Blueprint name/path to target a specific open Blueprint editor"}
            }
        },
        capabilities=("write",),
        risk="moderate",
        examples=(
            {},
            {"blueprint_name": "BP_Player"},
        ),
    ),
    ActionDef(
        id="graph.collapse_selection_to_macro",
        command="collapse_selection_to_macro",
        tags=("graph", "collapse", "selection", "macro", "refactor", "editor"),
        description="Collapse currently selected nodes in the focused Blueprint graph into a new macro using Unreal's native collapse-to-macro flow. Macros support latent nodes (e.g. Delay). Not supported in AnimGraphs.",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Optional Blueprint name/path to target a specific open Blueprint editor"}
            }
        },
        capabilities=("write",),
        risk="moderate",
        examples=(
            {},
            {"blueprint_name": "BP_Player"},
        ),
    ),
    ActionDef(
        id="graph.set_selected_nodes",
        command="set_selected_nodes",
        tags=("graph", "select", "selection", "nodes", "editor", "write"),
        description="Programmatically set the selection in the focused Blueprint graph editor by providing an array of node GUIDs. Clears the previous selection and selects only the specified nodes. Use 'append' to add to existing selection instead of replacing it.",
        input_schema={
            "type": "object",
            "properties": {
                "node_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Array of node GUID strings to select"
                },
                "blueprint_name": {"type": "string", "description": "Optional Blueprint name — if omitted, uses the currently focused editor"},
                "graph_name": {"type": "string", "description": "Optional graph name — if omitted, uses the focused graph"},
                "append": {"type": "boolean", "description": "If true, add to existing selection instead of replacing it (default: false)"}
            },
            "required": ["node_ids"]
        },
        capabilities=("write",),
        risk="safe",
        examples=(
            {"node_ids": ["A1B2C3D4-E5F6-7890-ABCD-EF1234567890"]},
            {"node_ids": ["GUID1", "GUID2", "GUID3"], "blueprint_name": "BP_Player"},
            {"node_ids": ["GUID1"], "append": True},
        ),
    ),
    ActionDef(
        id="graph.batch_select_and_act",
        command="batch_select_and_act",
        tags=("graph", "batch", "select", "selection", "group", "collapse", "comment", "refactor", "automation"),
        description="Batch grouped selection + action execution. For each group: clears selection, selects the group's nodes, executes the specified action (e.g. collapse_selection_to_function, auto_comment), and collects the result. Enables fully automated per-group operations without manual selection.",
        input_schema={
            "type": "object",
            "properties": {
                "groups": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "node_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Array of node GUID strings for this group"
                            },
                            "action": {"type": "string", "description": "Action command to execute on this selection (e.g. 'collapse_selection_to_function', 'auto_comment')"},
                            "action_params": {"type": "object", "description": "Optional extra params to pass to the action (e.g. comment_text, color for auto_comment)"}
                        },
                        "required": ["node_ids", "action"]
                    },
                    "description": "Array of group objects, each with node_ids and an action to perform"
                },
                "blueprint_name": {"type": "string", "description": "Optional Blueprint name"},
                "graph_name": {"type": "string", "description": "Optional graph name"}
            },
            "required": ["groups"]
        },
        capabilities=("write",),
        risk="moderate",
        examples=(
            {
                "groups": [
                    {"node_ids": ["GUID1", "GUID2"], "action": "collapse_selection_to_function"},
                    {"node_ids": ["GUID3", "GUID4"], "action": "auto_comment", "action_params": {"comment_text": "Movement Logic", "color": [0.15, 0.35, 0.65, 1]}}
                ]
            },
            {
                "blueprint_name": "BP_Player",
                "groups": [
                    {"node_ids": ["GUID1", "GUID2", "GUID3"], "action": "collapse_selection_to_function"}
                ]
            },
        ),
    ),
    ActionDef(
        id="graph.disconnect_pin",
        command="disconnect_blueprint_pin",
        tags=("graph", "disconnect", "pin", "unlink"),
        description="Disconnect all connections on a specific pin of a node",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "node_id": {"type": "string", "description": "GUID of the node"},
                "pin_name": {"type": "string", "description": "Name of the pin"},
                "graph_name": {"type": "string", "description": "Optional graph name"}
            },
            "required": ["blueprint_name", "node_id", "pin_name"]
        },
    ),
    ActionDef(
        id="graph.move_node",
        command="move_node",
        tags=("graph", "move", "position", "node"),
        description="Move (reposition) a node in a Blueprint graph",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "node_id": {"type": "string", "description": "GUID of the node"},
                "node_position": {"type": "array", "items": {"type": "number"}, "description": "[X, Y] new position"},
                "graph_name": {"type": "string", "description": "Optional graph name"}
            },
            "required": ["blueprint_name", "node_id", "node_position"]
        },
    ),
    ActionDef(
        id="graph.add_reroute",
        command="add_reroute_node",
        tags=("graph", "reroute", "knot", "wire"),
        description="Add a Reroute (Knot) node for cleaner wire routing",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "node_position": {"type": "array", "items": {"type": "number"}, "description": "[X, Y] position"},
                "graph_name": {"type": "string", "description": "Optional graph name"}
            },
            "required": ["blueprint_name"]
        },
    ),
    ActionDef(
        id="graph.add_comment",
        command="add_blueprint_comment",
        tags=("graph", "comment", "annotation", "note"),
        description="Add a comment box node to a Blueprint graph",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "comment_text": {"type": "string", "description": "Comment text"},
                "graph_name": {"type": "string", "description": "Optional graph name"},
                "node_position": {"type": "array", "items": {"type": "number"}, "description": "[X, Y] position"},
                "size": {"type": "array", "items": {"type": "number"}, "description": "[Width, Height]"},
                "color": {"type": "array", "items": {"type": "number"}, "description": "[R, G, B, A] 0.0-1.0"}
            },
            "required": ["blueprint_name", "comment_text"]
        },
    ),
    ActionDef(
        id="graph.auto_comment",
        command="auto_comment",
        tags=("graph", "comment", "auto", "annotation", "wrap", "bounding"),
        description="Auto-create a comment box that precisely wraps nodes. When node_ids is provided, wraps only those nodes. When node_ids is omitted, wraps ALL non-comment nodes in the graph.",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "graph_name": {"type": "string", "description": "Optional graph name (default: EventGraph)"},
                "node_ids": {"type": "array", "items": {"type": "string"}, "description": "Node GUIDs to wrap. OPTIONAL — omit to wrap all nodes in the graph."},
                "comment_text": {"type": "string", "description": "Comment text"},
                "color": {"type": "array", "items": {"type": "number"}, "description": "[R, G, B, A] 0.0-1.0 per Color Scheme"},
                "padding": {"type": "number", "description": "Extra padding in px around nodes (default: 40)"},
                "title_height": {"type": "number", "description": "Space reserved for comment title text (default: 36)"}
            },
            "required": ["blueprint_name", "comment_text"]
        },
        examples=(
            {"blueprint_name": "BP_Player", "graph_name": "UpdateRandomFloating", "comment_text": "浮动更新全流程", "color": [0.15, 0.35, 0.65, 1]},
            {"blueprint_name": "BP_Player", "node_ids": ["GUID1", "GUID2"], "comment_text": "BeginPlay Init", "color": [0.15, 0.55, 0.25, 1]},
        ),
    ),
    ActionDef(
        id="graph.describe",
        command="describe_graph",
        tags=("graph", "describe", "topology", "dump", "read"),
        description="Dump full graph topology: all nodes (GUID/type/title/position), all pins, all edges. Designed for AI-driven graph analysis.",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Blueprint package name or asset path"},
                "graph_name": {"type": "string", "description": "Target graph name (EventGraph, function name, etc.)"},
                "include_hidden_pins": {"type": "boolean", "description": "Include hidden pins (default: false)"},
                "include_orphan_pins": {"type": "boolean", "description": "Include orphan pins (default: false)"}
            },
            "required": ["blueprint_name"]
        },
        capabilities=("read",),
        examples=(
            {"blueprint_name": "BP_Player"},
            {"blueprint_name": "BP_Player", "graph_name": "EventGraph", "include_hidden_pins": True},
        ),
    ),
    # -- P3: Enhanced Graph Description --
    ActionDef(
        id="graph.describe_enhanced",
        command="describe_graph_enhanced",
        tags=("graph", "describe", "enhanced", "topology", "variables", "metadata", "read", "compact"),
        description="Enhanced graph topology dump: full PinType serialization, variable reference tracking, function signature expansion, and node metadata (breakpoints, enabled state). Use compact=true to omit metadata/function_signature/variable_references and use lightweight pin serialization (reduces 50-100KB → 10-20KB for large graphs).",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Blueprint package name or asset path"},
                "graph_name": {"type": "string", "description": "Target graph name (EventGraph, function name, etc.)"},
                "include_hidden_pins": {"type": "boolean", "description": "Include hidden pins (default: false)"},
                "include_orphan_pins": {"type": "boolean", "description": "Include orphan pins (default: false)"},
                "compact": {"type": "boolean", "description": "Compact mode: omit metadata, function_signature, variable_references and use lightweight pin serialization (default: false)"}
            },
            "required": ["blueprint_name"]
        },
        capabilities=("read",),
        examples=(
            {"blueprint_name": "BP_Player"},
            {"blueprint_name": "BP_Player", "graph_name": "EventGraph", "compact": True},
            {"blueprint_name": "BP_Player", "graph_name": "EventGraph", "include_hidden_pins": True, "include_orphan_pins": True},
        ),
    ),
    # -- P3: Patch System --
    ActionDef(
        id="graph.apply_patch",
        command="apply_graph_patch",
        tags=("graph", "patch", "apply", "declarative", "batch", "nodes", "connect"),
        description="Apply a declarative patch document to a Blueprint graph. Supports ops: add_node, remove_node, set_node_property, connect, disconnect, add_variable, set_variable_default, set_pin_default. Auto-compiles after execution.",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "graph_name": {"type": "string", "description": "Target graph (default: EventGraph)"},
                "continue_on_error": {"type": "boolean", "description": "Continue executing remaining ops if one fails (default: false)"},
                "ops": {
                    "type": "array",
                    "description": "Ordered list of patch operations",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {"type": "string", "enum": ["add_node", "remove_node", "set_node_property", "connect", "disconnect", "add_variable", "set_variable_default", "set_pin_default"]},
                            "id": {"type": "string", "description": "(add_node) Temp ID for referencing within this patch"},
                            "node_type": {"type": "string", "description": "(add_node) Event, CustomEvent, FunctionCall, Branch, VariableGet, VariableSet, Cast, Self, Reroute, MacroInstance, CreateDelegate, Delay, CreateWidget, InputAction, FormatText, SpawnActorFromClass"},
                            "event_name": {"type": "string", "description": "(add_node/Event) Event name e.g. BeginPlay"},
                            "function_name": {"type": "string", "description": "(add_node/FunctionCall) Function name"},
                            "target_class": {"type": "string", "description": "(add_node/FunctionCall) Owning class (self, GameplayStatics, Math, etc.)"},
                            "variable_name": {"type": "string", "description": "(add_node/VariableGet|Set) Variable name"},
                            "action_name": {"type": "string", "description": "(add_node/InputAction) Input action name"},
                            "class_name": {"type": "string", "description": "(add_node/CreateWidget|SpawnActorFromClass) Class path e.g. /Game/UI/WBP_HUD.WBP_HUD_C"},
                            "duration": {"type": "number", "description": "(add_node/Delay) Delay duration in seconds"},
                            "defaults": {"type": "object", "description": "(add_node/FunctionCall) Pin default values {pin_name: value}"},
                            "node": {"type": "string", "description": "(various ops) Node reference: temp ID, GUID, or $last_node"},
                            "from": {"type": "object", "description": "(connect) {node, pin}"},
                            "to": {"type": "object", "description": "(connect) {node, pin}"},
                            "pin": {"type": "string", "description": "(disconnect/set_pin_default) Pin name"},
                            "property": {"type": "string", "description": "(set_node_property) Property name"},
                            "value": {"type": "string", "description": "(set_node_property/set_pin_default/set_variable_default) Value"},
                            "name": {"type": "string", "description": "(add_variable/set_variable_default) Variable name"},
                            "type": {"type": "string", "description": "(add_variable) Variable type"},
                            "pos_x": {"type": "number", "description": "(add_node) X position"},
                            "pos_y": {"type": "number", "description": "(add_node) Y position"}
                        },
                        "required": ["op"]
                    }
                }
            },
            "required": ["blueprint_name", "ops"]
        },
        capabilities=("write",),
        risk="moderate",
        examples=(
            {
                "blueprint_name": "BP_MyActor",
                "ops": [
                    {"op": "add_node", "id": "evt", "node_type": "Event", "event_name": "BeginPlay"},
                    {"op": "add_node", "id": "print", "node_type": "FunctionCall", "function_name": "PrintString", "defaults": {"InString": "Hello from Patch!"}},
                    {"op": "connect", "from": {"node": "evt", "pin": "then"}, "to": {"node": "print", "pin": "execute"}},
                    {"op": "set_pin_default", "node": "print", "pin": "bPrintToScreen", "value": "true"},
                ]
            },
        ),
    ),
    ActionDef(
        id="graph.validate_patch",
        command="validate_graph_patch",
        tags=("graph", "patch", "validate", "dryrun", "check", "read"),
        description="Dry-run validation of a patch document. Returns per-op validation results without modifying the graph.",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "graph_name": {"type": "string", "description": "Target graph (default: EventGraph)"},
                "ops": {
                    "type": "array",
                    "description": "Ordered list of patch operations (same format as graph.apply_patch)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {"type": "string"}
                        },
                        "required": ["op"]
                    }
                }
            },
            "required": ["blueprint_name", "ops"]
        },
        capabilities=("read",),
        examples=(
            {
                "blueprint_name": "BP_MyActor",
                "ops": [
                    {"op": "add_node", "id": "evt", "node_type": "Event", "event_name": "BeginPlay"},
                    {"op": "add_node", "id": "print", "node_type": "FunctionCall", "function_name": "PrintString"},
                    {"op": "connect", "from": {"node": "evt", "pin": "then"}, "to": {"node": "print", "pin": "execute"}},
                ]
            },
        ),
    ),
    # P4 — Cross-Graph Node Transfer (Export / Import)
    ActionDef(
        id="graph.export_nodes",
        command="export_nodes_to_text",
        tags=("graph", "export", "nodes", "text", "serialize", "copy", "transfer", "cross-graph"),
        description="Serialize a set of Blueprint graph nodes to text using UE's native ExportNodesToText. The exported text can later be imported into any compatible graph via graph.import_nodes, enabling cross-graph node transfer workflows.",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint containing the source graph"},
                "graph_name": {"type": "string", "description": "Source graph name (default: EventGraph)"},
                "node_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Array of node GUID strings to export"
                }
            },
            "required": ["blueprint_name", "node_ids"]
        },
        capabilities=("read",),
        examples=(
            {
                "blueprint_name": "BP_MyActor",
                "node_ids": ["A1B2C3D4-E5F6-7890-ABCD-EF1234567890"]
            },
        ),
    ),
    ActionDef(
        id="graph.import_nodes",
        command="import_nodes_from_text",
        tags=("graph", "import", "nodes", "text", "deserialize", "paste", "transfer", "cross-graph"),
        description="Import (paste) nodes from previously exported text into a target Blueprint graph. Supports importing into a different graph than the export source, enabling cross-graph node migration. Optionally apply a position offset to avoid overlapping.",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the target Blueprint"},
                "graph_name": {"type": "string", "description": "Target graph name (default: EventGraph)"},
                "exported_text": {"type": "string", "description": "Node text obtained from graph.export_nodes"},
                "offset_x": {"type": "number", "description": "X position offset for pasted nodes (default: 0)"},
                "offset_y": {"type": "number", "description": "Y position offset for pasted nodes (default: 0)"}
            },
            "required": ["blueprint_name", "exported_text"]
        },
        examples=(
            {
                "blueprint_name": "BP_TargetActor",
                "exported_text": "<exported text from graph.export_nodes>",
                "offset_x": 200,
                "offset_y": 0
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
