Build the UE5 project by invoking the UnrealBuildTool via Python Editor Script.

```bash
python scripts/ue_python.py "
import unreal
result = unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
print('Saved:', result)
"
```

若需要完整 UBT 编译，需要知道 target 名称（如 MyGameEditor）。
