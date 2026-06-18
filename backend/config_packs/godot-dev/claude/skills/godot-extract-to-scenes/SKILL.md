---
name: godot-extract-to-scenes
version: 3.0.0
displayName: 将代码创建的对象提取为场景
description: >
  当构建 Godot 功能时，代码使用 .new() 创建节点而非使用场景时触发。
  检测 Timer.new()、Area2D.new()、Sprite2D.new() 等代码创建的对象。
  自动生成 .tscn 场景文件，更新父脚本使用 @onready 引用，并创建可复用的组件库。
author: Asreonn
license: MIT
category: game-development
type: tool
difficulty: intermediate
audience: [developers]
keywords:
  - godot
  - scene-extraction
  - component-library
  - new-operator
  - node-creation
  - code-refactoring
  - tscn-generation
  - gdscript
platforms: [macos, linux, windows]
repository: https://github.com/asreonn/godot-superpowers
homepage: https://github.com/asreonn/godot-superpowers#readme

permissions:
  filesystem:
    read: [".gd", ".tscn", ".tres"]
    write: [".tscn", ".tres", ".gd"]
  git: true

behavior:
  auto_rollback: true
  validation: true
  git_commits: true

outputs: "包含 .tscn 场景、预设资源、更新后的父脚本、git 提交的组件库"
requirements: "Git 仓库，Godot 4.x"
execution: "全自动执行，每个组件一次 git 提交"
integration: "godot-refactor 编排器的一部分，与 godot-split-scripts 协同工作"
---

# 将代码创建的对象提取为场景

## 核心原则

**每个节点都应该是一个场景。** 使用 `.new()` 创建的代码对象应当只在真正需要动态内容时作为罕见的例外。

## 此技能的功能

查找如下模式：
```gdscript
var timer = Timer.new()
timer.wait_time = 2.0
timer.one_shot = true
add_child(timer)
```

转换为：
```gdscript
@onready var timer: Timer = $Timer
# Timer 现在是场景节点，在编辑器中配置
```

## 检测模式

扫描以下模式：
- `Timer.new()`
- `Area2D.new()`、`CollisionShape2D.new()`
- `Sprite2D.new()`、`AnimatedSprite2D.new()`
- `AudioStreamPlayer.new()`、`AudioStreamPlayer2D.new()`
- `Control.new()`、`Label.new()`、`Button.new()`
- 任何 `Node*.new()` 模式

## 使用时机

### 你正在构建新功能
你的代码动态创建对象，但这些对象实际上应该作为场景存在。

### 你正在重构遗留代码
旧代码中的 `.new()` 调用使节点在编辑器中不可见。

### 你希望在检视器中可见
你希望在 Godot 编辑器中配置属性，而不是在代码中配置。

## 流程

1. **扫描** - 在 .gd 文件中查找所有 `.new()` 模式
2. **分析** - 确定节点类型、属性、父子关系
3. **生成** - 创建配置正确的 .tscn 场景文件
4. **更新** - 将代码创建替换为 @onready 引用
5. **提交** - 每个提取的组件一次 git 提交

## 转换示例

**转换前：**
```gdscript
# player.gd
func _ready():
    var hitbox = Area2D.new()
    hitbox.name = "Hitbox"
    var collision = CollisionShape2D.new()
    var shape = RectangleShape2D.new()
    shape.size = Vector2(32, 48)
    collision.shape = shape
    hitbox.add_child(collision)
    add_child(hitbox)
```

**转换后：**
```gdscript
# player.gd
@onready var hitbox: Area2D = $Hitbox
# Hitbox 现在作为场景节点配置在 player.tscn 中
```

**生成的文件：**
```ini
# components/hitbox_component.tscn
[gd_scene load_steps=2 format=3]

[sub_resource type="RectangleShape2D" id="1"]
size = Vector2(32, 48)

[node name="Hitbox" type="Area2D"]

[node name="CollisionShape2D" type="CollisionShape2D" parent="."]
shape = SubResource("1")
```

## 创建的内容

- `components/` 目录中的组件库
- 具有正确节点层级的 .tscn 场景文件
- 用于可复用配置的预设 .tres 文件
- 使用 @onready 引用更新后的父脚本
- 记录每次提取的 git 提交

## 智能检测

**跳过有意的动态创建：**
- 在循环中创建的对象（生成敌人）
- 条件创建的对象（不同武器类型）
- 可变类型的对象（插件系统）

**聚焦于静态对象：**
- 每次创建的都是相同对象
- 属性设置为常量值
- 应在编辑器中可见

## 集成

可与以下技能配合使用：
- **godot-split-scripts** - 先提取，再拆分大型脚本
- **godot-add-signals** - 对提取的组件使用 Signal
- **godot-refactor**（编排器）- 作为完整重构的一部分运行

## 安全性

- 每个操作都创建 git 提交
- 提取后运行验证测试
- 测试失败时自动回滚
- 原始代码保留在 git 历史中

## 不应使用的情况

以下情况不应提取：
- 对象是动态创建的（在循环中、基于数据）
- 对象类型在运行时变化
- 对象是真正的临时对象（频繁创建和销毁）
- 代码已经在使用 PackedScene.instantiate()

这些是 `.new()` 的合理用法，应保留在代码中。
