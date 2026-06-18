---
name: godot-fix-positions
version: 3.0.0
displayName: "Godot 位置同步编排器"
description: >
  当 Godot 项目在编辑器（.tscn）和代码（.gd）之间存在位置冲突、相机跟随背景、
  或运行时位置与编辑器预览不匹配时使用。编排所有 3 个位置同步子技能：
  sync-static-positions、sync-camera-positions 和 sync-parallax。
  每个操作针对特定的位置冲突类型。
author: "Asreonn"
license: MIT
category: game-development
type: agent
difficulty: beginner
audience: [developers, level-designers]
keywords:
  - godot
  - positions
  - editor-sync
  - camera
  - parallax
  - wysiwyg
  - level-design
  - godot4
platforms: [macos, linux, windows]
repository: https://github.com/asreonn/godot-superpowers
homepage: https://github.com/asreonn/godot-superpowers#readme
filesystem:
  read:
    - "${PROJECT_ROOT}/**/*.gd"
    - "${PROJECT_ROOT}/**/*.tscn"
    - "${PROJECT_ROOT}/project.godot"
  write:
    - "${PROJECT_ROOT}/**/*.gd"
    - "${PROJECT_ROOT}/**/*.tscn"
  deny:
    - "**/.env*"
    - "**/secrets*"
    - "**/*.key"
behavior:
  timeout: 300
  retry: 2
  cache: true
  interactive: true
use_cases:
  - "Node 在 _ready() 中设置的位置与编辑器预览不匹配"
  - "背景跟随相机但编辑器显示错误位置"
  - "视差层在游戏启动时跳动"
  - "希望编辑器中所见即所得"
  - "位置冲突导致关卡设计混乱"
  - "需要一次性同步所有位置类型"
outputs: "同步后的位置、更新的 .tscn 文件、清晰的归属文档、每种同步类型的 git 提交"
requirements: "Git 仓库、Godot 4.x"
execution: "自动检测，用户审批同步策略"
auto_rollback: "是 - 验证失败时自动回滚"
integration: "编排：godot-sync-static-positions、godot-sync-camera-positions、godot-sync-parallax"
---

# Godot 位置修复编排器

**此编排器按顺序运行 3 个位置同步子技能。如需单独操作，请直接调用子技能。**

## 核心原则：所见即所得（WYSIWYG）

**铁律**：编辑器预览必须与运行时行为一致。不允许出现意外。

此技能自动检测并解决编辑器定义的位置（.tscn 文件）与代码定义的位置（.gd 文件）之间的冲突。它处理静态冲突、相机跟随背景、视差层和玩家相对定位。

---

## 调用时 - 从这里开始

当此技能被调用时，立即执行以下步骤：

### 1. 验证 Godot 项目（5 秒）

```bash
# Check if this is a Godot project
ls project.godot 2>/dev/null && echo "✓ Godot project detected" || echo "✗ Not a Godot project"
```

**如果不是 Godot 项目：**
- 告知用户此技能仅适用于 Godot 项目
- 询问是否需要导航到正确的目录
- 在此停止

**如果是 Godot 项目：**
- 继续执行步骤 2

### 2. 开始阶段 1：检测与分析（自动）

**不要询问"你希望我做什么？"——立即开始分析。**

并行执行以下命令：

```bash
# Detect static position conflicts
find . -name "*.gd" -exec grep -l "position\s*=" {} \; | head -20

# Find camera-following patterns
grep -rn "position\s*=.*camera\|position\s*=.*player" --include="*.gd" . | head -20

# Find parallax backgrounds
find . -name "*parallax*.tscn" -o -name "*background*.tscn" | head -10

# Count potential conflicts
find . -name "*.gd" -exec grep -c "^\s*position\s*=" {} + | awk '{s+=$1} END {print s}'
```

### 3. 展示结果（30 秒）

