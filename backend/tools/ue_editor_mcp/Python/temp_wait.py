import time
import sys
sys.path.insert(0, r'C:\P111\Plugins\UEEditorMCP\Python')
from ue_bridge import UEBridge

for i in range(30):
    try:
        ue = UEBridge()
        res = ue.ping()
        print("Connected!")
        sys.exit(0)
    except:
        time.sleep(2)
print("Timeout")
sys.exit(1)
