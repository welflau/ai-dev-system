"""Layout action definitions."""

from __future__ import annotations

from .. import ActionDef


_LAYOUT_ACTIONS = [
    ActionDef(
        id="layout.auto_selected",
        command="auto_layout_selected",
        tags=("layout", "auto", "arrange", "nodes", "graph"),
        description="Auto-layout selected nodes or all nodes in a graph/blueprint",
        input_schema={
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["selected", "graph", "all"], "description": "Layout granularity"},
                "blueprint_name": {"type": "string", "description": "Blueprint name (optional)"},
                "graph_name": {"type": "string", "description": "Graph name (optional)"},
                "node_ids": {"type": "array", "items": {"type": "string"}, "description": "Node GUIDs for 'selected' mode"},
                "layer_spacing": {"type": "number", "description": "Horizontal spacing (>0 fixed px, <=0 auto width-aware; default: 0)"},
                "row_spacing": {"type": "number", "description": "Vertical spacing (>0 fixed px, <=0 auto height-aware; default: 0)"},
                "horizontal_gap": {"type": "number", "description": "Gap between layers in auto mode (default: 250)"},
                "vertical_gap": {"type": "number", "description": "Gap between rows in auto mode (default: 100)"},
                "crossing_passes": {"type": "integer", "description": "Barycenter optimization passes (default: 4)"},
                "pin_align_pure": {"type": "boolean", "description": "Align pure nodes to consumer input pin Y (default: true)"},
                "avoid_surrounding": {"type": "boolean", "description": "Avoid non-participating nodes in the same graph (default: false)"},
                "include_pure_deps": {"type": "boolean", "description": "Auto-include pure dependency nodes in selected mode (default: false)"},
                "surrounding_margin": {"type": "number", "description": "Obstacle margin when avoid_surrounding is enabled (default: 60)"},
                "preserve_comments": {"type": "boolean", "description": "Resize comment boxes to fit moved child nodes (default: true)"}
            }
        },
        examples=({"mode": "graph", "blueprint_name": "BP_Player"},),
    ),
    ActionDef(
        id="layout.auto_subtree",
        command="auto_layout_subtree",
        tags=("layout", "auto", "subtree", "arrange", "nodes"),
        description="Auto-layout an exec subtree starting from a root node",
        input_schema={
            "type": "object",
            "properties": {
                "root_node_id": {"type": "string", "description": "GUID of the root node"},
                "blueprint_name": {"type": "string", "description": "Blueprint name (optional)"},
                "graph_name": {"type": "string", "description": "Graph name (optional)"},
                "max_pure_depth": {"type": "integer", "description": "Max pure dependency depth (default: 3)"},
                "layer_spacing": {"type": "number", "description": "Horizontal spacing (>0 fixed px, <=0 auto width-aware; default: 0)"},
                "row_spacing": {"type": "number", "description": "Vertical spacing (>0 fixed px, <=0 auto height-aware; default: 0)"},
                "horizontal_gap": {"type": "number", "description": "Gap between layers in auto mode (default: 250)"},
                "vertical_gap": {"type": "number", "description": "Gap between rows in auto mode (default: 100)"},
                "crossing_passes": {"type": "integer", "description": "Barycenter optimization passes (default: 4)"},
                "pin_align_pure": {"type": "boolean", "description": "Align pure nodes to consumer input pin Y (default: true)"},
                "avoid_surrounding": {"type": "boolean", "description": "Avoid non-participating nodes in the same graph (default: false)"},
                "surrounding_margin": {"type": "number", "description": "Obstacle margin when avoid_surrounding is enabled (default: 60)"},
                "preserve_comments": {"type": "boolean", "description": "Resize comment boxes to fit moved child nodes (default: true)"}
            }
        },
    ),
    ActionDef(
        id="layout.auto_blueprint",
        command="auto_layout_blueprint",
        tags=("layout", "auto", "blueprint", "all", "graphs", "arrange"),
        description="Auto-layout ALL graphs in a Blueprint (EventGraph, Functions, Macros)",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Blueprint name (optional, defaults to focused editor)"},
                "layer_spacing": {"type": "number", "description": "Horizontal spacing (0=auto, default: auto)"},
                "row_spacing": {"type": "number", "description": "Vertical spacing (0=auto, default: auto)"},
                "horizontal_gap": {"type": "number", "description": "Gap between layers in auto mode (default: 250)"},
                "vertical_gap": {"type": "number", "description": "Gap between rows in auto mode (default: 100)"},
                "crossing_passes": {"type": "integer", "description": "Barycenter optimization passes (default: 4)"},
                "pin_align_pure": {"type": "boolean", "description": "Align pure nodes with consumer pin Y (default: true)"},
                "preserve_comments": {"type": "boolean", "description": "Resize comment boxes to fit children (default: true)"}
            }
        },
        examples=({"blueprint_name": "BP_Player"},),
    ),
    ActionDef(
        id="layout.layout_and_comment",
        command="layout_and_comment",
        tags=("layout", "comment", "auto", "group", "arrange", "non-overlap", "batch"),
        description=(
            "Combined action: auto-layout nodes then create non-overlapping comment boxes "
            "for each functional group. Solves the comment-overlap problem by inserting "
            "inter-group spacing BEFORE placing comments. Each group specifies its node_ids "
            "and comment_text; groups are separated vertically so comments never overlap."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Blueprint name (optional, defaults to focused editor)"},
                "graph_name": {"type": "string", "description": "Graph name (optional, defaults to focused graph)"},
                "groups": {
                    "type": "array",
                    "description": "Array of group objects, each defining a set of nodes and its comment",
                    "items": {
                        "type": "object",
                        "properties": {
                            "node_ids": {"type": "array", "items": {"type": "string"}, "description": "Node GUIDs belonging to this group"},
                            "comment_text": {"type": "string", "description": "Comment text for the group"},
                            "color": {"type": "array", "items": {"type": "number"}, "description": "[R, G, B, A] 0.0-1.0"}
                        },
                        "required": ["node_ids", "comment_text"]
                    }
                },
                "group_spacing": {"type": "number", "description": "Min Y gap between group AABBs in px (default: 80)"},
                "auto_layout": {"type": "boolean", "description": "Run auto-layout before commenting (default: true)"},
                "clear_existing": {"type": "boolean", "description": "Remove all existing comments first (default: false)"},
                "padding": {"type": "number", "description": "Comment box padding in px (default: 40)"},
                "title_height": {"type": "number", "description": "Comment title height in px (default: 36)"},
                "layer_spacing": {"type": "number", "description": "Horizontal spacing forwarded to auto-layout (default: 0=auto)"},
                "row_spacing": {"type": "number", "description": "Vertical spacing forwarded to auto-layout (default: 0=auto)"},
                "crossing_passes": {"type": "integer", "description": "Barycenter passes forwarded to auto-layout (default: 4)"}
            },
            "required": ["groups"]
        },
        examples=(
            {
                "blueprint_name": "BP_Player",
                "groups": [
                    {"node_ids": ["GUID1", "GUID2"], "comment_text": "初始化逻辑", "color": [0.15, 0.55, 0.25, 1]},
                    {"node_ids": ["GUID3", "GUID4", "GUID5"], "comment_text": "移动处理", "color": [0.15, 0.35, 0.65, 1]}
                ]
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
