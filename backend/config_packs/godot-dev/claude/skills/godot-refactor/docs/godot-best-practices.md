# Godot Best Practices Reference

Complete guide to clean Godot architecture patterns used in refactoring.

---

## Core Principles

1. **Scene-First Design**: Everything starts as a scene, code enhances it
2. **Signal-Based Communication**: Decouple via events, not direct calls
3. **Component Composition**: Build complex from simple, avoid deep inheritance
4. **Resource-Based Data**: Separate data from logic, use .tres files
5. **Single Responsibility**: Each script does one thing well

---

## Scene-First Design

### The Pattern

**Start with scenes, not code:**

```
1. Create .tscn file with nodes
2. Attach script to configure behavior
3. Compose scenes into larger scenes
4. Use code for logic, not structure
```

### Good Example

**player.tscn:**
```ini
[node name="Player" type="CharacterBody2D"]

[node name="Sprite2D" type="Sprite2D" parent="."]

[node name="CollisionShape2D" type="CollisionShape2D" parent="."]

[node name="AbilitySystem" type="Node" parent="."]

[node name="HealthComponent" type="Node" parent="."]
```

**player.gd:**
```gdscript
extends CharacterBody2D

@onready var abilities = $AbilitySystem
@onready var health = $HealthComponent

func _ready():
    health.depleted.connect(_on_death)
```

### Bad Example

```gdscript
# Creating structure in code
func _ready():
    var sprite = Sprite2D.new()
    add_child(sprite)

    var collision = CollisionShape2D.new()
    add_child(collision)

    var abilities = Node.new()
    add_child(abilities)
```

**Why it's bad:**
- Can't see structure in editor
- Hard to modify visually
- No inspector for properties
- Harder to debug

---

## Signal-Based Communication

### The Pattern

**Components communicate via signals, never direct calls:**

```
Component A emits signal → Event Bus → Component B receives signal
```

### Event Bus (Autoload)

**events.gd:**
```gdscript
extends Node
# Global event bus for cross-tree communication

# Player events
signal player_died
signal player_respawned(position: Vector2)
signal health_changed(current: int, max: int)

# Enemy events
signal enemy_spawned(enemy: Node2D)
signal enemy_killed(enemy: Node2D, score: int)

# Game events
signal score_updated(new_score: int)
signal level_completed(level: int)
signal game_paused
signal game_resumed
```

**Add to autoload:** Project → Project Settings → Autoload → Add `events.gd` as `Events`

### Good Example: Decoupled Communication

**enemy.gd (emitter):**
```gdscript
func _die():
    Events.enemy_killed.emit(self, score_value)
    queue_free()
```

**score_manager.gd (receiver):**
```gdscript
func _ready():
    Events.enemy_killed.connect(_on_enemy_killed)

func _on_enemy_killed(enemy: Node2D, score: int):
    current_score += score
    Events.score_updated.emit(current_score)
```

**ui_score_label.gd (receiver):**
```gdscript
func _ready():
    Events.score_updated.connect(_on_score_updated)

func _on_score_updated(new_score: int):
    text = "Score: %d" % new_score
```

**Benefits:**
- Enemy doesn't know about scoring system
- Score manager doesn't know about UI
- Easy to add new score listeners
- No import cycles

### Bad Example: Direct Coupling

```gdscript
# enemy.gd
func _die():
    var score_mgr = get_node("/root/ScoreManager")
    score_mgr.add_score(score_value)

    var ui = get_tree().get_first_node_in_group("ui")
    if ui.has_method("update_score"):
        ui.update_score()

    queue_free()
```

**Why it's bad:**
- Enemy knows too much about game structure
- Fragile to node path changes
- Hard to test in isolation
- Tight coupling

### Local vs Global Signals

**Use local signals** for parent-child communication:
```gdscript
# health_component.gd
signal health_changed(new_health: int)
signal depleted

# player.gd
func _ready():
    $HealthComponent.depleted.connect(_on_death)
```

**Use Events (global)** for cross-tree communication:
```gdscript
# player.gd
func _on_death():
    Events.player_died.emit()

# game_manager.gd
func _ready():
    Events.player_died.connect(_on_player_died)
```

---

## Component Composition

### The Pattern

**Build complex behaviors from simple components:**

