import sys
import json
sys.path.insert(0, r'C:\P111\Plugins\UEEditorMCP\Python')
from ue_bridge import UEBridge

ue = UEBridge()
res = ue.call('get_widget_tree', asset_path='/Game/P111/UI/Login/WBP_Login', widget_name='WBP_Login')

def find_node(n, name):
    if n and name in n.get('name', ''): return n
    for c in n.get('children', []) if n else []:
        f = find_node(c, name)
        if f: return f
    return None

print(json.dumps(find_node(res.get('tree', {}), 'MainHostGame_Btn'), indent=2))
