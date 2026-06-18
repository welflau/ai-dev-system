---
description: 根据游戏描述生成 UE 项目骨架结构
---

# /ue-scaffold

根据游戏类型和描述，生成标准 UE 项目骨架：目录结构、核心 C++ 类、基础配置。

## 用法

```
/ue-scaffold <游戏描述> [--output <路径>]
```

## 行为

1. 分析游戏类型（FPS/TPS/RPG/platformer 等），确定核心模块
2. 生成以下内容（缺任何一项都无法编译）：
   - `.uproject` 配置文件（**UTF-8 无 BOM**，自动启用 PythonScriptPlugin）
   - `Source/<Name>.Target.cs` — Game 编译目标（**必须**）
   - `Source/<Name>Editor.Target.cs` — Editor 编译目标（**必须**）
   - `Source/<Name>/<Name>.Build.cs` — 模块依赖
   - `Source/<Name>/<Name>.h/.cpp` — 模块入口
   - 核心 C++ 类（GameMode、PlayerController、Character）
   - `Config/DefaultGame.ini` / `DefaultEngine.ini` / `DefaultInput.ini`
   - `Content/` 目录结构（按资产命名规范）
3. 写入 `--output` 指定路径（默认当前目录）
4. **自动编译**：调用 `scripts/ue_build.js` 检测引擎路径并执行 UBT
   - 从 `.uproject` 的 `EngineAssociation` 字段读取版本（如 `"5.3"`）
   - 自动查找注册表和常见安装路径
   - 若找不到引擎，提示用户用 `--engine <路径>` 指定后重试
5. 编译成功后输出下一步操作指引

## 编译注意事项

- 参数命名：函数参数不能与基类成员同名（如 `SetupPlayerInputComponent` 参数应为 `PlayerInputComponent` 而非 `InputComponent`）
- `.uproject` 必须为 UTF-8 无 BOM，Windows 工具写文件时需显式指定编码
- `EngineAssociation` 必须与本机已安装的 UE 版本一致

## 核心类模板

根据游戏类型自动选择：

| 类型 | 生成的核心类 |
|------|------------|
| TPS/FPS | GameMode、PlayerController、Character（含 CameraComponent）、HUD |
| RPG | GameMode、PlayerController、Character（含 AttributeSet）、GameInstance（存档）|
| 平台跳跃 | GameMode、Character（含跳跃逻辑）、GameState（关卡管理）|
| 通用 | GameMode、PlayerController、Character |

## 执行前置

读取 `.claude/ue-config.json` 获取编译脚本路径（若存在）：

```python
config = json.loads(open('.claude/ue-config.json').read()) if os.path.exists('.claude/ue-config.json') else {}
ue_build = config.get('ue_build_script', '')
unrealecc_root = config.get('unrealecc_root', '')
```

若不在任何 UE 项目目录，从环境变量 `UNREALECC_ROOT` 获取 `ue_build.js` 路径。

## 注意事项

- 生成项目骨架**不需要** UE Editor 运行（纯文件生成）
- `.uproject` 必须使用 UTF-8 无 BOM 编码
- 生成完成后自动调用 `node {ue_build} --project <path>` 编译
- 编译成功后提示用户打开 UE Editor，再运行 `/ue-init`

## 示例

```
/ue-scaffold 第三人称动作 RPG，有技能系统和背包系统

/ue-scaffold 多人 FPS，5v5，有击中判定和击杀计分 --output D:/UEProjects/MyFPS

/ue-scaffold 2.5D 平台跳跃，单机，有关卡编辑器支持
```
