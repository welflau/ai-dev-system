---
name: godot-sync-camera-positions
version: 3.0.0
displayName: 同步摄像机跟随位置
description: >
  用于 Godot 中背景图层或元素在运行时跟随摄像机，但在编辑器中显示错误位置的情况。
  检测摄像机跟随模式，并将编辑器位置同步为典型的运行时状态。
  使编辑器预览准确显示玩家在游戏中看到的画面。
author: Asreonn
license: MIT
category: game-development
type: tool
difficulty: intermediate
audience: [developers]
keywords:
  - godot
  - camera-follow
  - editor-preview
  - background-layers
  - runtime-position
  - camera2d
  - level-design
  - wysiwyg
platforms: [macos, linux, windows]
repository: https://github.com/asreonn/godot-superpowers
homepage: https://github.com/asreonn/godot-superpowers#readme

permissions:
  filesystem:
    read: [".gd", ".tscn"]
    write: [".tscn"]
  git: true

behavior:
  auto_rollback: true
  validation: true
  git_commits: true

outputs: "同步后的摄像机感知位置、更新的 .tscn 文件、运行时注释、git 提交"
requirements: "Git 仓库、Godot 4.x"
execution: "自动检测并计算编辑器位置"
integration: "属于 godot-fix-positions 编排器的一部分，可与 godot-sync-parallax 配合使用"
---

# 同步摄像机跟随位置

## 核心原则

**编辑器预览应展示真实的游戏画面。** 跟随摄像机的元素需要特殊处理。

## 本技能的功能

找到类似这样的模式：
```gdscript
# background.gd
extends Sprite2D

func _process(delta):
    position = camera.position  # 运行时跟随摄像机

# background.tscn
[node name="Background" type="Sprite2D"]
position = Vector2(0, 0)  # 编辑器中显示在原点

# 结果：编辑器中背景在 (0,0)
# 但在游戏中，背景在摄像机位置（例如 500, 300）
# 关卡设计师看到的是错误的画面！
```

解决为：
```gdscript
# background.gd（未修改 - 运行时行为相同）
func _process(delta):
    position = camera.position

# background.tscn（更新为显示典型的摄像机位置）
[node name="Background" type="Sprite2D"]
position = Vector2(500, 300)  # 摄像机起始位置

# 结果：编辑器预览现在显示真实的游戏画面
```

## 检测模式

识别摄像机跟随代码：

### 直接跟随摄像机位置
```gdscript
func _process(delta):
    position = camera.position  # 摄像机跟随
    position = camera.global_position
    position = get_viewport().get_camera_2d().position
```

### 跟随玩家位置（间接跟随摄像机）
```gdscript
func _process(delta):
    position = player.position  # 玩家跟随摄像机
    # 背景跟随玩家 → 实际上跟随摄像机
```

### 带偏移的摄像机跟随
```gdscript
func _process(delta):
    position = camera.position + offset  # 带偏移的摄像机跟随
    position = player.position + Vector2(0, -100)
```

### 平滑跟随摄像机
```gdscript
func _process(delta):
    position = position.lerp(camera.position, 0.1)  # 平滑摄像机跟随
```

## 使用场景

### 背景图层
跟随摄像机以实现无限滚动效果的背景。

### UI 覆盖层
停留在摄像机位置的世界空间 UI。

### 关卡设计
想要看到游戏过程中区域的实际外观。

### 摄像机相对元素
任何相对于摄像机定位的元素。

## 流程

1. **扫描** - 找到引用摄像机/玩家的位置赋值
2. **分析** - 确定是否为摄像机跟随模式
3. **计算** - 确定典型的摄像机位置
4. **更新 .tscn** - 将编辑器位置设为计算的位置
5. **文档化** - 添加注释说明运行时行为
6. **验证** - 确保编辑器预览看起来正确
7. **提交** - 每次摄像机跟随同步创建 git 提交

## 同步策略

### 策略 1：摄像机起始位置
将编辑器位置设为摄像机的起始位置。

**最适用于：** 大多数摄像机跟随元素。

```gdscript
# background.gd
func _process(delta):
    position = camera.position

# 确定摄像机起始位置（从关卡场景或项目设置）
# 将 background.tscn 的 position 更新为 camera_start_position
```

### 策略 2：玩家起始位置 + 偏移
将编辑器位置设为玩家出生点 + 偏移。

**最适用于：** 带偏移跟随玩家的元素。

```gdscript
# cloud.gd
func _process(delta):
    position = player.position + Vector2(0, -200)  # 在玩家上方

# 找到玩家出生点
# 将 cloud.tscn 的 position 更新为 player_spawn + Vector2(0, -200)
```

### 策略 3：元数据注解
在场景中添加元数据说明运行时行为。

**最适用于：** 复杂的摄像机跟随逻辑。

```gdscript
# .tscn 中的元数据
[node name="Background"]
metadata/_editor_note = "Runtime: follows camera at camera.position"
```

## 智能检测

**识别摄像机跟随模式：**
```gdscript
# 摄像机跟随（会同步这些）
position = camera.position
position = $"/root/Main/Camera".position
position = player.position  # 如果玩家有摄像机
position.x = camera.position.x  # 水平跟随
```