向用户展示：
```
=== 编辑器位置同步分析 ===

项目：[从 project.godot 获取的项目名称]

检测到的冲突：
- 静态位置赋值：X
- 相机跟随元素：X
- 视差背景：X
- 玩家相对定位：X

总计：发现 X 个位置冲突

同步包括：
✓ 检测编辑器与代码的位置冲突
✓ 智能分类（有意设计 vs 冲突）
✓ 相机感知定位
✓ 多种同步策略
✓ 每次操作 git 提交
✓ 测试失败时自动回滚

您希望我：
1. 继续自动同步（推荐）
2. 先显示详细分析
3. 取消
```

### 4. 等待用户选择

- **如果选 1（继续）：** 立即开始阶段 2
- **如果选 2（详情）：** 显示逐文件的详细分析，然后提供继续选项
- **如果选 3（取消）：** 退出技能

**关键**：加载技能后不要停下来。不要询问"你希望我做什么？"。从步骤 1 立即开始。

---

## 何时使用此技能

当检测到以下任何症状时使用此技能：

**静态位置冲突：**
- `_ready()` 或 `_init()` 中出现 `position = Vector2(x, y)`
- 编辑器显示一个位置，运行时显示不同的位置
- 游戏启动时节点出现在错误的位置
- 视觉调试发现位置不匹配

**相机跟随元素：**
- 跟随相机位置的背景
- 追踪玩家的 UI 元素
- 带相机同步的视差层
- `position = camera.position` 模式

**玩家相对定位：**
- 相对于玩家定位的节点
- `position = player.position + offset` 模式
- 追踪玩家移动的元素
- 相机相对的 UI 元素

**编辑器预览不匹配：**
- "在编辑器中看起来正确但运行时不对"
- "游戏启动时背景会跳动"
- "我的 UI 元素位置不对"
- "相机跟随节点预览不正确"

### 决策流程图

```
用户提到位置问题
    ↓
是编辑器与运行时不匹配吗？
    ↓ 是                      ↓ 否
使用此技能                  其他问题
    ↓
运行阶段 1：检测
    ↓
发现冲突了吗？
    ↓ 是                      ↓ 否
运行阶段 2-3               记录干净状态
```

---

## 三个阶段

### 阶段 1：检测与分析（自动）

**目的**：检测位置冲突并进行智能分类。

**步骤：**

1. **扫描项目文件**
```bash
# Find all Godot script files
find . -name "*.gd" -type f

# Find all scene files
find . -name "*.tscn" -type f
```

2. **检测位置赋值**

扫描位置设置模式：

```bash
# Static position assignments
grep -rn "position\s*=\s*Vector2(" --include="*.gd" .

# Camera-following patterns
grep -rn "position\s*=.*camera" --include="*.gd" .

# Player-following patterns
grep -rn "position\s*=.*player" --include="*.gd" .

# Parallax patterns
grep -rn "ParallaxBackground\|ParallaxLayer" --include="*.gd" .
```

3. **解析 .tscn 文件中的位置**

从场景中提取位置属性：

```bash
# Find position declarations in .tscn files
grep -rn "^position\s*=\s*Vector2(" --include="*.tscn" .
```

4. **智能分类**

对每个检测到的位置赋值，分类为：

- **冲突**：`_ready()` 中的静态位置与 .tscn 不同
- **有意动态**：相机/玩家跟随（跳过）
- **有意动画**：Tween/动画（跳过）
- **逐帧赋值**：`_process()` 中的每帧赋值（严重警告）

**分类逻辑：**

```python
def classify_position_assignment(context):
    # Context = 30 lines around assignment

    # SKIP: Animation/tween
    if "tween" in context or "create_tween" in context:
        return "INTENTIONAL_ANIMATION"

    # SKIP: Camera following
    if "camera.position" in context or "get_viewport().get_camera" in context:
        return "INTENTIONAL_DYNAMIC"

    # SKIP: Player following
    if "player.position" in context or "target.position" in context:
        return "INTENTIONAL_DYNAMIC"

    # CRITICAL: Every frame assignment
    if "_process(" in context:
        return "PROCESS_ASSIGNMENT"

    # CONFLICT: Static assignment in _ready
    if "_ready(" in context and "Vector2(" in line:
        return "CONFLICT"

    return "UNKNOWN"
```

5. **创建冲突清单**

生成按优先级排序的列表：

