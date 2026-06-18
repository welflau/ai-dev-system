---
name: godot-add-signals
version: 3.0.0
displayName: 用 Signal 替换耦合
description: >
  当 Godot 代码中存在通过 get_node()、get_parent() 或直接引用产生的紧耦合依赖时使用。
  检测耦合模式并将其转换为基于 Signal 的通信方式。组件变得独立、可测试且可复用。
  在改进架构的同时精确保留原有行为。
author: Asreonn
license: MIT
category: game-development
type: tool
difficulty: intermediate
audience: [developers]
keywords:
  - godot
  - signals
  - decoupling
  - get-node
  - get-parent
  - architecture
  - gdscript
  - loose-coupling
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

outputs: "Signal 定义、Signal 连接、解耦组件、git 提交"
requirements: "Git 仓库, Godot 4.x"
execution: "全自动执行，保留原有行为"
integration: "godot-refactor 编排器的一部分，可与 godot-split-scripts 配合使用"
---

# 用 Signal 替换耦合

## 核心原则

**组件之间通过 Signal 通信，而非直接引用。** 耦合会使代码变得脆弱且难以测试。

## 本技能的功能

查找如下模式：
```gdscript
# player.gd
func take_damage(amount):
    health -= amount
    get_node("../UI/HealthBar").update(health)  # TIGHT COUPLING
    get_parent().get_node("ScoreManager").reduce_score()  # FRAGILE PATH
```

转换为：
```gdscript
# player.gd
signal health_changed(new_health)

func take_damage(amount):
    health -= amount
    health_changed.emit(health)  # SIGNAL - NO COUPLING
```

```gdscript
# main.gd (or scene setup)
func _ready():
    player.health_changed.connect(ui.health_bar.update)
    player.health_changed.connect(score_manager.on_player_damaged)
```

## 检测模式

识别以下模式：
- `get_node("../path")` - 向上路径导航
- `get_parent().something` - 父节点依赖
- `find_child("name")` - 运行时搜索
- `has_method()` - 紧接口耦合
- 直接的 owner 引用导致的循环依赖

## 使用场景

### 重构遗留代码
旧代码中存在通过 get_node 链产生的意大利面条式依赖。

### 构建可测试系统
希望在没有完整场景树的情况下独立测试组件。

### 创建可复用组件
组件应该能在不同上下文中使用而无需修改。

### 遇到脆弱代码
场景结构的变更会破坏无关功能。

## 流程

1. **扫描** - 查找所有 get_node()、get_parent()、find_child() 的使用
2. **分析** - 识别 Node 之间的信息流
3. **定义 Signal** - 为通信创建 Signal 定义
4. **替换** - 将直接调用转换为 Signal 发射
5. **连接** - 在合适的编排点连接 Signal
6. **验证** - 确保行为完全保留
7. **提交** - 每次解耦操作对应一次 git 提交

## 转换示例

**转换前（紧耦合）：**
```gdscript
# enemy.gd
extends CharacterBody2D

func die():
    var player = get_node("../Player")  # FRAGILE PATH
    player.add_score(100)

    var audio = get_parent().get_node("AudioManager")  # TIGHT COUPLING
    audio.play_sound("enemy_death")

    queue_free()
```

**转换后（基于 Signal）：**
```gdscript
# enemy.gd
extends CharacterBody2D

signal died(score_value: int)
signal death_sound_requested(sound_name: String)

func die():
    died.emit(100)
    death_sound_requested.emit("enemy_death")
    queue_free()
```

```gdscript
# main.gd (orchestrator)
func _ready():
    for enemy in enemies:
        enemy.died.connect(player.add_score)
        enemy.death_sound_requested.connect(audio_manager.play_sound)
```

## Signal 模式

### 一对多
一个发射器，多个监听器（生命值变化 → 更新 UI + 保存游戏 + 成就检查）。

### 事件广播
宣布某事发生，而不关心谁在监听。

### 请求-响应
请求服务而不知道提供者是谁（request_ammo → 由谁处理弹药就由谁响应）。

### 状态变更通知
状态变更时发出通知（entered_water、jumped、landed）。

## 创建的内容

- 带类型参数的 Signal 定义
- 在适当位置的 Signal 发射
- 在编排脚本中的 Signal 连接
- Signal 用途和参数的文档说明
- 记录每次解耦的 git 提交

## 智能分析

**识别耦合类型：**
- **结构耦合** - 依赖于场景树结构
- **接口耦合** - 调用其他 Node 的特定方法
- **数据耦合** - 访问其他 Node 的数据

**选择适当的解决方案：**
- Signal 用于事件和通知
- 依赖注入用于服务
- 场景组合用于可复用组件

## 集成

可与以下技能配合使用：
- **godot-split-scripts** - 先拆分，再解耦
- **godot-extract-to-scenes** - 提取场景，再添加 Signal
- **godot-refactor**（编排器） - 作为完整重构的一部分运行

## 安全性

- 精确保留原有行为
- Signal 连接自动测试
- 验证失败时回滚
- 原始耦合保留在 git 历史中

## 不应使用的情况

以下情况不需要添加 Signal：
- 父子关系是有意的设计
- 组件确实需要特定的父类型
- 耦合在同一职责边界内
- 添加 Signal 会使代码更复杂而非更简洁

合理耦合的示例：
- UI 按钮调用父对话框的关闭方法
- 子 Node 访问父节点的导出属性
- 组件访问 owner 的公共 API

## Signal 命名规范

**事件（过去时）：**
- `health_changed`
- `item_collected`
- `enemy_died`

**请求（祈使语气）：**
- `damage_requested`
- `play_sound`
- `spawn_particle`

**状态变更：**
- `entered_state`
- `exited_state`
- `state_changed`

## 优势

- **可测试性** - 无需完整场景树即可测试组件
- **可复用性** - 组件可在不同上下文中工作
- **灵活性** - 添加/移除监听器无需修改发射器
- **可维护性** - 修改不会破坏远处的代码
- **清晰性** - Signal 连接展示系统架构

## 常见转换

| 转换前（耦合） | 转换后（基于 Signal） |
|------------------|---------------------|
| `get_node("../Player").damage()` | `damage_dealt.emit()` → player 监听 |
| `get_parent().update_ui()` | `ui_update_requested.emit()` → UI 监听 |
| `owner.score += 10` | `score_changed.emit(10)` → owner 监听 |
| `find_child("Camera").shake()` | `screen_shake_requested.emit()` → camera 监听 |