**跳过非摄像机模式：**
```gdscript
# 非摄像机跟随（跳过这些）
position = target_position  # 通用目标
position = waypoints[index]  # 路径点跟随
position = mouse_position  # 鼠标跟随
```

## 示例转换

### 示例 1：背景图层

**之前：**
```gdscript
# background.gd
extends Sprite2D
@onready var camera = $"/root/Main/Camera2D"

func _process(delta):
    position = camera.position

# background.tscn
[node name="Background" type="Sprite2D"]
position = Vector2(0, 0)
texture = preload("res://assets/sky.png")
```

**编辑器视图：** 背景在原点 (0, 0) - 错误！
**游戏视图：** 背景在摄像机位置 (640, 360) - 正确！

**同步后：**
```gdscript
# background.gd（未修改）
extends Sprite2D
@onready var camera = $"/root/Main/Camera2D"

func _process(delta):
    # 运行时：跟随摄像机位置
    position = camera.position

# background.tscn（已更新）
[node name="Background" type="Sprite2D"]
position = Vector2(640, 360)  # 摄像机起始位置
texture = preload("res://assets/sky.png")
```

**编辑器视图：** 背景在 (640, 360) - 与游戏画面一致！
**游戏视图：** 背景在摄像机位置 - 与之前相同！

### 示例 2：玩家相对的云朵

**之前：**
```gdscript
# cloud.gd
extends Sprite2D

func _process(delta):
    position = player.position + Vector2(0, -200)

# cloud.tscn
[node name="Cloud" type="Sprite2D"]
position = Vector2(0, 0)
```

**同步后：**
```gdscript
# cloud.gd（未修改）
func _process(delta):
    # 运行时：在玩家上方 200 像素
    position = player.position + Vector2(0, -200)

# cloud.tscn（更新为显示在玩家出生点上方）
[node name="Cloud" type="Sprite2D"]
position = Vector2(320, -20)  # 玩家出生在 (320, 180)
```

## 摄像机位置检测

### 方法 1：在场景中查找 Camera2D
```bash
# 搜索 Camera2D 节点
grep -r "type=\"Camera2D\"" scenes/
# 在摄像机的父场景中查找位置值
```

### 方法 2：项目设置
```gdscript
# 检查视口大小（摄像机通常从中心开始）
# 默认：1280x720 → 摄像机在 (640, 360)
```

### 方法 3：询问用户
如果检测不确定，询问：
"你的摄像机从哪里开始？（例如，视口中心、玩家位置）"

## 创建的内容

- 更新后的 .tscn 文件，包含计算的位置
- 记录运行时行为的注释
- 复杂模式的元数据注解
- 确保编辑器预览正确的验证
- 每次同步操作的 git 提交

## 集成

可搭配使用：
- **godot-sync-static-positions** - 静态位置冲突
- **godot-sync-parallax** - 视差特定的摄像机跟随
- **godot-fix-positions**（编排器）- 所有位置同步操作

## 安全性

- 运行时行为不变
- 只更新 .tscn 编辑器位置
- 代码保持不变
- 验证失败时回滚
- 原始位置保留在 git 历史中

## 何时不使用

以下情况不要同步：
- 摄像机跟随逻辑复杂（多摄像机、切换）
- 位置在游戏过程中变化很大
- 编辑器位置有特定含义（不只是默认值）
- 摄像机起始位置未知/不确定

## 优势

- **真实预览** - 编辑器显示游戏画面
- **更好的关卡设计** - 看到玩家将看到的内容
- **调试友好** - 位置错误时一目了然
- **团队沟通** - 设计师看到准确的预览
- **所见即所得** - 预览与游戏一致

## 常见摄像机模式

### 无限滚动背景
```gdscript
func _process(delta):
    position.x = camera.position.x
    # 垂直位置固定，水平跟随摄像机
```

同步：将编辑器 x 设为摄像机起始 x，保持 y 不变。

### 平滑摄像机跟随
```gdscript
func _process(delta):
    position = position.lerp(camera.position, smoothness)
```

同步：将编辑器位置设为摄像机起始位置（最终位置）。

### 摄像机边界
```gdscript
func _process(delta):
    position = camera.position.clamp(min_bounds, max_bounds)
```

同步：将编辑器位置设为限制后的摄像机起始位置。

## 验证

同步后验证：
- 编辑器位置看起来合理（不在 0,0）
- .tscn 文件解析正确
- 场景加载无错误
- 视觉外观合理

## 文档化模式

```gdscript
# 运行时行为：
# - 在 _process 中跟随 camera.position
# - 编辑器位置设为摄像机起始位置：(640, 360)
# - 游戏过程中，位置将完全匹配摄像机
```

清晰的文档可以避免代码和编辑器位置有意不同时的困惑。

## 摄像机检测层级

1. 在当前场景中搜索 Camera2D
2. 在父场景中搜索 Camera2D
3. 检查项目视口大小（假设为中心）
4. 询问用户摄像机起始位置

智能检测最大限度地减少所需的用户输入。