| 文件 | 节点 | 编辑器位置 | 代码位置 | 分类 | 同步策略 |
|------|------|-----------|---------|------|---------|
| background.gd | Background | (0, 0) | camera.position | 动态 | 记录意图 |
| enemy.gd | Enemy | (500, 300) | (100, 150) | 冲突 | 代码 → 编辑器 |
| ui_label.gd | Label | (10, 10) | (50, 50) | 冲突 | 编辑器 → 代码 |

**阶段 1 输出：**
- 所有位置赋值已检测
- 冲突已智能分类
- 清单表格已生成
- 准备好进行同步

---

### 阶段 2：位置同步（三种策略）

按优先级处理冲突：严重 → 冲突 → 动态

**关键 - 每次操作后：**
1. Git 提交更改
2. **运行自动验证测试**
3. 如果测试失败：自动回滚并报告错误
4. 如果测试通过：**自动继续处理下一个冲突**
5. 除非测试失败或需要用户确认，否则不提示用户

**自动测试流程：**
```bash
# Quick validation test (runs after each git commit)
echo "Running validation test..."
godot --headless --quit-after 5 project.godot 2>&1 | tee test_output.log

# Check for errors
if grep -q "ERROR\|SCRIPT ERROR\|Parse Error" test_output.log; then
    echo "⚠️  Tests failed - reverting operation"
    git reset --hard HEAD~1
    echo "❌ Operation reverted. Error details:"
    grep "ERROR\|SCRIPT ERROR\|Parse Error" test_output.log
    # STOP and report to user
else
    echo "✓ Tests passed - continuing"
    rm test_output.log
    # CONTINUE to next operation automatically
fi
```

#### 策略 A：代码 → 编辑器同步

**目标**：代码位置应成为编辑器位置的静态位置冲突

**何时使用：**
- 代码位置是预期的最终位置
- 编辑器预览应与运行时一致
- 位置在 `_ready()` 中设置一次且不再改变

**流程：**

1. **检测冲突**
```bash
# Example: enemy.gd sets position in _ready()
grep -A5 "_ready" enemy.gd
```

示例代码：
```gdscript
# enemy.gd
func _ready():
    position = Vector2(100, 150)  # 与 .tscn 冲突
```

示例 .tscn：
```ini
[node name="Enemy" type="CharacterBody2D"]
position = Vector2(500, 300)  # 与代码不同
```

2. **更新 .tscn 文件**

解析并更新：
```python
# Read .tscn file
with open("enemy.tscn") as f:
    content = f.read()

# Find and replace position line
content = re.sub(
    r'position = Vector2\([^)]+\)',
    'position = Vector2(100, 150)',
    content
)

# Write back
with open("enemy.tscn", "w") as f:
    f.write(content)
```

3. **更新 .gd 文件**

移除静态赋值，添加注释：
```gdscript
# enemy.gd
func _ready():
    # 位置已移至 .tscn 以便在编辑器中可见
    # 原来：position = Vector2(100, 150)
    pass
```

4. **Git 提交**
```bash
git add enemy.tscn enemy.gd
git commit -m "Sync: Move enemy position from code to editor (.tscn)

- Updated enemy.tscn position to Vector2(100, 150)
- Removed static position assignment from enemy.gd
- Editor now matches runtime position"
```

5. **运行自动测试**（参见阶段 2 标题中的测试流程）

**成功标准：**
- .tscn 位置与预期运行时位置一致
- 代码赋值已移除
- 注释记录了更改
- 行为未改变

---

#### 策略 B：编辑器 → 代码同步

**目标**：位置应在代码中设置，移除 .tscn 位置

**何时使用：**
- 位置是计算/动态的
- .tscn 位置是任意/错误的
- 代码位置是事实来源

**流程：**

1. **保留代码赋值**

代码已经正确：
```gdscript
func _ready():
    position = Vector2(100, 150)  # 正确的位置
```

2. **将 .tscn 重置为默认值**

将 .tscn 更新为中性位置：
```ini
[node name="Enemy" type="CharacterBody2D"]
# position removed (defaults to Vector2(0, 0))
```

