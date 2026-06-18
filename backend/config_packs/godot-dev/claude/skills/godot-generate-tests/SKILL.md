---
name: godot-generate-tests
version: 1.0.0
displayName: 生成 Godot 测试
description: >
  在开发 Godot 游戏时需要为 GDScript 类、Signal、场景初始化和集成流程提供全面的测试覆盖时使用。
  生成 GUT 框架单元测试、集成测试、Mock/Stub 辅助工具和 CI/CD 测试运行器配置。
author: Asreonn
license: MIT
category: game-development
type: tool
difficulty: intermediate
audience: [developers]
keywords:
  - godot
  - testing
  - unit-test
  - gut
  - integration-test
  - mock
  - stub
  - tdd
  - gdscript
  - test-coverage
platforms: [macos, linux, windows]
repository: https://github.com/asreonn/godot-superpowers
homepage: https://github.com/asreonn/godot-superpowers#readme

permissions:
  filesystem:
    read: [".gd", ".tscn", ".tres"]
    write: [".gd", ".tscn", ".json", ".yml", ".yaml"]
  git: true

behavior:
  auto_rollback: true
  validation: true
  git_commits: true

outputs: "tests/ 目录中的测试文件、Mock 辅助工具、GUT 配置、CI/CD 工作流"
requirements: "Git 仓库，Godot 4.x，已安装 GUT 插件"
execution: "全自动执行，每个测试套件一次 git 提交"
integration: "godot-refactor 编排器的一部分，为提取的组件生成测试"
---

# 生成 Godot 测试

## 核心原则

**每个公开方法都应该被测试。** 测试证明你的代码能正常工作，并在重构时防止回归问题。

## 此技能的功能

为 Godot GDScript 代码生成全面的测试套件：
- 带有断言的公开方法单元测试
- Signal 连接和发射测试
- 场景初始化和生命周期测试
- 物理/处理循环行为测试
- 依赖项的 Mock 和 Stub 辅助工具
- GUT 框架配置
- 自动化测试的 CI/CD 集成

## 测试生成模式

### 公开方法的单元测试
```gdscript
# Tests for player.gd
extends GutTest

var player: Player

func before_each():
    player = Player.new()
    add_child_autofree(player)

func test_take_damage_reduces_health():
    player.health = 100
    player.take_damage(25)
    assert_eq(player.health, 75, "Health should decrease by damage amount")

func test_take_damage_does_not_go_below_zero():
    player.health = 10
    player.take_damage(25)
    assert_eq(player.health, 0, "Health should not go below zero")

func test_is_alive_returns_true_when_health_positive():
    player.health = 1
    assert_true(player.is_alive(), "Should be alive with positive health")

func test_is_alive_returns_false_when_health_zero():
    player.health = 0
    assert_false(player.is_alive(), "Should not be alive with zero health")
```

### Signal 连接测试
```gdscript
# Tests for signal connections and emissions
extends GutTest

var player: Player
var signal_received: bool = false
var signal_args: Array = []

func before_each():
    player = Player.new()
    add_child_autofree(player)
    signal_received = false
    signal_args.clear()

func _on_health_changed(new_health: int):
    signal_received = true
    signal_args.append(new_health)

func test_health_changed_signal_emitted_on_damage():
    player.health = 100
    player.health_changed.connect(_on_health_changed)
    player.take_damage(25)
    assert_true(signal_received, "health_changed signal should be emitted")
    assert_eq(signal_args[0], 75, "Signal should pass new health value")

func test_died_signal_emitted_when_health_reaches_zero():
    var died_received = false
    player.died.connect(func(): died_received = true)
    player.health = 10
    player.take_damage(10)
    assert_true(died_received, "died signal should be emitted when health reaches zero")
```

