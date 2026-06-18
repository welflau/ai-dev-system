---
name: godot-clean-conflicts
version: 3.0.0
displayName: 清理冲突操作
description: >
  当 Godot 代码中存在相互冲突的操作导致未定义行为时使用。检测同一属性在多处设置
  （_ready、_process、代码+编辑器）、同一 Signal 多次连接、冲突的物理模式、
  竞争的动画等问题。自动通过明确的所有权归属解决冲突。
author: Asreonn
license: MIT
category: game-development
type: tool
difficulty: intermediate
audience: [developers]
keywords:
  - godot
  - conflicts
  - race-conditions
  - duplicate-signals
  - physics-modes
  - animation-conflicts
  - gdscript
  - undefined-behavior
platforms: [macos, linux, windows]
repository: https://github.com/asreonn/godot-superpowers
homepage: https://github.com/asreonn/godot-superpowers#readme

permissions:
  filesystem:
    read: [".gd", ".tscn", ".tres"]
    write: [".gd", ".tscn"]
  git: true

behavior:
  auto_rollback: true
  validation: true
  git_commits: true

outputs: "冲突解决方案、明确的所有权模式、更新后的代码/场景、git 提交"
requirements: "Git 仓库, Godot 4.x"
execution: "自动检测，用户审批解决策略"
integration: "godot-refactor 编排器的一部分，解决架构冲突"
---

# 清理冲突操作

## 核心原则

**每个属性只有一个真实来源。** 冲突操作会导致未定义行为和调试噩梦。

## 本技能的功能

查找如下模式：
```gdscript
# player.gd
func _ready():
    position = Vector2(100, 100)  # Code sets position
    # BUT: .tscn also has position = Vector2(200, 200)
    # CONFLICT: Which position wins?

func _process(delta):
    rotation += delta  # Animation system ALSO modifying rotation
    # CONFLICT: Animation vs code control
```

解决为明确的所有权归属：
```gdscript
# player.gd
# Position is set in .tscn (editor owns position)
# Rotation is controlled by animation (animation owns rotation)

func _process(delta):
    # Rotation conflict removed
    pass
```

## 检测模式

识别以下问题：

### 属性冲突
- 同一属性在代码（_ready）和编辑器（.tscn）中设置
- 同一属性在 _process 和 _physics_process 中修改
- 属性同时被动画和代码控制

### Signal 冲突
- 同一 Signal 多次连接
- 重复的 lambda 连接
- Signal 连接时未检查 is_connected()

### 物理冲突
- RigidBody 的位置被代码控制（与物理引擎冲突）
- CharacterBody 同时被 _physics_process 和动画控制
- 碰撞层/掩码冲突（代码 vs 编辑器）

### 动画冲突
- AnimationPlayer 和代码同时修改同一属性
- 多个 AnimationPlayer 控制同一 Node
- Tween 和动画争夺控制权

## 使用场景

### 调试意外行为
属性值不正确，且不知道原因。

### 遇到竞态条件
时好时坏（依赖时序）。

### 出现重复事件
Signal 触发两次，操作执行多次。

### 与物理引擎对抗
代码试图直接控制物理体。

## 流程

1. **扫描** - 查找代码和场景中的冲突操作
2. **分析** - 确定每个属性应由谁拥有
3. **解决** - 应用冲突解决策略
4. **文档** - 添加注释说明所有权归属
5. **验证** - 确保行为现在是确定性的
6. **提交** - 每种冲突解决对应一次 git 提交

## 转换示例

### 冲突 1：位置在代码和编辑器中同时设置

**转换前（冲突）：**
```gdscript
# enemy.gd
func _ready():
    position = Vector2(500, 300)  # Code says here

# enemy.tscn
[node name="Enemy" type="CharacterBody2D"]
position = Vector2(100, 100)  # Editor says here
# RESULT: Confusing! Editor shows one place, game uses another
```

**转换后（解决 - 编辑器优先）：**
```gdscript
# enemy.gd
func _ready():
    # Position is set in scene file for editor visibility
    pass

# enemy.tscn
[node name="Enemy" type="CharacterBody2D"]
position = Vector2(500, 300)  # Updated to match intended position
# RESULT: What You See Is What You Get
```

### 冲突 2：重复的 Signal 连接

**转换前（冲突）：**
```gdscript
# ui.gd
func _ready():
    button.pressed.connect(_on_button_pressed)

func setup_ui():
    button.pressed.connect(_on_button_pressed)  # CONNECTED AGAIN!
    # RESULT: _on_button_pressed fires TWICE per click
```

**转换后（解决）：**
```gdscript
# ui.gd
func _ready():
    if not button.pressed.is_connected(_on_button_pressed):
        button.pressed.connect(_on_button_pressed)

func setup_ui():
    # Connection already exists, skip
    pass
# RESULT: Fires exactly once per click
```

