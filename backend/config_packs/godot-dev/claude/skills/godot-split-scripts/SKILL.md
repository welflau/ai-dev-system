---
name: godot-split-scripts
version: 3.0.0
displayName: 拆分臃肿脚本
description: >
  用于 Godot 脚本超过 150 行或承担多个职责时。
  检测做了太多事情的脚本（玩家移动 + 战斗 + 背包 + UI）。
  自动按照单一职责原则拆分为专注的脚本，
  精确保留原有行为，并为每次拆分创建 git 提交。
author: Asreonn
license: MIT
category: game-development
type: tool
difficulty: intermediate
audience: [developers]
keywords:
  - godot
  - script-splitting
  - refactoring
  - single-responsibility
  - component-pattern
  - gdscript
  - code-organization
  - monolithic-scripts
platforms: [macos, linux, windows]
repository: https://github.com/asreonn/godot-superpowers
homepage: https://github.com/asreonn/godot-superpowers#readme

permissions:
  filesystem:
    read: [".gd", ".tscn"]
    write: [".gd", ".tscn"]
  git: true

behavior:
  auto_rollback: true
  validation: true
  git_commits: true

outputs: "拆分后的单一职责脚本、保留的原有行为、每次拆分的 git 提交"
requirements: "Git 仓库、Godot 4.x"
execution: "全自动，包含行为验证"
integration: "属于 godot-refactor 编排器的一部分，可与 godot-add-signals 配合使用"
---

# 拆分臃肿脚本

## 核心原则

**一个脚本，一个职责。** 超过 150 行的脚本通常承担了太多事情。

## 本技能的功能

找到类似这样的脚本：
```gdscript
# player.gd - 500 行
class_name Player
extends CharacterBody2D

# 移动（第 1-100 行）
func _physics_process(delta): ...
func handle_input(): ...
func move(): ...

# 战斗（第 101-200 行）
func take_damage(amount): ...
func attack(): ...
func die(): ...

# 背包（第 201-350 行）
func add_item(item): ...
func remove_item(item): ...
func use_item(item): ...

# UI（第 351-500 行）
func update_health_bar(): ...
func show_inventory(): ...
```

转换为：
```gdscript
# player.gd - 50 行（协调器）
class_name Player
extends CharacterBody2D

@onready var movement = $MovementComponent
@onready var combat = $CombatComponent
@onready var inventory = $InventoryComponent
@onready var ui = $UIComponent

# 委托给各组件
```

## 检测模式

识别以下特征的脚本：
- 超过 150 行
- 有多个逻辑分区（如注释 "# 移动"、"# 战斗"）
- 处理不相关的职责（物理 + UI + 数据管理）
- 有大量用于不同系统的导出变量
- 混合了不同的抽象层级

## 使用场景

### 你正在添加新功能
向已经很大的脚本中添加新功能只会让情况更糟。

### 你正在调试复杂代码
大型脚本难以理解和测试。

### 你正在为团队协作做准备
更小的脚本减少合并冲突，改善代码审查体验。

### 你正在添加测试
单一职责的脚本更容易进行隔离测试。

## 流程

1. **扫描** - 找到超过 150 行的脚本
2. **分析** - 识别逻辑分组和职责
3. **拆分** - 将每个职责提取到独立脚本
4. **保留** - 确保行为完全不变
5. **验证** - 运行测试确认没有回归
6. **提交** - 每次拆分操作创建 git 提交

## 示例转换

**之前（player.gd - 300 行）：**
```gdscript
extends CharacterBody2D

const SPEED = 300.0
const JUMP_VELOCITY = -400.0

var health = 100
var max_health = 100
var inventory = []

func _physics_process(delta):
    # 移动逻辑（50 行）
    ...

func take_damage(amount):
    # 战斗逻辑（30 行）
    ...

func add_item(item):
    # 背包逻辑（40 行）
    ...

func update_ui():
    # UI 逻辑（30 行）
    ...
```

**之后（player.gd - 30 行）：**
```gdscript
extends CharacterBody2D

@onready var movement: MovementComponent = $MovementComponent
@onready var combat: CombatComponent = $CombatComponent
@onready var inventory: InventoryComponent = $InventoryComponent
@onready var ui: UIComponent = $UIComponent

func _ready():
    combat.health_changed.connect(ui.update_health_bar)
    inventory.item_added.connect(ui.update_inventory)
```

**创建的新文件：**
- `movement_component.gd` - 处理 SPEED、JUMP_VELOCITY、_physics_process
- `combat_component.gd` - 处理 health、take_damage、die
- `inventory_component.gd` - 处理 inventory 数组、add_item、remove_item
- `ui_component.gd` - 处理 update_health_bar、show_inventory

## 拆分策略

### 按领域拆分
按游戏概念拆分（移动、战斗、背包）。

### 按层级拆分
按抽象层级拆分（输入处理、状态管理、渲染）。

### 按职责拆分
按变更原因不同来拆分。

## 创建的内容

- 具有单一明确目的的组件脚本
- 保留在正确位置的 @export 变量
- 用于组件间通信的 Signal 连接
- 更新后的场景文件，包含新的组件 Node
- 记录每次拆分的 git 提交

## 智能分析

**识别清晰的边界：**
- 操作相同变量的函数
- 注释指示的逻辑分组
- 相关功能（所有 UI、所有物理）

**保留集成：**
- 主脚本委托给各组件
- 需要时通过 Signal 连接组件
- 公共 API 保持兼容

## 集成

可搭配使用：
- **godot-extract-to-scenes** - 提取场景后再拆分
- **godot-add-signals** - 为组件间通信添加 Signal
- **godot-refactor**（编排器）- 作为完整重构的一部分运行

## 安全性

- 精确保留原有行为（无功能变更）
- 每次拆分后运行验证测试
- 测试失败时自动回滚
- git 历史保留原始脚本

## 何时不使用

以下情况不要拆分：
- 脚本低于 150 行且职责单一
- 脚本有单一明确的职责
- 拆分后会使代码更难理解
- 函数紧密耦合且无法分离

保持简单的事情简单。

## 阈值配置

默认值：150 行（Godot 最佳实践）

可根据以下因素调整：
- 团队偏好
- 脚本复杂度
- 领域需求

低于阈值的脚本会被跳过，除非它们明显承担了多个职责。