### 场景初始化测试
```gdscript
# Tests for scene setup and node references
extends GutTest

var player_scene: PackedScene
var player: Player

func before_all():
    player_scene = load("res://scenes/player.tscn")

func before_each():
    player = player_scene.instantiate()
    add_child_autofree(player)

func test_player_has_required_nodes():
    assert_not_null(player.get_node_or_null("Sprite2D"), "Player should have Sprite2D")
    assert_not_null(player.get_node_or_null("CollisionShape2D"), "Player should have CollisionShape2D")
    assert_not_null(player.get_node_or_null("AnimationPlayer"), "Player should have AnimationPlayer")

func test_player_initializes_with_correct_health():
    assert_eq(player.health, 100, "Health should initialize to 100")
    assert_eq(player.max_health, 100, "Max health should initialize to 100")

func test_player_animation_player_has_idle_animation():
    var anim_player = player.get_node("AnimationPlayer")
    assert_true(anim_player.has_animation("idle"), "Should have idle animation")
```

### 物理/处理循环测试
```gdscript
# Tests for _physics_process and _process behavior
extends GutTest

var player: Player

func before_each():
    player = Player.new()
    add_child_autofree(player)

func test_velocity_applies_gravity_in_physics_process():
    player.velocity = Vector2(0, 0)
    player.gravity = 980.0

    # Simulate one physics frame (at 60 FPS)
    var delta = 1.0 / 60.0
    player._physics_process(delta)

    assert_almost_eq(player.velocity.y, 980.0 * delta, 0.01, "Velocity should increase by gravity * delta")

func test_move_and_slide_is_called_in_physics_process():
    # Mock the move_and_slide method
    var move_and_slide_called = false
    player.move_and_slide = func() -> bool:
        move_and_slide_called = true
        return true

    player._physics_process(0.016)
    assert_true(move_and_slide_called, "move_and_slide should be called")
```

## GUT 框架配置

### 测试文件结构
```
project/
├── addons/
│   └── gut/
│       └── ...
├── tests/
│   ├── unit/
│   │   ├── test_player.gd
│   │   ├── test_enemy.gd
│   │   └── test_inventory.gd
│   ├── integration/
│   │   ├── test_combat_system.gd
│   │   └── test_save_load.gd
│   ├── mocks/
│   │   ├── mock_player.gd
│   │   └── mock_enemy.gd
│   └── test_runner.gd
└── .gutconfig.json
```

### GUT 配置
```json
{
  "dirs": ["res://tests/unit", "res://tests/integration"],
  "prefix": "test_",
  "suffix": ".gd",
  "ignore_subdirs": ["mocks"],
  "log_level": 2,
  "should_exit": true,
  "should_exit_on_success": true,
  "compact_mode": false,
  "double_strategy": "partial",
  "pre_run_script": "",
  "post_run_script": ""
}
```

### 常用 GUT 断言
```gdscript
# Equality
assert_eq(actual, expected, "message")
assert_ne(actual, expected, "message")
assert_almost_eq(actual, expected, 0.01, "message")

# Boolean
assert_true(condition, "message")
assert_false(condition, "message")

# Null/Not Null
assert_null(value, "message")
assert_not_null(value, "message")

# Type
assert_is_instance_of(object, Class, "message")
assert_is_not_instance_of(object, Class, "message")

# String
assert_string_contains(string, substring, "message")
assert_string_begins_with(string, prefix, "message")
assert_string_ends_with(string, suffix, "message")

# Signal
assert_signal_emitted(object, "signal_name", "message")
assert_signal_not_emitted(object, "signal_name", "message")
assert_signal_emitted_with_parameters(object, "signal_name", [arg1, arg2])

# File
assert_file_exists("res://path/to/file")
assert_file_does_not_exist("res://path/to/file")
```

## 测试模板

