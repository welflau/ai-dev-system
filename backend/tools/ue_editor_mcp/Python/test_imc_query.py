import sys
sys.path.insert(0, r"c:\P111\Plugins\UEEditorMCP\Python")
from ue_bridge import UEBridge

ue = UEBridge()

# 测试连接
result = ue.call("ping")
print(f"[PING] {result}")

# 尝试通过 editor.get_asset_properties 查询 IMC 内容
result2 = ue.call("editor.get_asset_properties", asset_path="/Game/Input/IMC_Als_Default")
print(f"[GET_ASSET_PROPS] {result2}")

ue._conn.close()
