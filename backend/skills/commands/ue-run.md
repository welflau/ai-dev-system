---
description: 在运行中的 UE Editor 执行 Python 代码
args_hint: "<python code or 自然语言描述>"
requires_project: true
---

# /ue-run <python code | 自然语言描述>

在当前项目关联的 UE Editor 中执行 Python 代码。

支持两种输入形式：

1. **直接 Python 代码** — 原样发送执行
   ```
   /ue-run import unreal; print(unreal.SystemLibrary.get_engine_version())
   /ue-run import unreal; actors = unreal.EditorLevelLibrary.get_all_level_actors(); print(len(actors))
   ```

2. **自然语言描述** — 先由 AI 生成合适的 `import unreal` Python 代码，再调用 `ue_run_python` 工具执行
   ```
   /ue-run 列出关卡所有 Actor 的名称和类型
   /ue-run 把场景里所有点光源强度设为 5000
   /ue-run 在原点创建一个 Cube StaticMeshActor
   ```

**前置条件**：UE Editor 已运行，Python Remote Execution 已开启。

## 代码规范

- 遵循 `rules/ue-python.md` 的要求
- 修改资产必须包在 `ScopedEditorTransaction` 中
- 结尾调用 `save_all_dirty_assets()` 保存变更
- 包含验证逻辑，把操作结果 `print` 出来

## 错误处理

- UE Editor 未运行 → 提示用户先打开 Editor 并启用 Remote Execution
- Python 执行出错 → 显示错误信息并建议修正
