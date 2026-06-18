# Godot Refactoring Skill - Examples

This file demonstrates how the skill would be invoked and what outputs to expect.

---

## Example 1: Simple Timer Refactoring

### Before

**laser_beam.gd (with anti-pattern):**
```gdscript
extends Node2D

var _damage_tick_timer: Timer
var damage_tick_seconds: float = 0.5

func _ready():
    _setup_damage_timer()

func _setup_damage_timer() -> void:
    _damage_tick_timer = Timer.new()
    _damage_tick_timer.wait_time = damage_tick_seconds
    _damage_tick_timer.one_shot = false
    _damage_tick_timer.autostart = false
    add_child(_damage_tick_timer)
    _damage_tick_timer.timeout.connect(_on_damage_tick)

func _on_damage_tick():
    # Apply damage logic
    pass
```

### Skill Invocation

User says: "Refactor this Godot project to use scene-first architecture"

Skill automatically:
1. Detects Timer.new() anti-pattern
2. Generates laser_beam_damage_timer.tscn
3. Updates laser_beam.gd
4. Commits changes

### After

**laser_beam_damage_timer.tscn (generated):**
```ini
[gd_scene format=3]

[node name="DamageTimer" type="Timer"]
one_shot = false
autostart = false
```

**laser_beam.gd (refactored):**
```gdscript
extends Node2D

@onready var _damage_tick_timer: Timer = $DamageTimer
var damage_tick_seconds: float = 0.5

func _ready():
    _damage_tick_timer.wait_time = damage_tick_seconds
    _damage_tick_timer.timeout.connect(_on_damage_tick)

func _on_damage_tick():
    # Apply damage logic
    pass
```

**Git commit:**
```
commit abc123
Refactor: Extract Timer to scene in laser_beam.gd

- Created laser_beam_damage_timer.tscn with Timer node
- Updated laser_beam.gd to use @onready reference
- Removed Timer.new() and add_child() code
- Preserved signal connections and dynamic properties
```

**Outcome:**
- ✓ 7 lines removed
- ✓ Scene-first pattern established
- ✓ Behavior unchanged
- ✓ Timer visible in editor scene tree

---

## Example 2: Signal Decoupling

### Before

**base_station.gd (with tight coupling):**
```gdscript
extends Area2D

func _on_body_entered(body):
    if body.has_method("set_beam_enabled"):
        body.set_beam_enabled(false)

func _on_body_exited(body):
    if body.has_method("set_beam_enabled"):
        body.set_beam_enabled(true)
```

**player_movement.gd:**
```gdscript
extends CharacterBody2D

var _beam_active: bool = true

func set_beam_enabled(enabled: bool):
    _beam_active = enabled
```

### Skill Invocation

Skill detects `has_method()` anti-pattern and automatically:
1. Creates/updates events.gd
2. Refactors base_station.gd to emit signals
3. Refactors player_movement.gd to listen for signals

### After

**events.gd (created/updated):**
```gdscript
extends Node

# Safe zone signals
signal player_entered_safe_zone(zone: Node2D)
signal player_exited_safe_zone(zone: Node2D)
```

**base_station.gd (refactored):**
```gdscript
extends Area2D

func _on_body_entered(body):
    if body.is_in_group("player"):
        Events.player_entered_safe_zone.emit(self)

func _on_body_exited(body):
    if body.is_in_group("player"):
        Events.player_exited_safe_zone.emit(self)
```

**player_movement.gd (refactored):**
```gdscript
extends CharacterBody2D

var _beam_active: bool = true

func _ready():
    Events.player_entered_safe_zone.connect(_on_safe_zone_entered)
    Events.player_exited_safe_zone.connect(_on_safe_zone_exited)

func _on_safe_zone_entered(zone: Node2D):
    _beam_active = false

func _on_safe_zone_exited(zone: Node2D):
    _beam_active = true
```

**Git commit:**
```
commit def456
Refactor: Decouple base_station from player via signals

- Added player_entered/exited_safe_zone signals to Events
- Updated base_station to emit signals instead of direct calls
- Updated player to listen for safe zone signals
- Removed has_method check and direct dependency
```

