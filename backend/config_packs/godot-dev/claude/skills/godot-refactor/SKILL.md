---
name: godot-refactor
version: 3.0.0
displayName: "Godot 重构编排器"
description: >
  当 Godot 项目存在代码创建的对象、通过直接引用导致的紧耦合、超过 150 行的
  巨型脚本、或需要采用场景优先的信号与组合架构时使用。编排所有 5 个代码质量
  子技能：extract-to-scenes、split-scripts、add-signals、extract-resources
  和 clean-conflicts。每个操作独立运行，带有 git 提交和验证。
author: "Asreonn"
license: MIT
category: game-development
type: agent
difficulty: intermediate
audience: [developers, teams]
keywords:
  - godot
  - refactoring
  - code-quality
  - scene-architecture
  - signals
  - composition
  - gdscript
  - clean-code
  - godot4
platforms: [macos, linux, windows]
repository: https://github.com/asreonn/godot-superpowers
homepage: https://github.com/asreonn/godot-superpowers#readme
filesystem:
  read:
    - "${PROJECT_ROOT}/**/*.gd"
    - "${PROJECT_ROOT}/**/*.tscn"
    - "${PROJECT_ROOT}/project.godot"
    - "${PROJECT_ROOT}/**/*.tres"
  write:
    - "${PROJECT_ROOT}/**/*.gd"
    - "${PROJECT_ROOT}/**/*.tscn"
    - "${PROJECT_ROOT}/components/**"
    - "${PROJECT_ROOT}/resources/**"
  deny:
    - "**/.env*"
    - "**/secrets*"
    - "**/*.key"
    - "**/*.pem"
behavior:
  timeout: 600
  retry: 3
  cache: true
  interactive: true
use_cases:
  - "构建新功能时代码使用 .new() 而非场景"
  - "脚本超过 150 行且承担过多职责"
  - "代码中存在 get_node() 链导致紧耦合"
  - "游戏数据硬编码在 const 数组中"
  - "需要为团队协作建立整洁的架构"
  - "为代码审查或测试做准备"
  - "希望对整个项目进行全面重构"
outputs: "组件库、拆分后的脚本、Signal 架构、Resource 文件、每个操作的 git 提交"
requirements: "Git 仓库、Godot 4.x、bash 工具（grep、find、awk）"
execution: "完全自动，阶段 1 分析后用户审批"
auto_rollback: "是 - 验证测试失败时自动回滚"
integration: "编排：godot-extract-to-scenes、godot-split-scripts、godot-add-signals、godot-extract-resources、godot-clean-conflicts"
---

# Godot 重构编排器

**此编排器按顺序运行 5 个代码质量子技能。如需单独操作，请直接调用子技能。**

## 核心原则：场景优先、Signal 驱动、组件组合

**铁律**：重构期间不允许任何功能或视觉变更。没有例外。

此技能自动将 Godot 项目重构为更整洁、更模块化的架构，同时保持完全相同的行为。每个操作都会创建一次 git 提交。随时可以回滚。

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

### 2. 开始阶段 1：分析与基线（自动）

**不要询问"你希望我做什么？"——立即开始分析。**

并行执行以下命令：

```bash
# Detect code-created objects
grep -rn "\.new()" --include="*.gd" . | grep -E "(Node|Timer|Area|Sprite|Control|Collision)" | wc -l

# Detect monolithic scripts
find . -name "*.gd" -exec wc -l {} + | awk '$1 > 150' | wc -l

# Detect tight coupling
grep -rn "get_node\|has_method" --include="*.gd" . | wc -l

# Detect inline data
grep -rn "^[[:space:]]*const.*\[" --include="*.gd" . | wc -l
```

### 3. 展示结果（30 秒）

