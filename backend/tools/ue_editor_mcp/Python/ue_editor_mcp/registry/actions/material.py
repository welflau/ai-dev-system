"""Materials action definitions."""

from __future__ import annotations

from .. import ActionDef


_MATERIAL_ACTIONS = [
    ActionDef(
        id="material.create",
        command="create_material",
        tags=("material", "create", "asset", "shader"),
        description="Create a new Material asset",
        input_schema={
            "type": "object",
            "properties": {
                "material_name": {"type": "string", "description": "Name of the Material"},
                "path": {"type": "string", "description": "Content path (default: /Game/Materials)"},
                "domain": {"type": "string", "description": "Material domain (Surface, PostProcess, DeferredDecal, LightFunction, UI)"},
                "blend_mode": {"type": "string", "description": "Blend mode (Opaque, Masked, Translucent, Additive, Modulate)"},
                "if_exists": {"type": "string", "enum": ["error", "overwrite", "skip", "reuse"], "description": "Existing asset policy. Default error; use overwrite for clean retry, skip/reuse to continue with existing asset."}
            },
            "required": ["material_name"]
        },
        examples=({"material_name": "M_Glow", "domain": "Surface", "blend_mode": "Translucent"},),
    ),
    ActionDef(
        id="material.list_expression_classes",
        command="list_material_expression_classes",
        tags=("material", "expression", "class", "list", "reflection", "read"),
        description="List all UMaterialExpression classes discovered through Unreal reflection, including aliases accepted by material.add_expression",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Optional case-insensitive filter on class/short/display name"},
                "include_aliases": {"type": "boolean", "description": "Include accepted aliases for material.add_expression (default: true)"}
            }
        },
        capabilities=("read",),
    ),
    ActionDef(
        id="material.add_expression",
        command="add_material_expression",
        tags=("material", "expression", "node", "graph"),
        description="Add an expression node to a Material graph. expression_class accepts any reflected UMaterialExpression short name, full class name, or alias from material.list_expression_classes.",
        input_schema={
            "type": "object",
            "properties": {
                "material_name": {"type": "string", "description": "Name of the Material"},
                "expression_class": {"type": "string", "description": "Reflected UMaterialExpression class/alias (e.g. ActorPositionWS, ObjectPositionWS, CameraPosition, ScalarParameter)"},
                "node_name": {"type": "string", "description": "Unique name for this node"},
                "position": {"type": "array", "items": {"type": "number"}, "description": "[X, Y] position"},
                "properties": {"type": "object", "description": "Property name/value pairs"}
            },
            "required": ["material_name", "expression_class", "node_name"]
        },
    ),
    ActionDef(
        id="material.connect_expressions",
        command="connect_material_expressions",
        tags=("material", "connect", "wire", "expression"),
        description="Connect output of one material expression to input of another",
        input_schema={
            "type": "object",
            "properties": {
                "material_name": {"type": "string", "description": "Name of the Material"},
                "source_node": {"type": "string", "description": "Source expression name"},
                "source_output_index": {"type": "integer", "description": "Output pin index (default: 0)"},
                "target_node": {"type": "string", "description": "Target expression name"},
                "target_input": {"type": "string", "description": "Input pin name (A, B, Alpha, etc.)"}
            },
            "required": ["material_name", "source_node", "target_node", "target_input"]
        },
    ),
    ActionDef(
        id="material.connect_to_output",
        command="connect_to_material_output",
        tags=("material", "connect", "output", "basecolor", "emissive"),
        description="Connect an expression to the material's main output (BaseColor, EmissiveColor, Metallic, etc.)",
        input_schema={
            "type": "object",
            "properties": {
                "material_name": {"type": "string", "description": "Name of the Material"},
                "source_node": {"type": "string", "description": "Source expression name"},
                "source_output_index": {"type": "integer", "description": "Output pin index (default: 0)"},
                "material_property": {"type": "string", "description": "Material property (BaseColor, EmissiveColor, Metallic, Roughness, Normal, Opacity, etc.)"}
            },
            "required": ["material_name", "source_node", "material_property"]
        },
    ),
    ActionDef(
        id="material.set_expression_property",
        command="set_material_expression_property",
        tags=("material", "expression", "property", "set"),
        description="Set a property on an existing material expression",
        input_schema={
            "type": "object",
            "properties": {
                "material_name": {"type": "string", "description": "Name of the Material"},
                "node_name": {"type": "string", "description": "Expression node name"},
                "property_name": {"type": "string", "description": "Property to set"},
                "property_value": {"type": "string", "description": "Value to set"}
            },
            "required": ["material_name", "node_name", "property_name", "property_value"]
        },
    ),
    ActionDef(
        id="material.compile",
        command="compile_material",
        tags=("material", "compile", "validate", "error", "diagnostic"),
        description="Compile a material, wait for shader compilation to finish, and return real compile errors with associated expression info. Returns errors[] array with message, expression_name, expression_class, and optional node_name for each error.",
        input_schema={
            "type": "object",
            "properties": {
                "material_name": {"type": "string", "description": "Name of the Material (optional; uses current material if omitted)"}
            },
            "required": []
        },
    ),
    ActionDef(
        id="material.create_instance",
        command="create_material_instance",
        tags=("material", "instance", "create", "parameter"),
        description="Create a Material Instance with parameter overrides",
        input_schema={
            "type": "object",
            "properties": {
                "instance_name": {"type": "string", "description": "Name for the instance"},
                "parent_material": {"type": "string", "description": "Parent material name"},
                "path": {"type": "string", "description": "Content path (default: /Game/Materials)"},
                "scalar_parameters": {"type": "object", "description": "Scalar parameter overrides {name: value}"},
                "vector_parameters": {"type": "object", "description": "Vector parameter overrides {name: [R,G,B,A]}"},
                "texture_parameters": {"type": "object", "description": "Texture parameter overrides {name: asset_path}"},
                "static_switch_parameters": {"type": "object", "description": "Static switch parameter overrides {name: bool}"}
            },
            "required": ["instance_name", "parent_material"]
        },
    ),
    ActionDef(
        id="material.set_property",
        command="set_material_property",
        tags=("material", "property", "set", "shading"),
        description="Set a property on a Material asset (ShadingModel, TwoSided, BlendMode, etc.)",
        input_schema={
            "type": "object",
            "properties": {
                "material_name": {"type": "string", "description": "Name of the Material"},
                "property_name": {"type": "string", "description": "Property (ShadingModel, TwoSided, BlendMode, etc.)"},
                "property_value": {"type": "string", "description": "Value to set"}
            },
            "required": ["material_name", "property_name", "property_value"]
        },
    ),
    ActionDef(
        id="material.create_post_process_volume",
        command="create_post_process_volume",
        tags=("material", "postprocess", "volume", "level"),
        description="Create a Post Process Volume actor in the level",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name for the volume"},
                "location": {"type": "array", "items": {"type": "number"}, "description": "[X, Y, Z]"},
                "infinite_extent": {"type": "boolean", "description": "Apply everywhere (default: true)"},
                "priority": {"type": "number", "description": "Priority (default: 0.0)"},
                "post_process_materials": {"type": "array", "items": {"type": "string"}, "description": "Materials to add"}
            },
            "required": ["name"]
        },
    ),
    # Phase 4 Material Actions
    ActionDef(
        id="material.get_summary",
        command="get_material_summary",
        tags=("material", "summary", "inspect", "graph", "debug"),
        description="Get full material graph structure: all expressions, connections, properties, and comments",
        input_schema={
            "type": "object",
            "properties": {
                "material_name": {"type": "string", "description": "Name of the Material"}
            },
            "required": ["material_name"]
        },
        capabilities=("read",),
    ),
    ActionDef(
        id="material.remove_expression",
        command="remove_material_expression",
        tags=("material", "expression", "remove", "delete", "node"),
        description="Remove one or more expressions from a material by node_name",
        input_schema={
            "type": "object",
            "properties": {
                "material_name": {"type": "string", "description": "Name of the Material"},
                "node_name": {"type": "string", "description": "Single node name to remove"},
                "node_names": {"type": "array", "items": {"type": "string"}, "description": "Array of node names to remove"}
            },
            "required": ["material_name"]
        },
        capabilities=("write", "destructive"),
        risk="destructive",
    ),
    ActionDef(
        id="material.auto_layout",
        command="auto_layout_material",
        tags=("material", "layout", "auto", "graph", "organize"),
        description="Auto-layout material graph nodes using data-flow topological sort",
        input_schema={
            "type": "object",
            "properties": {
                "material_name": {"type": "string", "description": "Name of the Material"},
                "layer_spacing": {"type": "number", "description": "Horizontal spacing (>0=fixed px, 0=auto)"},
                "row_spacing": {"type": "number", "description": "Vertical spacing (>0=fixed px, 0=auto)"}
            },
            "required": ["material_name"]
        },
    ),
    ActionDef(
        id="material.auto_comment",
        command="auto_comment_material",
        tags=("material", "comment", "auto", "annotate", "graph"),
        description="Add a comment node wrapping specified (or all) material expressions. Supports overwrite (replace same-text comment) and clear_all (remove all comments first).",
        input_schema={
            "type": "object",
            "properties": {
                "material_name": {"type": "string", "description": "Name of the Material"},
                "comment_text": {"type": "string", "description": "Comment text"},
                "node_names": {"type": "array", "items": {"type": "string"}, "description": "Node names to wrap ($expr_N, param names, $selected). Default: all"},
                "color": {"type": "array", "items": {"type": "number"}, "description": "[R, G, B, A] (0-1)"},
                "padding": {"type": "number", "description": "Padding around nodes in pixels (default: 40)"},
                "use_selected": {"type": "boolean", "description": "Wrap currently selected nodes in editor (default: false)"},
                "overwrite": {"type": "boolean", "description": "Remove existing comments with same text before creating (default: false)"},
                "clear_all": {"type": "boolean", "description": "Remove ALL existing comments before creating (default: false)"}
            },
            "required": ["material_name", "comment_text"]
        },
    ),
    # Phase 5: Material apply actions
    ActionDef(
        id="material.apply_to_component",
        command="apply_material_to_component",
        tags=("material", "apply", "component", "actor", "assign"),
        description="Apply a material to a specific component on a level actor. Finds actor by name, optionally targets a specific component, and sets the material at the given slot index.",
        input_schema={
            "type": "object",
            "properties": {
                "actor_name": {"type": "string", "description": "Name of the Actor in the level"},
                "material_path": {"type": "string", "description": "Asset path of the material (e.g. /Game/Materials/M_Example)"},
                "component_name": {"type": "string", "description": "Component name (default: first PrimitiveComponent)"},
                "slot_index": {"type": "integer", "description": "Material slot index (default: 0)"}
            },
            "required": ["actor_name", "material_path"]
        },
    ),
    ActionDef(
        id="material.apply_to_actor",
        command="apply_material_to_actor",
        tags=("material", "apply", "actor", "assign", "all", "components"),
        description="Apply a material to ALL PrimitiveComponents on a level actor at the given slot index. Useful for quickly replacing all materials on an actor.",
        input_schema={
            "type": "object",
            "properties": {
                "actor_name": {"type": "string", "description": "Name of the Actor in the level"},
                "material_path": {"type": "string", "description": "Asset path of the material"},
                "slot_index": {"type": "integer", "description": "Material slot index (default: 0)"}
            },
            "required": ["actor_name", "material_path"]
        },
    ),
    ActionDef(
        id="material.refresh_editor",
        command="refresh_material_editor",
        tags=("material", "refresh", "editor", "update", "ui", "graph", "rebuild"),
        description="Refresh the Material Editor UI for a given material. Call after a batch of graph modifications (add_expression, connect, set_property, etc.) to make changes visible in the open editor without closing and reopening it. Rebuilds the graph, re-links expressions, refreshes previews, and notifies the editor.",
        input_schema={
            "type": "object",
            "properties": {
                "material_name": {"type": "string", "description": "Name of the Material to refresh"}
            },
            "required": ["material_name"]
        },
    ),
    ActionDef(
        id="material.get_selected_nodes",
        command="get_material_selected_nodes",
        tags=("material", "selected", "nodes", "selection", "editor", "get", "read"),
        description="Returns the currently selected material expression nodes in the open material editor. Automatically detects the active material editor — no material_name required. Useful for inspecting which nodes the user has selected before performing operations on them.",
        input_schema={
            "type": "object",
            "properties": {
                "material_name": {"type": "string", "description": "Name of the Material (auto-detected if omitted)"}
            },
            "required": []
        },
        capabilities=("read",),
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
