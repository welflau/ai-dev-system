# Refactoring Operations Guide

Detailed step-by-step procedures for each refactoring operation.

---

## Operation A: Extract Code-Created Objects to Modular Components

**Goal**: Replace `.new()` node creation with modular, reusable components and preset-based configuration.

**Key Principle**: Zero duplication. Every node type created once as a base component, reused infinitely with different presets.

### Detection Phase

1. **Find all .new() calls:**
```bash
grep -rn "\.new()" --include="*.gd" . | grep -E "(Node|Timer|Area|Sprite|RigidBody|Character|Control|Collision|Label|Button|Audio)"
```

2. **For each match**, extract full context (30 lines):
   - File path and line number
   - Variable name
   - Assigned properties (next 20 lines)
   - Method calls (to understand behavior)
   - Signal connections
   - Parent node context

### Analysis Phase - Intelligent Node Selection

For each detected instance:

**1. Use node-selection-guide.md to analyze:**
   - Variable name patterns
   - Property assignments
   - Method calls
   - Parent context
   - Apply decision trees

**2. Calculate confidence score:**
   - 90%+ → Auto-select node type
   - 75-89% → Auto-select with review note
   - 50-74% → Ask user (present top 2-3 options)
   - <50% → Use safe fallback (Node2D or Node)

**3. Consult godot-node-reference.md:**
   - Get node properties and best practices
   - Identify optimal configuration properties
   - Check related nodes for better fit

**Example Analysis:**
```gdscript
# Code:
_damage_timer = Timer.new()
_damage_timer.wait_time = 0.5
_damage_timer.one_shot = false
_damage_timer.autostart = false
add_child(_damage_timer)
_damage_timer.timeout.connect(_on_damage)

# Analysis:
- Variable: "_damage_timer" → +30% (semantic name)
- Properties: wait_time, one_shot → +40%
- Methods: .timeout.connect() → +35%
- Decision tree: Perfect Timer match → +25%
- Total: 95% confidence ✓
# Decision: AUTO-SELECT Timer
```

### Component Library Check Phase

For the selected node type:

**1. Check if component library category exists:**
```bash
ls -d components/{category}/ 2>/dev/null
# Categories: timers, areas, sprites, physics, ui, audio, etc.
```

**2. If library exists:**
   - Reuse existing base component
   - Skip base generation (save time)
   - Go to Step 4 (Preset generation)

**3. If library doesn't exist:**
   - Generate full component structure
   - Go to Step 2 below

### Component Generation Phase (First Time)

**Create for each NEW node type:**

**Step 1: Generate Resource Configuration Class**

File: `res://components/{category}/{type}_config.gd`

```gdscript
extends Resource
class_name {Type}Config

## Property documentation
@export var property1: Type = default_value
@export var property2: Type = default_value
@export var property3: Type = default_value
```

Example for Timer:
```gdscript
# res://components/timers/timer_config.gd
extends Resource
class_name TimerConfig

@export var wait_time: float = 1.0
@export var one_shot: bool = false
@export var autostart: bool = false
```

**Step 2: Generate Configurable Component Script**

File: `res://components/{category}/configurable_{type}.gd`

```gdscript
extends {NodeType}
class_name Configurable{Type}

@export var config: {Type}Config

func _ready():
    if config:
        apply_config(config)

func apply_config(cfg: {Type}Config) -> void:
    # Apply all configuration properties
    property1 = cfg.property1
    property2 = cfg.property2
    # Handle special cases (signals, initialization)
    if cfg.autostart and is_class({Type}):
        start()  # For Timer, Camera, etc.
```

Example for Timer:
```gdscript
# res://components/timers/configurable_timer.gd
extends Timer
class_name ConfigurableTimer

@export var config: TimerConfig

func _ready():
    if config:
        apply_config(config)

func apply_config(cfg: TimerConfig) -> void:
    wait_time = cfg.wait_time
    one_shot = cfg.one_shot
    if cfg.autostart:
        start()
```

**Step 3: Generate Base Component Scene**

File: `res://components/{category}/configurable_{type}.tscn`

```ini
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://components/{category}/configurable_{type}.gd" id="1"]

[node name="{Type}" type="{NodeType}"]
script = ExtResource("1")
```

Example for Timer:
```ini
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://components/timers/configurable_timer.gd" id="1"]

[node name="Timer" type="Timer"]
script = ExtResource("1")
```

### Preset Generation Phase

**Create for EACH detected instance:**

**1. Create directory structure** (if first preset):
```bash
mkdir -p res://components/{category}/presets
```

**2. Generate preset resource:**

File: `res://components/{category}/presets/{preset_name}.tres`

Extract configuration from analyzed code:

```ini
[gd_resource type="{Type}Config" format=3]

[resource]
property1 = extracted_value
property2 = extracted_value
property3 = extracted_value
```