**Outcome:**
- ✓ Zero coupling between base_station and player
- ✓ is_in_group() used instead of has_method()
- ✓ Events.gd provides clear signal contract
- ✓ Easy to add more safe zone listeners

---

## Example 3: Monolithic Script Split

### Before

**player_movement.gd (287 lines - too large!):**
```gdscript
extends CharacterBody2D

# Input handling (45 lines)
var _input_direction: Vector2

func _get_input():
    # ... input code ...
    pass

# Physics movement (53 lines)
@export var speed: float = 300.0
@export var acceleration: float = 1500.0

func _physics_process(delta):
    # ... movement code ...
    pass

# Ability system (58 lines)
var _dash_ready: bool = true
var _jump_ready: bool = true

func _activate_dash():
    # ... dash code ...
    pass

func _activate_jump():
    # ... jump code ...
    pass

# Health management (54 lines)
var current_health: int = 100
var max_health: int = 100

func take_damage(amount: int):
    # ... health code ...
    pass

# UI updates (77 lines)
@onready var health_bar = $UI/HealthBar

func _update_ui():
    # ... UI code ...
    pass
```

### Skill Invocation

Skill detects 287 lines and automatically:
1. Analyzes script structure
2. Identifies 4 distinct responsibilities
3. Creates 3 component scripts
4. Implements signal communication
5. Updates main script

### After

**player_movement.gd (98 lines - focused!):**
```gdscript
extends CharacterBody2D

@onready var abilities: PlayerAbilities = $Abilities
@onready var health: PlayerHealth = $Health
@onready var ui: PlayerUI = $UI

@export var speed: float = 300.0
@export var acceleration: float = 1500.0

var _input_direction: Vector2

func _ready():
    health.died.connect(_on_death)
    abilities.dash_activated.connect(_on_dash)

func _get_input():
    _input_direction = Input.get_vector("left", "right", "up", "down")

func _physics_process(delta):
    _get_input()
    velocity = velocity.move_toward(_input_direction * speed, acceleration * delta)
    move_and_slide()

func _on_dash(dash_velocity: Vector2):
    velocity = dash_velocity

func _on_death():
    set_physics_process(false)
```

**player_abilities.gd (58 lines - component):**
```gdscript
extends Node
class_name PlayerAbilities

signal dash_activated(dash_velocity: Vector2)
signal jump_activated

@export var dash_cooldown: float = 2.0
@export var dash_speed: float = 500.0

var _dash_ready: bool = true

func _input(event):
    if event.is_action_pressed("dash") and _dash_ready:
        _activate_dash()

func _activate_dash():
    var direction = Input.get_vector("left", "right", "up", "down")
    dash_activated.emit(direction * dash_speed)
    _dash_ready = false

    await get_tree().create_timer(dash_cooldown).timeout
    _dash_ready = true
```

**player_health.gd (54 lines - component):**
```gdscript
extends Node
class_name PlayerHealth

signal health_changed(current: int, max: int)
signal damage_taken(amount: int)
signal died

@export var max_health: int = 100

var current_health: int:
    set(value):
        var old = current_health
        current_health = clampi(value, 0, max_health)
        if current_health != old:
            health_changed.emit(current_health, max_health)
            if current_health == 0:
                died.emit()

func _ready():
    current_health = max_health

func take_damage(amount: int):
    damage_taken.emit(amount)
    current_health -= amount
```

**player_ui.gd (77 lines - component):**
```gdscript
extends Node
class_name PlayerUI

@onready var health_bar = get_node("/root/Main/UI/HealthBar")
@onready var ability_cooldowns = get_node("/root/Main/UI/Abilities")

func _ready():
    get_parent().health.health_changed.connect(_on_health_changed)

func _on_health_changed(current: int, max: int):
    health_bar.value = float(current) / max
```

**Git commit:**
```
commit ghi789
Refactor: Split player_movement.gd into components (287→98 lines)

- Extracted PlayerAbilities component (58 lines)
- Extracted PlayerHealth component (54 lines)
- Extracted PlayerUI component (77 lines)
- Implemented signal-based communication
- Main script now focused on input + physics only
```

