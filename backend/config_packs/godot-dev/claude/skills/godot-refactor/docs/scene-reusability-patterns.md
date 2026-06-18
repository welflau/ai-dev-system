# Scene Reusability Patterns

**Purpose:** Generate modular, reusable scenes with automatic component library organization.

**Core Principle:** Extract code-created nodes into configurable scene components with preset resources. Maximize reusability, minimize duplication.

---

## Overview

Instead of creating nodes in code with hardcoded properties, we create:

1. **Configurable Component Scene** - Base scene template with a script
2. **Configuration Resource Class** - Stores configuration data
3. **Preset Resource** - Specific configuration instance
4. **Parent Integration** - Parent scene instances component with preset

Benefits:
- ✅ Zero duplicate scenes
- ✅ Reuse same scene with different presets
- ✅ Inspector-configurable properties
- ✅ Modular, organized component library
- ✅ Easy to test and maintain
- ✅ Automatic library organization by category

---

## Component Library Structure

### Directory Convention

```
project_root/
└─ res://
   └─ components/
      ├─ timers/
      │  ├─ configurable_timer.tscn (base scene)
      │  ├─ configurable_timer.gd (script)
      │  ├─ timer_config.gd (resource class)
      │  └─ presets/
      │     ├─ damage_timer.tres (0.5s one-shot)
      │     ├─ cooldown_timer.tres (2.0s one-shot)
      │     └─ repeating_tick.tres (0.1s repeating)
      ├─ areas/
      │  ├─ configurable_area.tscn
      │  ├─ configurable_area.gd
      │  ├─ area2d_config.gd
      │  └─ presets/
      │     ├─ damage_zone.tres
      │     ├─ detection_area.tres
      │     └─ pickup_zone.tres
      ├─ sprites/
      │  ├─ configurable_sprite.tscn
      │  ├─ configurable_sprite.gd
      │  ├─ sprite2d_config.gd
      │  └─ presets/
      │     ├─ player_sprite.tres
      │     └─ enemy_sprite.tres
      ├─ ui/
      │  ├─ buttons/
      │  │  ├─ configurable_button.tscn
      │  │  ├─ configurable_button.gd
      │  │  └─ button_config.gd
      │  └─ labels/
      │     ├─ configurable_label.tscn
      │     ├─ configurable_label.gd
      │     └─ label_config.gd
      └─ physics/
         ├─ bodies/
         │  ├─ configurable_body.tscn
         │  ├─ configurable_body.gd
         │  └─ physics_body_config.gd
         └─ shapes/
            ├─ circle_collision.tscn
            └─ box_collision.tscn
```

### Naming Conventions

- **Base Scenes:** `configurable_{type}.tscn` (e.g., `configurable_timer.tscn`)
- **Scripts:** `configurable_{type}.gd` (e.g., `configurable_timer.gd`)
- **Config Classes:** `{type}_config.gd` (e.g., `timer_config.gd`)
- **Presets:** Descriptive names: `damage_timer.tres`, `cooldown_timer.tres`
- **Directories:** Plural, category-based: `timers/`, `areas/`, `sprites/`, `ui/`

---

## Pattern: Configurable Components with Preset Resources

### Step 1: Analyze Code-Created Node

Example code being refactored:

```gdscript
# In parent.gd
func _ready():
    # Create damage timer
    _damage_timer = Timer.new()
    _damage_timer.wait_time = 0.5
    _damage_timer.one_shot = false
    _damage_timer.autostart = false
    add_child(_damage_timer)
    _damage_timer.timeout.connect(_on_damage)

    # Create cooldown timer
    _cooldown_timer = Timer.new()
    _cooldown_timer.wait_time = 2.0
    _cooldown_timer.one_shot = true
    _cooldown_timer.autostart = false
    add_child(_cooldown_timer)
    _cooldown_timer.timeout.connect(_on_cooldown)
```

**Extracted Configuration:**
- Node Type: Timer
- Damage: wait_time=0.5, one_shot=false
- Cooldown: wait_time=2.0, one_shot=true
- Both: autostart=false

---

### Step 2: Generate Resource Configuration Class

**File:** `res://components/timers/timer_config.gd`

```gdscript
extends Resource
class_name TimerConfig

## Timer wait time in seconds
@export var wait_time: float = 1.0

## Only emit timeout once
@export var one_shot: bool = false

## Start timer automatically on ready
@export var autostart: bool = false
```

**Notes:**
- Inherits from Resource (makes it saveable as .tres file)
- `@export` makes properties editable in Inspector
- Provide sensible defaults
- Comment each property for clarity

---

### Step 3: Generate Configurable Component Script

**File:** `res://components/timers/configurable_timer.gd`

