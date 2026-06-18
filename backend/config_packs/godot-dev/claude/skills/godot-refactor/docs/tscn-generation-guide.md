# .tscn File Generation Guide

Complete reference for generating valid Godot scene (.tscn) files programmatically.

---

## .tscn File Format Basics

Godot .tscn files use a custom INI-like format with specific sections and properties.

**Key principles:**
- Sections start with `[section_name]`
- Properties use `key = value` format
- Indentation doesn't matter (but use for readability)
- String values use double quotes: `text = "value"`
- Numbers don't use quotes: `wait_time = 1.0`
- Arrays use GDScript syntax: `position = Vector2(0, 0)`

---

## Minimal Template

**Simplest valid scene:**
```ini
[gd_scene format=3]

[node name="Root" type="Node"]
```

**With script attachment:**
```ini
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://script.gd" id="1"]

[node name="Root" type="Node"]
script = ExtResource("1")
```

---

## Header Section

### Format

```ini
[gd_scene load_steps=N format=3 uid="uid://unique_id_here"]
```

**Parameters:**
- `load_steps`: Number of resources to load (count `[ext_resource]` and `[sub_resource]` sections + 1)
- `format`: Always `3` for Godot 4.x
- `uid`: Optional unique identifier (Godot generates if omitted)

### UID Generation

UIDs are base64-like strings. **Best practice**: Omit and let Godot generate.

If you must generate:
```python
import random
import base64

def generate_uid():
    random_bytes = random.randbytes(16)
    encoded = base64.b64encode(random_bytes).decode('ascii')
    # Clean up to match Godot format
    return encoded.replace('+', '').replace('/', '')[:13]

uid = f"uid://{generate_uid()}"
```

**Example output:**
```ini
[gd_scene load_steps=2 format=3 uid="uid://b8kx5m2vgwxyz"]
```

---

## External Resources Section

External resources are files referenced by this scene (scripts, textures, other scenes).

### Script Resource

```ini
[ext_resource type="Script" path="res://path/to/script.gd" id="1"]
```

### Texture Resource

```ini
[ext_resource type="Texture2D" path="res://assets/sprite.png" id="2"]
```

### Scene Resource (for instancing)

```ini
[ext_resource type="PackedScene" path="res://scenes/child_scene.tscn" id="3"]
```

**Referencing in nodes:**
```ini
[node name="Sprite" type="Sprite2D"]
texture = ExtResource("2")
```

---

## Node Section

### Basic Node

```ini
[node name="NodeName" type="NodeType"]
```

**Common node types:**
- `Node` - Base node
- `Node2D` - 2D base
- `Node3D` - 3D base (Godot 4)
- `Control` - UI base
- `Timer` - Timer utility
- `Area2D` - 2D area detection
- `Sprite2D` - 2D sprite display
- `CollisionShape2D` - 2D collision shape
- `Label` - UI text label
- `Button` - UI button

### Node with Parent

```ini
[node name="Child" type="Node2D" parent="."]
```

**Parent notation:**
- `.` = root node
- `Parent/Child` = nested path
- Use `/` for path separators

### Node with Properties

```ini
[node name="Timer" type="Timer"]
wait_time = 1.0
one_shot = false
autostart = true
```

---

## Property Types

### Strings

```ini
text = "Hello World"
placeholder = "Enter text..."
```

### Numbers

```ini
# Integers
health = 100
max_count = 50

# Floats (always include decimal)
wait_time = 1.0
speed = 250.0
```

### Booleans

```ini
one_shot = true
autostart = false
visible = true
```

### Vectors

```ini
# Vector2
position = Vector2(100, 200)
scale = Vector2(1.5, 1.5)

# Vector3
position = Vector3(0, 10, 0)
```

### Colors

```ini
modulate = Color(1, 0, 0, 1)  # RGBA
self_modulate = Color(0.5, 0.5, 1, 1)
```

### Enums

```ini
# Timer process mode
process_callback = 1  # Use integer value

# Often need to look up enum value
# Timer.TIMER_PROCESS_PHYSICS = 0
# Timer.TIMER_PROCESS_IDLE = 1
```

### Resources

```ini
texture = ExtResource("2")
script = ExtResource("1")
```

---

## Complete Templates by Node Type

### Timer

```ini
[gd_scene format=3]

[node name="Timer" type="Timer"]
wait_time = 1.0
one_shot = false
autostart = false
```

**Common properties:**
- `wait_time: float` - Duration in seconds
- `one_shot: bool` - Fire once or repeat
- `autostart: bool` - Start on scene load
- `process_callback: int` - 0=physics, 1=idle

---

### Area2D

