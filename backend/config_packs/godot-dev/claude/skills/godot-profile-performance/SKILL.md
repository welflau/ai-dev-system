---
name: godot-profile-performance
version: 1.0.0
displayName: Godot 性能分析器
description: 检测 Godot 项目中的性能瓶颈，包括高开销的 _process 函数、循环中的 get_node() 调用、_process 中的实例化操作，并提供优化建议和 Godot 内置分析器集成
author: Asreonn
license: MIT
category: game-development
type: tool
difficulty: intermediate
audience:
  - developers
keywords:
  - godot
  - performance
  - profiler
  - optimization
  - _process
  - frame-time
  - bottleneck
  - memory
  - gdscript
platforms:
  - macos
  - linux
  - windows
repository: https://github.com/asreonn/godot-superpowers
homepage: https://github.com/asreonn/godot-superpowers#readme
permissions:
  filesystem:
    - read: "**/*.gd"
    - read: "**/project.godot"
    - write: "**/*.gd"
    - write: "**/optimization_report.md"
---

# Godot 性能分析器

## 概述

分析 Godot 项目以检测 GDScript 代码中的性能瓶颈。识别帧关键函数（如 `_process`、`_physics_process` 和 `_draw`）中的高开销操作。提供可操作的优化建议，包含优化前后的代码示例，并与 Godot 内置分析器集成进行验证。

**核心原则：** 帧时间非常宝贵——高开销操作应放在 `_ready` 或信号处理函数中，而非每帧回调中。

## 适用场景

**适合使用：**
- 帧率下降或性能不稳定
- CPU 使用率异常偏高
- 游戏过程中出现卡顿
- `_process` 函数包含复杂逻辑
- 内存使用量持续增长
- 发布游戏或重大更新前

**不适合用于：**
- 网络/服务器性能问题（使用服务器分析工具）
- GPU/着色器优化（使用 Godot 的 GPU 分析器）
- 物理模拟调优（使用 Godot 的物理调试工具）

## 检测模式

### 重型 _process 函数

**触发条件：** `_process` 或 `_physics_process` 中代码行数 >15 行的函数

**检测方法：**
```bash
# Count lines in process functions
rg "^func _process" -A 50 --glob "*.gd" | wc -l
```

**阈值：**
- 警告：>15 行
- 严重：>30 行

### 循环中的 get_node()

**模式：**
```gdscript
# ❌ 错误：在 _process 中调用 get_node()
func _process(delta):
    get_node("UI/HealthBar").value = health  # Called every frame!
    get_node("Player").position = position
```

**检测正则：**
```regex
func _process.*\n(?:.*\n)*?\s+get_node\(
```

### _process 中的实例化

**模式：**
```gdscript
# ❌ 错误：每帧创建对象
func _process(delta):
    var bullet = Bullet.new()  # Memory churn!
    add_child(bullet)
```

**检测关键词：**
- `_process` 或 `_physics_process` 中的 `.new()`
- 帧回调中的 `.instantiate()`
- 循环中的 `add_child()` 或 `remove_child()`

### _physics_process 中的复杂操作

**反模式：**
- 重型寻路计算
- 复杂的 AI 状态机
- 大型数组操作
- 文件 I/O 或网络调用

## 分析流程

### 帧时间分析

**步骤：**
1. 启用 Godot 分析器（Debug > Profiler）
2. 运行游戏 60 秒进行典型游玩
3. 识别 "Time (ms)" 值偏高的函数
4. 按 "Time %" 排序找到最大消耗者
5. 查找每帧 >0.1ms 的函数

**判读标准：**
- <0.01ms：优秀
- 0.01-0.05ms：良好
- 0.05-0.1ms：可接受
- >0.1ms：需要优化

### 内存使用检测

**指标：**
- 内存监控中持续增长
- 频繁的垃圾回收峰值
- Node 数量随时间递增

**检测方法：**
```bash
# Check for object creation in process functions
rg "\.new\(\)|instantiate\(\)" -B 5 -A 2 --glob "*.gd" | \
  rg -A 10 "func _process|func _physics_process"
```

### 绘制调用优化

**检查项：**
- Godot "Monitors" 标签页 > "Draw Calls"
- 每个独立材质 = 额外的绘制调用
- GPU 蒙皮 vs CPU 蒙皮

**优化目标：**
- 2D 游戏 <100 次绘制调用
- 简单 3D <500 次绘制调用
- 使用纹理图集减少材质切换

### 物理性能

**危险信号：**
- 碰撞形状复杂度过高
- 刚体过多（>100）
- 复杂多边形碰撞
- `_physics_process` 执行非物理相关工作

## 优化建议

### 缓存 Node 引用

**优化前：**
```gdscript
extends CharacterBody2D

func _process(delta):
    get_node("UI/HealthBar").value = health
    get_node("UI/ManaBar").value = mana
    get_node("UI/LevelLabel").text = str(level)
```

**优化后：**
```gdscript
extends CharacterBody2D

@onready var health_bar = $UI/HealthBar
@onready var mana_bar = $UI/ManaBar
@onready var level_label = $UI/LevelLabel

func _process(delta):
    health_bar.value = health
    mana_bar.value = mana
    level_label.text = str(level)
```

