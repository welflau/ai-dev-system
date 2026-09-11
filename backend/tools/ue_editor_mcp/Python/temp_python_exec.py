import sys
sys.path.insert(0, r'C:\P111\Plugins\UEEditorMCP\Python')
from ue_bridge import UEBridge
import json

ue = UEBridge()

script = """
import unreal

bp = unreal.EditorAssetLibrary.load_asset('/Game/P111/UI/Login/WBP_Login')

# Create Array variables
unreal.BlueprintEditorLibrary.add_member_variable(bp, "MaxPlayersOptions", unreal.EdGraphPinType(pin_category="text", pin_container_type=unreal.PinContainerType.ARRAY))
unreal.BlueprintEditorLibrary.add_member_variable(bp, "ConnectionOptions", unreal.EdGraphPinType(pin_category="text", pin_container_type=unreal.PinContainerType.ARRAY))

# We can't set array default values using set_blueprint_variable_default_value easily if it doesn't support arrays
# But we can try setting the string representation
unreal.BlueprintEditorLibrary.set_blueprint_variable_default_value(bp, "MaxPlayersOptions", '("2人","4人","8人","16人")')
unreal.BlueprintEditorLibrary.set_blueprint_variable_default_value(bp, "ConnectionOptions", '("局域网 (LAN)","在线匹配")')

unreal.BlueprintEditorLibrary.compile_blueprint(bp)
"""

res = ue.call("python.execute", script=script)
print(json.dumps(res, indent=2))