### 类测试模板
```gdscript
# tests/unit/test_{class_name}.gd
extends GutTest

var {class_instance}: {ClassName}

func before_all():
    # Runs once before all tests in this file
    pass

func before_each():
    # Runs before each test
    {class_instance} = {ClassName}.new()
    add_child_autofree({class_instance})

func after_each():
    # Runs after each test
    # Autofree handles cleanup
    pass

func after_all():
    # Runs once after all tests
    pass

# Test public methods
func test_{method_name}_{expected_behavior}():
    # Arrange
    {class_instance}.{setup_method}()

    # Act
    var result = {class_instance}.{method_name}()

    # Assert
    assert_eq(result, expected_value, "message")

# Test signals
func test_{signal_name}_emitted_when_{condition}():
    var signal_received = false
    {class_instance}.{signal_name}.connect(func(): signal_received = true)

    # Trigger condition
    {class_instance}.{trigger_method}()

    assert_true(signal_received, "message")
```

### Signal 测试模板
```gdscript
# Signal-specific tests
test_{signal_name}_connections:
  - Connects to {target_node} on ready
  - Emits with correct parameters
  - Disconnects on exit
  - Can be connected multiple times
  - Callback receives expected data
```

### 场景测试模板
```gdscript
# tests/unit/test_{scene_name}_scene.gd
extends GutTest

var {scene_name}_scene: PackedScene
var {scene_instance}: Node

func before_all():
    {scene_name}_scene = load("res://{path}/{scene_name}.tscn")
    assert_not_null({scene_name}_scene, "Scene should load successfully")

func before_each():
    {scene_instance} = {scene_name}_scene.instantiate()
    add_child_autofree({scene_instance})

func test_scene_has_required_children():
    # Verify node hierarchy
    assert_not_null({scene_instance}.get_node_or_null("{ChildNode}"), "Should have {ChildNode}")

func test_scene_initial_state():
    # Verify initial property values
    assert_eq({scene_instance}.{property}, {expected_value}, "Initial value should be correct")

func test_scene_ready_initializes_components():
    # Simulate ready
    await get_tree().process_frame

    # Verify initialization
    assert_true({scene_instance}.{component}.is_initialized, "Component should initialize on ready")
```

## Mock/Stub 生成

### Mock 类模板
```gdscript
# tests/mocks/mock_{class_name}.gd
class_name Mock{ClassName}
extends {BaseClass}

# Mock state tracking
var {method_name}_calls: Array = []
var {method_name}_return_value = null

func {method_name}(args):
    {method_name}_calls.append(args)
    return {method_name}_return_value

# Helper to configure return value
func set_{method_name}_return(value):
    {method_name}_return_value = value

# Helper to verify calls
func assert_{method_name}_called(times: int = 1):
    assert_eq({method_name}_calls.size(), times, "Expected {method_name} to be called {times} times")

func assert_{method_name}_called_with(args):
    var found = false
    for call in {method_name}_calls:
        if call == args:
            found = true
            break
    assert_true(found, "Expected {method_name} to be called with {args}")
```

### 依赖项的 Stub 辅助工具
```gdscript
# tests/mocks/stub_helpers.gd
class_name StubHelpers

static func stub_player() -> Player:
    var player = Player.new()
    player.health = 100
    player.max_health = 100
    player.speed = 200
    player.damage = 10
    return player

static func stub_enemy(enemy_type: String = "basic") -> Enemy:
    var enemy = Enemy.new()
    enemy.enemy_type = enemy_type
    match enemy_type:
        "basic":
            enemy.health = 50
            enemy.damage = 5
        "boss":
            enemy.health = 500
            enemy.damage = 25
    return enemy

static func stub_weapon(weapon_type: String) -> Weapon:
    var weapon = Weapon.new()
    weapon.weapon_type = weapon_type
    weapon.damage = _get_weapon_damage(weapon_type)
    return weapon

static func _get_weapon_damage(weapon_type: String) -> int:
    match weapon_type:
        "sword": return 15
        "bow": return 10
        "staff": return 20
        _: return 5
```

