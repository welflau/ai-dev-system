---
name: godot-extract-resources
version: 3.0.0
displayName: 将数据提取为 Resource
description: >
  当 Godot 代码中存在硬编码的游戏数据（如 const 数组、字典或内嵌值）时使用。检测内联数据
  如敌人属性、物品定义、关卡配置等。自动提取为 .tres Resource 文件，使数据在编辑器中
  可见、易于修改，并支持数据驱动的设计。
author: Asreonn
license: MIT
category: game-development
type: tool
difficulty: beginner
audience: [developers]
keywords:
  - godot
  - resources
  - data-driven
  - const-arrays
  - dictionaries
  - tres-files
  - gdscript
  - game-data
platforms: [macos, linux, windows]
repository: https://github.com/asreonn/godot-superpowers
homepage: https://github.com/asreonn/godot-superpowers#readme

permissions:
  filesystem:
    read: [".gd", ".tres"]
    write: [".gd", ".tres", ".tscn"]
  git: true

behavior:
  auto_rollback: true
  validation: true
  git_commits: true

outputs: "Resource 文件（.tres）、Resource 脚本定义、更新后的引用代码、git 提交"
requirements: "Git 仓库, Godot 4.x"
execution: "全自动执行，保留数据完整性"
integration: "godot-refactor 编排器的一部分，创建数据驱动的架构"
---

# 将数据提取为 Resource

## 核心原则

**数据属于 Resource，而非代码。** 硬编码的值会使迭代缓慢且容易出错。

## 本技能的功能

查找如下模式：
```gdscript
# enemy.gd
const ENEMY_DATA = {
    "goblin": {"health": 50, "speed": 100, "damage": 10},
    "orc": {"health": 100, "speed": 80, "damage": 20},
    "dragon": {"health": 500, "speed": 150, "damage": 50}
}
```

转换为：
```gdscript
# enemy_stats.gd
class_name EnemyStats
extends Resource

@export var enemy_name: String
@export var health: int
@export var speed: float
@export var damage: int
```

创建 Resource 文件：
- `resources/enemies/goblin.tres`
- `resources/enemies/orc.tres`
- `resources/enemies/dragon.tres`

更新代码：
```gdscript
# enemy.gd
@export var stats: EnemyStats

func _ready():
    health = stats.health
    speed = stats.speed
    damage = stats.damage
```

## 检测模式

识别以下模式：
- 包含数据结构的 `const` 数组
- 包含游戏数据的字典
- 内嵌的配置值
- 硬编码的属性、参数、设置
- 基于类型字符串的 switch 语句

## 使用场景

### 构建数据密集型游戏
包含大量物品、敌人、关卡或配置的游戏。

### 迭代平衡性
希望无需修改代码即可快速调整数值。

### 与设计师协作
非程序员需要编辑游戏数据。

### 添加 Mod 支持
外部数据文件可实现 Mod 支持。

## 流程

1. **扫描** - 查找 const 数组、包含结构化数据的字典
2. **分析** - 识别数据模式和关系
3. **定义** - 创建 Resource 类定义
4. **提取** - 生成包含数据的 .tres 文件
5. **更新** - 修改代码以加载 Resource
6. **验证** - 确保数据正确加载
7. **提交** - 每种 Resource 类型对应一次 git 提交

## 转换示例

**转换前（硬编码数据）：**
```gdscript
# item_manager.gd
const ITEMS = [
    {
        "id": "health_potion",
        "name": "Health Potion",
        "description": "Restores 50 HP",
        "heal_amount": 50,
        "icon": "res://icons/potion.png"
    },
    {
        "id": "sword",
        "name": "Iron Sword",
        "description": "A basic sword",
        "damage": 15,
        "icon": "res://icons/sword.png"
    }
]

func get_item(id: String):
    for item in ITEMS:
        if item.id == id:
            return item
    return null
```