Example for damage timer:
```ini
# res://components/timers/presets/damage_timer.tres
[gd_resource type="TimerConfig" format=3]

[resource]
wait_time = 0.5
one_shot = false
autostart = false
```

Example for cooldown timer (reuses base):
```ini
# res://components/timers/presets/cooldown_timer.tres
[gd_resource type="TimerConfig" format=3]

[resource]
wait_time = 2.0
one_shot = true
autostart = false
```

### Parent Scene Integration Phase

**1. Add ext_resource entries:**

```ini
[ext_resource type="PackedScene" path="res://components/{category}/configurable_{type}.tscn" id="X"]
[ext_resource type="Resource" path="res://components/{category}/presets/{preset_name}.tres" id="Y"]
```

**2. Add instance node:**

```ini
[node name="{InstanceName}" parent="." instance=ExtResource("X")]
config = ExtResource("Y")
```

Example for parent.tscn:
```ini
[gd_scene load_steps=3 format=3]

[ext_resource type="PackedScene" path="res://components/timers/configurable_timer.tscn" id="1"]
[ext_resource type="Resource" path="res://components/timers/presets/damage_timer.tres" id="2"]
[ext_resource type="Resource" path="res://components/timers/presets/cooldown_timer.tres" id="3"]

[node name="Parent" type="Node2D"]

[node name="DamageTimer" parent="." instance=ExtResource("1")]
config = ExtResource("2")

[node name="CooldownTimer" parent="." instance=ExtResource("1")]
config = ExtResource("3")
```

### Parent Script Integration Phase

**1. Add @onready references:**

```gdscript
@onready var _damage_timer: ConfigurableTimer = $DamageTimer
@onready var _cooldown_timer: ConfigurableTimer = $CooldownTimer
```

**2. Update _ready() function:**

Remove:
```gdscript
_damage_timer = Timer.new()
_damage_timer.wait_time = 0.5
_damage_timer.one_shot = false
add_child(_damage_timer)
_damage_timer.timeout.connect(_on_damage)
```

Replace with:
```gdscript
_damage_timer.timeout.connect(_on_damage)
_cooldown_timer.timeout.connect(_on_cooldown)
```

Configuration is now applied by the component and preset!

**Example parent.gd:**
```gdscript
extends Node2D

@onready var _damage_timer: ConfigurableTimer = $DamageTimer
@onready var _cooldown_timer: ConfigurableTimer = $CooldownTimer

func _ready():
    # Configuration already applied by presets
    # Just connect signals
    _damage_timer.timeout.connect(_on_damage)
    _cooldown_timer.timeout.connect(_on_cooldown)

func _on_damage():
    print("Damage!")

func _on_cooldown():
    print("Cooldown finished!")
```

### Validation Phase

**1. Component structure validation:**
```bash
✓ res://components/{category}/configurable_{type}.gd exists
✓ res://components/{category}/configurable_{type}.tscn exists
✓ res://components/{category}/{type}_config.gd exists
✓ res://components/{category}/presets/{preset_name}.tres exists
```

**2. Script validation:**
```bash
# Check for syntax errors
gdscript -c res://components/{category}/configurable_{type}.gd
```

**3. Behavioral equivalence:**
- Component applies all extracted configuration
- Signals still connect properly
- Behavior unchanged

### Git Commit Phase

```bash
git add components/ parent.gd parent.tscn
git commit -m "Refactor: Extract {NodeType} to modular component in parent.gd

- Created components/{category}/configurable_{type}.tscn (reusable base)
- Created components/{category}/configurable_{type}.gd (configurable script)
- Created components/{category}/{type}_config.gd (configuration resource)
- Created components/{category}/presets/{preset_name}.tres (extracted preset)
- Updated parent.tscn to instance component with preset
- Updated parent.gd to use @onready reference
- Removed {NodeType}.new() and add_child() code
- Preserved signal connections via component pattern"
```

### Special Cases

**Case 1: Second Timer Detection (Reuse)**

```gdscript
# New code being refactored:
_cooldown_timer = Timer.new()
_cooldown_timer.wait_time = 2.0
_cooldown_timer.one_shot = true
add_child(_cooldown_timer)
```

**Action:**
- ✓ Component library exists (timers/)
- ✓ Skip base generation (already have configurable_timer.tscn/gd)
- Generate new preset: `cooldown_timer.tres`
- Instance same base with different preset
- ZERO duplication!

**Case 2: Node with Complex Hierarchy**

```gdscript
var area = Area2D.new()
add_child(area)

var shape = CircleShape2D.new()
shape.radius = 50.0

var collision = CollisionShape2D.new()
collision.shape = shape
area.add_child(collision)

area.body_entered.connect(_on_body_entered)
```

