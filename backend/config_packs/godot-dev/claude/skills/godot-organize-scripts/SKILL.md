---
name: godot-organize-scripts
version: 3.0.0
displayName: 整理脚本文件
description: >
  当 Godot 项目的脚本分散且没有清晰组织时使用。检测脚本并按类别
  （角色、敌人、组件、管理器、工具类）整理。创建清晰的结构以展示
  架构层级和关系。保留所有引用和 class_name 声明。
author: Asreonn
license: MIT
category: game-development
type: tool
difficulty: beginner
audience: [developers]
keywords:
  - godot
  - script-organization
  - gdscript
  - file-structure
  - code-architecture
  - components
  - managers
  - best-practices
platforms: [macos, linux, windows]
repository: https://github.com/asreonn/godot-superpowers
homepage: https://github.com/asreonn/godot-superpowers#readme

permissions:
  filesystem:
    read: [".gd"]
    write: ["*"]
    move: true
    delete: false
  git: true

behavior:
  auto_rollback: true
  validation: true
  git_commits: true

outputs: "整理后的脚本目录、移动的文件并保留引用、git 提交"
requirements: "Git 仓库、Godot 4.x"
execution: "全自动，保留引用"
integration: "godot-organize-project 编排器的一部分，与 godot-split-scripts 协同工作"
---

# 整理脚本文件

## 核心原则

**脚本按架构层级和职责整理。** 代码结构揭示设计。

## 本技能的功能

查找类似这样的脚本目录：
```
scripts/
├── player.gd
├── enemy.gd
├── health_component.gd
├── game_manager.gd
├── utility.gd
├── inventory.gd
├── ui_manager.gd
└── ...（50 多个脚本）
```

转换为：
```
scripts/
├── characters/
│   ├── player.gd
│   └── character_base.gd
├── enemies/
│   ├── enemy.gd
│   ├── goblin.gd
│   └── enemy_ai.gd
├── components/
│   ├── health_component.gd
│   ├── movement_component.gd
│   └── combat_component.gd
├── managers/
│   ├── game_manager.gd
│   ├── ui_manager.gd
│   └── audio_manager.gd
├── systems/
│   └── inventory.gd
└── utility/
    ├── math_helper.gd
    └── constants.gd
```

## 检测模式

识别：
- 按架构角色分类的脚本
- 基类 vs 实现类
- 可复用组件 vs 特定实体
- 系统/管理器脚本
- 工具/辅助脚本

## 何时使用

### 代码库增长
脚本不断增多，组织已经丢失。

### 理解架构
希望文件夹结构反映设计。

### 团队新人入职
新开发者需要快速导航代码。

### 大规模重构之前
清晰的组织使重构更安全。

## 流程

1. **扫描** - 清点所有 .gd 文件并分析内容
2. **分类** - 根据角色和命名确定类别
3. **分组** - 查找相关脚本（继承、依赖）
4. **规划** - 创建目标目录结构
5. **移动** - 重新定位脚本，保留引用
6. **更新** - 修复 preload()、extends、场景中的路径
7. **验证** - 确保所有脚本正确加载
8. **提交** - 每个类别移动后进行 git 提交

## 组织结构

### 角色
玩家和 NPC 的脚本。
```
characters/
├── player.gd
├── npc.gd
├── character_base.gd
└── character_state_machine.gd
```

### 敌人
敌人实体和 AI 的脚本。
```
enemies/
├── enemy_base.gd
├── goblin.gd
├── orc.gd
├── ai/
│   ├── enemy_ai.gd
│   ├── patrol_ai.gd
│   └── chase_ai.gd
└── behaviors/
    ├── attack_behavior.gd
    └── flee_behavior.gd
```

### 组件
可复用的组件脚本。
```
components/
├── health_component.gd
├── movement_component.gd
├── combat_component.gd
├── inventory_component.gd
└── hitbox_component.gd
```

### 管理器
单例模式的管理器脚本。
```
managers/
├── game_manager.gd
├── audio_manager.gd
├── scene_manager.gd
├── save_manager.gd
└── input_manager.gd
```

### 系统
游戏系统（背包、任务、对话）。
```
systems/
├── inventory_system.gd
├── quest_system.gd
├── dialog_system.gd
└── crafting_system.gd
```

### UI
UI 相关脚本。
```
ui/
├── main_menu.gd
├── pause_menu.gd
├── hud.gd
├── inventory_ui.gd
└── widgets/
    ├── health_bar.gd
    └── button_hover.gd
```