### 冲突 3：动画与代码控制冲突

**转换前（冲突）：**
```gdscript
# player.gd
func _process(delta):
    sprite.rotation += delta * rotation_speed  # Code controls rotation

# player.tscn has AnimationPlayer controlling sprite.rotation
# RESULT: Jittery rotation, both systems fighting
```

**转换后（解决 - 动画优先）：**
```gdscript
# player.gd
func _process(delta):
    # Rotation is controlled by animation system
    # Code can trigger animations: animation_player.play("rotate")
    pass

# AnimationPlayer has full control of sprite.rotation
# RESULT: Smooth animation, clear ownership
```

### 冲突 4：物理体位置控制冲突

**转换前（冲突）：**
```gdscript
# enemy.gd
extends RigidBody2D

func _physics_process(delta):
    position = target_position  # CONFLICT with physics engine!
    # Physics engine wants to control position
    # Code also tries to control position
    # RESULT: Jittery movement, physics fighting code
```

**转换后（解决 - 使用正确的 Body 类型）：**
```gdscript
# enemy.gd
extends CharacterBody2D  # Changed to CharacterBody for code control

func _physics_process(delta):
    position = target_position  # Now appropriate for CharacterBody
    # CharacterBody2D is designed for code-controlled movement
    # RESULT: Smooth movement, no conflict
```

**备选解决方案（保留 RigidBody）：**
```gdscript
# enemy.gd
extends RigidBody2D

func _physics_process(delta):
    # Use forces instead of direct position control
    apply_force((target_position - position) * force_strength)
    # Work WITH physics engine, not against it
    # RESULT: Realistic physics-based movement
```

## 冲突解决策略

### 1. 编辑器优先（位置/旋转/缩放）
将代码中定义的值移到 .tscn 中，以便在编辑器中可见。

### 2. 代码优先（动态状态）
当代码需要完全控制时，移除编辑器中的值。

### 3. 动画优先（动画属性）
代码触发动画，不直接修改属性。

### 4. 物理优先（RigidBody）
使用力/脉冲而非直接控制属性。

### 5. 一次性初始化
建立清晰的模式：编辑器负责初始值，代码负责后续变更。

## 创建的内容

- 冲突解决文档
- 说明所有权决策的注释
- 移除冲突后更新的代码
- 更新后的 .tscn 文件（含正确的值）
- 每种冲突类型解决对应的 git 提交

## 智能分析

**检测冲突严重程度：**
- **严重** - 导致崩溃或数据损坏
- **高** - 导致错误行为
- **中** - 导致性能问题
- **低** - 导致混淆但可工作

**按优先级解决：**
1. 严重冲突优先
2. 高影响冲突
3. 性能冲突
4. 清晰性冲突

## 集成

可与以下技能配合使用：
- **godot-sync-static-positions** - 专门解决位置冲突
- **godot-split-scripts** - 分离有助于防止冲突
- **godot-refactor**（编排器） - 作为完整重构的一部分运行

## 安全性

- 每种解决策略经过验证
- 保留行为或经审批后有意变更
- 验证失败时回滚
- 原始代码保留在 git 历史中

## 不应使用的情况

以下情况不需要"修复"：
- 有意的覆盖模式（编辑器默认值，代码覆盖）
- 临时值（代码初始化，然后释放控制）
- 状态机模式（不同模式在不同时间拥有属性）
- 动画混合（有意的属性共享）

并非所有冲突都是 bug — 有些是架构模式。

## 常见冲突

| 冲突类型 | 症状 | 解决方案 |
|---------|------|---------|
| _ready 和 .tscn 中同时设置位置 | 游戏中位置不正确 | 编辑器优先（移到 .tscn） |
| 重复的 Signal 连接 | 事件触发多次 | 先检查 is_connected() |
| 动画 + 代码控制旋转 | 动画抖动 | 动画优先（移除代码） |
| RigidBody 位置控制 | 物理异常 | 改用力 |
| _process + _physics_process | 行为不一致 | 根据需要选择其一 |

## 优势

- **可预测性** - 行为是确定性的
- **可调试性** - 明确的所有权使问题一目了然
- **性能** - 没有冗余操作
- **可维护性** - 清晰的模式便于后续修改
- **所见即所得** - 编辑器预览与游戏行为一致

## 添加的文档

对于每个解决方案，添加如下注释：
```gdscript
# Position is controlled by .tscn (editor-visible)
# Rotation is controlled by AnimationPlayer "idle"
# Scale is controlled by code (dynamic resizing)
```

明确的所有权 = 清晰的代码。
