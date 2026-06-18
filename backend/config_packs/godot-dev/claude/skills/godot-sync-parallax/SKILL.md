---
name: godot-sync-parallax
version: 3.0.0
displayName: 同步视差图层位置
description: >
  用于 Godot 中 ParallaxBackground/ParallaxLayer 节点因视差乘数而在编辑器中
  显示错误位置的情况。根据摄像机起始位置和视差运动缩放计算正确的编辑器位置。
  使视差图层在编辑器中逼真预览，匹配游戏中的外观。
author: Asreonn
license: MIT
category: game-development
type: tool
difficulty: intermediate
audience: [developers]
keywords:
  - godot
  - parallax
  - parallax-background
  - parallax-layer
  - motion-scale
  - editor-preview
  - camera-position
  - gdscript
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

outputs: "同步后的视差位置、校正后的图层偏移、更新的 .tscn 文件、git 提交"
requirements: "Git 仓库、Godot 4.x"
execution: "根据视差属性自动计算"
integration: "属于 godot-fix-positions 编排器的一部分，专用于视差系统"
---

# 同步视差图层位置

## 核心原则

**视差图层需要特殊的数学计算才能在编辑器中正确预览。** Motion scale 会影响运行时位置。

## 本技能的功能

Godot 中的视差系统比较复杂：
```gdscript
# Godot 的视差公式：
final_position = layer_position - (camera_position * motion_scale)
```

**问题：**
- 编辑器中显示图层在 `layer_position`
- 运行时显示图层在 `layer_position - (camera_position * motion_scale)`
- 编辑器预览与游戏画面不匹配

**解决方案：**
计算正确的 `layer_position`，使运行时外观匹配预期设计。

## 问题示例

```ini
# parallax_background.tscn
[node name="ParallaxBackground" type="ParallaxBackground"]

[node name="SkyLayer" type="ParallaxLayer" parent="."]
motion_scale = Vector2(0.2, 0.2)  # 慢速视差
position = Vector2(0, 0)

# 摄像机起始于 (640, 360)
# 运行时位置：0 - (640 * 0.2) = -128（错误！）
# 天空图层在游戏中向左偏移
```

**同步后：**
```ini
[node name="SkyLayer" type="ParallaxLayer" parent="."]
motion_scale = Vector2(0.2, 0.2)
position = Vector2(128, 72)  # 已校正！

# 运行时位置：128 - (640 * 0.2) = 0（正确！）
# 天空图层在游戏中居中显示，与编辑器一致
```

## 检测模式

识别视差系统：

### ParallaxBackground 结构
```ini
[node name="ParallaxBackground" type="ParallaxBackground"]
scroll_offset = Vector2(0, 0)
scroll_base_scale = Vector2(1, 1)

[node name="Layer1" type="ParallaxLayer" parent="."]
motion_scale = Vector2(0.5, 0.5)
motion_offset = Vector2(0, 0)
```

### 具有不同缩放的多图层
```ini
[node name="SkyLayer" parent="ParallaxBackground"]
motion_scale = Vector2(0.1, 0.1)  # 非常慢（远处）

[node name="MountainsLayer" parent="ParallaxBackground"]
motion_scale = Vector2(0.3, 0.3)  # 较慢（中距离）

[node name="TreesLayer" parent="ParallaxBackground"]
motion_scale = Vector2(0.7, 0.7)  # 较快（近处）
```

## 使用场景

### 设计视差背景
在编辑器中创建多层视差效果。

### 调试视差问题
图层在游戏中出现在错误位置。

### 可视化关卡设计
希望视差系统实现所见即所得。

### 多视差图层
具有不同缩放比例的复杂多层视差。

## 流程

1. **扫描** - 找到 ParallaxBackground 和 ParallaxLayer Node
2. **检测摄像机** - 找到摄像机起始位置
3. **计算** - 应用反向视差公式
4. **更新位置** - 在 .tscn 中校正图层位置
5. **更新偏移** - 如需要，调整 motion_offset
6. **验证** - 确保图层正确对齐
7. **提交** - 每个视差系统创建 git 提交

## 视差数学

### 正向公式（Godot 的运行时计算）
```
displayed_position = layer_position - (camera_position * motion_scale)
```

### 反向公式（编辑器所需）
```
layer_position = desired_position + (camera_position * motion_scale)
```

### 计算示例

**希望天空图层在游戏中居中于 (0, 0)：**
- 摄像机起始于：(640, 360)
- Motion scale：(0.2, 0.2)
- 计算：layer_position = 0 + (640 * 0.2) = 128
- 计算：layer_position = 0 + (360 * 0.2) = 72
- **在编辑器中设置图层位置：(128, 72)**

## 示例转换

### 示例 1：天空图层

**之前（错误）：**
```ini
[node name="SkyLayer" type="ParallaxLayer"]
motion_scale = Vector2(0.2, 0.2)
position = Vector2(0, 0)
# 精灵在图层相对位置 (0, 0)

# 摄像机在 (640, 360)
# 运行时：0 - (640 * 0.2) = -128
# 天空向左偏移了 -128 像素（错误）
```

**之后（修正）：**
```ini
[node name="SkyLayer" type="ParallaxLayer"]
motion_scale = Vector2(0.2, 0.2)
position = Vector2(128, 72)  # 已校正
# 精灵在图层相对位置 (0, 0)

# 运行时：128 - (640 * 0.2) = 0
# 天空居中显示（正确）
```

### 示例 2：多图层

