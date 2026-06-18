---
description: 在运行中的 UE Editor 里执行 Python 代码
---

# /ue-run

在当前运行的 UE Editor 中执行 Python 代码，返回执行结果。

## 用法

```
/ue-run <描述或代码片段>
```

## P-Start 协议（执行前必查）

```python
config    = json.loads(open('.claude/ue-config.json', encoding='utf-8').read())
ue_python = config['ue_python_script']
```

读取 `.claude/ue-runtime/PSP.md`，用「执行 Python / 连接 UE Editor」匹配，汇报：

```
[P-Start] 已查 PSP：命中 PSP-004（连接 UE Editor 必须用 {ue_python_script}）
```

若 `ue-config.json` 不存在，提示用户先运行 `/ue-init`。

## 行为

1. P-Start 协议（见上）
2. 根据用户描述生成合适的 `import unreal` Python 代码
3. 通过 `Bash("python {ue_python_script} \"...\"")` 发送到 UE Editor
4. 返回执行结果或错误信息

## 代码规范

- 遵循 `rules/ue-python.md` 的要求
- 修改资产必须包在 `ScopedEditorTransaction` 中
- 结尾调用 `save_all_dirty_assets()` 保存变更
- 包含验证逻辑，把操作结果 `print` 出来

## 错误处理

- 退出码 2：UE Editor 未运行，提示用户先打开 Editor 并启用 Python Plugin
- 退出码 1：Python 执行出错，显示错误信息并建议修正

## 示例

```
/ue-run 列出当前关卡所有 Actor 的名称和类型
/ue-run 把场景里所有点光源的强度设为 5000
/ue-run 查询 /Game/Characters/ 目录下的所有蓝图资产
```