```
Player (Node2D)
├─ Sprite2D
├─ CollisionShape2D
├─ MovementComponent (script)
├─ HealthComponent (script)
├─ AbilityComponent (script)
└─ InputComponent (script)
```

### Component Example

**health_component.gd:**
```gdscript
extends Node
class_name HealthComponent

signal health_changed(current: int, max: int)
signal damage_taken(amount: int)
signal depleted

@export var max_health: int = 100

var current_health: int:
    set(value):
        var old = current_health
        current_health = clampi(value, 0, max_health)
        if current_health != old:
            health_changed.emit(current_health, max_health)
            if current_health == 0:
                depleted.emit()

func _ready():
    current_health = max_health

func take_damage(amount: int) -> void:
    damage_taken.emit(amount)
    current_health -= amount

func heal(amount: int) -> void:
    current_health += amount
```

**Using the component:**
```gdscript
# player.gd
@onready var health = $HealthComponent

func _ready():
    health.depleted.connect(_on_death)
    health.damage_taken.connect(_on_damage)

func _on_collision(damage: int):
    health.take_damage(damage)
```

### Benefits

- Reusable across entities (player, enemies, destructibles)
- Easy to test in isolation
- Single responsibility (only handles health)
- Composable (add/remove without affecting others)

### Component Guidelines

**Each component should:**
- Extend `Node` (not a visual type)
- Have `class_name` for easy reference
- Use `@export` for configuration
- Emit signals for state changes
- Have focused responsibility (one thing)

**Script size:**
- 80-120 lines optimal
- Max 150 lines before splitting
- If >5 unrelated functions, consider splitting

---

## Resource-Based Data

### The Pattern

**Separate data from logic using Resource classes:**

```
Data (.tres) ←→ Resource class (.gd) ←→ Game logic (.gd)
```

### Resource Class Example

**weapon_data.gd:**
```gdscript
extends Resource
class_name WeaponData

@export var weapon_name: String
@export var damage: int
@export var fire_rate: float
@export var projectile_scene: PackedScene
@export var icon: Texture2D
```

**Create .tres files:**

**weapons/laser.tres:**
```gdscript
# (Create via Godot editor: Inspector → New Resource → WeaponData)
# Or manually:
```
```ini
[gd_resource type="WeaponData" load_steps=3 format=3]

[ext_resource type="Script" path="res://weapon_data.gd" id="1"]
[ext_resource type="PackedScene" path="res://projectiles/laser_bolt.tscn" id="2"]

[resource]
script = ExtResource("1")
weapon_name = "Laser"
damage = 10
fire_rate = 0.5
projectile_scene = ExtResource("2")
```

**Using in code:**

**weapon_system.gd:**
```gdscript
@export var weapon_data: WeaponData

func _ready():
    print("Using weapon: ", weapon_data.weapon_name)

func _fire():
    var projectile = weapon_data.projectile_scene.instantiate()
    projectile.damage = weapon_data.damage
    get_tree().current_scene.add_child(projectile)
```

### Benefits

- Data editable in inspector
- Share data across scenes
- Easy to balance (no code changes)
- Version control friendly
- Support for inheritance (base weapon → variants)

### Resource vs Const

**Use Resource when:**
- Data is complex (multiple fields)
- Data changes during development
- Want inspector editing
- Need asset references (scenes, textures)

**Use const when:**
- Simple single values
- Truly constant (GRAVITY, MAX_SPEED)
- Used as enums

```gdscript
# Good const usage
const GRAVITY = 980.0
const States = ["IDLE", "RUNNING", "JUMPING"]

# Bad const usage (should be Resource)
const ENEMY_TYPES = [
    {"name": "Basic", "health": 100, "speed": 200},
    {"name": "Fast", "health": 50, "speed": 400}
]
```

---

## Single Responsibility Principle

### The Pattern

**Each script has one clear job:**

```
player_movement.gd → Only handles movement physics
player_abilities.gd → Only handles ability activation
player_input.gd → Only handles input reading
player_animation.gd → Only handles animation state
```

### Good Example: Focused Scripts