**影响：** 每帧消除 3 次节点查找（每次约 0.01ms）

### 将初始化移至 _ready

**优化前：**
```gdscript
func _process(delta):
    var gravity = ProjectSettings.get("physics/2d/default_gravity")
    velocity.y += gravity * delta
```

**优化后：**
```gdscript
var gravity

func _ready():
    gravity = ProjectSettings.get("physics/2d/default_gravity")

func _process(delta):
    velocity.y += gravity * delta
```

### 子弹/粒子的对象池

**优化前：**
```gdscript
func shoot():
    var bullet = BulletScene.instantiate()
    bullet.position = global_position
    get_parent().add_child(bullet)
```

**优化后：**
```gdscript
var bullet_pool: Array[Bullet] = []

func _ready():
    # Pre-instantiate bullets
    for i in range(50):
        var bullet = BulletScene.instantiate()
        bullet.hide()
        bullet_pool.append(bullet)
        get_parent().add_child(bullet)

func shoot():
    for bullet in bullet_pool:
        if not bullet.visible:
            bullet.position = global_position
            bullet.show()
            bullet.activate()
            return
```

**影响：** 消除游戏过程中的实例化开销

### 基于 Signal 的更新

**优化前：**
```gdscript
func _process(delta):
    # Checking every frame if health changed
    if health != previous_health:
        update_health_bar()
        previous_health = health
```

**优化后：**
```gdscript
signal health_changed(new_health)

var health = 100:
    set(value):
        if health != value:
            health = value
            health_changed.emit(health)

func _ready():
    health_changed.connect(update_health_bar)
```

### 批量数组操作

**优化前：**
```gdscript
func _process(delta):
    for enemy in enemies:
        if enemy.position.distance_to(player.position) < 100:
            enemy.target_player()
```

**优化后：**
```gdscript
var check_timer = 0.0
const CHECK_INTERVAL = 0.1  # Check 10x per second, not 60x

func _process(delta):
    check_timer += delta
    if check_timer >= CHECK_INTERVAL:
        check_timer = 0
        update_enemy_targets()

func update_enemy_targets():
    for enemy in enemies:
        if enemy.position.distance_to(player.position) < 100:
            enemy.target_player()
```

## Godot 分析器集成

### 启用分析器

1. 使用 Debug > Start with Profiler 运行游戏
2. 或在游戏运行时点击底部面板的 "Profiler" 标签
3. 启用特定监控项：
   - CPU Time
   - Function Time
   - Node Count
   - Memory
   - Draw Calls

### 关键监控指标

**帧时间（ms）：**
- 显示每帧总耗时
- 目标：60 FPS 时 <16.67ms，30 FPS 时 <33.33ms
- 峰值表示卡顿

**函数分析：**
- 列出所有函数并按时间排序
- 关注 `_process`、`_physics_process`、`_draw`
- 点击函数名查看调用者

**内存监控：**
- 监视持续增长
- 突然的峰值表示内存分配
- 平台期后的下降 = 垃圾回收

### 分析工作流

```
1. 建立基准线（未优化）
   └─ 记录 60 秒的分析器数据

2. 识别前 3 大时间消耗者
   └─ 在分析器中按 "Time %" 排序

3. 应用优化
   └─ 使用上述模式

4. 验证改进效果
   └─ 重新分析，对比指标
   └─ 验证帧时间降低

5. 对下一个瓶颈重复以上步骤
```

## 示例

### 示例 1：UI 控制器优化

**问题：**
```gdscript
# ui_controller.gd
extends Control

func _process(delta):
    # Called every frame - 5 node lookups!
    get_node("HealthBar").value = player.health
    get_node("ManaBar").value = player.mana
    get_node("LevelLabel").text = "Level: " + str(player.level)
    get_node("XpBar").value = player.xp
    get_node("GoldLabel").text = "Gold: " + str(player.gold)
```

**分析器输出：**
```
Function          | Time (ms) | Time %
----------------------------------------
_process          | 0.18      | 12.3%
get_node          | 0.15      | 10.2%  (x5)
```

**优化后：**
```gdscript
# ui_controller.gd
extends Control

@onready var health_bar = $HealthBar
@onready var mana_bar = $ManaBar
@onready var level_label = $LevelLabel
@onready var xp_bar = $XpBar
@onready var gold_label = $GoldLabel

func _ready():
    # Connect to player signals instead of polling
    player.health_changed.connect(_on_health_changed)
    player.mana_changed.connect(_on_mana_changed)
    player.leveled_up.connect(_on_leveled_up)
    player.xp_changed.connect(_on_xp_changed)
    player.gold_changed.connect(_on_gold_changed)

func _on_health_changed(value): health_bar.value = value
func _on_mana_changed(value): mana_bar.value = value
func _on_leveled_up(level): level_label.text = "Level: " + str(level)
func _on_xp_changed(value): xp_bar.value = value
func _on_gold_changed(value): gold_label.text = "Gold: " + str(value)
```

