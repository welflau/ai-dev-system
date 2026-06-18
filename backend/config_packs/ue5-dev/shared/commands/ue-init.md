---
description: 初始化 UE 项目的 AI 工作流配置
---

# /ue-init

初始化当前 UE 项目目录，完善引擎路径配置，验证 UE Editor 连接。

## 前置条件

必须在 **UE 项目目录**下运行（不是 UnrealECC 目录）：

```bash
cd D:/UEProjects/MyGame
claude
/ue-init
```

## 行为

1. **读取 `.claude/ue-config.json`**（由 `install-ue.js --target` 生成）
2. **验证引擎路径**：确认 `engine_path` 正确，显示版本号
3. **检测引擎源码**（自动判断）：
   - 检查 `engine_path/Engine/Source/Runtime` 是否存在
   - 写入 `has_source` 和 `engine_source_path`
   - 告知用户当前 `/ue-extend` 的能力边界
4. **初始化运行时目录**：
   - 运行 `python {unrealecc_root}/scripts/ue_runtime_init.py --project .`
   - 创建 `.claude/ue-runtime/`（PROJECT_MAP / SUBSYSTEMS / DECISIONS / PROGRESS）
   - 创建 `.claude/ue-knowledge/`（子系统能力文档存放处）
   - 已存在则跳过，不覆盖
5. **验证 UE Editor 连接**：
   - 运行 `python {ue_python_script} "import unreal; print(unreal.SystemLibrary.get_engine_version())"`
   - 成功则更新 `editor_online: true`
6. **更新 `ue-config.json`**，写入完整字段

## 引擎源码版本说明

| 版本 | `has_source` | `/ue-extend` 能力 |
|------|-------------|------------------|
| 商店版（Launcher）| `false` | 只能读 `.h` 头文件，Phase 3 无法改引擎源码 |
| 源码版（GitHub）| `true` | 完整读 `.cpp`，可修改引擎源码（最小化改动）|

## 脚本调用说明

所有 `/ue-*` 命令通过 `ue-config.json` 中的绝对路径调用工具脚本，不依赖相对路径：

```bash
# 从 ue-config.json 读取
ue_python_script = config["ue_python_script"]
# 例如：F:/A_Works/UnrealECC/scripts/ue_python.py

# 执行时使用绝对路径
python {ue_python_script} "import unreal; ..."
```

若 `ue-config.json` 不存在，先运行：

```bash
node F:/A_Works/UnrealECC/scripts/install-ue.js --target .
```

## 输出示例

```
✅  引擎路径    G:\EpicGames\UE_5.3
✅  源码版本    has_source=true（/ue-extend 完整能力可用）
✅  Editor      在线（UE 5.5.3）
✅  配置更新    .claude/ue-config.json
```

## 使用时机

- 新 UE 项目首次使用 UnrealECC 时运行一次
- 切换引擎版本或项目后重新运行
- Editor 连接失败时重新运行以刷新 `editor_online` 状态