**Solution:** Create component with hierarchy:
```ini
[gd_scene load_steps=2 format=3]

[sub_resource type="CircleShape2D" id="1"]
radius = 50.0

[node name="Area2D" type="Area2D"]
script = ExtResource("1")
config = ExtResource("2")

[node name="CollisionShape2D" parent="." type="CollisionShape2D"]
shape = SubResource("1")
```

**Case 3: Conditional Node Creation**

```gdscript
if has_shield:
    _shield = Sprite2D.new()
    add_child(_shield)
```

**Solution:** Create component, control in parent:
```gdscript
@onready var _shield: ConfigurableSprite = $Shield

func _ready():
    _shield.visible = has_shield
```

**Case 4: Dynamic Loop Creation**

```gdscript
for i in 3:
    var timer = Timer.new()
    timer.wait_time = i + 1.0
    add_child(timer)
```

**Solution:** Keep dynamic instantiation (appropriate pattern):
```gdscript
var timer_scene = preload("res://components/timers/configurable_timer.tscn")
var timer_config = preload("res://components/timers/timer_config.gd")

for i in 3:
    var config = timer_config.new()
    config.wait_time = i + 1.0

    var timer = timer_scene.instantiate()
    timer.config = config
    add_child(timer)
```

---

## Operation B: Split Monolithic Scripts

**Goal**: Divide large scripts (>150 lines) into focused components.

### Detection Phase

```bash
find . -name "*.gd" -exec wc -l {} + | awk '$1 > 150 {print $2 " (" $1 " lines)"}'
```

### Analysis Phase

For each large script:

**1. Read the full file:**
```bash
cat player_movement.gd
```

**2. Identify sections** by:
- Comment headers (`# === Section Name ===`)
- Function groupings (related functions together)
- Signal definitions
- Distinct responsibilities

**Example analysis:**
```
player_movement.gd (287 lines)

Lines 1-45: Input handling (read input, convert to direction)
Lines 46-98: Physics movement (apply forces, move_and_slide)
Lines 99-156: Ability system (dash, jump, shoot)
Lines 157-210: Health management (take damage, heal, die)
Lines 211-287: UI updates (health bar, ability cooldowns)
```

**3. Group by responsibility:**
```
Core (keep in main): Input + Physics (143 lines)
Extract to components:
  - player_abilities.gd (58 lines)
  - player_health.gd (54 lines)
  - player_ui.gd (77 lines)
```

### Planning Phase

**1. Define interfaces** (what each component exposes):

**player_abilities.gd:**
```gdscript
signal ability_used(ability_name: String)
signal cooldown_started(ability: String, duration: float)

func activate_dash() -> void
func activate_jump() -> void
func activate_shoot() -> void
```

**player_health.gd:**
```gdscript
signal health_changed(current: int, max: int)
signal damage_taken(amount: int)
signal died

func take_damage(amount: int) -> void
func heal(amount: int) -> void
```

**player_ui.gd:**
```gdscript
func update_health(current: int, max: int) -> void
func update_ability_cooldown(ability: String, progress: float) -> void
```

**2. Map dependencies:**
- Abilities needs to emit events → Use Events.gd
- Health needs to notify UI → Direct signal
- UI listens to health → Signal connection

### Extraction Phase

**1. Create new script files:**

```bash
touch player_abilities.gd player_health.gd player_ui.gd
```

**2. Write component scripts:**

**player_abilities.gd:**
```gdscript
extends Node
class_name PlayerAbilities

signal ability_used(ability_name: String)
signal cooldown_started(ability: String, duration: float)

@export var dash_cooldown: float = 2.0
@export var dash_speed: float = 500.0

var _dash_ready: bool = true

func _input(event):
    if event.is_action_pressed("dash") and _dash_ready:
        activate_dash()

func activate_dash() -> void:
    ability_used.emit("dash")
    _dash_ready = false

    await get_tree().create_timer(dash_cooldown).timeout
    _dash_ready = true

# (Move all ability-related functions here)
```

**3. Update main script:**

Add component references:
```gdscript
@onready var abilities: PlayerAbilities = $Abilities
@onready var health: PlayerHealth = $Health
@onready var ui: PlayerUI = $UI

func _ready():
    health.damage_taken.connect(ui.update_health)
    abilities.ability_used.connect(_on_ability_used)
```

Remove extracted code, replace with delegation:
```gdscript
# OLD: 58 lines of ability code
# NEW:
func _on_ability_used(ability_name: String):
    match ability_name:
        "dash":
            velocity = abilities.dash_velocity
```

**4. Create component nodes in parent .tscn** (if exists):

```ini
[node name="Abilities" type="Node" parent="."]
script = ExtResource("player_abilities.gd")

[node name="Health" type="Node" parent="."]
script = ExtResource("player_health.gd")

[node name="UI" type="Node" parent="."]
script = ExtResource("player_ui.gd")
```

### Signal Migration Phase

**Replace direct calls with signals:**