### 部分 Mock 的测试替身
```gdscript
# Using GUT's partial double for selective mocking
extends GutTest

var player: Player

func before_each():
    # Create partial double - only mock specific methods
    player = partial_double(Player).instantiate()
    add_child_autofree(player)

func test_player_uses_real_movement_but_mocked_combat():
    # Real movement
    player.velocity = Vector2(100, 0)
    player._physics_process(0.016)

    # Mocked combat - stub the take_damage method
    stub(player, "take_damage").to_return(false)

    # Test that combat uses stub
    var result = player.take_damage(100)
    assert_eq(result, false, "Should use stubbed return value")
```

## 转换示例

### 示例 1：玩家战斗类

**转换前（脚本）：**
```gdscript
# player.gd
class_name Player
extends CharacterBody2D

@export var health: int = 100
@export var max_health: int = 100
@export var damage: int = 10

signal health_changed(new_health: int)
signal died

func take_damage(amount: int) -> void:
    health = max(0, health - amount)
    health_changed.emit(health)
    if health == 0:
        died.emit()

func heal(amount: int) -> void:
    health = min(max_health, health + amount)
    health_changed.emit(health)

func is_alive() -> bool:
    return health > 0

func attack(target: Node) -> void:
    if target.has_method("take_damage"):
        target.take_damage(damage)
```

**转换后（测试文件）：**
```gdscript
# tests/unit/test_player.gd
extends GutTest

var player: Player

func before_each():
    player = Player.new()
    add_child_autofree(player)

func test_take_damage_reduces_health():
    player.health = 100
    player.take_damage(25)
    assert_eq(player.health, 75)

func test_take_damage_clamps_at_zero():
    player.health = 10
    player.take_damage(25)
    assert_eq(player.health, 0)

func test_heal_increases_health():
    player.health = 50
    player.heal(25)
    assert_eq(player.health, 75)

func test_heal_clamps_at_max_health():
    player.health = 90
    player.max_health = 100
    player.heal(25)
    assert_eq(player.health, 100)

func test_is_alive_true_with_health():
    player.health = 1
    assert_true(player.is_alive())

func test_is_alive_false_with_zero_health():
    player.health = 0
    assert_false(player.is_alive())

func test_health_changed_signal_emitted_on_damage():
    watch_signals(player)
    player.take_damage(25)
    assert_signal_emitted(player, "health_changed")

func test_died_signal_emitted_on_fatal_damage():
    watch_signals(player)
    player.health = 25
    player.take_damage(25)
    assert_signal_emitted(player, "died")

func test_attack_calls_take_damage_on_target():
    var mock_target = partial_double(CharacterBody2D).instantiate()
    add_child_autofree(mock_target)
    stub(mock_target, "take_damage").to_do_nothing()

    player.attack(mock_target)

    assert_called(mock_target, "take_damage")
```

### 示例 2：物品栏系统

**转换前（脚本）：**
```gdscript
# inventory.gd
class_name Inventory
extends Node

signal item_added(item: Item, slot: int)
signal item_removed(item: Item, slot: int)
signal inventory_full

const MAX_SLOTS = 20
var items: Array[Item] = []

func add_item(item: Item) -> bool:
    if items.size() >= MAX_SLOTS:
        inventory_full.emit()
        return false

    items.append(item)
    item_added.emit(item, items.size() - 1)
    return true

func remove_item(slot: int) -> Item:
    if slot < 0 or slot >= items.size():
        return null

    var item = items[slot]
    items.remove_at(slot)
    item_removed.emit(item, slot)
    return item

func has_item(item_name: String) -> bool:
    for item in items:
        if item.name == item_name:
            return true
    return false

func get_item_count() -> int:
    return items.size()

func is_full() -> bool:
    return items.size() >= MAX_SLOTS
```