```ini
[gd_scene format=3]

[node name="Area2D" type="Area2D"]
monitoring = true
monitorable = true

[node name="CollisionShape2D" type="CollisionShape2D" parent="."]
```

**Common properties:**
- `monitoring: bool` - Detect other bodies
- `monitorable: bool` - Can be detected
- `collision_layer: int` - Physics layer (bitmask)
- `collision_mask: int` - Detection mask (bitmask)

**Note:** CollisionShape2D requires a `shape` sub-resource (see Sub-Resources section).

---

### Sprite2D

```ini
[gd_scene load_steps=2 format=3]

[ext_resource type="Texture2D" path="res://icon.png" id="1"]

[node name="Sprite2D" type="Sprite2D"]
texture = ExtResource("1")
centered = true
```

**Common properties:**
- `texture: Texture2D` - Image to display
- `centered: bool` - Center on position
- `offset: Vector2` - Texture offset
- `hframes: int` - Sprite sheet columns
- `vframes: int` - Sprite sheet rows
- `frame: int` - Current frame index

---

### CollisionShape2D

```ini
[gd_scene load_steps=2 format=3]

[sub_resource type="RectangleShape2D" id="1"]
size = Vector2(50, 50)

[node name="CollisionShape2D" type="CollisionShape2D"]
shape = SubResource("1")
```

**Common shapes:**
- `RectangleShape2D` - Box shape
- `CircleShape2D` - Circle shape
- `CapsuleShape2D` - Capsule shape

---

### Control (UI Base)

```ini
[gd_scene format=3]

[node name="Control" type="Control"]
layout_mode = 3
anchors_preset = 15
anchor_right = 1.0
anchor_bottom = 1.0
grow_horizontal = 2
grow_vertical = 2
```

**Common properties:**
- `layout_mode: int` - Layout calculation mode
- `anchors_preset: int` - Predefined anchor configuration
- `anchor_left/right/top/bottom: float` - Anchor positions (0.0-1.0)
- `offset_left/right/top/bottom: float` - Offset from anchors
- `grow_horizontal/vertical: int` - Grow direction

---

### Label

```ini
[gd_scene format=3]

[node name="Label" type="Label"]
text = "Hello World"
horizontal_alignment = 1
vertical_alignment = 1
```

**Common properties:**
- `text: String` - Display text
- `horizontal_alignment: int` - 0=left, 1=center, 2=right
- `vertical_alignment: int` - 0=top, 1=center, 2=bottom
- `autowrap_mode: int` - Text wrapping mode

---

### Button

```ini
[gd_scene format=3]

[node name="Button" type="Button"]
text = "Click Me"
flat = false
```

**Common properties:**
- `text: String` - Button label
- `flat: bool` - Flat style
- `disabled: bool` - Interactive state
- `toggle_mode: bool` - Toggle button

---

## Sub-Resources Section

Sub-resources are embedded resources (shapes, materials, etc.) used within the scene.

### Rectangle Shape

```ini
[sub_resource type="RectangleShape2D" id="1"]
size = Vector2(50, 50)
```

### Circle Shape

```ini
[sub_resource type="CircleShape2D" id="2"]
radius = 25.0
```

### Capsule Shape

```ini
[sub_resource type="CapsuleShape2D" id="3"]
radius = 20.0
height = 60.0
```

### Using Sub-Resources

```ini
[gd_scene load_steps=2 format=3]

[sub_resource type="RectangleShape2D" id="1"]
size = Vector2(50, 50)

[node name="CollisionShape2D" type="CollisionShape2D"]
shape = SubResource("1")
```

**Note:** Update `load_steps` to include sub-resources.

---

## Complete Multi-Node Examples

### Timer with Script

```ini
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://components/damage_timer.gd" id="1"]

[node name="DamageTimer" type="Timer"]
script = ExtResource("1")
wait_time = 0.5
one_shot = false
autostart = false
```

---

### Area2D with Collision Shape

```ini
[gd_scene load_steps=2 format=3]

[sub_resource type="CircleShape2D" id="1"]
radius = 50.0

[node name="DetectionArea" type="Area2D"]
monitoring = true
monitorable = false

[node name="CollisionShape2D" type="CollisionShape2D" parent="."]
shape = SubResource("1")
```

---

### Sprite with Multiple Children

```ini
[gd_scene load_steps=3 format=3]

[ext_resource type="Texture2D" path="res://assets/player.png" id="1"]

[sub_resource type="RectangleShape2D" id="1"]
size = Vector2(32, 48)

[node name="Player" type="Node2D"]

[node name="Sprite2D" type="Sprite2D" parent="."]
texture = ExtResource("1")

[node name="CollisionShape2D" type="CollisionShape2D" parent="."]
shape = SubResource("1")
```