或者明确设置为原点：
```ini
position = Vector2(0, 0)
```

3. **添加文档**

添加注释说明：
```gdscript
func _ready():
    # 位置在代码中设置（不在 .tscn 中）
    # 编辑器显示 (0,0)，运行时显示计算后的位置
    position = Vector2(100, 150)
```

4. **Git 提交**
```bash
git commit -m "Sync: Keep enemy position in code, reset editor

- Removed position from enemy.tscn (defaults to origin)
- Kept code position assignment
- Runtime position calculated in _ready()"
```

5. **运行自动测试**

---

#### 策略 C：相机感知定位（特殊）

**目标**：背景、视差层、相机跟随元素

**何时使用：**
- 背景跟随相机
- 视差层
- 玩家相对的 UI 元素
- 动态相机定位

**特殊情况 - 用户的背景问题：**

**问题**：背景在编辑器中定位在 (0, 0)，但运行时跟随相机，导致关卡设计时产生困惑。

**解决方案**：

1. **检测相机跟随模式**

```gdscript
# background.gd
func _process(delta):
    position = camera.position  # 跟随相机
```

2. **计算预期的编辑器位置**

查找典型的相机起始位置：
```bash
# Search for camera or player spawn position
grep -rn "camera.*position\|player.*position" --include="*.tscn" .
```

示例：相机从 (512, 300) 开始

3. **将 .tscn 更新为相机起始位置**

```ini
[node name="Background" type="Sprite2D"]
position = Vector2(512, 300)  # 相机起始位置
```

4. **记录相机相对行为**

```gdscript
# background.gd
func _process(delta):
    # 编辑器说明：.tscn 中的位置显示相机起始位置
    # 以获得准确的关卡设计预览。运行时跟随相机。
    position = camera.position
```

5. **创建编辑器预览工具（可选）**

生成编辑器插件以显示相机范围：

```gdscript
# addons/camera_preview/camera_preview.gd
@tool
extends EditorPlugin

func _enter_tree():
    # Draw camera bounds in editor
    pass
```

**结果：**
- 编辑器显示真实的预览
- 背景出现在预期的相机位置
- 关卡设计是准确的
- 运行时行为未改变

6. **Git 提交**
```bash
git commit -m "Sync: Camera-aware background positioning

- Updated background.tscn to camera start position
- Added documentation for camera-following behavior
- Editor now shows accurate runtime preview"
```

7. **运行自动测试**

**成功标准：**
- 编辑器预览显示真实的相机视图
- 运行时行为未改变
- 关卡设计是准确的
- 文档说明了动态行为

---

### 阶段 3：验证与报告

**目的**：确保同步成功且无回归。

**步骤：**

1. **在 Godot 中打开项目**
```bash
godot --editor project.godot
```

2. **视觉验证**
- 在编辑器中打开同步后的场景
- 将编辑器位置与清单对比
- 验证位置与预期一致

3. **运行时验证**
```bash
# Run main scene for 10 seconds
godot --quit-after 10 project.godot
```

4. **检查冲突**
```bash
# Re-run detection to verify all conflicts resolved
grep -rn "position\s*=\s*Vector2(" --include="*.gd" . | wc -l
```

5. **生成报告**

```
=== 位置同步完成 ===

已解决的冲突：X
- 代码 → 编辑器：X
- 编辑器 → 代码：X
- 相机感知：X

修改的文件：
- X 个 .tscn 文件已更新
- X 个 .gd 文件已更新

创建的 git 提交：X

所有测试通过 ✓
未检测到回归 ✓
编辑器预览与运行时一致 ✓
```

---

## 支持文件

此技能使用模块化参考文件：

- **position-detection-patterns.md**：所有位置检测的 grep 模式
- **sync-strategies.md**：详细的分步流程
- **camera-aware-positioning.md**：相机/视差处理
- **validation-tests.md**：测试流程

阅读这些文件获取详细的实现指导。

---

## 危险信号 - 停止

这些想法意味着你在为偏离规范找借口：