**Before:**
```gdscript
# In _physics_process (main script)
if health <= 0:
    _die()
    _update_ui()
    _disable_abilities()
```

**After:**
```gdscript
# In health component
func take_damage(amount: int):
    current_health -= amount
    if current_health <= 0:
        died.emit()

# In main script _ready()
health.died.connect(_on_player_died)
health.died.connect(abilities.disable_all)
health.died.connect(ui.show_death_screen)

func _on_player_died():
    # Main script only handles physics
    velocity = Vector2.ZERO
    set_physics_process(false)
```

### Validation Phase

**1. Line count check:**
```bash
wc -l player_movement.gd player_abilities.gd player_health.gd player_ui.gd

# Should show:
# 98 player_movement.gd
# 58 player_abilities.gd
# 54 player_health.gd
# 77 player_ui.gd
```

**2. Responsibility check:**
- Main script: Only input + physics
- Each component: Single focused responsibility
- No overlapping concerns

**3. Behavioral check:**
- All abilities still work
- Health changes properly
- UI updates correctly
- No errors in console

### Git Commit Phase

```bash
git add player_movement.gd player_abilities.gd player_health.gd player_ui.gd
git commit -m "Refactor: Split player_movement.gd into components (287→98 lines)

- Extracted PlayerAbilities component (58 lines)
- Extracted PlayerHealth component (54 lines)
- Extracted PlayerUI component (77 lines)
- Implemented signal-based communication
- Main script now focused on input + physics only"
```

---

## Operation C: Implement Signal-Based Decoupling

**Goal**: Replace direct node access with signal-based communication.

### Detection Phase

```bash
# Find all coupling patterns
grep -rn "get_node\|get_parent\|has_method" --include="*.gd" . > coupling.txt
```

### Analysis Phase

For each coupling instance:

**Example:**
```gdscript
# base_station.gd:92
func _on_body_entered(body):
    if body.has_method("set_beam_enabled"):
        body.set_beam_enabled(false)
```

**Analyze:**
- What: Calling `set_beam_enabled(false)` on entering body
- Why: Player entering base station should disable laser beam
- Who: Unknown body type (duck typing via has_method)
- Communication: base_station → player

### Events.gd Setup Phase

**1. Check if Events.gd exists:**
```bash
[ -f events.gd ] && echo "Exists" || echo "Need to create"
```

**2. If doesn't exist, create:**
```gdscript
# events.gd
extends Node
# Global event bus for cross-tree communication

# (Will be populated as signals are added)
```

**3. Add to autoload** (if not already):
```gdscript
# project.godot
[autoload]
Events="*res://events.gd"
```

### Signal Definition Phase

**1. Determine signal name and parameters:**

Pattern: `{subject}_{past_tense_verb}_{context}`

Examples:
- `player_entered_safe_zone(zone: Node2D)`
- `enemy_spawned(enemy: Node2D, type: String)`
- `ability_activated(ability_name: String, actor: Node2D)`

For our example:
```gdscript
signal player_entered_safe_zone(zone: Node2D)
signal player_exited_safe_zone(zone: Node2D)
```

**2. Add to Events.gd:**
```gdscript
# events.gd
extends Node

# Safe zones
signal player_entered_safe_zone(zone: Node2D)
signal player_exited_safe_zone(zone: Node2D)
```

### Emitter Update Phase

Update the code that triggers the event:

**Before (base_station.gd):**
```gdscript
func _on_body_entered(body):
    if body.has_method("set_beam_enabled"):
        body.set_beam_enabled(false)
```

**After (base_station.gd):**
```gdscript
func _on_body_entered(body):
    if body.is_in_group("player"):  # Better than has_method
        Events.player_entered_safe_zone.emit(self)
```

**Changes:**
- Remove `has_method` check
- Use `is_in_group` for type checking (more explicit)
- Emit signal instead of direct call
- Pass `self` so receiver knows which zone

### Receiver Update Phase

Update the code that responds to the event:

**Before (player_movement.gd):**
```gdscript
# set_beam_enabled was called directly
func set_beam_enabled(enabled: bool):
    _beam_active = enabled
```

**After (player_movement.gd):**
```gdscript
func _ready():
    Events.player_entered_safe_zone.connect(_on_entered_safe_zone)
    Events.player_exited_safe_zone.connect(_on_exited_safe_zone)

func _on_entered_safe_zone(zone: Node2D):
    _beam_active = false

func _on_exited_safe_zone(zone: Node2D):
    _beam_active = true
```

**Changes:**
- Connect to signals in _ready()
- Create callback functions
- Can add zone-specific logic if needed

### Cleanup Phase

**1. Remove unused functions** (if only used for coupling):
```gdscript
# Can remove if no other callers:
# func set_beam_enabled(enabled: bool)
```

**2. Remove imports/dependencies:**
```gdscript
# If base_station.gd had:
# const Player = preload("res://player.gd")
# This can be removed now
```

