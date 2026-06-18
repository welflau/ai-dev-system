---
name: godot-sync-static-positions
version: 3.0.0
displayName: 同步静态位置
description: >
  当 Godot 节点的位置同时在 .tscn（编辑器）和 _ready()（代码）中设置时使用，
  这会导致实际运行时位置产生混乱。检测与编辑器值冲突的静态位置赋值。
  同步到单一事实来源，使编辑器预览与游戏行为一致（所见即所得）。
author: Asreonn
license: MIT
category: game-development
type: tool
difficulty: beginner
audience: [developers]
keywords:
  - godot
  - position-sync
  - editor-preview
  - wysiwyg
  - static-positions
  - node-position
  - level-design
  - tscn-files
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

outputs: "同步后的位置、更新的 .tscn 或 .gd 文件、清晰的归属文档、git 提交"
requirements: "Git 仓库、Godot 4.x"
execution: "自动检测，用户审批同步策略"
integration: "godot-fix-positions 编排器的一部分，与 godot-clean-conflicts 协作"
---

# 同步静态位置

## 核心原则

**所见即所得。** 对于静态位置，编辑器预览应与游戏行为一致。

## 此技能的功能

查找如下冲突：
```gdscript
# enemy.gd
func _ready():
    position = Vector2(500, 300)  # 代码设置在这里

# enemy.tscn
[node name="Enemy" type="CharacterBody2D"]
position = Vector2(100, 100)  # 编辑器设置在这里

# 结果：令人困惑！编辑器显示错误的位置
```

解决为：
```gdscript
# enemy.gd
func _ready():
    # 位置已在场景文件中设置，以便在编辑器中可见
    pass

# enemy.tscn
[node name="Enemy" type="CharacterBody2D"]
position = Vector2(500, 300)  # 更新为匹配预期位置

# 结果：编辑器预览与游戏一致
```

## 检测模式

识别以下情况：

### _ready() 中的直接位置赋值
```gdscript
func _ready():
    position = Vector2(100, 150)  # 静态冲突
    global_position = Vector2(500, 300)  # 静态冲突
```

### Node 属性赋值
```gdscript
func _ready():
    $Sprite.position = Vector2(10, 20)  # 子节点位置冲突
    get_node("CollisionShape2D").position = Vector2(0, 0)
```

### 多属性冲突
```gdscript
func _ready():
    position = Vector2(100, 100)
    rotation = deg_to_rad(45)  # 也是位置相关的
    scale = Vector2(2, 2)
```

## 何时使用

### 关卡设计工作流
在编辑器中放置物体，但代码覆盖了位置。

### 调试位置问题
"为什么这个节点在错误的位置？"

### 维护所见即所得
希望编辑器预览是准确的。

### 为协作做准备
关卡设计师需要准确的编辑器预览。

## 流程

1. **扫描** - 查找 _ready() 中的位置赋值
2. **对比** - 与 .tscn 值进行比较
3. **检测冲突** - 识别静态冲突（非动态）
4. **选择策略** - 用户选择同步方向
5. **应用** - 更新 .tscn 或 .gd 文件
6. **记录** - 添加注释说明归属关系
7. **验证** - 确保编辑器/游戏之间的位置一致
8. **提交** - 每次冲突解决后进行 git 提交

## 同步策略

### 策略 1：编辑器优先（推荐用于静态位置）
将代码中的值移到 .tscn，从代码中移除。

**何时使用：**
- 位置应在编辑器中可见
- 设计师控制的布局
- 静态物体定位

**示例：**
```gdscript
# 修改前
func _ready():
    position = Vector2(500, 300)

# 修改后
func _ready():
    # 位置已在场景文件中设置
    pass
```
```ini
# enemy.tscn 已更新
position = Vector2(500, 300)
```

### 策略 2：代码优先（保持动态）
移除编辑器中的值，保留代码赋值。

**何时使用：**
- 位置在运行时计算
- 依赖于其他节点/数据
- 程序化定位

**示例：**
```gdscript
# 修改前
func _ready():
    position = spawn_point.position + offset  # 动态的！

# 修改后
func _ready():
    # 位置是动态计算的（参见 spawn_point）
    position = spawn_point.position + offset
```
```ini
# enemy.tscn - 位置已移除或设置为 (0,0) 作为占位符
```

### 策略 3：记录意图
保留两者，但添加清晰的注释。