向用户展示：
```
=== Godot 重构分析 ===

项目：[从 project.godot 获取的项目名称]

检测到的反模式：
- 代码创建的对象：X
- 巨型脚本：X
- 紧耦合：X
- 内联数据：X
- 冲突操作：（将在重构后检测）

总计：发现 X 个反模式

重构包括：
✓ 每次操作后自动测试
✓ 测试失败时自动回滚
✓ 每次操作 git 提交
✓ 按需推送到远程

您希望我：
1. 继续自动重构（推荐）
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

**代码创建的对象：**
- 在 `_ready()`、`_process()` 或其他生命周期方法中调用 `.new()`
- 使用 `add_child()` 添加程序化创建的节点
- 在代码中创建 Timer、Area、Sprite

**巨型脚本：**
- 脚本超过 150 行
- 一个文件中包含多个不相关的职责
- 什么都做的上帝对象

**紧耦合：**
- 用 `get_node()` 链访问其他节点
- 调用前进行 `has_method()` 检查
- 跨节点直接访问属性
- 行为依赖于父子关系

**内联数据：**
- 包含游戏数据的 `const` 数组
- 脚本中硬编码的配置
- 应该作为 Resource 的数据

**深层继承：**
- 脚本继承超过 2 层
- 使用继承进行代码复用而非组合

### 决策流程图

```
用户提到 Godot 项目
    ↓
是否存在上述任何症状？
    ↓ 是                      ↓ 否
使用此技能                  常规开发
    ↓
运行阶段 1：分析
    ↓
发现反模式了吗？
    ↓ 是                      ↓ 否
运行阶段 2-4               记录干净状态
```

---

## 四个阶段

### 阶段 1：分析与基线（自动）

**目的**：检测所有反模式并创建安全基线。

**步骤：**

1. **扫描项目文件**
```bash
# Find all Godot script files
find . -name "*.gd" -type f

# Find all scene files
find . -name "*.tscn" -type f
```

2. **检测反模式**

使用 `anti-patterns-detection.md` 中的检测模式：

```bash
# Code-created objects
grep -rn "\.new()" --include="*.gd" .

# Monolithic scripts (>150 lines)
find . -name "*.gd" -exec wc -l {} + | awk '$1 > 150 {print $2 " (" $1 " lines)"}'

# Tight coupling
grep -rn "get_node\|get_parent\|has_method" --include="*.gd" .

# Inline data
grep -rn "^[[:space:]]*const.*\[" --include="*.gd" .
```

3. **创建 Git 基线**

```bash
# Save current branch
current_branch=$(git branch --show-current)

# Create baseline tag
git tag baseline-$(date +%Y%m%d-%H%M%S)

