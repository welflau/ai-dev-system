---
description: 在运行中的 UE Editor 执行 Python 代码
args_hint: "<python code>"
requires_project: true
---

# /ue-run <python code>

在当前项目关联的 UE Editor 中直接执行 Python 代码。

```
/ue-run import unreal; print(unreal.SystemLibrary.get_engine_version())
/ue-run import unreal; actors = unreal.EditorLevelLibrary.get_all_level_actors(); print(len(actors))
```

**前置条件**：UE Editor 已运行，Python Remote Execution 已开启。