**结果：**
```
Function          | Time (ms) | Time %
----------------------------------------
_process          | 0.00      | 0.0%   (removed!)
_on_health_changed| 0.01      | 0.7%   (event-driven)
```

### 示例 2：敌人生成器修复

**问题：**
```gdscript
# spawner.gd
extends Node2D

func _process(delta):
    if enemies.size() < max_enemies:
        var enemy = EnemyScene.instantiate()  # Memory churn!
        enemy.position = random_position()
        add_child(enemy)
        enemies.append(enemy)
```

**内存泄漏：** 持续实例化且无对象池

**优化后：**
```gdscript
# spawner.gd
extends Node2D

var spawn_timer = 0.0
const SPAWN_RATE = 2.0  # Check spawn every 2 seconds

func _process(delta):
    spawn_timer += delta
    if spawn_timer >= SPAWN_RATE:
        spawn_timer = 0
        try_spawn()

func try_spawn():
    if enemies.size() < max_enemies:
        spawn_enemy()

func spawn_enemy():
    # Consider object pool for frequent spawns
    var enemy = EnemyScene.instantiate()
    enemy.position = random_position()
    add_child(enemy)
    enemies.append(enemy)
```

**进一步改进：** 对频繁生成的敌人使用对象池

### 示例 3：物理优化

**问题：**
```gdscript
# player.gd
extends CharacterBody2D

func _physics_process(delta):
    # Heavy calculation every physics frame
    var nearby = get_tree().get_nodes_in_group("enemies")
    for enemy in nearby:
        if global_position.distance_to(enemy.global_position) < detection_radius:
            enemy.set_target(self)

    # Do physics
    velocity.y += gravity * delta
    move_and_slide()
```

**分析器输出：**
```
Function              | Time (ms) | Time %
--------------------------------------------
_physics_process      | 0.45      | 28.5%
get_nodes_in_group    | 0.25      | 15.8%
distance_to           | 0.12      | 7.6%
```

**优化后：**
```gdscript
# player.gd
extends CharacterBody2D

var detection_timer = 0.0
const DETECTION_RATE = 0.2  # 5x per second

func _physics_process(delta):
    # Separate physics from AI
    velocity.y += gravity * delta
    move_and_slide()

    # Run detection less frequently
    detection_timer += delta
    if detection_timer >= DETECTION_RATE:
        detection_timer = 0
        update_enemy_detection()

func update_enemy_detection():
    var nearby = get_tree().get_nodes_in_group("enemies")
    for enemy in nearby:
        if global_position.distance_to(enemy.global_position) < detection_radius:
            enemy.set_target(self)
```

**结果：** 物理帧时间降低约 60%

## 成功标准

性能优化成功的标志：

### 量化指标
- [ ] 目标函数帧时间降低 >50%
- [ ] `_process` 函数代码行数 <15 行
- [ ] `_process` 或 `_physics_process` 中零 `get_node()` 调用
- [ ] 帧回调中零 `.new()` 或 `.instantiate()` 调用
- [ ] 分析器中前 3 个函数的 "Time %" 合计 <30%
- [ ] 帧时间稳定在 60 FPS 目标的 <16.67ms
- [ ] 内存使用稳定（无持续增长）

### 定性检查
- [ ] Node 引用在 `_ready()` 或 `@onready` 中缓存
- [ ] 复杂逻辑已移至信号或定时器
- [ ] 频繁实例化使用对象池
- [ ] `_physics_process` 仅包含物理相关代码
- [ ] 分析器数据显示相比基准线有改善

### 验证步骤
1. **优化前分析：** 记录基准指标
2. **应用优化：** 进行针对性修改
3. **优化后分析：** 对比指标
4. **游戏内验证：** 测试实际游玩体验是否更流畅
5. **检查边界情况：** 确保优化在所有场景下有效

## 快速参考

| 模式 | 检测方法 | 修复方案 | 影响 |
|------|----------|----------|------|
| _process 中的 get_node() | 搜索：`_process` 后的 `get_node` | 使用 `@onready` 缓存 | 每次调用约 0.01ms |
| _process 中的 .new() | 搜索：帧函数中的 `.new()` | 使用对象池 | 消除 GC 压力 |
| 重型 _process | 行数 >15 | 移至信号/定时器 | 减少每帧负载 |
| 物理 + AI | `_physics_process` 中的 AI | 使用定时器分离 | 降低 5-10 倍 |
| 未缓存的设置 | 循环中的 `ProjectSettings.get()` | 在 `_ready` 中缓存 | 一次性开销 |

## 常见错误

### 错误："以后再优化"
**问题：** 技术债务累积，后期更难修复
**修复：** 尽早且频繁地分析，及时修复瓶颈

### 错误：过早优化
**问题：** 优化了不是瓶颈的代码
**修复：** 始终先分析，聚焦最大时间消耗者

### 错误：微优化
**问题：** 花数小时节省 0.001ms
**修复：** 针对 >0.1ms 的函数，忽略其余

### 错误：不验证改进效果
**问题：** 假设优化有效却未测量
**修复：** 始终在优化前后运行分析器

### 错误：只优化发布版本
**问题：** 调试版本有不同的性能特征
**修复：** 对发布版本进行分析以获取准确数据
