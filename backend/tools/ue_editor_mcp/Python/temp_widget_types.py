import sys
sys.path.insert(0, r'C:\P111\Plugins\UEEditorMCP\Python')
from ue_bridge import UEBridge

ue = UEBridge()
res = ue.call('get_widget_tree', asset_path='/Game/P111/UI/Login/WBP_Login', widget_name='WBP_Login')

def get_types(n):
    types = [(n.get('name',''), n.get('class',''))]
    for c in n.get('children', []):
        types.extend(get_types(c))
    return types

tree = res.get('tree', {})
for t in get_types(tree):
    print(f"{t[0]}: {t[1]}")