# Initial commit if there are uncommitted changes
git add .
git commit -m "Baseline: Pre-refactoring state (on $current_branch)"
```

4. **生成重构清单**

创建按优先级排序的列表：

| 优先级 | 反模式 | 文件 | 行号 | 操作 |
|--------|--------|------|------|------|
| 1 | 内联数据 | enemy_data.gd | 45-78 | 提取为 .tres |
| 2 | 代码创建的 Timer | laser_beam.gd | 38-45 | 提取为 .tscn |
| 3 | 紧耦合 | base_station.gd | 92 | Signal 解耦 |
| 4 | 巨型脚本 | player_movement.gd | 287 行 | 拆分脚本 |

**阶段 1 输出：**
- 基线 git 提交/标签已创建
- 反模式已检测并排序
- 清单表格已生成
- 准备好进行自动重构

---

### 阶段 2：自动重构（五项操作）

按优先级处理反模式：数据 → 场景 → Signal → 脚本 → 冲突

**关键 - 每次操作后：**
1. Git 提交更改
2. **运行自动验证测试**
3. 如果测试失败：自动回滚并报告错误
4. 如果测试通过：**自动继续下一项操作**
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

**注意：** 如果测试失败，停止工作流并向用户报告。否则，自动继续执行所有操作。

#### 操作 A：将代码创建的对象提取为模块化组件

**目标**：任何创建节点的 `.new()` 调用

**增强流程：**

1. **检测与分析**
   - 查找节点类型的 `.new()` 调用
   - 提取 30 行上下文（属性、方法、Signal）
   - 分析变量名、属性、方法
   - 参考 `node-selection-guide.md` 决策树
   - 计算节点类型的置信度分数
   - 从 `godot-node-reference.md` 中选择最佳节点

2. **检查组件库**
   - `components/{category}/` 是否存在？（例如 `components/timers/`）
   - 如果存在：复用基础组件，跳到步骤 4
   - 如果不存在：生成完整的组件结构（步骤 2-3）

3. **生成组件（仅首次）**
   - 创建 `{type}_config.gd`（带 @export 属性的 Resource 类）
   - 创建 `configurable_{type}.gd`（继承节点并应用配置的脚本）
   - 创建 `configurable_{type}.tscn`（带脚本的基础场景）
   - 创建模块化、可复用的基础

4. **生成预设 Resource**
   - 从分析的代码中提取属性
   - 创建 `presets/{preset_name}.tres`（具体配置）
   - 每个检测到的实例获得唯一预设
   - 预设引用基础组件

5. **更新父场景**
   - 为基础场景和预设添加 ext_resource 条目
   - 用预设 Resource 实例化基础组件
   - 相同场景复用，不同预设 = 零重复

6. **更新父脚本**
   - 添加组件实例的 @onready 引用
   - 保留 Signal 连接
   - 移除 .new()、add_child()、静态属性赋值
   - 配置现在来自预设 Resource

7. **Git 提交与验证**
   - 提交所有组件文件和父级更改
   - 运行验证测试
   - 确保行为未改变

**示例变换：**

修改前（代码创建）：
```gdscript
func _ready():
    _damage_timer = Timer.new()
    _damage_timer.wait_time = 0.5
    _damage_timer.one_shot = false
    add_child(_damage_timer)
    _damage_timer.timeout.connect(_on_damage)

    _cooldown_timer = Timer.new()
    _cooldown_timer.wait_time = 2.0
    _cooldown_timer.one_shot = true
    add_child(_cooldown_timer)
    _cooldown_timer.timeout.connect(_on_cooldown)
```

修改后（第一个 Timer - 创建完整组件）：
```
创建的文件：
✓ components/timers/timer_config.gd（Resource 类）
✓ components/timers/configurable_timer.gd（可复用脚本）
✓ components/timers/configurable_timer.tscn（可复用基础场景）
✓ components/timers/presets/damage_timer.tres（配置预设）

parent.gd:
@onready var _damage_timer: ConfigurableTimer = $DamageTimer

func _ready():
    _damage_timer.timeout.connect(_on_damage)
```

修改后（第二个 Timer - 复用基础）：
```
创建的文件：
✓ components/timers/presets/cooldown_timer.tres（仅新增预设！）

parent.gd:
@onready var _damage_timer: ConfigurableTimer = $DamageTimer
@onready var _cooldown_timer: ConfigurableTimer = $CooldownTimer

func _ready():
    _damage_timer.timeout.connect(_on_damage)
    _cooldown_timer.timeout.connect(_on_cooldown)