---

### Nested Hierarchy

```ini
[gd_scene format=3]

[node name="Root" type="Node2D"]

[node name="Parent" type="Node2D" parent="."]
position = Vector2(100, 100)

[node name="Child" type="Node2D" parent="Parent"]
position = Vector2(50, 0)

[node name="GrandChild" type="Sprite2D" parent="Parent/Child"]
```

---

## Signal Connections

Signals can be connected in .tscn files:

```ini
[node name="Button" type="Button"]
text = "Click"

[connection signal="pressed" from="Button" to="." method="_on_button_pressed"]
```

**Format:**
```ini
[connection signal="signal_name" from="source_node" to="target_node" method="method_name"]
```

**Best practice:** Connect signals in script `_ready()` instead for clarity.

---

## Instancing Other Scenes

```ini
[gd_scene load_steps=2 format=3]

[ext_resource type="PackedScene" path="res://scenes/bullet.tscn" id="1"]

[node name="Root" type="Node2D"]

[node name="BulletInstance" parent="." instance=ExtResource("1")]
position = Vector2(100, 100)
```

**Override properties:**
```ini
[node name="BulletInstance" parent="." instance=ExtResource("1")]
position = Vector2(100, 100)
modulate = Color(1, 0, 0, 1)
```

---

## Common Mistakes

| Mistake | Problem | Fix |
|---------|---------|-----|
| Missing decimal in float | `wait_time = 1` | Use `wait_time = 1.0` |
| Wrong quotes | `text = 'value'` | Use double quotes: `text = "value"` |
| Incorrect load_steps | Scene won't load | Count all ext_resource + sub_resource + 1 |
| Missing node type | Invalid scene | Always include `type="NodeType"` |
| Wrong parent path | Node not where expected | Use `.` for root, `/` for separators |
| Enum as string | Property ignored | Use integer enum value |
| Missing shape for collision | Collision doesn't work | Add sub_resource for shape |

---

## Validation Checklist

Before saving a generated .tscn file:

- [ ] `[gd_scene]` header present with `format=3`
- [ ] `load_steps` matches resource count
- [ ] All `[ext_resource]` have unique IDs
- [ ] All `[sub_resource]` have unique IDs
- [ ] Root `[node]` exists (no `parent`)
- [ ] All child nodes have valid `parent` paths
- [ ] All `type` attributes are valid Godot types
- [ ] Floats include decimal point
- [ ] Strings use double quotes
- [ ] No syntax errors (test by opening in Godot)

---

## Testing Generated Scenes

```bash
# Open scene in Godot (will show errors if invalid)
godot --editor -e path/to/scene.tscn

# Check for errors in console
# Valid scene = no red errors
```

**Automated validation** (Python):

```python
import re

def validate_tscn(filepath):
    with open(filepath) as f:
        content = f.read()

    errors = []

    # Check header
    if not re.search(r'\[gd_scene.*format=3', content):
        errors.append("Missing or invalid gd_scene header")

    # Check root node
    if not re.search(r'\[node name="[^"]+" type="[^"]+"\]', content):
        errors.append("Missing root node")

    # Check property syntax
    for line in content.split('\n'):
        if '=' in line and not line.startswith('['):
            if not re.match(r'^[a-z_]+ = ', line.strip()):
                errors.append(f"Invalid property syntax: {line}")

    return errors

errors = validate_tscn("generated_scene.tscn")
if errors:
    print("Validation errors:", errors)
else:
    print("Scene is valid")
```

---

## Code Generation Helper

Python function to generate .tscn from parameters:

```python
def generate_tscn(node_type, node_name, properties=None, script_path=None):
    """
    Generate a simple .tscn file.

    Args:
        node_type: Godot node type (e.g., "Timer", "Area2D")
        node_name: Node name in scene tree
        properties: Dict of property_name: value
        script_path: Optional script to attach
    """
    lines = []

    # Header
    load_steps = 2 if script_path else 1
    lines.append(f"[gd_scene load_steps={load_steps} format=3]")
    lines.append("")

    # Script resource
    if script_path:
        lines.append(f'[ext_resource type="Script" path="{script_path}" id="1"]')
        lines.append("")

    # Root node
    lines.append(f'[node name="{node_name}" type="{node_type}"]')
    if script_path:
        lines.append('script = ExtResource("1")')

    # Properties
    if properties:
        for key, value in properties.items():
            if isinstance(value, bool):
                lines.append(f"{key} = {'true' if value else 'false'}")
            elif isinstance(value, (int, float)):
                # Ensure floats have decimal
                if isinstance(value, float) and '.' not in str(value):
                    value = f"{value}.0"
                lines.append(f"{key} = {value}")
            elif isinstance(value, str):
                lines.append(f'{key} = "{value}"')
            else:
                # Complex types (Vector2, etc.) - pass as string
                lines.append(f"{key} = {value}")

    return "\n".join(lines)

# Usage
tscn = generate_tscn(
    node_type="Timer",
    node_name="DamageTimer",
    properties={
        "wait_time": 1.0,
        "one_shot": False,
        "autostart": False
    },
    script_path="res://components/damage_timer.gd"
)

with open("damage_timer.tscn", "w") as f:
    f.write(tscn)
```

