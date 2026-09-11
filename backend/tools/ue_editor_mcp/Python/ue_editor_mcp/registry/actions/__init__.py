"""Action definitions package, split by functional domain."""

from __future__ import annotations

from .. import ActionRegistry
from .blueprint import _BLUEPRINT_ACTIONS
from .component import _COMPONENT_ACTIONS
from .editor import _EDITOR_ACTIONS
from .layout import _LAYOUT_ACTIONS
from .node_event import _NODE_EVENT_ACTIONS
from .node_dispatcher import _NODE_DISPATCHER_ACTIONS
from .node_function import _NODE_FUNCTION_ACTIONS
from .node_variable import _NODE_VARIABLE_ACTIONS
from .node_reference import _NODE_REFERENCE_ACTIONS
from .node_flow import _NODE_FLOW_ACTIONS
from .graph import _GRAPH_ACTIONS
from .variable_management import _VARIABLE_MGMT_ACTIONS
from .function_management import _FUNCTION_MGMT_ACTIONS
from .struct_switch import _STRUCT_SWITCH_ACTIONS
from .material import _MATERIAL_ACTIONS
from .widget import _WIDGET_ACTIONS
from .input_mapping import _INPUT_ACTIONS
from .async_action import _ASYNC_ACTION_ACTIONS
from .widget_variable import _WIDGET_VARIABLE_ACTIONS
from .self_evolution import _SELF_EVOLUTION_ACTIONS
from .niagara import _NIAGARA_ACTIONS
from .niagara_renderer import _NIAGARA_RENDERER_ACTIONS
from .player_traversal import _PLAYER_TRAVERSAL_ACTIONS


_ACTION_GROUPS = (
    _BLUEPRINT_ACTIONS,
    _COMPONENT_ACTIONS,
    _EDITOR_ACTIONS,
    _LAYOUT_ACTIONS,
    _NODE_EVENT_ACTIONS,
    _NODE_DISPATCHER_ACTIONS,
    _NODE_FUNCTION_ACTIONS,
    _NODE_VARIABLE_ACTIONS,
    _NODE_REFERENCE_ACTIONS,
    _NODE_FLOW_ACTIONS,
    _GRAPH_ACTIONS,
    _VARIABLE_MGMT_ACTIONS,
    _FUNCTION_MGMT_ACTIONS,
    _STRUCT_SWITCH_ACTIONS,
    _MATERIAL_ACTIONS,
    _WIDGET_ACTIONS,
    _INPUT_ACTIONS,
    _ASYNC_ACTION_ACTIONS,
    _WIDGET_VARIABLE_ACTIONS,
    _SELF_EVOLUTION_ACTIONS,
    _NIAGARA_ACTIONS,
    _NIAGARA_RENDERER_ACTIONS,
    _PLAYER_TRAVERSAL_ACTIONS,
)


def register_all_actions(registry: ActionRegistry) -> None:
    """Register every action in the registry."""
    for actions in _ACTION_GROUPS:
        registry.register_many(actions)
