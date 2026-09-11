"""Node Flow Control action definitions."""

from __future__ import annotations

from .. import ActionDef


_NODE_FLOW_ACTIONS = [
    ActionDef(
        id="node.add_branch",
        command="add_blueprint_branch_node",
        tags=("node", "branch", "if", "condition", "flow"),
        description="Add a Branch (If/Then/Else) node",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "graph_name": {"type": "string", "description": "Optional graph name"},
                "node_position": {"type": "string", "description": "[X, Y] position"}
            },
            "required": ["blueprint_name"]
        },
    ),
    ActionDef(
        id="node.add_macro",
        command="add_macro_instance_node",
        tags=("node", "macro", "loop", "foreach", "forloop", "whileloop", "doonce", "gate", "flow"),
        description="Add a macro instance node (ForEachLoop, ForLoop, WhileLoop, DoOnce, Gate, etc.)",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "macro_name": {"type": "string", "description": "Macro name (ForEachLoop, ForLoop, WhileLoop, DoOnce, Gate, etc.)"},
                "graph_name": {"type": "string", "description": "Optional graph name"},
                "node_position": {"type": "array", "items": {"type": "number"}, "description": "[X, Y] position"}
            },
            "required": ["blueprint_name", "macro_name"]
        },
        examples=({"blueprint_name": "BP_Player", "macro_name": "ForEachLoop"},),
    ),
    ActionDef(
        id="node.add_sequence",
        command="add_sequence_node",
        tags=("node", "sequence", "flow", "control", "exec"),
        description="Add an Execution Sequence node (native K2 node with multiple Then outputs)",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "graph_name": {"type": "string", "description": "Optional graph name"},
                "node_position": {"type": "array", "items": {"type": "number"}, "description": "[X, Y] position"}
            },
            "required": ["blueprint_name"]
        },
        examples=({"blueprint_name": "BP_Player"},),
    ),
    # ── DataTable Row CRUD ──
    ActionDef(
        id="editor.create_data_table",
        command="create_data_table",
        tags=("editor", "asset", "datatable", "data_table", "create", "write"),
        description="Create a DataTable asset with the specified RowStruct.",
        input_schema={
            "type": "object",
            "properties": {
                "asset_name": {"type": "string", "description": "Asset name without path, e.g. DT_BuffDefaults"},
                "package_path": {"type": "string", "description": "Package path, e.g. /Game/P111/Data/DataTables"},
                "row_struct": {"type": "string", "description": "UScriptStruct path, e.g. /Script/P111.P111BuffEntry"},
                "save": {"type": "boolean", "description": "Save after creating (default: true)"},
            },
            "required": ["asset_name", "package_path", "row_struct"],
        },
        capabilities=("write",),
        risk="moderate",
    ),
    ActionDef(
        id="data_table_get_rows",
        command="data_table_get_rows",
        tags=("datatable", "data_table", "row", "read", "get"),
        description="Read all rows from a DataTable asset, returned as a JSON array of {row_name, field1, field2, ...}",
        input_schema={
            "type": "object",
            "properties": {
                "asset_path": {"type": "string", "description": "DataTable asset path, e.g. /Game/Data/DT_MyTable"},
            },
            "required": ["asset_path"],
        },
        capabilities=("read",),
    ),
    ActionDef(
        id="data_table_add_row",
        command="data_table_add_row",
        tags=("datatable", "data_table", "row", "add", "create", "write"),
        description="Add a new row to a DataTable. RowName must be unique. property_values is a JSON object mapping field names to values.",
        input_schema={
            "type": "object",
            "properties": {
                "asset_path": {"type": "string", "description": "DataTable asset path"},
                "row_name": {"type": "string", "description": "Unique row name"},
                "property_values": {"type": "object", "description": "Field name → value mapping"},
                "save": {"type": "boolean", "description": "Save after writing (default: true)"},
            },
            "required": ["asset_path", "row_name", "property_values"],
        },
        capabilities=("write",),
    ),
    ActionDef(
        id="data_table_set_row_property",
        command="data_table_set_row_property",
        tags=("datatable", "data_table", "row", "set", "property", "write"),
        description="Set a single property value on an existing DataTable row without touching other rows.",
        input_schema={
            "type": "object",
            "properties": {
                "asset_path": {"type": "string", "description": "DataTable asset path"},
                "row_name": {"type": "string", "description": "Target row name"},
                "property_name": {"type": "string", "description": "Property name to modify"},
                "property_value": {"type": ["string", "number", "boolean"], "description": "New value"},
                "save": {"type": "boolean", "description": "Save after writing (default: true)"},
            },
            "required": ["asset_path", "row_name", "property_name", "property_value"],
        },
        capabilities=("write",),
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