---

## Real-World Code → .tscn Examples

### Example 1: Timer Creation

**Code:**
```gdscript
func _ready():
    _damage_timer = Timer.new()
    _damage_timer.wait_time = 0.5
    _damage_timer.one_shot = false
    add_child(_damage_timer)
    _damage_timer.timeout.connect(_on_damage_tick)
```

**Generated .tscn:**
```ini
[gd_scene format=3]

[node name="DamageTimer" type="Timer"]
wait_time = 0.5
one_shot = false
autostart = false
```

**Updated code:**
```gdscript
@onready var _damage_timer: Timer = $DamageTimer

func _ready():
    _damage_timer.timeout.connect(_on_damage_tick)
```

---

### Example 2: Area2D with Shape

**Code:**
```gdscript
func _setup_detection():
    _detection_area = Area2D.new()
    add_child(_detection_area)

    var shape = CircleShape2D.new()
    shape.radius = 100.0

    var collision = CollisionShape2D.new()
    collision.shape = shape
    _detection_area.add_child(collision)

    _detection_area.body_entered.connect(_on_body_detected)
```

**Generated .tscn:**
```ini
[gd_scene load_steps=2 format=3]

[sub_resource type="CircleShape2D" id="1"]
radius = 100.0

[node name="DetectionArea" type="Area2D"]

[node name="CollisionShape2D" type="CollisionShape2D" parent="."]
shape = SubResource("1")
```

**Updated code:**
```gdscript
@onready var _detection_area: Area2D = $DetectionArea

func _ready():
    _detection_area.body_entered.connect(_on_body_detected)
```

---

## Component Library Pattern

When extracting code-created nodes, use the modular component pattern from `scene-reusability-patterns.md`.

### Configurable Component Scene Template

**Base component for maximum reusability:**

```ini
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://components/{category}/configurable_{type}.gd" id="1"]

[node name="{Type}" type="{NodeType}"]
script = ExtResource("1")
```

**Example - Configurable Timer:**

```ini
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://components/timers/configurable_timer.gd" id="1"]

[node name="Timer" type="Timer"]
script = ExtResource("1")
```

**Example - Configurable Area2D:**

```ini
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://components/areas/configurable_area.gd" id="1"]

[node name="Area2D" type="Area2D"]
script = ExtResource("1")

[node name="CollisionShape2D" parent="." type="CollisionShape2D"]
```

### Parent Scene Using Component with Preset

**Parent scene instances reusable component with preset:**

```ini
[gd_scene load_steps=4 format=3]

[ext_resource type="PackedScene" path="res://components/timers/configurable_timer.tscn" id="1"]
[ext_resource type="Resource" path="res://components/timers/presets/damage_timer.tres" id="2"]
[ext_resource type="Resource" path="res://components/timers/presets/cooldown_timer.tres" id="3"]

[node name="Parent" type="Node2D"]

[node name="DamageTimer" parent="." instance=ExtResource("1")]
config = ExtResource("2")

[node name="CooldownTimer" parent="." instance=ExtResource("1")]
config = ExtResource("3")
```

**Key Points:**
- Same `configurable_timer.tscn` reused (id="1")
- Different presets assigned (id="2" and id="3")
- `load_steps` counts total resources: 3 (timer.tscn) + 2 (presets) + 1 = 6 → but we don't count parent references, so it's load_steps=4
- Zero scene duplication
- Maximum reusability

### Hierarchical Component Template

**For components with nested nodes:**

```ini
[gd_scene load_steps=3 format=3]

[ext_resource type="Script" path="res://components/physics/configurable_body.gd" id="1"]

[sub_resource type="BoxShape2D" id="1"]
size = Vector2(50, 50)

[node name="Body" type="RigidBody2D"]
script = ExtResource("1")

[node name="Sprite2D" parent="." type="Sprite2D"]

[node name="CollisionShape2D" parent="." type="CollisionShape2D"]
shape = SubResource("1")
```

---

**Use this guide** in Operation A of the refactoring skill to generate valid .tscn files automatically.