**转换后（基于 Resource）：**
```gdscript
# item_data.gd
class_name ItemData
extends Resource

@export var id: String
@export var item_name: String
@export_multiline var description: String
@export var icon: Texture2D
@export_group("Stats")
@export var heal_amount: int
@export var damage: int
```

```gdscript
# item_manager.gd
@export var items: Array[ItemData]

func get_item(id: String) -> ItemData:
    for item in items:
        if item.id == id:
            return item
    return null
```

**创建的文件：**
- `resources/items/health_potion.tres`
- `resources/items/iron_sword.tres`

## Resource 模式

### 简单 Resource
单一值（属性、设置、常量）。

### 组合 Resource
Resource 引用其他 Resource（武器 + 属性 + 效果）。

### Resource 库
不同类别的 Resource 数组。

### Resource 继承
基础 Resource 类与特化变体。

## 创建的内容

- `resources/` 或 `scripts/resources/` 中的 Resource 类定义
- 按目录结构组织的 .tres 文件
- 使用 @export var resource: ResourceType 的更新代码
- Resource 模式文档
- 每次 Resource 提取对应的 git 提交

## 智能分析

**识别数据类型：**
- **配置** - 设置、常量、调优值
- **内容** - 物品、敌人、关卡、技能
- **行为** - AI 模式、状态机、规则

**按类别组织：**
- `resources/items/` - 物品数据
- `resources/enemies/` - 敌人属性
- `resources/levels/` - 关卡配置
- `resources/abilities/` - 技能定义

## 集成

可与以下技能配合使用：
- **godot-extract-to-scenes** - 场景引用 Resource
- **godot-split-scripts** - Resource 减少脚本体量
- **godot-refactor**（编排器） - 作为完整重构的一部分运行

## 安全性

- 提取过程中精确保留数据
- 验证确保 Resource 正确加载
- 验证失败时回滚
- 原始数据保留在 git 历史中

## 不应使用的情况

以下情况不需要提取：
- 数据是真正的常量（数学常量、引擎限制）
- 数据在运行时变化（计算值）
- 数据是临时状态（不是配置）
- 提取会使代码更复杂

合理硬编码数据的示例：
- `const PI = 3.14159`
- `const MAX_PLAYERS = 4`（引擎限制）
- 基于其他数据的计算值

## Resource 组织

```
resources/
├── items/
│   ├── consumables/
│   │   ├── health_potion.tres
│   │   └── mana_potion.tres
│   └── weapons/
│       ├── iron_sword.tres
│       └── steel_axe.tres
├── enemies/
│   ├── goblin.tres
│   ├── orc.tres
│   └── dragon.tres
└── levels/
    ├── level_1.tres
    └── level_2.tres
```

## 优势

- **快速迭代** - 无需重新编译即可修改数据
- **设计师友好** - 在 Godot 检查器中编辑值
- **类型安全** - @export 提供验证和自动补全
- **可 Mod 化** - 外部 .tres 文件可被修改
- **版本控制** - 数据变更与代码变更分开追踪
- **热重载** - Godot 自动重载 Resource 变更

## 常见转换

| 转换前（硬编码） | 转换后（Resource） |
|-------------------|------------------|
| `const STATS = {...}` | `@export var stats: Stats` |
| `var data = ITEMS[0]` | `var data = preload("item.tres")` |
| `if type == "fire":` | `if ability.element == Element.FIRE:` |
| `const CONFIG = {...}` | `@export var config: GameConfig` |

## Resource 类型

### 内置 Resource
- Texture2D, Material, AudioStream
- Animation, Curve, Gradient
- Theme, StyleBox, Font

### 自定义 Resource
- EnemyStats, ItemData, LevelConfig
- AbilityDefinition, QuestData
- 任何游戏特定的数据结构

### Resource 集合
- Array[ItemData] 用于物品数据库
- Dictionary 用于查找表
- Resource 库场景