**转换后（测试文件）：**
```gdscript
# tests/unit/test_inventory.gd
extends GutTest

var inventory: Inventory

func before_each():
    inventory = Inventory.new()
    add_child_autofree(inventory)

func test_add_item_returns_true_when_space_available():
    var item = Item.new()
    item.name = "Sword"
    assert_true(inventory.add_item(item))

func test_add_item_returns_false_when_full():
    # Fill inventory
    for i in range(Inventory.MAX_SLOTS):
        inventory.add_item(Item.new())

    var result = inventory.add_item(Item.new())
    assert_false(result)

func test_add_item_emits_item_added_signal():
    watch_signals(inventory)
    var item = Item.new()
    item.name = "Sword"

    inventory.add_item(item)

    assert_signal_emitted_with_parameters(inventory, "item_added", [item, 0])

func test_add_item_emits_inventory_full_when_no_space():
    watch_signals(inventory)
    for i in range(Inventory.MAX_SLOTS):
        inventory.add_item(Item.new())

    inventory.add_item(Item.new())
    assert_signal_emitted(inventory, "inventory_full")

func test_remove_item_returns_item_at_slot():
    var item = Item.new()
    item.name = "Sword"
    inventory.add_item(item)

    var removed = inventory.remove_item(0)
    assert_eq(removed, item)

func test_remove_item_returns_null_for_invalid_slot():
    assert_null(inventory.remove_item(-1))
    assert_null(inventory.remove_item(100))

func test_remove_item_emits_item_removed_signal():
    var item = Item.new()
    item.name = "Sword"
    inventory.add_item(item)
    watch_signals(inventory)

    inventory.remove_item(0)
    assert_signal_emitted_with_parameters(inventory, "item_removed", [item, 0])

func test_has_item_returns_true_when_item_present():
    var item = Item.new()
    item.name = "Sword"
    inventory.add_item(item)

    assert_true(inventory.has_item("Sword"))

func test_has_item_returns_false_when_item_not_present():
    assert_false(inventory.has_item("NonExistent"))

func test_get_item_count_returns_number_of_items():
    assert_eq(inventory.get_item_count(), 0)
    inventory.add_item(Item.new())
    assert_eq(inventory.get_item_count(), 1)
    inventory.add_item(Item.new())
    assert_eq(inventory.get_item_count(), 2)

func test_is_full_returns_true_at_capacity():
    for i in range(Inventory.MAX_SLOTS):
        inventory.add_item(Item.new())
    assert_true(inventory.is_full())

func test_is_full_returns_false_when_not_full():
    assert_false(inventory.is_full())
```

### 示例 3：集成测试 - 战斗系统

**集成测试：**
```gdscript
# tests/integration/test_combat_system.gd
extends GutTest

var player: Player
var enemy: Enemy
var combat_manager: CombatManager

func before_each():
    player = load("res://scenes/player.tscn").instantiate()
    enemy = load("res://scenes/enemy.tscn").instantiate()
    combat_manager = CombatManager.new()

    add_child_autofree(player)
    add_child_autofree(enemy)
    add_child_autofree(combat_manager)

    combat_manager.player = player
    combat_manager.enemy = enemy

func test_player_attack_damages_enemy():
    enemy.health = 100
    var initial_health = enemy.health

    player.attack(enemy)

    assert_lt(enemy.health, initial_health, "Enemy should take damage from player attack")

func test_enemy_death_emits_signal():
    watch_signals(enemy)
    enemy.health = 1

    player.attack(enemy)

    assert_signal_emitted(enemy, "died")

func test_combat_manager_tracks_damage_dealt():
    player.damage = 25
    enemy.health = 100

    combat_manager.initiate_combat()
    player.attack(enemy)

    assert_eq(combat_manager.damage_dealt, 25, "Combat manager should track damage dealt")

func test_combat_ends_when_enemy_dies():
    enemy.health = 1

    combat_manager.initiate_combat()
    player.attack(enemy)

    assert_true(combat_manager.is_combat_ended, "Combat should end when enemy dies")
```

## CI/CD 集成