**Outcome:**
- ✓ 66% reduction in main script size (287 → 98)
- ✓ 4 focused, reusable components
- ✓ Signal-based architecture
- ✓ Each component <150 lines
- ✓ Components can be reused for enemies, NPCs, etc.

---

## Example 4: Data Extraction to Resources

### Before

**enemy_spawner.gd (with inline data):**
```gdscript
extends Node2D

const ENEMY_TYPES = [
    {"type": "basic", "health": 100, "speed": 200, "score": 10},
    {"type": "fast", "health": 50, "speed": 400, "score": 20},
    {"type": "tank", "health": 300, "speed": 100, "score": 30}
]

func _spawn_enemy():
    var data = ENEMY_TYPES[randi() % ENEMY_TYPES.size()]
    var enemy = preload("res://enemy.tscn").instantiate()
    enemy.health = data["health"]
    enemy.speed = data["speed"]
    enemy.score_value = data["score"]
    add_child(enemy)
```

### Skill Invocation

Skill detects const array and automatically:
1. Creates EnemyTypeData resource class
2. Generates 3 .tres files
3. Updates enemy_spawner.gd to use resources

### After

**enemy_type_data.gd (created):**
```gdscript
extends Resource
class_name EnemyTypeData

@export var type_name: String = ""
@export var health: int = 100
@export var speed: float = 200.0
@export var score_value: int = 10
@export var enemy_scene: PackedScene
```

**data/enemy_types/basic.tres (generated):**
```ini
[gd_resource type="EnemyTypeData" load_steps=3 format=3]

[ext_resource type="Script" path="res://enemy_type_data.gd" id="1"]
[ext_resource type="PackedScene" path="res://enemies/basic_enemy.tscn" id="2"]

[resource]
script = ExtResource("1")
type_name = "basic"
health = 100
speed = 200.0
score_value = 10
enemy_scene = ExtResource("2")
```

**enemy_spawner.gd (refactored):**
```gdscript
extends Node2D

@export var enemy_types: Array[EnemyTypeData] = []

func _spawn_enemy():
    var data = enemy_types[randi() % enemy_types.size()]
    var enemy = data.enemy_scene.instantiate()
    enemy.health = data.health
    enemy.speed = data.speed
    enemy.score_value = data.score_value
    add_child(enemy)
```

**Git commit:**
```
commit jkl012
Refactor: Extract enemy data to .tres resources

- Created EnemyTypeData Resource class
- Generated basic.tres, fast.tres, tank.tres
- Updated enemy_spawner to use Resource array
- Removed inline ENEMY_TYPES const
- Data now editable in Inspector
```

**Outcome:**
- ✓ Data separated from code
- ✓ Editable in Godot Inspector (no code changes needed)
- ✓ Type-safe Resource class
- ✓ Each enemy type is a reusable asset
- ✓ Easy to add new enemy types (just create .tres file)

---

## Example 5: Full Project Refactoring

### Project: Space Shooter Game

**Before (Detection Phase):**

```
Scanning Godot project: ./space-shooter

Anti-patterns detected:
- Code-created objects: 8
  - laser_beam.gd: Timer (line 38)
  - enemy.gd: Area2D (line 45)
  - player.gd: Timer x2 (lines 67, 89)
  - bullet.gd: Timer (line 23)
  - powerup.gd: Area2D (line 34)
  - ui_manager.gd: Label (line 56)

- Monolithic scripts: 2
  - player_movement.gd (287 lines)
  - game_manager.gd (203 lines)

- Tight coupling: 5
  - base_station.gd: has_method check (line 92)
  - enemy.gd: get_node to player (line 78)
  - powerup.gd: get_parent access (line 45)
  - ui_manager.gd: get_tree access (line 34)
  - bullet.gd: has_method check (line 67)

- Inline data: 2
  - enemy_spawner.gd: ENEMY_TYPES const (lines 12-16)
  - powerup_spawner.gd: POWERUP_DATA const (lines 8-14)

Total: 17 anti-patterns
```

### Refactoring Progress

