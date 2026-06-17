Build the current UE5 project.

```bash
# 检查引擎路径和 target 名称
python scripts/ue_python.py "import unreal; print(unreal.SystemLibrary.get_engine_version())"
```

若需要完整编译，请告知 target 名称（如 MyGameEditor），然后执行 UBT 编译命令。
