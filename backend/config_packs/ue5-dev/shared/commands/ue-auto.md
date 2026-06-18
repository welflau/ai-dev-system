---
description: 根据游戏描述自动完成完整 UE 项目开发流程
---

# /ue-auto

输入一句游戏描述，AI 自动规划并执行从架构到关卡的完整开发流程。用户只需在关键节点确认。

## 用法

```
/ue-auto <游戏描述> [--output <项目路径>] [--skip-arch] [--dry-run]
```

## 执行前置

```python
import json, os
config     = json.loads(open('.claude/ue-config.json', encoding='utf-8').read())
ue_python  = config['ue_python_script']
ue_build   = config['ue_build_script']
unrealecc  = config['unrealecc_root']
output     = args.output or f"D:/UEProjects/{project_name}"
```

若 `.claude/ue-config.json` 不存在，提示先运行：
```
node {unrealecc_root}/scripts/install-ue.js --target .
/ue-init
```

## 执行流程

委托 `ue-orchestrator` agent 驱动以下阶段：

```
阶段 0  策划文档（GDD）→ /ue-gdd 生成 .claude/ue-runtime/GDD.md
        ↓
[CHECKPOINT 1] 向用户展示 GDD 摘要，确认：
  - 游戏类型和核心玩法是否正确？
  - out-of-scope 边界是否认可？
  - 规模估计（原型/Demo/完整）是否合适？
  等待用户答复后继续。（可跳过：--skip-gdd）

阶段 1  技术架构      → spawn ue-architect 读取 GDD，确定核心类/子系统
        ↓
[CHECKPOINT 2] 向用户展示架构方案，确认：
  - 核心 C++ 类结构是否认可？
  - 是否需要 GAS / BehaviorTree / 其他子系统？
  - 哪些需求在本次范围外？
  等待用户答复后继续。

阶段 2  项目骨架      → /ue-scaffold 生成文件 + ue_build.js 编译
        /ue-ci --skip-compile  → L1 静态检查
        /ue-ci --level l3      → 资产结构验证
        ↓ 编译失败：自动修复重试（最多 3 次）
[CHECKPOINT 3] 展示编译结果和 CI 报告，确认：
  - 编译 0 error，CI 全通过？
  - diff_summary 里有没有意外改动？
  继续生成蓝图？（Y/N）

阶段 3  核心蓝图      → spawn ue-blueprint-coder（按 GDD 中角色设计生成 BP）
阶段 4  测试关卡      → spawn ue-level-designer（按 GDD 中关卡设计布置场景）
        ↓
阶段 5  验收截图      → /ue-review 截图 + 场景诊断
        ↓
[CHECKPOINT 4] 展示截图和场景诊断，用户签收：
  - 截图是否符合 GDD 中的关卡设计？
  - 有没有明显问题需要修正？
  确认后输出最终报告。

输出报告（含 GDD 完成度 vs 实现对比、下一步建议）
```

## 参数说明

| 参数 | 说明 |
|------|------|
| `--output <path>` | 项目生成路径（默认 `D:/UEProjects/<ProjectName>`）|
| `--skip-gdd` | 跳过 GDD 生成（项目已有 GDD.md 时使用）|
| `--skip-arch` | 跳过架构设计阶段（适合简单项目）|
| `--dry-run` | 只输出规划，不实际执行 |
| `--stop-after <n>` | 执行到第 n 阶段后暂停（供逐步验证）|

## 进度追踪

每个阶段完成后自动更新 `.claude/ue-runtime/PROGRESS.md`。
GDD 保存到 `.claude/ue-runtime/GDD.md`，供后续会话参考。

## 适用场景

| 场景 | 建议 |
|------|------|
| 从零开始 | `/ue-auto`（完整 6 阶段，含 GDD）|
| 已有 GDD | `/ue-auto --skip-gdd` |
| 快速原型 | `/ue-auto --skip-arch --stop-after 4` |
| 仅生成文档 | 使用 `/ue-gdd` 替代 |
| 仅生成骨架 | 使用 `/ue-scaffold` 替代 |

## 示例

```
/ue-auto 第三人称动作游戏，单机，有近战战斗和跳跃

/ue-auto 俯视角双摇杆射击，有敌人 AI 追击和道具拾取
         --output D:/UEProjects/MyShooter

/ue-auto 2.5D 平台跳跃，有检查点系统 --skip-arch

/ue-auto 第一人称解谜游戏，有可互动物品 --dry-run
```

## 注意事项

- 需要 UE Editor 在线（阶段 3-5）
- 项目目录不能已存在（阶段 2 会新建）
- 阶段 2 编译可能需要 3-5 分钟
- 完整流程约 10-20 分钟（取决于项目复杂度）