```
Phase 1: Analysis & Baseline ✓
- Working on current branch: main
- Tagged baseline: baseline-20260202-032300
- Generated manifest with 17 operations

Phase 2: Automatic Refactoring
Operation D (Data): 2/2 complete ✓
- Extracted EnemyTypeData → 3 .tres files
- Extracted PowerupData → 4 .tres files

Operation A (Scenes): 8/8 complete ✓
- Created 8 .tscn scene files
- Updated 6 .gd scripts

Operation C (Signals): 5/5 complete ✓
- Created events.gd with 8 signals
- Updated 5 coupled scripts

Operation B (Scripts): 2/2 complete ✓
- Split player_movement.gd → 4 components
- Split game_manager.gd → 3 components

Phase 3: Git Commits ✓
- 17 commits created
- Tagged: refactor-complete-20260202

Phase 4: Verification ✓
- Visual check: PASS
- Functional check: PASS
- Performance: 60 FPS → 60 FPS (0 Δ)
- Console: 0 new errors
```

### After (Results)

```
Refactoring Report

Summary:
- Duration: ~3 hours (automatic)
- Operations: 17
- Files modified: 12
- Files created: 15 (.tscn + .tres + components)
- Lines reduced: 485 (31%)

Metrics Before:
- Scripts: 18
- Avg size: 148 lines
- Code-created nodes: 8
- Couplings: 5
- Inline data: 2

Metrics After:
- Scripts: 28 (+10 components)
- Avg size: 89 lines
- Code-created nodes: 0 ✓
- Couplings: 0 ✓
- Inline data: 0 ✓

Verification: ✓ ALL PASS
- Zero functional changes
- Zero visual changes
- Performance unchanged
- All anti-patterns eliminated
```

---

## Example 6: Modular Component Library Building

### Scenario: Progressive Timer Extraction

**Step 1: First Timer Detection**

Code being refactored:
```gdscript
# enemy_ai.gd
func _ready():
    _attack_timer = Timer.new()
    _attack_timer.wait_time = 2.0
    _attack_timer.one_shot = false
    add_child(_attack_timer)
    _attack_timer.timeout.connect(_on_attack)
```

**Intelligent Selection:**
- Variable: "_attack_timer" → +30%
- Properties: wait_time, one_shot → +40%
- Methods: .timeout.connect() → +35%
- Total: 95% confidence → **AUTO-SELECT Timer**

**Component Generation:**
```
✓ Created components/timers/timer_config.gd (resource class)
✓ Created components/timers/configurable_timer.gd (configurable script)
✓ Created components/timers/configurable_timer.tscn (base scene)
✓ Created components/timers/presets/attack_timer.tres (configuration)
✓ Updated enemy_ai.tscn to instance component with preset
✓ Updated enemy_ai.gd with @onready reference
```

**Result:**
```
components/
└─ timers/
   ├─ configurable_timer.tscn (1 reusable base)
   ├─ configurable_timer.gd
   ├─ timer_config.gd
   └─ presets/
      └─ attack_timer.tres
```

**Updated enemy_ai.gd:**
```gdscript
@onready var _attack_timer: ConfigurableTimer = $AttackTimer

func _ready():
    _attack_timer.timeout.connect(_on_attack)
```

**Updated enemy_ai.tscn:**
```ini
[gd_scene load_steps=2 format=3]

[ext_resource type="PackedScene" path="res://components/timers/configurable_timer.tscn" id="1"]
[ext_resource type="Resource" path="res://components/timers/presets/attack_timer.tres" id="2"]

[node name="Enemy" type="CharacterBody2D"]

[node name="AttackTimer" parent="." instance=ExtResource("1")]
config = ExtResource("2")
```

---

### Step 2: Second Timer Detection (Same Project)

Code being refactored:
```gdscript
# player.gd
func _ready():
    _dash_cooldown = Timer.new()
    _dash_cooldown.wait_time = 1.5
    _dash_cooldown.one_shot = true
    add_child(_dash_cooldown)
    _dash_cooldown.timeout.connect(_on_dash_ready)
```

**Intelligent Selection:**
- Same pattern → **Timer** at 95% confidence

**Component Check:**
- `components/timers/` exists? **YES** ✓
- Reuse existing base: configurable_timer.tscn ✓
- Skip base generation (save time) ✓

