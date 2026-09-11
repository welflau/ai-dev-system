"""Component Properties action definitions."""

from __future__ import annotations

from .. import ActionDef


_COMPONENT_ACTIONS = [
    ActionDef(
        id="component.set_property",
        command="set_component_property",
        tags=("component", "property", "set"),
        description="Set a property on a component in a Blueprint",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "component_name": {"type": "string", "description": "Name of the component"},
                "property_name": {"type": "string", "description": "Name of the property"},
                "property_value": {"type": "string", "description": "Value to set"}
            },
            "required": ["blueprint_name", "component_name", "property_name", "property_value"]
        },
        examples=({"blueprint_name": "BP_Lamp", "component_name": "Light", "property_name": "Intensity", "property_value": "5000"},),
    ),
    ActionDef(
        id="component.set_static_mesh",
        command="set_static_mesh_properties",
        tags=("component", "mesh", "material", "static"),
        description="Set static mesh, material, and overlay material on a StaticMeshComponent",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "component_name": {"type": "string", "description": "Name of the component"},
                "static_mesh": {"type": "string", "description": "Path to static mesh asset"},
                "material": {"type": "string", "description": "Path to material asset"},
                "overlay_material": {"type": "string", "description": "Path to overlay material"}
            },
            "required": ["blueprint_name", "component_name"]
        },
        examples=({"blueprint_name": "BP_Cube", "component_name": "Mesh", "static_mesh": "/Engine/BasicShapes/Cube"},),
    ),
    ActionDef(
        id="component.set_skeletal_mesh",
        command="set_skeletal_mesh_properties",
        tags=("component", "mesh", "material", "skeletal", "character"),
        description="Set skeletal mesh, anim class, material, and relative transform on a SkeletalMeshComponent; supports inherited Character Mesh via CDO fallback.",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "component_name": {"type": "string", "description": "Name of the SkeletalMeshComponent, commonly Mesh"},
                "skeletal_mesh": {"type": "string", "description": "Path to skeletal mesh asset"},
                "anim_class": {"type": "string", "description": "Path to AnimBlueprint asset or generated class"},
                "material": {"type": "string", "description": "Path to material asset"},
                "relative_location": {"type": "array", "items": {"type": "number"}, "description": "[x, y, z]"},
                "relative_rotation": {"type": "array", "items": {"type": "number"}, "description": "[pitch, yaw, roll]"},
                "relative_scale": {"type": "array", "items": {"type": "number"}, "description": "[x, y, z]"},
            },
            "required": ["blueprint_name", "component_name"],
        },
        examples=({"blueprint_name": "BP_Player", "component_name": "Mesh", "skeletal_mesh": "/Game/Characters/Hero/Hero"},),
    ),
    ActionDef(
        id="component.set_physics",
        command="set_physics_properties",
        tags=("component", "physics", "simulate", "gravity", "mass"),
        description="Set physics properties on a component",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the Blueprint"},
                "component_name": {"type": "string", "description": "Name of the component"},
                "simulate_physics": {"type": "boolean", "description": "Enable physics simulation"},
                "gravity_enabled": {"type": "boolean", "description": "Enable gravity"},
                "mass": {"type": "number", "description": "Mass in kg"},
                "linear_damping": {"type": "number", "description": "Linear damping"},
                "angular_damping": {"type": "number", "description": "Angular damping"}
            },
            "required": ["blueprint_name", "component_name"]
        },
        examples=({"blueprint_name": "BP_Ball", "component_name": "Sphere", "simulate_physics": True, "mass": 10.0},),
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
