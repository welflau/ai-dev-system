"""Player traversal setup action definitions."""

from __future__ import annotations

from .. import ActionDef


_PLAYER_TRAVERSAL_ACTIONS = [
    ActionDef(
        id="player_traversal.add_component",
        command="add_component_to_blueprint",
        tags=("player", "traversal", "movement", "dash", "doublejump", "component"),
        description="Add the reusable PlayerTraversalComponent to a 2.5D or TPS Character Blueprint.",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the target Character Blueprint"},
                "component_type": {
                    "type": "string",
                    "description": "Component class name; default is PlayerTraversalComponent",
                    "default": "PlayerTraversalComponent",
                },
                "component_name": {
                    "type": "string",
                    "description": "Component instance name; default is PlayerTraversal",
                    "default": "PlayerTraversal",
                },
                "component_properties": {
                    "type": "object",
                    "description": "Optional default properties such as TraversalMode, DashSpeed, DashDuration, DashCooldown, JumpNiagaraComponentName, DashNiagaraComponentName, BackpackComponentName, BackpackMesh.",
                },
            },
            "required": ["blueprint_name"],
        },
        examples=(
            {
                "blueprint_name": "BP_SideScrollingCharacter",
                "component_type": "PlayerTraversalComponent",
                "component_name": "PlayerTraversal",
                "component_properties": {
                    "TraversalMode": "SideScrolling2D",
                    "DashSpeed": "1600.0",
                    "DashDuration": "0.18",
                    "DashCooldown": "0.45",
                },
            },
        ),
    ),
    ActionDef(
        id="player_traversal.set_backpack_mesh",
        command="set_static_mesh_properties",
        tags=("player", "traversal", "backpack", "mesh", "stackobot"),
        description="Assign the migrated StackOBot backpack mesh to a Backpack StaticMeshComponent on a Character Blueprint.",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the target Character Blueprint"},
                "component_name": {
                    "type": "string",
                    "description": "Backpack StaticMeshComponent name; default is Backpack",
                    "default": "Backpack",
                },
                "static_mesh": {
                    "type": "string",
                    "description": "Backpack mesh asset path, for example /Game/StackOBot/Characters/Backpack/Mesh/SM_Backpack.SM_Backpack",
                },
                "material": {"type": "string", "description": "Optional material asset path"},
                "overlay_material": {"type": "string", "description": "Optional overlay material asset path"},
            },
            "required": ["blueprint_name", "component_name", "static_mesh"],
        },
        examples=(
            {
                "blueprint_name": "BP_SideScrollingCharacter",
                "component_name": "Backpack",
                "static_mesh": "/Game/StackOBot/Characters/Backpack/Mesh/SM_Backpack.SM_Backpack",
            },
        ),
    ),
    ActionDef(
        id="player_traversal.set_fx_binding",
        command="set_component_property",
        tags=("player", "traversal", "fx", "niagara", "jetpack", "dash", "doublejump"),
        description="Set a PlayerTraversalComponent binding property for jump, dash, backpack, or jetpack FX.",
        input_schema={
            "type": "object",
            "properties": {
                "blueprint_name": {"type": "string", "description": "Name of the target Character Blueprint"},
                "component_name": {
                    "type": "string",
                    "description": "PlayerTraversalComponent instance name; default is PlayerTraversal",
                    "default": "PlayerTraversal",
                },
                "property_name": {
                    "type": "string",
                    "description": "Property to set, e.g. JumpNiagaraComponentName, DashNiagaraComponentName, JumpNiagaraSystem, DashNiagaraSystem, BackpackComponentName, BackpackMesh",
                },
                "property_value": {"type": "string", "description": "UE text-format property value"},
            },
            "required": ["blueprint_name", "component_name", "property_name", "property_value"],
        },
        examples=(
            {
                "blueprint_name": "BP_SideScrollingCharacter",
                "component_name": "PlayerTraversal",
                "property_name": "DashNiagaraSystem",
                "property_value": "/Game/StackOBot/FX/JetpackThruster/FX_JetpackThruster.FX_JetpackThruster",
            },
        ),
    ),
]
