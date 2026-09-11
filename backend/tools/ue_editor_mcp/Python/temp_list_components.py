import sys
import time
import json

sys.path.insert(0, r'C:\P111\Plugins\UEEditorMCP\Python')
from ue_bridge import UEBridge
ue = UEBridge()

print("Waiting for UE5...")
for i in range(60):
    try:
        if ue.ping().get('success'):
            print("Connected!")
            break
    except:
        pass
    time.sleep(2)

# Inspect via list_widget_components which uses Blueprint reflection (might give different result)
res = ue.call('list_widget_components', widget_name='WBP_Login')
print("=== list_widget_components ===")
print(json.dumps(res, indent=2, ensure_ascii=False)[:5000])
