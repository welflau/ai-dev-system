import sys
sys.path.insert(0, r'C:\P111\Plugins\UEEditorMCP\Python')
from ue_bridge import UEBridge

ue = UEBridge()
res = ue.call('get_widget_tree', asset_path='/Game/P111/UI/Login/WBP_Login', widget_name='WBP_Login')

def extract_names(n):
    names = [n.get('name', '')]
    for c in n.get('children', []):
        names.extend(extract_names(c))
    return names

tree = res.get('tree', {})
names = extract_names(tree)
print("All widget names:")
print("\n".join([n for n in names if n]))
