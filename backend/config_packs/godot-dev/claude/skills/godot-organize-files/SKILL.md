---
name: godot-organize-files
version: 3.0.0
displayName: 整理项目文件结构
description: >
  当 Godot 项目文件分散且没有清晰组织时使用。检测资源、脚本、场景和
  资源文件在根目录或不一致的位置。自动创建遵循 Godot 最佳实践的
  有组织的目录结构，移动文件并保留引用，更新所有依赖关系。
author: Asreonn
license: MIT
category: game-development
type: tool
difficulty: beginner
audience: [developers]
keywords:
  - godot
  - file-organization
  - directory-structure
  - project-cleanup
  - best-practices
  - asset-management
  - gdscript
  - godot-project
platforms: [macos, linux, windows]
repository: https://github.com/asreonn/godot-superpowers
homepage: https://github.com/asreonn/godot-superpowers#readme

permissions:
  filesystem:
    read: ["*"]
    write: ["*"]
    move: true
    delete: false
  git: true

behavior:
  auto_rollback: true
  validation: true
  git_commits: true

outputs: "整理后的目录结构、移动的文件并保留引用、git 提交"
requirements: "Git 仓库、Godot 4.x"
execution: "全自动，保留引用"
integration: "godot-organize-project 编排器的一部分，与 organize-assets 和 organize-scripts 协同工作"
---

# 整理项目文件结构

## 核心原则

**清晰的结构 = 轻松的导航。** 文件应该在你期望的位置。

## 本技能的功能

查找类似这样的项目：
```
my_game/
├── project.godot
├── player.gd
├── enemy.gd
├── sprite1.png
├── sound.wav
├── level1.tscn
├── main_menu.tscn
├── utility.gd
└── ...（50 多个文件在根目录）
```

转换为：
```
my_game/
├── project.godot
├── assets/
│   ├── sprites/
│   │   └── sprite1.png
│   └── audio/
│       └── sound.wav
├── scenes/
│   ├── levels/
│   │   └── level1.tscn
│   └── ui/
│       └── main_menu.tscn
└── scripts/
    ├── player.gd
    ├── enemy.gd
    └── utility.gd
```

## 检测模式

识别：
- 根目录中应该被整理的文件
- 不一致的命名（CamelCase、snake_case 混用）
- 资源与代码混杂
- 没有按类型或领域进行逻辑分组

## 何时使用

### 开始新项目
从一开始就建立结构。

### 接手遗留项目
项目在没有结构的情况下自然增长。

### 准备团队协作
团队需要一致的文件位置。

### 大规模重构之前
清晰的结构使重构更容易。

## 流程

1. **扫描** - 清点所有项目文件和当前结构
2. **分析** - 确定文件类型和关系
3. **规划** - 创建目标目录结构
4. **移动** - 重新定位文件，保留所有引用
5. **更新** - 修复 .tscn、.gd、project.godot 中的路径
6. **验证** - 确保所有引用仍然有效
7. **提交** - 每个逻辑分组移动后进行 git 提交

## 标准结构

### 推荐的组织方式

```
project_root/
├── project.godot
├── assets/
│   ├── sprites/
│   │   ├── characters/
│   │   ├── enemies/
│   │   ├── items/
│   │   └── environment/
│   ├── audio/
│   │   ├── music/
│   │   ├── sfx/
│   │   └── voice/
│   ├── fonts/
│   ├── materials/
│   ├── shaders/
│   └── models/       # 用于 3D 项目
├── scenes/
│   ├── characters/
│   ├── enemies/
│   ├── levels/
│   ├── ui/
│   └── components/
├── scripts/
│   ├── characters/
│   ├── enemies/
│   ├── components/
│   ├── managers/
│   └── utility/
├── resources/
│   ├── items/
│   ├── enemies/
│   └── abilities/
├── addons/           # 第三方插件
└── docs/             # 文档（可选）
```

## 创建的内容

- 整理后的目录结构
- 移动的文件并保留引用
- 更新的 .tscn 文件中的新路径
- 更新的脚本 preload() 路径
- 更新的 project.godot 自动加载配置
- 记录整理过程的 git 提交

## 智能分析

**检测文件类型：**
- **资源** - .png, .jpg, .wav, .ogg, .ttf, .glb
- **场景** - .tscn, .scn
- **脚本** - .gd, .cs
- **Resource** - .tres, .res
- **配置** - .cfg, .json, project.godot

**确定分组方式：**
- 按类型（精灵图、脚本、场景）
- 按领域（角色、敌人、UI）
- 按功能（组件、管理器、工具类）

## 集成

协同工作：
- **godot-organize-assets** - 进一步整理资源文件
- **godot-organize-scripts** - 进一步整理脚本文件
- **godot-organize-project**（编排器）- 作为完整整理的一部分运行

## 安全性

- 移动过程中保留所有文件引用
- Godot 的 .import 文件自动更新
- 验证失败时回滚
- 原始结构保存在 git 历史中

## 何时不使用

不要在以下情况重新整理：
- 项目已有清晰的结构
- 开发冲刺中期（时机不佳）
- 有意使用不同的自定义结构
- 外部工具依赖当前路径

## 路径更新

### 脚本更新
```gdscript
# 之前
var scene = preload("res://player.tscn")

# 之后
var scene = preload("res://scenes/characters/player.tscn")
```

### 场景更新
```ini
# 之前
[ext_resource path="res://player.gd" type="Script"]

# 之后
[ext_resource path="res://scripts/characters/player.gd" type="Script"]
```

### 自动加载更新
```ini
# 之前
[autoload]
GameManager="*res://game_manager.gd"

# 之后
[autoload]
GameManager="*res://scripts/managers/game_manager.gd"
```

## 整理策略

### 按类型（简单项目）
将所有精灵图放在一起，所有脚本放在一起。

### 按领域（中型项目）
按游戏概念分组（角色、敌人、关卡）。

### 按功能（大型项目）
按功能分组（战斗系统、背包系统）。

### 混合策略
组合策略（资源按类型，脚本按领域）。

## 收益

- **可发现性** - 在期望的位置找到文件
- **可扩展性** - 结构支持增长
- **新人入职** - 新团队成员轻松导航
- **一致性** - 项目间相同的结构
- **工具支持** - 工具在有组织的项目中工作更好

## 常见模式

| 之前 | 之后 |
|--------|-------|
| 根目录中的 `player.gd` | `scripts/characters/player.gd` |
| 根目录中的 `sprite.png` | `assets/sprites/characters/sprite.png` |
| 根目录中的 `level.tscn` | `scenes/levels/level.tscn` |
| 根目录中的 `item_data.tres` | `resources/items/item_data.tres` |

## 配置

可针对以下内容自定义：
- 不同的命名约定
- 替代结构（src/ 代替 scripts/）
- 项目特定的需求
- 团队偏好

默认值遵循 Godot 最佳实践和社区标准。
