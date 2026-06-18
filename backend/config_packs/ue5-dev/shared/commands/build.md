Build the current UE5 project.

```bash
# 检查引擎版本
python scripts/ue_python.py "import unreal; print(unreal.SystemLibrary.get_engine_version())"

# 保存未提交的资产
python scripts/ue_python.py "
import unreal
result = unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
print('Saved:', result)
"
```

若需要完整 UBT 编译，请告知 target 名称（如 MyGameEditor），然后执行 UBT 编译命令。