```gdscript
extends Timer
class_name ConfigurableTimer

## Configuration resource applied at startup
@export var config: TimerConfig

func _ready():
    # Apply configuration if preset is assigned
    if config:
        apply_config(config)

## Apply configuration resource to timer
func apply_config(cfg: TimerConfig) -> void:
    wait_time = cfg.wait_time
    one_shot = cfg.one_shot
    if cfg.autostart:
        start()
```

**Key Features:**
- Extends the actual node type (Timer, Area2D, etc.)
- `@export var config` - Inspector property for preset
- `apply_config()` method - Applies preset to node
- Optional configuration (works without config too)
- Autostart handled in apply_config()

---

### Step 4: Generate Base Component Scene

**File:** `res://components/timers/configurable_timer.tscn`

```ini
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://components/timers/configurable_timer.gd" id="1"]

[node name="Timer" type="Timer"]
script = ExtResource("1")
```

**Notes:**
- Scene contains actual node type (Timer)
- Node name matches type for clarity
- Only script attached - no preset (preset assigned by parent)
- Scene can be instantiated standalone or with preset

---

### Step 5: Generate Preset Resources

**File:** `res://components/timers/presets/damage_timer.tres`

```ini
[gd_resource type="TimerConfig" format=3]

[resource]
wait_time = 0.5
one_shot = false
autostart = false
```

**File:** `res://components/timers/presets/cooldown_timer.tres`

```ini
[gd_resource type="TimerConfig" format=3]

[resource]
wait_time = 2.0
one_shot = true
autostart = false
```

**File:** `res://components/timers/presets/repeating_tick.tres`

```ini
[gd_resource type="TimerConfig" format=3]

[resource]
wait_time = 0.1
one_shot = false
autostart = true
```

**Notes:**
- Separate .tres file for each preset
- Descriptive names: `damage_timer`, `cooldown_timer`
- Easy to see differences between presets
- Editable in Inspector for tweaking

---

### Step 6: Update Parent Scene

**File:** `res://parent.tscn`

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

**Notes:**
- Instance base scene multiple times (reuse!)
- Each instance uses different preset
- Same scene, different configurations
- Inspector shows which preset assigned

---

### Step 7: Update Parent Script

**File:** `res://parent.gd`

```gdscript
extends Node2D

# Reference to the damage timer (via @onready)
@onready var _damage_timer: ConfigurableTimer = $DamageTimer

# Reference to the cooldown timer
@onready var _cooldown_timer: ConfigurableTimer = $CooldownTimer

func _ready():
    # Connect signals (configuration already applied)
    _damage_timer.timeout.connect(_on_damage)
    _cooldown_timer.timeout.connect(_on_cooldown)

func _on_damage():
    print("Damage applied!")

func _on_cooldown():
    print("Cooldown finished!")
```

**Key Changes:**
- Remove node creation code
- Use `@onready` to reference scene instances
- Connect signals in `_ready()`
- Configuration already applied by scene/preset
- Much cleaner and more declarative

---

## Automatic Component Library Building

### First Detection (First Timer)

**Situation:** Analyzing code, find first `Timer.new()` with wait_time=0.5, one_shot=false

**Actions:**

1. Analyze context → Select **Timer** node
2. Check if `components/timers/` exists
3. **Doesn't exist**, so generate:
   - `configurable_timer.gd` (script)
   - `configurable_timer.tscn` (base scene)
   - `timer_config.gd` (resource class)
4. Create preset: `components/timers/presets/damage_timer.tres` (0.5s)
5. Update parent.tscn to instance component with preset
6. Update parent.gd to reference via @onready

**Result:**
```
✓ Component library initialized
✓ Base timer component created
✓ Damage preset created
✓ Parent updated to use component
```

---

### Second Detection (Second Timer)

**Situation:** Next code block has `Timer.new()` with wait_time=2.0, one_shot=true

**Actions:**

1. Analyze context → Select **Timer** node
2. Check if `components/timers/` exists
3. **Exists!** So skip base scene generation:
   - `configurable_timer.tscn` already exists ✓
   - `configurable_timer.gd` already exists ✓
   - `timer_config.gd` already exists ✓
4. Create new preset only: `components/timers/presets/cooldown_timer.tres` (2.0s)
5. Update parent.tscn to instance base component with new preset
6. Update parent.gd to reference new timer via @onready

**Result:**
```
✓ Reused existing component base
✓ Created new preset for variation
✓ Zero scene duplication
✓ Component library growing
```

---

### Third Detection (First Area2D)

**Situation:** Find first `Area2D.new()` with monitoring=true, monitorable=true

**Actions:**

1. Analyze context → Select **Area2D** node
2. Check if `components/areas/` exists
3. **Doesn't exist**, so generate area component:
   - `configurable_area.gd` (script)
   - `configurable_area.tscn` (base scene)
   - `area2d_config.gd` (resource class)