**player_movement.gd (95 lines):**
```gdscript
extends CharacterBody2D
class_name PlayerMovement

signal movement_state_changed(state: String)

@export var speed: float = 300.0
@export var acceleration: float = 1500.0

var movement_enabled: bool = true

func _physics_process(delta):
    if not movement_enabled:
        return

    var direction = Input.get_vector("left", "right", "up", "down")
    velocity = velocity.move_toward(direction * speed, acceleration * delta)
    move_and_slide()

    _update_state()

func _update_state():
    if velocity.length() > 10:
        movement_state_changed.emit("moving")
    else:
        movement_state_changed.emit("idle")

func enable_movement(enabled: bool):
    movement_enabled = enabled
```

**player_abilities.gd (87 lines):**
```gdscript
extends Node
class_name PlayerAbilities

signal ability_activated(ability_name: String)
signal cooldown_started(ability: String, duration: float)

@export var dash_cooldown: float = 2.0
@export var dash_distance: float = 200.0

var _dash_ready: bool = true

func _input(event):
    if event.is_action_pressed("dash") and _dash_ready:
        _activate_dash()

func _activate_dash():
    ability_activated.emit("dash")
    _dash_ready = false
    Events.player_dashed.emit(dash_distance)

    await get_tree().create_timer(dash_cooldown).timeout
    _dash_ready = true
```

### Bad Example: God Object

**player.gd (423 lines):**
```gdscript
# Handles movement, abilities, health, input, animation, inventory, quests...
# TOO MANY RESPONSIBILITIES
```

### When to Split

**Split a script when:**
- >150 lines
- >3 distinct responsibilities
- >5 signals defined
- Multiple comment section headers
- Hard to name (doing too much)

**How to split:**
1. Identify logical groups of functions
2. Create component scripts
3. Define signal interfaces
4. Move code to components
5. Connect signals in main script

---

## Naming Conventions

### Files

```
snake_case.gd       # Scripts
snake_case.tscn     # Scenes
snake_case.tres     # Resources
PascalCase (dir)    # Folders for organization
```

### Classes

```gdscript
class_name PlayerMovement  # PascalCase
class_name EnemySpawner
class_name WeaponData
```

### Variables

```gdscript
var player_speed: float       # snake_case
var _private_var: int         # Prefix with _ for private
@onready var _timer: Timer    # Always type hint @onready
@export var max_health: int   # snake_case for exports
```

### Functions

```gdscript
func move_character():         # snake_case
func _on_timer_timeout():      # Callbacks prefixed with _on_
func _private_helper():        # Private functions prefixed with _
```

### Signals

```gdscript
signal health_changed          # snake_case
signal ability_activated       # Past tense for events
signal enemy_spawned           # Not "enemy_spawn"
```

### Constants

```gdscript
const MAX_SPEED = 400.0        # SCREAMING_SNAKE_CASE
const GRAVITY = 980.0
```

---

## @onready Best Practices

### The Pattern

**Use @onready for all node references:**

```gdscript
@onready var sprite: Sprite2D = $Sprite2D
@onready var health: HealthComponent = $HealthComponent
@onready var timer: Timer = $AbilityTimer
```

### Good Practices

```gdscript
# Always type hint
@onready var _timer: Timer = $Timer

# Private if only used internally
@onready var _sprite: Sprite2D = $Sprite2D

# Group at top of script
@onready var health = $HealthComponent
@onready var movement = $MovementComponent
@onready var abilities = $AbilityComponent
```

### Bad Practices

```gdscript
# No type hint
@onready var timer = $Timer

# Getting in _ready() instead
func _ready():
    timer = $Timer  # Should use @onready

# Direct access without reference
func update():
    $Sprite2D.visible = false  # Should cache as @onready
```

### When Not to Use @onready

```gdscript
# Dynamic children (created at runtime)
var bullet: PackedScene = preload("res://bullet.tscn")

func _fire():
    var instance = bullet.instantiate()
    add_child(instance)

# Optional nodes (might not exist)
func _ready():
    var optional = get_node_or_null("OptionalChild")
    if optional:
        optional.setup()
```

---

## Script Size Guidelines

**Optimal sizes:**
- **80-120 lines**: Sweet spot, focused and readable
- **120-150 lines**: Acceptable, but watch for split opportunities
- **>150 lines**: Should be split into components

**Line counting includes:**
- All code
- Comments
- Blank lines

**Doesn't count toward splitting:**
- Long @export var lists (configuration is okay)
- Large match/switch statements (enum handling is okay)