**何时使用：**
- 编辑器中的初始位置，被有意覆盖
- 默认位置带有代码覆盖
- 两个值都有意义

**示例：**
```gdscript
# 修改前
func _ready():
    position = start_position

# 修改后
func _ready():
    # 编辑器位置是默认出生点，被覆盖为 start_position
    position = start_position
```

## 智能检测

**识别静态冲突（修复这些）：**
```gdscript
func _ready():
    position = Vector2(100, 100)  # 字面量常数 - 静态
    position = Vector2(CONSTANT_X, CONSTANT_Y)  # 常量 - 静态
    $Child.position = Vector2(10, 10)  # 字面量 - 静态
```

**跳过动态定位（属于有意设计）：**
```gdscript
func _ready():
    position = player.position  # 变量引用 - 动态
    position = get_spawn_point()  # 函数调用 - 动态
    if some_condition:
        position = Vector2(100, 100)  # 条件性 - 动态

func _process(delta):
    position = target  # 每帧 - 动态（跳过）
```

**关键区别：静态 = 每次都相同，动态 = 运行时变化**

## 生成内容

- 同步后的 .tscn 文件，包含正确的位置
- 更新或清理后的代码文件
- 记录位置归属的注释
- 确保同步成功的验证
- 每次同步操作的 git 提交

## 常见冲突

### 冲突 1：出生位置
```gdscript
# 修改前：代码设置 (500, 300)，编辑器设置 (0, 0)
func _ready():
    position = Vector2(500, 300)

# 修改后：编辑器已更新，代码已移除
# enemy.tscn: position = Vector2(500, 300)
```

### 冲突 2：子节点偏移
```gdscript
# 修改前：子节点偏移在代码中，不在编辑器中
func _ready():
    $Sprite.position = Vector2(0, -10)

# 修改后：Sprite 位置已移入 .tscn
# enemy.tscn: [node name="Sprite"] position = Vector2(0, -10)
```

### 冲突 3：多属性
```gdscript
# 修改前：位置、旋转、缩放都在代码中
func _ready():
    position = Vector2(100, 100)
    rotation = deg_to_rad(45)
    scale = Vector2(1.5, 1.5)

# 修改后：所有属性都在 .tscn 中，代码干净
# enemy.tscn 已设置所有三个属性
```

## 集成

与以下技能协作：
- **godot-sync-camera-positions** - 跟随相机的元素
- **godot-sync-parallax** - 视差层专用同步
- **godot-clean-conflicts** - 通用冲突解决
- **godot-fix-positions**（编排器）- 所有位置同步操作

## 安全性

- 原始位置保留在 git 中
- 验证确保同步正确性
- 验证失败时自动回滚
- .tscn 格式精确保留

## 何时不应使用

以下情况不要同步：
- 位置是动态计算的
- 位置根据游戏状态变化
- 有意的位置覆盖模式
- 位置在 _process() 中设置（每帧）

**合法的代码控制位置：**
```gdscript
# 这些不应该同步到 .tscn
func _ready():
    position = get_spawn_location_from_data()  # 数据驱动
    position = player.position + offset  # 相对于玩家
    position = area.get_random_point()  # 程序化
```

## 好处

- **所见即所得** - 编辑器显示准确的位置
- **设计师友好** - 在编辑器中进行关卡设计，而非代码
- **便于调试** - 位置来源一目了然
- **一致性** - 清晰的归属模式
- **可视化** - 预览与游戏完全一致

## 位置归属模式

同步后，清晰的模式会浮现：

| 位置类型 | 归属方 | 示例 |
|---------|--------|------|
| 静态出生点 | 编辑器 (.tscn) | 敌人出生位置 |
| 子节点偏移 | 编辑器 (.tscn) | Sprite 相对于父节点 |
| 动态位置 | 代码 (_ready, _process) | 跟随玩家、程序化 |
| 动画位置 | AnimationPlayer | 动画运动 |
| 物理位置 | 物理引擎 | RigidBody2D |

## 验证

同步后验证：
- .tscn 文件正确解析
- 位置值与预期目标一致
- 引用（@onready）仍然有效
- 场景无错误加载
- 视觉位置与代码位置一致

## 添加的文档

```gdscript
# 位置在场景文件中设置为 (500, 300)
# 旋转由 AnimationPlayer "rotate" 控制
# 缩放由代码控制（基于生命值的动态缩放）
```

清晰的归属 = 清晰的代码 = 更少的 bug。