**3. Remove get_node chains:**
```gdscript
# Before:
var player = get_node("/root/Main/Player")

# After: Not needed, use signals
```

### Validation Phase

**1. Connection check:**
```bash
# Run game, check console for errors like:
# "Signal 'player_entered_safe_zone' not found"
```

**2. Behavioral check:**
- Trigger the event (enter safe zone)
- Verify receiver responds (beam disabled)
- Check no errors

**3. Decoupling check:**
```bash
# base_station.gd should NOT reference player
grep -n "player\|Player" base_station.gd
# Should only show signal emit, no direct refs
```

### Git Commit Phase

```bash
git add events.gd base_station.gd player_movement.gd
git commit -m "Refactor: Decouple base_station from player via signals

- Added player_entered/exited_safe_zone signals to Events
- Updated base_station to emit signals instead of direct calls
- Updated player to listen for safe zone signals
- Removed has_method check and direct dependency"
```

### Common Patterns

**Pattern 1: Method call → Signal**
```gdscript
# Before: obj.method(args)
# After: Events.signal_name.emit(args)
```

**Pattern 2: Property access → Signal**
```gdscript
# Before: obj.property = value
# After: Events.property_changed.emit(obj, value)
```

**Pattern 3: Parent access → Signal**
```gdscript
# Before: get_parent().update_score(10)
# After: Events.score_increased.emit(10)
```

---

## Operation D: Extract Data to .tres Resources

**Goal**: Move inline const data to Resource files.

### Detection Phase

```bash
grep -rn "^[[:space:]]*const.*\[" --include="*.gd" . > inline_data.txt
```

### Analysis Phase

For each const declaration:

**Example:**
```gdscript
# enemy_spawner.gd:12-16
const ENEMY_TYPES = [
    {"type": "basic", "health": 100, "speed": 200},
    {"type": "fast", "health": 50, "speed": 400},
    {"type": "tank", "health": 300, "speed": 100}
]
```

**Analyze structure:**
- Array of dictionaries
- Fields: type (String), health (int), speed (float)
- 3 data entries

### Resource Class Phase

**1. Design Resource class:**

```gdscript
# enemy_type_data.gd
extends Resource
class_name EnemyTypeData

@export var type_name: String
@export var health: int
@export var speed: float
@export var enemy_scene: PackedScene  # Optional: link to prefab
```

**2. Create the file:**
```bash
cat > enemy_type_data.gd << 'EOF'
extends Resource
class_name EnemyTypeData

@export var type_name: String = ""
@export var health: int = 100
@export var speed: float = 200.0
@export var enemy_scene: PackedScene
EOF
```

### Resource Files Phase

**1. Create directory:**
```bash
mkdir -p data/enemy_types
```

**2. Generate .tres files** for each data entry:

**Manual method** (via Godot):
- Open Godot editor
- Create new resource: FileSystem → right-click → New Resource
- Select EnemyTypeData
- Set properties in Inspector
- Save as `data/enemy_types/basic.tres`

**Programmatic method** (generate text):
```bash
cat > data/enemy_types/basic.tres << 'EOF'
[gd_resource type="EnemyTypeData" load_steps=2 format=3]

[ext_resource type="Script" path="res://enemy_type_data.gd" id="1"]

[resource]
script = ExtResource("1")
type_name = "basic"
health = 100
speed = 200.0
EOF
```

Repeat for "fast" and "tank".

**3. Link scenes if applicable:**
```ini
[ext_resource type="PackedScene" path="res://enemies/basic_enemy.tscn" id="2"]

[resource]
script = ExtResource("1")
type_name = "basic"
health = 100
speed = 200.0
enemy_scene = ExtResource("2")
```

### Code Update Phase

**1. Update script to use resources:**

**Before (enemy_spawner.gd):**
```gdscript
const ENEMY_TYPES = [...]

func _spawn_enemy():
    var data = ENEMY_TYPES[randi() % ENEMY_TYPES.size()]
    var enemy = create_enemy(data["type"])
    enemy.health = data["health"]
    enemy.speed = data["speed"]
```

**After (enemy_spawner.gd):**
```gdscript
@export var enemy_types: Array[EnemyTypeData] = []

func _spawn_enemy():
    var data = enemy_types[randi() % enemy_types.size()]
    var enemy = data.enemy_scene.instantiate()
    enemy.health = data.health
    enemy.speed = data.speed
```

**2. Remove const declaration:**
```gdscript
# Delete lines 12-16
```

### Inspector Configuration Phase

**If spawner has .tscn file:**

1. Open spawner scene in Godot
2. Select root node
3. In Inspector, find `enemy_types` array
4. Set size to 3
5. Drag .tres files into array slots:
   - [0]: basic.tres
   - [1]: fast.tres
   - [2]: tank.tres
6. Save scene

**If no .tscn file:**