| 合理化借口 | 现实 | 修正方法 |
|-----------|------|---------|
| "这个动态位置是冲突" | 错误分类会破坏行为 | 使用智能分类器 |
| "我要同步所有位置" | 过度同步会破坏有意的动态定位 | 只同步真正的冲突 |
| "相机跟随是冲突" | 错误——这是有意设计 | 跳过动态模式 |
| "我不需要测试这个更改" | 未测试 = 已损坏 | 始终验证 |
| "编辑器中差不多就行" | 铁律没有例外 | 只接受精确位置 |
| "我手动修复 .tscn" | 手动编辑会产生错误 | 通过程序解析 |

---

## 快速参考：冲突 → 策略

| 冲突类型 | 检测方式 | 策略 |
|---------|---------|------|
| _ready() 中的静态赋值 | _ready 中的 `position = Vector2()` | 代码 → 编辑器 |
| 计算位置 | `position = calc_spawn()` | 编辑器 → 代码 |
| 相机跟随 | `position = camera.position` | 相机感知 |
| 视差层 | ParallaxLayer + scroll | 相机感知 |
| 玩家相对 | `position = player.position + offset` | 记录动态 |
| 动画/Tween | `tween_property("position")` | 跳过（有意设计）|
| 逐帧 (_process) | _process 中的 position | 严重警告 |

---

## 相机感知定位 - 特殊功能

### 用户的背景用例

**问题描述：**
- 背景层在编辑器中定位于 (0, 0)
- 运行时背景跟随相机：`position = camera.position`
- 编辑器显示错误位置 → 关卡设计时令人困惑
- 需求：在编辑器和运行时都显示正确位置

**解决方案：**

1. **检测相机起始位置**
```bash
# Find main camera or player spawn point
grep -rn "Camera2D\|player.*position" --include="*.tscn" .
```

2. **计算编辑器位置**
```python
# Parse camera start position from main scene
camera_start = Vector2(512, 300)  # Example

# Set background .tscn to camera start
background_position = camera_start
```

3. **更新背景 .tscn**
```ini
[node name="Background" type="Sprite2D"]
position = Vector2(512, 300)  # 相机起始位置（原来是 0, 0）
```

4. **记录行为**
```gdscript
# background.gd
# 编辑器预览：位置设置为相机起始位置以获得准确的关卡设计
# 运行时：动态跟随相机
func _process(delta):
    position = camera.position
```

5. **创建视差处理器（如需要）**

对于 ParallaxBackground 节点：
```gdscript
# parallax_background.gd
@export var camera_start_position := Vector2(512, 300)

func _ready():
    # Set initial scroll to camera start
    scroll_offset = camera_start_position
```

**结果：**
- 编辑器显示背景在相机起始位置
- 关卡设计是准确的
- 运行时按预期跟随相机
- 所见即所得已实现 ✓

---

## 执行策略

此技能**完全自动运行**：

1. 用户在 Godot 项目上调用技能
2. 阶段 1：扫描并报告发现
3. 用户批准同步
4. 阶段 2：执行所有同步操作并提交
5. 阶段 3：验证并报告结果

**需要用户输入的地方：**
- 初始调用
- 阶段 1 分析后的审批
- 策略选择（如有歧义）
- 最终验证检查

**其他一切都是自动的：**
- 位置冲突检测
- 智能分类
- .tscn 文件更新
- 脚本修改
- Git 提交
- 测试

---

## 成功标准

同步完成的条件：

- 所有静态位置冲突已解决
- 相机跟随元素已记录
- 编辑器预览与运行时位置一致
- 所有场景无错误加载
- 行为与基线相同
- 视觉外观未改变
- 干净的 git 历史，带有描述性提交

---

## 与其他技能的集成

**配合良好的技能：**
- **godot-refactoring**：在位置同步前进行重构
- **场景层级清理器**：将背景组织到分组中
- **场景布局组织器**：在位置同步后对齐

**最佳实践工作流：**
1. 运行 godot-refactoring（如需要）
2. 运行 editor-position-sync
3. 运行 scene-hierarchy-cleaner（如需要）
4. 继续开发

---

**记住**：编辑器预览是视觉设计的事实来源。运行时必须与你在编辑器中看到的一致。不允许出现意外。