### Example: Perfect Size Script

```gdscript
extends Node
class_name EnemySpawner
# 98 lines total - perfect size

signal enemy_spawned(enemy: Node2D)

@export var enemy_scene: PackedScene
@export var spawn_interval: float = 2.0
@export var max_enemies: int = 10

var _active_enemies: int = 0
@onready var _spawn_timer: Timer = $SpawnTimer

func _ready():
    _spawn_timer.timeout.connect(_on_spawn_timer_timeout)
    _spawn_timer.wait_time = spawn_interval
    _spawn_timer.start()

func _on_spawn_timer_timeout():
    if _active_enemies < max_enemies:
        _spawn_enemy()

func _spawn_enemy():
    var enemy = enemy_scene.instantiate()
    get_tree().current_scene.add_child(enemy)
    enemy.tree_exiting.connect(_on_enemy_died)
    _active_enemies += 1
    enemy_spawned.emit(enemy)

func _on_enemy_died():
    _active_enemies -= 1
```

---

## Architecture Patterns

### Game Manager Pattern

**game_manager.gd (autoload):**
```gdscript
extends Node

var current_level: int = 1
var player_lives: int = 3

func _ready():
    Events.player_died.connect(_on_player_died)
    Events.level_completed.connect(_on_level_completed)

func _on_player_died():
    player_lives -= 1
    if player_lives <= 0:
        game_over()
    else:
        respawn_player()

func _on_level_completed(level: int):
    current_level = level + 1
    load_level(current_level)
```

### State Machine Pattern

**state_machine.gd:**
```gdscript
extends Node
class_name StateMachine

signal state_changed(from: String, to: String)

var current_state: State
var states: Dictionary = {}

func _ready():
    for child in get_children():
        if child is State:
            states[child.name] = child
            child.transition_requested.connect(_on_transition_requested)

func _on_transition_requested(state_name: String):
    change_state(state_name)

func change_state(state_name: String):
    if current_state:
        current_state.exit()

    var old = current_state.name if current_state else ""
    current_state = states[state_name]
    current_state.enter()

    state_changed.emit(old, state_name)
```

### Object Pool Pattern

**object_pool.gd:**
```gdscript
extends Node
class_name ObjectPool

@export var pool_size: int = 20
@export var object_scene: PackedScene

var _available: Array[Node] = []
var _active: Array[Node] = []

func _ready():
    for i in pool_size:
        var obj = object_scene.instantiate()
        obj.set_process(false)
        add_child(obj)
        _available.append(obj)

func acquire() -> Node:
    if _available.is_empty():
        return null

    var obj = _available.pop_back()
    _active.append(obj)
    obj.set_process(true)
    return obj

func release(obj: Node):
    _active.erase(obj)
    _available.append(obj)
    obj.set_process(false)
```

---

## Testing and Validation

### Test Isolated Components

```gdscript
# test_health_component.gd (in addons/gut or similar)
extends GutTest

func test_damage_reduces_health():
    var health = HealthComponent.new()
    health.max_health = 100
    health._ready()

    health.take_damage(30)

    assert_eq(health.current_health, 70)

func test_depleted_signal_emits():
    var health = HealthComponent.new()
    health.max_health = 100
    health._ready()

    watch_signals(health)

    health.take_damage(100)

    assert_signal_emitted(health, "depleted")
```

### Manual Testing Checklist

When refactoring:
- [ ] Scene loads without errors
- [ ] All @onready vars resolve (no null refs)
- [ ] Signals connect successfully (no errors in console)
- [ ] Behavior identical to before
- [ ] Performance unchanged (±2 FPS)

---

## Common Patterns Summary

| Need | Pattern | Implementation |
|------|---------|----------------|
| Reusable behavior | Component | Extend Node, attach as child |
| Cross-tree communication | Signal via Events | Events.signal_name.emit() |
| Configurable data | Resource | extends Resource, .tres files |
| Multiple states | State Machine | StateMachine with State children |
| Many temporary objects | Object Pool | Pre-instantiate, acquire/release |
| Global state | Autoload | Singleton script |
| Parent-child messages | Local signals | Define signal, emit from child |

---

**Use these patterns** throughout the refactoring skill to replace anti-patterns with clean, maintainable code.