### GitHub Actions 工作流
```yaml
# .github/workflows/godot-tests.yml
name: Godot Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Godot
        uses: chickensoft-games/setup-godot@v1
        with:
          version: 4.2.1
          use-dotnet: false

      - name: Install GUT
        run: |
          git clone https://github.com/bitwes/Gut.git addons/gut
          # Or use your project's specific GUT version

      - name: Run Tests
        run: |
          godot --headless --script addons/gut/gut_cmdln.gd -gexit

      - name: Upload Test Results
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: test-results
          path: gut_logs/
```

### GitLab CI 配置
```yaml
# .gitlab-ci.yml
test:godot:
  image: barichello/godot-ci:4.2.1
  script:
    - git clone https://github.com/bitwes/Gut.git addons/gut
    - godot --headless --script addons/gut/gut_cmdln.gd -gexit
  artifacts:
    when: always
    paths:
      - gut_logs/
    expire_in: 1 week
```

### 测试运行器脚本
```gdscript
# tests/test_runner.gd
extends SceneTree

func _init():
    var gut = load("res://addons/gut/gut.gd").new()
    gut.connect("tests_finished", _on_tests_finished)

    # Configure from .gutconfig.json
    var config = _load_config()

    for dir in config.dirs:
        gut.add_directory(dir)

    gut.set_yield_between_tests(true)
    gut.set_exit_on_success(config.should_exit_on_success)

    root.add_child(gut)
    gut.test_scripts()

func _on_tests_finished():
    quit()

func _load_config() -> Dictionary:
    var file = FileAccess.open("res://.gutconfig.json", FileAccess.READ)
    if file:
        return JSON.parse_string(file.get_as_text())
    return {}
```

## 使用时机

### 你正在添加新功能
在编写新代码的同时生成测试以确保正确性。

### 你正在重构遗留代码
在重构前创建测试以验证行为不变。

### 你需要对修改有信心
全面的测试套件防止回归问题。

### 你正在配置 CI/CD
自动化测试确保每次提交的代码质量。

### 你在实践 TDD
生成测试模板以加速红-绿-重构循环。

## 不应使用的情况

### 原型/一次性代码
不要为即将重写的代码编写测试。

### 简单的 Setter/Getter
测试简单的属性访问只增加噪音而无价值。

### 仅编辑器工具
只在编辑器中运行的代码不需要运行时测试。

### 纯视觉/美术代码
纯粹的视觉变更最好手动测试。

## 安全性

- 生成的测试是起点 - 请审查并定制
- 测试包含解释预期行为的注释
- 边界情况通过具体的测试用例记录
- 如果测试破坏了现有代码，可自动回滚
- git 提交跟踪测试文件生成

## 集成

可与以下技能配合使用：
- **godot-extract-to-scenes** - 为提取的组件生成测试
- **godot-split-scripts** - 为每个拆分的模块创建测试
- **godot-refactor**（编排器）- 重构后进行全面测试
- **godot-add-signals** - 测试 Signal 连接和发射

## 流程

1. **扫描** - 查找项目中所有 .gd 文件
2. **分析** - 识别公开方法、Signal 和节点引用
3. **生成** - 使用 GUT 框架结构创建测试文件
4. **Mock** - 为依赖项生成 Stub 辅助工具
5. **配置** - 创建 .gutconfig.json 和 CI/CD 工作流
6. **提交** - 包含测试套件的 git 提交

## 生成的结构

```
tests/
├── unit/
│   ├── test_{class1}.gd      # 每个类的单元测试
│   ├── test_{class2}.gd
│   └── ...
├── integration/
│   ├── test_{system1}.gd     # 集成测试套件
│   └── ...
├── mocks/
│   ├── mock_{class1}.gd      # Mock 实现
│   ├── stub_helpers.gd       # 测试夹具工具
│   └── ...
├── scenes/
│   ├── test_{scene1}.gd      # 场景实例化测试
│   └── ...
└── test_runner.gd            # 命令行测试运行器
```