Create preload defaults:
```gdscript
@export var enemy_types: Array[EnemyTypeData] = [
    preload("res://data/enemy_types/basic.tres"),
    preload("res://data/enemy_types/fast.tres"),
    preload("res://data/enemy_types/tank.tres")
]
```

### Validation Phase

**1. Resource loading check:**
```bash
# Open in Godot, check for errors
godot --editor -e project.godot
# Look for "Failed to load resource" errors
```

**2. Type safety check:**
```gdscript
# Verify type hints work
func _spawn_enemy():
    var data: EnemyTypeData = enemy_types[0]
    print(data.type_name)  # Should autocomplete
```

**3. Behavioral check:**
- Spawn enemies
- Verify correct health/speed values
- No errors in console

### Git Commit Phase

```bash
git add enemy_type_data.gd data/enemy_types/*.tres enemy_spawner.gd
git commit -m "Refactor: Extract enemy data to .tres resources

- Created EnemyTypeData Resource class
- Generated basic.tres, fast.tres, tank.tres
- Updated enemy_spawner to use Resource array
- Removed inline ENEMY_TYPES const
- Data now editable in Inspector"
```

### Advanced: Resource Inheritance

For complex data with variants:

**Base resource:**
```gdscript
# weapon_data.gd
extends Resource
class_name WeaponData

@export var weapon_name: String
@export var damage: int
```

**Specialized resource:**
```gdscript
# projectile_weapon_data.gd
extends WeaponData
class_name ProjectileWeaponData

@export var projectile_speed: float
@export var projectile_scene: PackedScene
```

**Usage:**
```gdscript
@export var weapons: Array[WeaponData]  # Can hold both types
```

---

## Common Challenges

### Challenge 1: Circular Dependencies

**Problem:** Component A needs Component B, B needs A.

**Solution:** Use signals to break cycle:
```gdscript
# A emits signal → Events → B receives
# B emits signal → Events → A receives
# No direct references
```

### Challenge 2: Deeply Nested Nodes

**Problem:** `get_node("../../UI/HealthBar")`

**Solution:** Flatten via signals:
```gdscript
# Health component emits signal
signal health_changed(current, max)

# UI listens at root level
func _ready():
    $Player/Health.health_changed.connect($UI/HealthBar.update)
```

### Challenge 3: Dynamic Node Creation

**Problem:** Can't use @onready for runtime nodes.

**Solution:** Use scenes:
```gdscript
var bullet_scene = preload("res://bullet.tscn")

func _shoot():
    var bullet = bullet_scene.instantiate()
    get_tree().current_scene.add_child(bullet)
```

### Challenge 4: Node Order Dependencies

**Problem:** @onready fails if nodes not ready yet.

**Solution:** Use `get_node_or_null` with deferred:
```gdscript
func _ready():
    call_deferred("_setup")

func _setup():
    var node = get_node_or_null("Path")
    if node:
        node.configure()
```

---

## Operation E: Clean Conflicting/Ineffective Operations

**Goal**: Remove code that runs without errors but has no effect or conflicts with other code.

**IMPORTANT**: Run this operation **last**, after Operations A-D complete. Refactoring may introduce or remove conflicts, so check at the end.

### Detection Phase

Run comprehensive conflict detection:

```bash
# Create detection report
echo "=== Conflict Detection Report ===" > conflicts_report.txt
echo "Generated: $(date)" >> conflicts_report.txt
echo "" >> conflicts_report.txt

# 1. Duplicate property assignments
echo "## Duplicate Assignments:" >> conflicts_report.txt
for prop in "scale" "position" "rotation" "modulate" "visible"; do
    echo "Checking $prop..." >&2
    grep -rn "\.$prop\s*=" --include="*.gd" . | \
    awk -F: -v prop="$prop" '
    {
        file=$1; line=$2;
        if (file==prev_file && line-prev_line<20) {
            print file":"prev_line" and "line" - Duplicate "prop" assignment"
        }
        prev_file=file; prev_line=line
    }' >> conflicts_report.txt
done

# 2. Self-assignments
echo "" >> conflicts_report.txt
echo "## Self-Assignments:" >> conflicts_report.txt
grep -rn "position\s*=\s*position\|scale\s*=\s*scale\|rotation\s*=\s*rotation" --include="*.gd" . >> conflicts_report.txt

# 3. Redundant defaults
echo "" >> conflicts_report.txt
echo "## Redundant Defaults:" >> conflicts_report.txt
grep -rn "modulate\s*=\s*Color(1,\s*1,\s*1,\s*1)\|modulate\s*=\s*Color\.WHITE" --include="*.gd" . >> conflicts_report.txt
grep -rn "scale\s*=\s*Vector2(1,\s*1)\|scale\s*=\s*Vector2\.ONE" --include="*.gd" . >> conflicts_report.txt

# 4. Conflicting tweens
echo "" >> conflicts_report.txt
echo "## Conflicting Tweens:" >> conflicts_report.txt
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
}' >> conflicts_report.txt

# 5. Overridden function calls
echo "" >> conflicts_report.txt
echo "## Overridden Calls:" >> conflicts_report.txt
for func in "set_process" "set_physics_process" "queue_free"; do
    grep -rn "$func\(" --include="*.gd" . | \
    awk -F: -v func="$func" '
    {
        file=$1; line=$2;
        if (file==prev_file && line-prev_line<30) {
            print file":"prev_line" and "line" - Multiple "func" calls"
        }
        prev_file=file; prev_line=line
    }' >> conflicts_report.txt
done

# 6. Code after queue_free
echo "" >> conflicts_report.txt
echo "## Code After queue_free (ERROR):" >> conflicts_report.txt
grep -A3 "queue_free()" --include="*.gd" . | \
grep -A2 "queue_free" | \
grep -v "^--$" | \
grep -v "queue_free()" >> conflicts_report.txt

cat conflicts_report.txt
```