4. Create preset: `components/areas/presets/detection_area.tres`
5. Update parent.tscn and parent.gd

**Result:**
```
✓ New component category created (areas)
✓ Base area component created
✓ Detection preset created
✓ Component library expanded
```

---

## Component Library After Full Refactoring

```
components/
├─ timers/
│  ├─ configurable_timer.tscn (1 base scene, reused 5 times)
│  ├─ configurable_timer.gd
│  ├─ timer_config.gd
│  └─ presets/
│     ├─ damage_timer.tres
│     ├─ cooldown_timer.tres
│     ├─ repeating_tick.tres
│     ├─ effect_duration.tres
│     └─ ui_pulse.tres
├─ areas/
│  ├─ configurable_area.tscn (1 base scene, reused 3 times)
│  ├─ configurable_area.gd
│  ├─ area2d_config.gd
│  └─ presets/
│     ├─ damage_zone.tres
│     ├─ detection_area.tres
│     └─ pickup_zone.tres
├─ sprites/
│  ├─ configurable_sprite.tscn (1 base scene, reused 2 times)
│  ├─ configurable_sprite.gd
│  ├─ sprite2d_config.gd
│  └─ presets/
│     ├─ player_sprite.tres
│     └─ enemy_sprite.tres
└─ physics/
   └─ bodies/
      ├─ configurable_body.tscn (1 base scene, reused 2 times)
      ├─ configurable_body.gd
      ├─ physics_body_config.gd
      └─ presets/
         ├─ player_body.tres
         └─ enemy_body.tres

Statistics:
- Base Scenes Created: 4
- Times Reused: 12+
- Duplicate Scenes: 0
- Presets: 15+
- Code Reduction: 70%+
```

---

## Advanced Pattern: Hierarchical Configs

For complex components, use inheritance:

```gdscript
# base_config.gd
extends Resource
class_name BaseConfig

@export var name: String = "Unnamed"
@export var enabled: bool = true

# timer_config.gd
extends BaseConfig
class_name TimerConfig

@export var wait_time: float = 1.0
@export var one_shot: bool = false
```

Benefits:
- Shared configuration properties
- Extensible config hierarchy
- Consistent interface

---

## Pattern: Component Factory

For creating components dynamically:

```gdscript
# component_factory.gd
extends Node
class_name ComponentFactory

static func create_timer(config: TimerConfig, parent: Node) -> ConfigurableTimer:
    var scene = load("res://components/timers/configurable_timer.tscn")
    var timer = scene.instantiate()
    timer.config = config
    parent.add_child(timer)
    return timer

static func create_area(config: Area2DConfig, parent: Node) -> ConfigurableArea:
    var scene = load("res://components/areas/configurable_area.tscn")
    var area = scene.instantiate()
    area.config = config
    parent.add_child(area)
    return area
```

Usage:
```gdscript
# Create timer from preset at runtime
var timer = ComponentFactory.create_timer(
    load("res://components/timers/presets/damage_timer.tres"),
    self
)
```

---

## Pattern: Configuration Validation

Add validation to detect misconfiguration:

```gdscript
# configurable_timer.gd
extends Timer
class_name ConfigurableTimer

@export var config: TimerConfig

func _ready():
    if config:
        if not _validate_config(config):
            push_error("Invalid timer configuration: %s" % config)
            return
        apply_config(config)

func _validate_config(cfg: TimerConfig) -> bool:
    if cfg.wait_time <= 0:
        push_warning("Timer wait_time should be positive")
        return false
    return true

func apply_config(cfg: TimerConfig) -> void:
    wait_time = cfg.wait_time
    one_shot = cfg.one_shot
    if cfg.autostart:
        start()
```

---

## Pattern: Dynamic Property Application

For handling additional properties not in config:

```gdscript
# configurable_timer.gd
extends Timer
class_name ConfigurableTimer

@export var config: TimerConfig
@export var custom_properties: Dictionary = {}  # Additional properties

func _ready():
    if config:
        apply_config(config)

    # Apply any custom properties
    for key in custom_properties:
        set(key, custom_properties[key])

func apply_config(cfg: TimerConfig) -> void:
    wait_time = cfg.wait_time
    one_shot = cfg.one_shot
    if cfg.autostart:
        start()
```

---

## Anti-Patterns to Avoid

### ❌ Creating Every Variation as Separate Scene

```
❌ WRONG:
components/timers/
├─ damage_timer.tscn
├─ cooldown_timer.tscn
├─ repeating_timer.tscn
└─ ui_timer.tscn
(4 separate scenes = duplication)
```

```
✅ RIGHT:
components/timers/
├─ configurable_timer.tscn (1 reusable base)
└─ presets/
   ├─ damage_timer.tres
   ├─ cooldown_timer.tres
   ├─ repeating_timer.tres
   └─ ui_timer.tres
(1 base scene + 4 presets = no duplication)
```