### 工具类
辅助和工具脚本。
```
utility/
├── constants.gd
├── math_helper.gd
├── vector_utils.gd
└── debug_draw.gd
```

### Resource（脚本定义）
自定义 Resource 类定义。
```
resources/
├── item_data.gd
├── enemy_stats.gd
├── ability_definition.gd
└── level_config.gd
```

## 分类逻辑

### 角色脚本
- 名称包含 "player"、"npc"、"character"
- 继承 CharacterBody2D 或自定义角色基类
- 处理玩家/NPC 特定逻辑

### 敌人脚本
- 名称包含 "enemy"、"monster"、怪物类型
- 继承敌人基类或包含 AI 逻辑
- 处理敌对实体行为

### 组件脚本
- 名称以 "_component" 结尾
- 设计用于跨实体复用
- 单一职责（生命值、移动等）

### 管理器脚本
- 名称以 "_manager" 结尾
- 通常为自动加载的单例
- 管理全局状态或服务

### 系统脚本
- 名称以 "_system" 结尾
- 处理游戏机制（背包、任务）
- 领域特定逻辑

### 工具脚本
- 名称类似 "helper"、"utils"、"constants"
- 无状态的辅助函数
- 数学或字符串工具

## 创建的内容

- 按类别整理的脚本目录
- 专门分组的子目录
- 移动的脚本并保留引用
- 更新的 class_name 引用
- 更新 project.godot 中的自动加载路径
- 每个类别的 git 提交

## 智能分析

**检测关系：**
- 继承（基类和实现类）
- 依赖（preload 其他脚本的脚本）
- 命名模式（约定揭示用途）

**保持内聚性：**
- 相关脚本保持在一起
- 基类 + 派生类在同一类别
- 组件族分组

## 引用更新

### 脚本预加载
```gdscript
# 之前
const EnemyScene = preload("res://enemy.gd")

# 之后
const EnemyScene = preload("res://scripts/enemies/enemy.gd")
```

### 类继承
```gdscript
# 之前
extends "res://character_base.gd"

# 之后
extends "res://scripts/characters/character_base.gd"
```

### 场景脚本附加
```ini
# 之前
[ext_resource path="res://player.gd" type="Script"]

# 之后
[ext_resource path="res://scripts/characters/player.gd" type="Script"]
```

## 集成

协同工作：
- **godot-split-scripts** - 先拆分，再整理
- **godot-organize-files** - 基础文件整理
- **godot-organize-project**（编排器）- 完整项目整理

## 安全性

- 保留所有脚本引用
- class_name 声明正常工作
- 自动加载路径自动更新
- 验证失败时回滚
- 原始结构保存在 git 历史中

## 何时不使用

不要在以下情况重新整理：
- 脚本已经组织良好
- 架构要求自定义结构
- 冲刺中期（时机不佳）
- 外部工具依赖当前路径

## 收益

- **可发现性** - 按职责找到脚本
- **架构可见性** - 结构反映设计
- **新人入职** - 新开发者轻松导航
- **重构** - 清晰的变更边界
- **测试** - 更容易按层测试

## 命名约定

**可选：在整理时重命名**
- `PlayerController.gd` → `player_controller.gd`（snake_case）
- `EnemyAI.gd` → `enemy_ai.gd`

Godot 惯例偏好使用 snake_case 作为文件名。

## 架构层级

**典型层级结构：**
1. **实体** - characters/、enemies/
2. **组件** - components/
3. **系统** - systems/、managers/
4. **UI** - ui/
5. **工具类** - utility/

组织方式反映依赖方向（工具类不依赖任何东西，实体依赖所有东西）。

## 常见转换

| 之前 | 之后 |
|--------|-------|
| scripts/ 中的 `player.gd` | `scripts/characters/player.gd` |
| scripts/ 中的 `enemy_ai.gd` | `scripts/enemies/ai/enemy_ai.gd` |
| 混杂的 `health_component.gd` | `scripts/components/health_component.gd` |
| 根目录中的 `game_manager.gd` | `scripts/managers/game_manager.gd` |
| 分散的 `utils.gd` | `scripts/utility/math_helper.gd` |

## 配置

可针对以下内容自定义：
- 不同的架构模式（MVC、类 ECS 等）
- 团队特定的类别
- 领域特定的分组
- 整理深度（扁平 vs 深层级）

默认值遵循 Godot 基于组件的架构模式。