```

**关键好处：**

- 智能节点选择（无随意选择）
- 模块化组件（跨项目可复用）
- 零重复（相同基础，不同预设）
- 检查器可配置（在编辑器中编辑预设）
- 自动构建库（有机增长）
- Signal 连接保留
- 行为未改变（铁律维持）

**成功标准：**
- 组件结构已创建（如果是同类型首次）
- 预设 Resource 已创建，包含提取的值
- 父场景用预设实例化组件
- 父脚本有 @onready 引用
- Signal 连接有效
- 旧代码已移除
- 行为未改变

---

#### 操作 B：拆分巨型脚本

**目标**：超过 150 行且包含多个职责的脚本

**检测：**
```bash
find . -name "*.gd" -exec wc -l {} + | awk '$1 > 150'
```

**对每个检测到的脚本：**

1. **分析脚本结构**
   - 识别逻辑区段（查找注释标题、函数分组）
   - 找出职责（输入、物理、技能、UI 等）
   - 确定区段之间的依赖关系

2. **规划拆分**
   - 主脚本保留核心职责
   - 将次要职责提取为组件
   - 定义组件之间的 Signal 接口

3. **创建组件脚本**

   示例：拆分 `player_movement.gd`（287 行）

   提取为 `player_abilities.gd`：
   ```gdscript
   extends Node
   class_name PlayerAbilities

   signal ability_used(ability_name: String)
   signal cooldown_started(duration: float)

   # Ability-related functions moved here
   ```

4. **更新主脚本**
   ```gdscript
   @onready var abilities: PlayerAbilities = $Abilities

   func _ready():
       abilities.ability_used.connect(_on_ability_used)
   ```

5. **实现 Signal 通信**
   - 用 Signal 替换直接函数调用
   - 在 _ready() 中连接 Signal
   - 移除紧耦合

6. **Git 提交**
   ```bash
   git add player_movement.gd player_abilities.gd
   git commit -m "Refactor: Split abilities from player_movement.gd"
   ```

7. **运行自动测试**（参见阶段 2 标题中的测试流程）

**成功标准：**
- 主脚本少于 150 行
- 组件脚本职责单一（80-120 行最佳）
- 基于 Signal 的通信
- 无直接依赖
- 行为未改变

---

#### 操作 C：实现基于 Signal 的解耦

**目标**：通过 get_node()、has_method()、直接调用产生的紧耦合

**检测：**
```bash
grep -rn "get_node\|has_method" --include="*.gd" .
```

**对每个检测到的耦合：**

1. **识别关系**
   - 正在访问什么？
   - 交换的是什么信息？
   - 这是基于事件还是状态查询？

2. **创建/使用 Events Autoload**

   如果不存在，创建 `events.gd`：
   ```gdscript
   extends Node
   # Global event bus

   signal player_entered_safe_zone(zone: Node2D)
   signal enemy_spawned(enemy: Node2D)
   signal score_changed(new_score: int)
   ```

   添加到项目设置：Project → Project Settings → Autoload

3. **用 Signal 替换直接耦合**

   修改前：
   ```gdscript
   func _on_body_entered(body):
       if body.has_method("set_beam_enabled"):
           body.set_beam_enabled(false)
   ```

   修改后（发射端）：
   ```gdscript
   func _on_body_entered(body):
       if body.is_in_group("player"):
           Events.player_entered_safe_zone.emit(self)
   ```

   修改后（接收端）：
   ```gdscript
   func _ready():
       Events.player_entered_safe_zone.connect(_on_safe_zone)

   func _on_safe_zone(zone):
       set_beam_enabled(false)
   ```

4. **移除耦合代码**
   - 删除 get_node() 调用
   - 删除 has_method() 检查
   - 删除直接属性访问

5. **Git 提交**
   ```bash
   git add events.gd base_station.gd player_movement.gd
   git commit -m "Refactor: Decouple base_station from player via signals"
   ```

6. **运行自动测试**（参见阶段 2 标题中的测试流程）

**成功标准：**
- 不再通过 get_node() 访问行为
- 不再有 has_method() 检查
- Events.gd 已存在并被使用
- Signal 连接已建立
- 行为未改变

---

#### 操作 D：将数据提取为 .tres Resource

**目标**：包含游戏数据的 `const` 声明

**检测：**
```bash
grep -rn "^[[:space:]]*const.*\[" --include="*.gd" .
```

**对每个检测到的数据常量：**

1. **分析数据结构**
   ```gdscript
   const ENEMY_TYPES = [
       {"type": "basic", "health": 100, "speed": 200},
       {"type": "fast", "health": 50, "speed": 400}
   ]
   ```

2. **创建 Resource 类**

   创建 `enemy_type_data.gd`：
   ```gdscript
   extends Resource
   class_name EnemyTypeData

   @export var type_name: String
   @export var health: int
   @export var speed: float
   ```

3. **生成 .tres 文件**

   创建 `enemy_types/basic.tres`：
   ```ini
   [gd_resource type="EnemyTypeData" load_steps=2 format=3]

   [ext_resource type="Script" path="res://enemy_type_data.gd" id="1"]

   [resource]
   script = ExtResource("1")
   type_name = "basic"
   health = 100
   speed = 200.0
   ```

4. **更新脚本以使用 Resource**
   ```gdscript
   @export var enemy_types: Array[EnemyTypeData]

   # In scene, assign resources via inspector
   ```

5. **移除 const 声明**

6. **Git 提交**
   ```bash
   git add enemy_type_data.gd enemy_types/*.tres enemy_spawner.gd
   git commit -m "Refactor: Extract enemy data to .tres resources"
   ```

7. **运行自动测试**（参见阶段 2 标题中的测试流程）

**成功标准：**
- Resource 类已创建
- .tres 文件已生成，数据正确
- 脚本已更新为使用 Resource
- Const 声明已移除
- 行为未改变

---

#### 操作 E：清理冲突/无效操作

**目标**：运行不报错但无实际效果或与其他代码冲突的代码

**重要**：此操作在操作 A-D 完成**之后**运行，因为重构可能引入或移除冲突。

**检测：**
```bash
# Run comprehensive conflict detection
bash << 'EOF'
echo "=== Detecting Conflicting Operations ==="

# Self-assignments
echo "Self-assignments:"
grep -rn "position\s*=\s*position\|scale\s*=\s*scale\|rotation\s*=\s*rotation" --include="*.gd" .

# Redundant defaults
echo "Redundant defaults:"
grep -rn "modulate\s*=\s*Color\.WHITE\|scale\s*=\s*Vector2\.ONE" --include="*.gd" .

# Duplicate property assignments (common properties)
echo "Checking for duplicate assignments..."
for prop in "scale" "position" "rotation" "modulate" "visible"; do
    grep -rn "\.$prop\s*=" --include="*.gd" . | \
    awk -F: -v prop="$prop" '{
        file=$1; line=$2;
        if (file==prev_file && line-prev_line<20) {
            print file":"prev_line" and "line" - Duplicate "prop
        }
        prev_file=file; prev_line=line
    }'
done

# Conflicting tweens
echo "Conflicting tweens:"
grep -n "tween_property" --include="*.gd" -r . | \
awk -F: '{
    file=$1; line=$2;
    if (match($0, /tween_property.*"([^"]+)"/, arr)) {
        prop=arr[1];
        key=file":"prop;
        if (key in seen && line-seen[key]<15) {
            print file":"seen[key]" and "line" - Conflicting tweens on "prop
        }
        seen[key]=line
    }
}'

# Code after queue_free
echo "Code after queue_free:"
grep -A2 "queue_free()" --include="*.gd" . | grep -v "^--$"

EOF
```

**对每个检测到的冲突：**

1. **自动修复**（无需用户输入）：
   - 自赋值：完全移除
   - `queue_free()` 之后的代码：移到 queue_free 之前
   - 明显的冗余默认值：移除

2. **需要用户确认**（询问用户）：
   - 重复赋值：保留哪个值？
   - 冲突的 Tween：保留哪个还是链接？
   - 多次 process 调用：最终期望状态？

3. **示例修复：**

   **自赋值：**
   ```gdscript
   # Before
   position = position

   # After (remove line)
   ```

   **重复赋值：**
   ```gdscript
   # Before
   sprite.scale = Vector2(2, 2)  # Line 45
   sprite.scale = Vector2(1, 1)  # Line 52

   # After (keep last)
   sprite.scale = Vector2(1, 1)  # Line 52
   ```

   **冲突的 Tween（用户选择"链接"）：**
   ```gdscript
   # Before
   var tween1 = create_tween()
   tween1.tween_property(self, "scale", Vector2(2,2), 1.0)
   var tween2 = create_tween()
   tween2.tween_property(self, "scale", Vector2(0.5,0.5), 1.0)

   # After
   var tween = create_tween()
   tween.tween_property(self, "scale", Vector2(2,2), 1.0)
   tween.tween_property(self, "scale", Vector2(0.5,0.5), 1.0)
   ```

4. **Git 提交**
   ```bash
   git add <modified files>
   git commit -m "Refactor: Clean conflicting/ineffective operations

   - Removed self-assignments
   - Fixed duplicate property assignments
   - Resolved conflicting tweens
   - Cleaned up redundant operations

   No functional changes - code cleanup only"
   ```

5. **运行自动测试**（参见阶段 2 标题中的测试流程）

**成功标准：**
- 不再有自赋值
- 不再有明显的重复赋值
- 冲突的 Tween 已解决
- queue_free() 之后的代码已移动
- 行为未改变

**注意：** 参见 `conflicting-operations-detection.md` 获取全面的检测模式，以及 `refactoring-operations.md` 操作 E 获取详细流程。

---

### 阶段 3：Git 提交（自动）

**每次操作后**，使用清晰的消息提交：

```bash
# Template
git add <files>
git commit -m "Refactor: <Operation> in <file> - <specific change>"

# Examples
git commit -m "Refactor: Extract Timer to scene in laser_beam.gd"
git commit -m "Refactor: Split abilities from player_movement.gd (287→142 lines)"
git commit -m "Refactor: Decouple base_station from player via signals"
git commit -m "Refactor: Extract enemy data to .tres resources"
git commit -m "Refactor: Clean conflicting/ineffective operations"
```

**所有操作完成后：**
```bash
git tag refactor-complete-$(date +%Y%m%d)
```

**提交历史应显示：**
- 基线提交
- 每个重构操作一次提交（A、B、C、D、E）
- 清晰、描述性的消息
- 易于审查
- 易于回滚单个更改

**按需推送：**

所有操作完成后，询问用户：
```
=== 重构完成 ===

所有操作成功完成！
执行了 5 项操作，在当前分支上创建了 X 次提交。

是否推送到远程仓库？
1. 是，立即推送
2. 否，我稍后手动推送
3. 先让我看看提交日志

选择 [1-3]：
```

**如果用户选 1（立即推送）：**
```bash
# Push to current branch's remote
git push origin $(git branch --show-current)
```

**如果用户选 3（先看日志）：**
```bash
git log --oneline --graph baseline-*..HEAD
# Then ask again: Push now? [y/n]
```

**如果用户在工作流中任何时候说"push"或"推送"：**
```bash
# Immediately push current branch
git push origin $(git branch --show-current)
echo "✓ Pushed to remote"
```

---

### 阶段 4：最终验证（精简、自动）

**目的**：确保无功能或视觉回归。

**步骤：**

1. **在 Godot 中打开项目**
   ```bash
   godot --editor path/to/project.godot
   ```

2. **检查错误**
   - 控制台中无红色错误
   - 无缺失节点的黄色警告
   - 所有场景成功加载

3. **视觉验证**
   - 运行主场景
   - 快速视觉检查（30 秒）
   - 与预期行为对比

4. **游玩测试检查清单**（来自 `verification-checklist.md`）：
   - [ ] 玩家移动正常
   - [ ] 技能正确触发
   - [ ] 敌人正常生成和行为
   - [ ] UI 正确更新
   - [ ] 无崩溃或错误

5. **性能基线**（可选）：
   ```bash
   # Compare FPS before/after
   # Should be identical ±2 FPS
   ```

**如果验证失败：**

```bash
# Rollback procedure
git reset --hard baseline-YYYYMMDD-HHMMSS
git tag refactor-failed-$(date +%Y%m%d-%H%M%S)

# Report what broke
# Debug with systematic-debugging skill
```

**如果验证成功：**

报告摘要：
```
✓ 重构完成
✓ 执行了 8 项操作
✓ 3 个文件中 287 行缩减为 142 行
✓ 创建了 4 个 .tscn 场景
✓ 创建了 2 个 .tres Resource
✓ 建立了基于 Signal 的架构
✓ 无功能变更
✓ 所有测试通过
```

---

## 支持文件

此技能使用模块化参考文件：

- **anti-patterns-detection.md**：所有用于检测的 grep/find 模式
- **refactoring-operations.md**：详细的分步流程
- **godot-best-practices.md**：整洁模式参考
- **tscn-generation-guide.md**：.tscn 文件格式模板
- **verification-checklist.md**：测试流程

阅读这些文件获取详细的实现指导。

---

## 危险信号 - 停止

这些想法意味着你在为偏离规范找借口：

| 合理化借口 | 现实 | 修正方法 |
|-----------|------|---------|
| "既然在这里，让我顺便加个功能" | 功能蔓延违反铁律 | 只重构，不加功能 |
| "这个行为有问题，我现在就修" | Bug 修复是另一项工作 | 记录 bug，只做重构 |
| "我不需要测试这个更改" | 未测试 = 已损坏 | 始终验证 |
| "我再改几处后一起提交" | 失去了粒度 | 每次操作提交一次 |
| "这个 .tscn 格式差不多就行" | 无效场景会崩溃 | 使用精确格式 |
| "用户不会注意到这个视觉变化" | 铁律没有例外 | 回滚并修复 |
| "Signal 对这个来说太过了" | 耦合会逐渐回来 | 还是用 Signal |
| "我以后再手动测试" | 以后永远不会来 | 现在就测试 |
| "这个脚本 160 行也还行" | 随意的例外会越来越多 | 150 行就拆分 |
| "我理解这个模式了，不需要读" | 假设会产生 bug | 读指南 |

---

## 快速参考：反模式 → 整洁模式

| 反模式 | 整洁模式 | 工具 |
|--------|---------|------|
| 代码中 `Timer.new()` | 带 Timer 的 .tscn 场景 | 操作 A |
| `get_node("../Player")` | 通过 Events 的 Signal | 操作 C |
| `if has_method("take_damage"):` | Signal 监听器 | 操作 C |
| 287 行脚本 | 拆分为 3 个专注的脚本 | 操作 B |
| `const WEAPONS = [...]` | .tres Resource | 操作 D |
| `add_child(sprite)` | 场景组合 | 操作 A |
| 直接方法调用 | Signal emit/connect | 操作 C |
| 深层继承 | 组件组合 | 操作 A+B |

---

## 文件操作流程

```
1. 数据提取
   带 const 的 .gd → Resource 类 .gd + .tres 文件

2. 场景提取
   带 .new() 的 .gd → 带 @onready 的 .gd + 新 .tscn

3. Signal 解耦
   带 get_node() 的 .gd → events.gd + 更新后的 .gd 文件

4. 脚本拆分
   大型 .gd → 多个带 Signal 的专注 .gd 文件
```

---

## Godot 命名约定

**场景 (.tscn)：**
- 节点名使用 PascalCase：`DamageTimer`、`AbilitySystem`
- 文件名使用 snake_case：`damage_timer.tscn`、`ability_system.tscn`

**脚本 (.gd)：**
- 文件使用 snake_case：`player_movement.gd`、`enemy_spawner.gd`
- class_name 使用 PascalCase：`class_name PlayerMovement`

**Resource (.tres)：**
- 文件使用 snake_case：`enemy_types/basic.tres`
- Resource 类使用 PascalCase：`class_name EnemyTypeData`

**Signal：**
- 使用 snake_case：`signal ability_used`、`signal player_entered_safe_zone`
- 事件使用过去时态：`signal enemy_spawned`（不是 `enemy_spawn`）

**@onready 变量：**
- 带类型提示的 snake_case：`@onready var _damage_timer: Timer = $DamageTimer`
- 私有变量使用下划线前缀：`_damage_timer`、`_ability_system`

---

## 常见错误

| 错误 | 后果 | 修正方法 |
|------|------|---------|
| 无效的 .tscn 格式 | 场景无法在 Godot 中加载 | 使用精确的模板格式 |
| .tscn 中缺失节点类型 | Godot 无法解析场景 | 始终指定 `type="Timer"` |
| 忘记 @onready | 运行时空引用 | 为所有节点引用添加 @onready |
| 错误的 Signal 签名 | 连接静默失败 | 精确匹配参数类型 |
| 移除了必要的 .new() | 某些对象应该被代码创建 | 只重构场景节点 |
| 每次操作后不测试 | 错误累积 | 每次提交后测试 |
| 通过全局变量耦合 | 不同的耦合，相同的问题 | 仅用 Events 解耦 |
| 过度拆分脚本 | 太多小文件 | 80-120 行最佳 |
| 异步 Signal 不做检查 | 竞态条件 | 验证节点存在 |
| "稍微"改变行为 | 违反铁律 | 立即回滚 |

---

## Signal 架构模式

**事件总线 (Events.gd)：**
```gdscript
# Use for global events
signal player_died
signal level_completed(level_num: int)
signal score_changed(new_score: int)
```

**直接节点 Signal：**
```gdscript
# Use for parent-child communication
signal health_depleted
signal ability_activated(ability_name: String)
```

**何时使用哪种：**
- Events.gd：跨树通信、全局状态变更
- 节点 Signal：父子关系、本地行为

---

## 实际影响

重构后的预期改进：

**代码质量：**
- 总代码行数减少 30-50%
- 脚本平均 80-120 行（从 150-300 行降低）
- 零直接节点依赖
- 全面采用基于 Signal 的架构

**可维护性：**
- 变更隔离到单个文件
- 组件可跨场景复用
- 可以单独测试组件
- 新开发者更快上手

**性能：**
- 与基线相同（±2 FPS）
- 场景加载略快
- 内存使用不变

---

## 执行策略

此技能**完全自动运行**：

1. 用户在 Godot 项目上调用技能
2. 阶段 1：扫描并报告发现
3. 用户批准重构
4. 阶段 2-3：在当前分支上执行所有操作并提交
5. 阶段 4：验证并报告结果

**需要用户输入的地方：**
- 初始调用
- 阶段 1 分析后的审批
- 最终验证检查（30 秒）

**其他一切都是自动的：**
- 反模式检测
- .tscn 文件生成
- 脚本修改
- 在当前分支上 git 提交
- 测试

---

## 成功标准

重构完成的条件：

- 场景节点不再有 `.new()` 调用
- 所有脚本少于 150 行
- 建立了基于 Signal 的架构
- 不再通过 `get_node()` 访问行为
- 数据存储在 .tres Resource 中
- 当前分支上有干净的 git 历史和描述性提交
- 所有场景无错误加载
- 行为与基线相同
- 视觉外观未改变
- 性能在 ±2 FPS 范围内

---

## 重构后

成功重构后：

1. **继续开发**
   - 更改已在当前分支上
   - 如尚未推送则推送到远程
   - 继续正常的开发工作流

2. **记录架构**
   - 创建架构图
   - 记录 Signal 流程
   - 列出组件职责

3. **建立标准**
   - 使用这个整洁的架构作为模板
   - 将模式应用到新代码
   - 防止反模式回归

4. **考虑进一步改进**（独立任务）：
   - 添加单元测试（使用 TDD 技能）
   - 优化性能（先分析）
   - 添加新功能（使用头脑风暴技能）

---

**记住**：重构改变的是代码内部的工作方式，而非外部的功能表现。铁律是绝对的。