### Analysis Phase

Review the report and categorize findings:

**Auto-fixable** (no user input needed):
- Self-assignments → Remove entirely
- Code after `queue_free()` → Remove lines after queue_free
- Redundant defaults in `_ready()` → Remove if no prior changes

**User confirmation needed**:
- Duplicate assignments → Ask which value to keep
- Conflicting tweens → Ask which tween to keep or chain
- Multiple process calls → Ask for final intended state

**Report only** (manual fix):
- Complex tween conflicts with AnimationPlayer
- Conditional logic that appears intentional

### Auto-Fix Phase

**1. Self-assignments:**

```bash
# Find and remove self-assignments
for file in $(grep -l "position\s*=\s*position\|scale\s*=\s*scale" --include="*.gd" -r .); do
    echo "Fixing self-assignments in $file..."
    # Use Edit tool to remove the offending lines
    # Example: position = position
done
```

For each detected self-assignment:

```gdscript
# BEFORE:
func _update():
    position = position  # Line 42
    scale *= Vector2(1, 1)  # Line 43
    rotation += 0.0  # Line 44

# AFTER:
func _update():
    # (all three lines removed - they do nothing)
```

**2. Code after queue_free:**

```gdscript
# BEFORE:
func _die():
    queue_free()
    print("I'm dead")  # ← Never executes!
    emit_signal("died")  # ← Never executes!

# AFTER:
func _die():
    print("I'm dead")
    emit_signal("died")
    queue_free()  # Always last
```

**3. Obvious redundant defaults:**

```gdscript
# BEFORE (in _ready):
func _ready():
    modulate = Color.WHITE  # ← Redundant
    scale = Vector2.ONE  # ← Redundant
    # ... other setup

# AFTER:
func _ready():
    # (removed redundant defaults)
    # ... other setup
```

### User Confirmation Phase

**For duplicate assignments:**

Present to user:
```
⚠️  Duplicate assignment detected:

File: player_movement.gd
Lines: 45, 52
Property: sprite.scale

Line 45: sprite.scale = Vector2(2, 2)
Line 52: sprite.scale = Vector2(1, 1)

The second assignment overwrites the first without reading between them.

Recommendation: Remove line 45 (keep line 52)

Apply fix? [y/n/skip]:
```

**For conflicting tweens:**

Present to user:
```
⚠️  Conflicting tweens detected:

File: player.gd
Function: _start_animation()

Line 92: var tween1 = create_tween()
Line 93: tween1.tween_property(self, "scale", Vector2(2,2), 1.0)

Line 95: var tween2 = create_tween()
Line 96: tween2.tween_property(self, "scale", Vector2(0.5,0.5), 1.0)

Both tweens run simultaneously on the same property.

Options:
1. Keep first tween only (scale to 2,2)
2. Keep second tween only (scale to 0.5,0.5)
3. Chain them (2,2 then 0.5,0.5 in sequence)
4. Skip this fix (I'll handle manually)

Choice [1-4]:
```

**For process state changes:**

```
⚠️  Multiple set_process calls detected:

File: enemy.gd
Function: _ready()

Line 12: set_process(true)
Line 18: set_process(false)

What is the intended final state?
1. Process enabled (remove line 18)
2. Process disabled (remove line 12)
3. Skip this fix

Choice [1-3]:
```

### Cleanup Execution Phase

Based on user responses, apply fixes:

**For duplicate assignment fix:**
```gdscript
# User chose: Remove line 45

# BEFORE:
sprite.scale = Vector2(2, 2)  # Line 45
# ... some code without reading sprite.scale
sprite.scale = Vector2(1, 1)  # Line 52

# AFTER:
# (line 45 removed)
# ... some code
sprite.scale = Vector2(1, 1)  # Line 52
```