**Component Generation:**
```
✗ Skipped: timer_config.gd (already exists)
✗ Skipped: configurable_timer.gd (already exists)
✗ Skipped: configurable_timer.tscn (already exists)
✓ Created components/timers/presets/dash_cooldown.tres (NEW preset only!)
✓ Updated player.tscn to instance same component with NEW preset
✓ Updated player.gd with @onready reference
```

**Result:**
```
components/
└─ timers/
   ├─ configurable_timer.tscn (1 reusable base)
   ├─ configurable_timer.gd
   ├─ timer_config.gd
   └─ presets/
      ├─ attack_timer.tres (from Step 1)
      └─ dash_cooldown.tres (NEW - from Step 2)

ZERO scene duplication!
Same base, different presets.
```

**Updated player.gd:**
```gdscript
@onready var _dash_cooldown: ConfigurableTimer = $DashCooldown

func _ready():
    _dash_cooldown.timeout.connect(_on_dash_ready)
```

---

### Step 3: Third Timer Detection (Another Team Member's Code)

Code being refactored:
```gdscript
# boss.gd
func _ready():
    _phase_timer = Timer.new()
    _phase_timer.wait_time = 5.0
    _phase_timer.one_shot = true
    add_child(_phase_timer)
    _phase_timer.timeout.connect(_on_phase_change)
```

**Component Check:**
- `components/timers/` exists? **YES** ✓
- Reuse existing base: configurable_timer.tscn ✓

**Component Generation:**
```
✓ Created components/timers/presets/phase_timer.tres (NEW preset only!)
✓ Updated boss.tscn
✓ Updated boss.gd
```

**Final Component Library:**
```
components/
└─ timers/
   ├─ configurable_timer.tscn (1 base, reused 3 times)
   ├─ configurable_timer.gd
   ├─ timer_config.gd
   └─ presets/
      ├─ attack_timer.tres (enemy_ai.gd)
      ├─ dash_cooldown.tres (player.gd)
      └─ phase_timer.tres (boss.gd)

Statistics:
- Base scenes: 1
- Usage count: 3
- Duplicate scenes: 0 ✓
- Presets: 3
- Code reduction: 70%+
```

---

### Step 4: Fourth Detection - Different Node Type (Area2D)

Code being refactored:
```gdscript
# bullet.gd
func _ready():
    _hitbox = Area2D.new()
    add_child(_hitbox)

    var shape = CircleShape2D.new()
    shape.radius = 10.0

    var collision = CollisionShape2D.new()
    collision.shape = shape
    _hitbox.add_child(collision)

    _hitbox.body_entered.connect(_on_hit)
```

**Intelligent Selection:**
- Variable: "_hitbox" → +25%
- Methods: .body_entered.connect() → +35%
- get_overlapping_bodies pattern? No
- Decision tree: Detection area → **Area2D** at 85% confidence

**Component Check:**
- `components/areas/` exists? **NO**
- Generate full component structure

**Component Generation:**
```
✓ Created components/areas/area2d_config.gd (resource class)
✓ Created components/areas/configurable_area.gd (configurable script)
✓ Created components/areas/configurable_area.tscn (base scene with collision child)
✓ Created components/areas/presets/bullet_hitbox.tres (configuration)
✓ Updated bullet.tscn
✓ Updated bullet.gd
```

**Final Library State:**
```
components/
├─ timers/
│  ├─ configurable_timer.tscn (3 presets)
│  ├─ configurable_timer.gd
│  ├─ timer_config.gd
│  └─ presets/ (3 files)
└─ areas/ (NEW CATEGORY)
   ├─ configurable_area.tscn (1 preset)
   ├─ configurable_area.gd
   ├─ area2d_config.gd
   └─ presets/
      └─ bullet_hitbox.tres

Component library auto-organized!
Growing as we refactor.
```

---

## How to Use These Examples

1. **Find similar pattern** in your codebase
2. **Invoke godot-refactoring skill**
3. **Skill automatically detects** anti-patterns
4. **Review manifest**, approve refactoring
5. **Skill executes** all operations with commits
6. **Verify results** match expectations
7. **Merge or continue** development on clean code

The skill handles all the tedious work automatically while preserving exact behavior.