**之前（全部在原点）：**
```ini
[node name="Sky" type="ParallaxLayer"]
motion_scale = Vector2(0.1, 0.1)
position = Vector2(0, 0)

[node name="Mountains" type="ParallaxLayer"]
motion_scale = Vector2(0.3, 0.3)
position = Vector2(0, 0)

[node name="Trees" type="ParallaxLayer"]
motion_scale = Vector2(0.7, 0.7)
position = Vector2(0, 0)

# 所有图层在运行时向左偏移
```

**之后（已校正）：**
```ini
[node name="Sky" type="ParallaxLayer"]
motion_scale = Vector2(0.1, 0.1)
position = Vector2(64, 36)  # 640*0.1, 360*0.1

[node name="Mountains" type="ParallaxLayer"]
motion_scale = Vector2(0.3, 0.3)
position = Vector2(192, 108)  # 640*0.3, 360*0.3

[node name="Trees" type="ParallaxLayer"]
motion_scale = Vector2(0.7, 0.7)
position = Vector2(448, 252)  # 640*0.7, 360*0.7

# 所有图层在运行时正确居中
```

## 进阶：Motion Offset

### Motion Offset 与 Position 的区别
- **position**：图层的基础位置
- **motion_offset**：随 motion_scale 一起应用的额外偏移

组合公式：
```
displayed_position = (layer_position + motion_offset) - (camera_position * motion_scale)
```

同步时会同时考虑这两个属性。

## 智能检测

**识别视差系统：**
- 存在 ParallaxBackground Node
- ParallaxLayer 子节点的 motion_scale 不等于 (1, 1)
- 图层的 Sprite/TextureRect 子节点

**检测摄像机：**
1. 场景层级中的 Camera2D
2. 来自父场景的摄像机位置
3. 视口中心（默认：1280x720 的 640, 360）

**计算校正：**
- 根据每个图层的 motion_scale 单独计算
- 考虑 motion_offset
- 处理 ParallaxBackground 的 scroll_offset

## 创建的内容

- 更新后的 .tscn 文件，包含校正的图层位置
- 记录视差计算的注释
- 确保图层正确对齐的验证
- 每个视差系统的 git 提交

## 集成

可搭配使用：
- **godot-sync-camera-positions** - 非视差的摄像机跟随
- **godot-sync-static-positions** - 静态位置冲突
- **godot-fix-positions**（编排器）- 所有位置同步操作

## 安全性

- 运行时的视差行为不变
- 只更新编辑器位置
- 原始 .tscn 保留在 git 中
- 验证确保图层对齐
- 验证失败时回滚

## 何时不使用

以下情况不要同步：
- 视差位置是故意偏移的
- 自定义视差实现（非 ParallaxBackground）
- 运行时动态缩放视差
- 摄像机位置变化很大

## 优势

- **可视化设计** - 在编辑器中设计视差图层
- **所见即所得** - 预览与游戏一致
- **调试方便** - 图层对不齐时一目了然
- **快速迭代** - 立即看到效果
- **团队友好** - 关卡设计师在编辑器中工作

## 常见视差模式

### 无限滚动背景
```ini
[node name="CloudsLayer" type="ParallaxLayer"]
motion_scale = Vector2(0.2, 0)  # 仅水平
motion_mirroring = Vector2(1280, 0)  # 水平重复
```

同步：仅校正水平位置。

### 垂直视差（平台跳跃游戏）
```ini
[node name="SkyLayer" type="ParallaxLayer"]
motion_scale = Vector2(0, 0.1)  # 仅垂直
```

同步：仅校正垂直位置。

### 完整 2D 视差
```ini
[node name="BackgroundLayer" type="ParallaxLayer"]
motion_scale = Vector2(0.3, 0.3)  # 双轴
```

同步：同时校正 x 和 y 位置。

## 验证

同步后验证：
- 所有图层在编辑器中可见
- 图层顺序保留（从后到前）
- 精灵按预期对齐
- 没有图层在负坐标位置（除非是有意为之）
- 编辑器预览看起来逼真

## 摄像机位置检测

### 优先级顺序
1. 当前场景中的 Camera2D → 使用其位置
2. 父场景中的 Camera2D → 使用其位置
3. 视口大小 → 假设为中心（width/2, height/2）
4. 项目设置 → 获取视口大小
5. 不确定时询问用户

## 文档化模式

```gdscript
# 视差图层已根据摄像机起始位置校正：(640, 360)
# motion_scale: (0.2, 0.2)
# 公式：position = desired_runtime_position + (camera * motion_scale)
# 计算：(0, 0) + (640 * 0.2, 360 * 0.2) = (128, 72)
```

清晰的文档展示计算方法。

## 常见问题修复

| 问题 | 原因 | 解决方案 |
|-------|-------|----------|
| 图层在游戏中向左偏移 | position = (0,0)，motion_scale < 1 | 添加偏移：camera * motion_scale |
| 图层在开始时跳动 | 编辑器位置不等于运行时位置 | 使用公式同步位置 |
| 图层对不齐 | 不同的摄像机假设 | 统一摄像机起始位置 |
| 预览与游戏不匹配 | 未考虑视差数学 | 应用反向视差公式 |

## 性能注意事项

视差系统效率很高，但需注意：
- 限制图层数量（通常 3-5 层）
- 对静态背景使用 TextureRect
- 对无限滚动考虑使用 motion_mirroring
- 避免在视差图层上使用重型着色器

同步位置不影响性能，只影响编辑器可用性。
