import unreal

bp = unreal.EditorAssetLibrary.load_blueprint_class('/Game/P111/UI/Login/WBP_Login')
if not bp:
    bp = unreal.EditorAssetLibrary.load_asset('/Game/P111/UI/Login/WBP_Login')

# We can just add the MakeArray nodes and wire them.
# However, UE Python API for Blueprint manipulation is very limited. 
# Let's see if we can set the default values using a temporary struct or just using ue_bridge.py variable.create.