**For conflicting tween fix (Option 3: Chain):**
```gdscript
# BEFORE:
var tween1 = create_tween()
tween1.tween_property(self, "scale", Vector2(2, 2), 1.0)

var tween2 = create_tween()
tween2.tween_property(self, "scale", Vector2(0.5, 0.5), 1.0)

# AFTER:
var tween = create_tween()
tween.tween_property(self, "scale", Vector2(2, 2), 1.0)
tween.tween_property(self, "scale", Vector2(0.5, 0.5), 1.0)
```

**For process state fix (Option 2: Disabled):**
```gdscript
# BEFORE:
func _ready():
    set_process(true)   # Line 12
    # ... setup
    set_process(false)  # Line 18

# AFTER:
func _ready():
    # (line 12 removed)
    # ... setup
    set_process(false)  # Line 18
```

### Validation Phase

After each fix:

**1. Syntax check:**
```bash
# Quick parse check
godot --headless --check-only --script path/to/file.gd
```

**2. Behavioral verification:**
- Run the scene
- Verify affected nodes behave identically
- Check console for new warnings/errors

**3. Performance check (optional):**
```bash
# Removing no-ops may slightly improve performance
# Should be negligible, but verify no regression
```

### Git Commit Phase

After all conflicts cleaned:

```bash
git add <all modified files>
git commit -m "Refactor: Clean conflicting/ineffective operations

- Removed self-assignments (no effect)
- Removed code after queue_free()
- Removed redundant default value assignments
- Fixed conflicting tweens (chained where appropriate)
- Cleaned up overridden function calls

Files affected: <count> files
Lines removed: <count> useless lines
No functional changes - purely cleanup"
```

### Special Cases

**Case 1: Conditional duplicate assignments**

```gdscript
# NOT a conflict (different execution paths):
if player_health > 50:
    sprite.scale = Vector2(1, 1)
else:
    sprite.scale = Vector2(0.5, 0.5)

# This is FINE - keep as-is
```

**Case 2: Intentional reset to default**

```gdscript
# May be intentional clarification:
func _reset():
    modulate = Color.WHITE  # Explicit reset after effects
    scale = Vector2.ONE
    rotation = 0.0

# Ask user before removing (context matters)
```

**Case 3: Tweens with parallel mode**

```gdscript
# NOT a conflict (TRANS_PARALLEL):
var tween = create_tween().set_parallel(true)
tween.tween_property(sprite, "scale", Vector2(2,2), 1.0)
tween.tween_property(sprite, "modulate", Color.RED, 1.0)

# Different properties - this is FINE
```

**Case 4: AnimationPlayer and tween conflict**

```gdscript
# COMPLEX conflict:
# AnimationPlayer animates sprite.rotation in _ready()
# Script also tweens sprite.rotation

# Report to user for manual fix:
# "AnimationPlayer and tween both control sprite.rotation - manual review needed"
```

### Summary Report

After Operation E completes:

```
✓ Operation E: Conflicting Operations - Complete

Summary:
- Self-assignments removed: 3
- Redundant defaults removed: 5
- Duplicate assignments fixed: 2
- Conflicting tweens resolved: 1
- Process calls cleaned: 2
- Code after queue_free moved: 1

Total useless lines removed: 14
Files affected: 4 files

All fixes tested and verified.
No functional changes.
```

---

## Common Challenges

### Challenge 1: False Positives in Loops

**Problem:** Detection flags assignments in loops as duplicates.

```gdscript
for i in 10:
    position = Vector2(i * 10, 0)  # ← Looks like duplicate, but it's a loop!
```

**Solution:** Check context - if inside loop/conditional, skip.

### Challenge 2: Timing-Dependent Tweens

**Problem:** Two tweens on same property with delays might be intentional.

```gdscript
var tween1 = create_tween()
tween1.tween_property(self, "scale", Vector2(2,2), 1.0)

await get_tree().create_timer(5.0).timeout

var tween2 = create_tween()
tween2.tween_property(self, "scale", Vector2(1,1), 1.0)
```

**Solution:** Detect `await` between tweens - if present, likely intentional sequence.

### Challenge 3: Defensive Defaults

**Problem:** Programmer sets defaults explicitly for clarity.

```gdscript
func _ready():
    # Explicitly set all defaults for documentation
    visible = true
    modulate = Color.WHITE
    scale = Vector2.ONE
```

**Solution:** If 3+ defaults in a row, ask user if intentional documentation.

### Challenge 4: Animation State Resets

**Problem:** Code that looks redundant but resets animation state.

```gdscript
func _reset_animation():
    sprite.frame = 0
    sprite.modulate = Color.WHITE  # ← Might seem redundant
    sprite.scale = Vector2.ONE
```

**Solution:** Function name contains "reset" or "init" → likely intentional, skip or ask.

---

**Use this operation** as the final step in the refactoring workflow to ensure maximum code cleanliness.
