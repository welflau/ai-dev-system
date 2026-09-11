import sys
import json
sys.path.insert(0, r'C:\P111\Plugins\UEEditorMCP\Python')
from ue_bridge import UEBridge

ue = UEBridge()
res = ue.call('get_widget_tree', asset_path='/Game/P111/UI/Login/WBP_Login', widget_name='WBP_Login')

def find_node(n, name):
    if n.get('name') == name: return n
    for c in n.get('children', []):
        f = find_node(c, name)
        if f: return f
    return None

print("HostButtons_Row:")
print(json.dumps(find_node(res.get('tree', {}), 'HostButtons_Row'), indent=2))
print("ServerBrowserButtons_Row:")
print(json.dumps(find_node(res.get('tree', {}), 'ServerBrowserButtons_Row'), indent=2))