### ❌ Storing Config in Scene Instead of Resource

```
❌ WRONG:
# In configurable_timer.tscn node properties
[node name="Timer" type="Timer"]
wait_time = 0.5
one_shot = false
# Hardcoded - can't be shared

✅ RIGHT:
# configurable_timer.tscn (generic)
[node name="Timer" type="Timer"]
script = ExtResource("1")
config = ExtResource("2")  # References preset

# damage_timer.tres (specific)
[resource]
wait_time = 0.5
one_shot = false
```

### ❌ Duplicating Presets

```
❌ WRONG:
presets/
├─ enemy_damage_timer_v1.tres
├─ enemy_damage_timer_v2.tres  # Copy of v1?
└─ enemy_damage_timer.tres

✅ RIGHT:
presets/
├─ enemy_damage_timer.tres  # Single source of truth
# Version control for iterations
```

### ❌ Creating Components for Single-Use Objects

```
❌ WRONG:
# Creating a component library for one-off, unique objects
components/
├─ boss_timer/
├─ boss_area/
├─ boss_sprite/
# Used only once

✅ RIGHT:
# Keep one-off objects in main scene
# Only create components for reusable patterns
# Boss can still instance components for its parts
boss.tscn
├─ BossSprite (instance of configurable_sprite)
├─ BossArea (instance of configurable_area)
├─ BossPhase1Timer (instance of configurable_timer)
```

---

## Integration with Refactoring Operations

### During Operation A Execution

1. **Detect** → Find `.new()` call for Timer
2. **Select** → Use node-selection-guide.md → Choose **Timer**
3. **Check Library** → Does `components/timers/` exist?
   - No: Generate full component (base scene, script, config class)
   - Yes: Skip base generation
4. **Generate Preset** → Create preset .tres with extracted properties
5. **Update Parent** → Instance base component with preset in parent.tscn
6. **Update Parent Script** → Add @onready reference, keep signal connections

### Success Criteria

✅ Base component created (if first of type)
✅ Preset resource created with extracted values
✅ Parent scene instances component
✅ Parent script references via @onready
✅ Signals connected
✅ Old code removed
✅ Behavior unchanged

---

## Configuration Best Practices

### 1. Group Related Properties

```gdscript
# Good: Logically organized
class_name PhysicsBodyConfig extends Resource

# Physics properties
@export var mass: float = 1.0
@export var friction: float = 0.5
@export var bounce: float = 0.0

# Collision properties
@export var collision_layer: int = 1
@export var collision_mask: int = 1
```

### 2. Use Meaningful Defaults

```gdscript
# Good defaults that make sense
@export var wait_time: float = 1.0  # 1 second is common
@export var enabled: bool = true  # Usually enabled by default

# Avoid confusing defaults
❌ @export var wait_time: float = 0.0  # Confusing edge case
```

### 3. Document Complex Properties

```gdscript
## Friction coefficient (0 = no friction, 1 = high friction)
@export var friction: float = 0.5

## Bloom intensity (0 = no bloom, 1 = full bloom)
@export var bloom_intensity: float = 0.5
```

### 4. Use Enums for Categorical Properties

```gdscript
class_name LightConfig extends Resource

enum BlendMode { ADD, MUL, MIX }

@export var blend_mode: BlendMode = BlendMode.ADD
@export var energy: float = 1.0
```

---

## Testing Components

### Unit Test Example

```gdscript
# test_configurable_timer.gd
extends GutTest

func test_timer_applies_config():
    var config = TimerConfig.new()
    config.wait_time = 0.5
    config.one_shot = true

    var timer = ConfigurableTimer.new()
    timer.config = config
    timer._ready()

    assert_eq(timer.wait_time, 0.5)
    assert_eq(timer.one_shot, true)

func test_timer_starts_with_autostart():
    var config = TimerConfig.new()
    config.autostart = true

    var timer = ConfigurableTimer.new()
    timer.config = config
    timer._ready()

    assert_true(timer.is_stopped() == false)
```

---

## Summary

**Modular Component Pattern:**

1. **Identify Reusable Node** → Analysis and selection
2. **Create Config Class** → Store properties as resource
3. **Create Component Script** → Extend node, apply config
4. **Create Base Scene** → Template with script attached
5. **Create Presets** → Specific configurations as .tres files
6. **Update Parent Scene** → Instance base, assign preset
7. **Update Parent Script** → @onready reference, connect signals
8. **Organize Library** → By category in `components/` directory

**Result:**
- ✅ Modular, reusable components
- ✅ Zero scene duplication
- ✅ Inspector-configurable
- ✅ Organized component library
- ✅ Easy to maintain and extend
- ✅ Reduces code, increases clarity

This pattern enables professional, maintainable Godot projects with proper component organization and zero waste.
