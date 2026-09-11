import sys
sys.path.insert(0, r'C:\P111\Plugins\UEEditorMCP\Python')
from ue_bridge import UEBridge
import json

ue = UEBridge()

actions = [
    {
        "type": "apply_graph_patch",
        "params": {
            "blueprint_name": "WBP_Login",
            "graph_name": "EventGraph",
            "ops": [
                {
                    "op": "add_node",
                    "id": "Get_RotMax",
                    "node_type": "VariableGet",
                    "variable_name": "HostMaxPlayers_Rotator"
                },
                {
                    "op": "add_node",
                    "id": "Populate_Max",
                    "node_type": "FunctionCall",
                    "function_name": "PopulateTextLabels",
                    "target_class": "CommonRotator"
                },
                {
                    "op": "connect",
                    "from": {"node": "Get_RotMax", "pin": "HostMaxPlayers_Rotator"},
                    "to": {"node": "Populate_Max", "pin": "self"}
                },
                {
                    "op": "add_node",
                    "id": "Make_MaxArray",
                    "node_type": "MakeArray",
                    "num_inputs": 4
                },
                {
                    "op": "connect",
                    "from": {"node": "Make_MaxArray", "pin": "Array"},
                    "to": {"node": "Populate_Max", "pin": "Labels"}
                },
                {
                    "op": "set_pin_default",
                    "node": "Make_MaxArray",
                    "pin": "[0]",
                    "value": "2人"
                },
                {
                    "op": "set_pin_default",
                    "node": "Make_MaxArray",
                    "pin": "[1]",
                    "value": "4人"
                },
                {
                    "op": "set_pin_default",
                    "node": "Make_MaxArray",
                    "pin": "[2]",
                    "value": "8人"
                },
                {
                    "op": "set_pin_default",
                    "node": "Make_MaxArray",
                    "pin": "[3]",
                    "value": "16人"
                },
                {
                    "op": "add_node",
                    "id": "Get_RotConn",
                    "node_type": "VariableGet",
                    "variable_name": "HostConnection_Rotator"
                },
                {
                    "op": "add_node",
                    "id": "Populate_Conn",
                    "node_type": "FunctionCall",
                    "function_name": "PopulateTextLabels",
                    "target_class": "CommonRotator"
                },
                {
                    "op": "connect",
                    "from": {"node": "Get_RotConn", "pin": "HostConnection_Rotator"},
                    "to": {"node": "Populate_Conn", "pin": "self"}
                },
                {
                    "op": "add_node",
                    "id": "Make_ConnArray",
                    "node_type": "MakeArray",
                    "num_inputs": 2
                },
                {
                    "op": "connect",
                    "from": {"node": "Make_ConnArray", "pin": "Array"},
                    "to": {"node": "Populate_Conn", "pin": "Labels"}
                },
                {
                    "op": "set_pin_default",
                    "node": "Make_ConnArray",
                    "pin": "[0]",
                    "value": "局域网 (LAN)"
                },
                {
                    "op": "set_pin_default",
                    "node": "Make_ConnArray",
                    "pin": "[1]",
                    "value": "在线匹配"
                },
                {
                    "op": "connect",
                    "from": {"node": "8B4A7FF84EF0BD0373DA7AA36C125744", "pin": "then"},
                    "to": {"node": "Populate_Max", "pin": "execute"}
                },
                {
                    "op": "connect",
                    "from": {"node": "Populate_Max", "pin": "then"},
                    "to": {"node": "Populate_Conn", "pin": "execute"}
                }
            ]
        }
    },
    {
        "type": "auto_layout_selected",
        "params": {
            "blueprint_name": "WBP_Login",
            "graph_name": "EventGraph",
            "mode": "all"
        }
    },
    {
        "type": "compile_blueprint",
        "params": {
            "blueprint_name": "WBP_Login"
        }
    },
    {
        "type": "save_all",
        "params": {}
    }
]

res = ue.call("batch_execute", commands=actions)
print(json.dumps(res, indent=2))
