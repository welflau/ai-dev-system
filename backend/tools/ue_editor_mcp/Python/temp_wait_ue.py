import sys
import time

sys.path.insert(0, r'C:\P111\Plugins\UEEditorMCP\Python')
from ue_bridge import UEBridge
ue = UEBridge()

print("Waiting for UE5 to start...")
for i in range(30):
    try:
        res = ue.ping()
        if res.get('success'):
            print("Connected!")
            break
    except Exception as e:
        pass
    time.sleep(1)

res = ue.call('get_widget_tree', asset_path='/Game/P111/UI/Login/WBP_Login', widget_name='WBP_Login')

def get_types(n):
    types = [(n.get('name',''), n.get('class',''))]
    for c in n.get('children', []):
        types.extend(get_types(c))
    return types

tree = res.get('tree', {})
if not tree:
    print("Tree is empty or error:", res)
else:
    names = [t[0] for t in get_types(tree)]
    print("MainHostGame_Btn exists:", 'MainHostGame_Btn' in names)
    print("ServerBrowserButtons_Row exists:", 'ServerBrowserButtons_Row' in names)
