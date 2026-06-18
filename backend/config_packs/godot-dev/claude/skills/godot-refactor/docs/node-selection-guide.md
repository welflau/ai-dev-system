# Intelligent Node Selection Guide

**Purpose:** Systematically analyze code patterns and intelligently select optimal Godot 4.x nodes with confidence scoring.

**Usage:** Use this guide during refactoring Operation A to detect code-created nodes and select the best node type instead of arbitrary choices.

---

## Overview

When detecting `.new()` calls or manual node creation patterns, use this guide to:

1. Analyze context clues (variable names, properties, methods)
2. Apply decision trees for the general category
3. Calculate confidence score
4. Select optimal node (or ask user if uncertain)

---

## Decision Trees

### 1. Timing/Delay Operations

```
Needs timing or delay?
├─ Wait N seconds then execute once → Timer (one_shot=true)
├─ Wait N seconds then repeat → Timer (one_shot=false)
├─ Animate property value over time → Tween
├─ Frame-by-frame delay → await get_tree().process_frame
├─ Deferred call (next frame) → call_deferred()
└─ Complex animation with keyframes → AnimationPlayer
```

**Key Pattern Recognition:**
- `wait_time`, `Timer.new()` → **Timer**
- `timeout`, `.start()`, `.stop()` → **Timer**
- `tween_property`, `create_tween()`, `animate` → **Tween**
- `_ready()` then pause then `emit_signal()` → **Timer**

**Confidence Multipliers:**
- Variable name contains "timer" → +25%
- Contains `.start()` call → +20%
- Has wait_time property → +40%

---

### 2. Visual 2D Nodes (Static vs Animated)

```
Need visual on screen (2D)?
├─ Static image (no animation)
│  ├─ Simple sprite → Sprite2D
│  ├─ Tiled background → Sprite2D or TileMap
│  ├─ Colored shape → Polygon2D
│  └─ Line/path → Line2D
├─ Animated sprites (frame sequence)
│  ├─ Multiple animation sets → AnimatedSprite2D
│  └─ Single animation → AnimatedSprite2D or AnimationPlayer
├─ Custom drawn shapes → Node2D + _draw()
├─ Advanced rendering → MeshInstance2D
└─ Many identical objects → MultiMeshInstance2D
```

**Key Pattern Recognition:**
- `.texture` property → **Sprite2D**
- `texture` + `region_enabled` → **Sprite2D** with region
- `sprite_frames`, `.play()` → **AnimatedSprite2D**
- `_draw()` method → **Node2D** (custom drawing)
- `vertices`, `polygon` → **Polygon2D**
- `points` (array of Vector2) → **Line2D**

**Confidence Multipliers:**
- Variable name contains "sprite" → +25%
- Has .texture assignment → +30%
- Has .play() or animation → +35%

---

### 3. Physics Bodies (Solid Objects)

```
Needs physics collision/solid body?
├─ Player/character movement (controlled)
│  └─ CharacterBody2D
├─ Physics-driven movement (gravity, forces)
│  ├─ Heavy object → RigidBody2D
│  └─ Light object/projectile → RigidBody2D
├─ Non-moving obstacle/wall/platform
│  └─ StaticBody2D
├─ Animated obstacle (moves but no physics)
│  └─ AnimatableBody2D
└─ Just checking collisions (no solid collision)
   └─ Area2D (detection, not solid)
```

**Key Pattern Recognition:**
- Variable name: player, character → **CharacterBody2D**
- `.move_and_slide()` pattern → **CharacterBody2D**
- `.velocity` assignment → **CharacterBody2D**
- `gravity`, `.apply_force()` → **RigidBody2D**
- Wall, platform, static → **StaticBody2D**
- Trigger, detection, monitoring → **Area2D**
- No collision needed → Regular Node2D

**Confidence Multipliers:**
- Variable contains "player" → +40%
- Has velocity property → +35%
- Has mass property → +30%
- Name contains "wall", "platform" → +30%

---

### 4. Detection/Trigger Areas (Non-Solid)

```
Need to detect overlaps WITHOUT solid collision?
├─ Damage zone/hit area → Area2D
├─ Pickup trigger → Area2D
├─ Sight/detection zone → Area2D
├─ Pressure plate/sensor → Area2D
├─ Win condition/goal area → Area2D
└─ Just visual collision check → Area2D
```

**Key Pattern Recognition:**
- `overlapping_bodies()` → **Area2D**
- `.monitoring = true` → **Area2D**
- `.monitorable = true` → **Area2D**
- Signal: `body_entered`, `body_exited` → **Area2D**
- "area", "zone", "trigger", "detect" in name → **Area2D**

**Confidence Multipliers:**
- Method calls like `get_overlapping_bodies()` → +40%
- Variable name contains "area" or "zone" → +25%
- Connecting to area signals → +35%

---

### 5. Audio Playback

```
Need to play audio?
├─ Background music (non-spatial)
│  └─ AudioStreamPlayer
├─ 2D sound (positional in 2D space)
│  ├─ Footsteps → AudioStreamPlayer2D
│  ├─ Positional effects → AudioStreamPlayer2D
│  └─ Character voice → AudioStreamPlayer2D
├─ 3D sound (positional in 3D space)
│  ├─ 3D effects → AudioStreamPlayer3D
│  ├─ 3D footsteps → AudioStreamPlayer3D
│  └─ 3D voice → AudioStreamPlayer3D
└─ Music → AudioStreamPlayer
```

**Key Pattern Recognition:**
- Parent is Node2D → **AudioStreamPlayer2D**
- Parent is Node3D → **AudioStreamPlayer3D**
- Parent is Node → **AudioStreamPlayer**
- Variable contains "music", "bgm" → **AudioStreamPlayer**
- Variable contains "sfx", "sound" → AudioStreamPlayer2D or 3D
- `.attenuation`, `max_distance` → Audio2D or 3D

**Confidence Multipliers:**
- Parent node type clear → +35%
- Variable name specific → +25%
- Audio settings present → +20%

---

### 6. UI Elements

```
Need UI element?
├─ Text display
│  ├─ Simple text → Label
│  ├─ Formatted text (colors, bold) → RichTextLabel
│  └─ Editable text → TextEdit
├─ User input
│  ├─ Single line input → LineEdit
│  ├─ Multi-line input → TextEdit
│  ├─ Button press → Button
│  ├─ Toggle on/off → CheckBox or CheckButton
│  └─ Dropdown menu → OptionButton
├─ Progress/status
│  ├─ Health/progress bar → ProgressBar
│  ├─ Spinning loading → Control (_draw spinner)
│  └─ Status indicator → ColorRect or Panel
├─ Layout container
│  ├─ Horizontal arrangement → HBoxContainer
│  ├─ Vertical arrangement → VBoxContainer
│  ├─ Grid arrangement → GridContainer
│  ├─ Tabbed interface → TabContainer
│  └─ Scrollable content → ScrollContainer
├─ Image/icon display
│  ├─ Texture in UI → TextureRect
│  └─ Clickable image → TextureButton
└─ Base UI element
   └─ Custom UI logic → Control
```

**Key Pattern Recognition:**
- `.text` property → **Label** (if read-only) or **RichTextLabel** (if formatted)
- `pressed` signal → **Button**
- `text_changed` signal → **LineEdit** or **TextEdit**
- `button_pressed` property → **CheckBox**
- `add_child()` multiple times → **Container** type
- `separation` property → **HBox/VBox/GridContainer**
- Variable contains "label", "text" → UI text node
- Variable contains "button", "btn" → **Button**

**Confidence Multipliers:**
- Variable name matches type → +30%
- Signal connections clear → +25%
- Layout properties present → +20%

---

### 7. Lighting

```
Need 2D lighting?
├─ Localized light source (lantern, torch)
│  └─ PointLight2D
├─ Directional light (sun, moon)
│  └─ DirectionalLight2D
├─ Light that moves with object
│  └─ PointLight2D (as child)
├─ Shadows from objects
│  └─ LightOccluder2D (child of objects)
└─ Light collection/flickering
   └─ Multiple PointLight2D with Tween
```

**Key Pattern Recognition:**
- "light", "lamp", "lantern" in name → **PointLight2D**
- "sun", "moon", "sky" → **DirectionalLight2D**
- `energy`, `color` properties → Light node
- `shadow_enabled` → Any light node

**Confidence Multipliers:**
- "Light" in variable name → +30%
- Has energy/color properties → +25%

---

### 8. Particles

```
Need particle effects?
├─ High performance (modern devices)
│  └─ GPUParticles2D
├─ Compatibility (older devices)
│  └─ CPUParticles2D
├─ CPU control needed
│  └─ CPUParticles2D
└─ Performance critical
   └─ GPUParticles2D
```

**Key Pattern Recognition:**
- "particles", "effect", "explosion" → Particles node
- `emitting = true` → Particles
- `amount` property → Particles
- Mobile/web target → **CPUParticles2D**
- Desktop/modern → **GPUParticles2D**

**Confidence Multipliers:**
- "particle" in name → +35%
- `process_material` property → +25%

---

### 9. Navigation/AI Pathfinding

```
Need AI movement/pathfinding?
├─ AI enemy pathfinding
│  ├─ 2D → NavigationAgent2D
│  └─ 3D → NavigationAgent3D
├─ Define walkable areas
│  ├─ 2D → NavigationRegion2D
│  └─ 3D → NavigationRegion3D
├─ Moving obstacles in path
│  └─ NavigationObstacle2D/3D
└─ Bridge regions/special paths
   └─ NavigationLink2D/3D
```

**Key Pattern Recognition:**
- "agent", "pathfind", "nav" in name → **NavigationAgent**
- "region", "mesh" for navigation → **NavigationRegion**
- Pair of agents moving independently → **NavigationAgent**

**Confidence Multipliers:**
- "agent" in name → +35%
- "path" or "nav" in name → +25%

---

## Variable Name Pattern Matching

Analyze variable names for quick type hints:

```
Pattern → Likely Node Type
=====================================
_timer, timer, *_timer → Timer
_delay, delay_timer → Timer
_sprite, sprite, *_sprite → Sprite2D
_animated_sprite, animated_sprite → AnimatedSprite2D
_body, body, *_body → RigidBody2D or CharacterBody2D
_area, area, detect* → Area2D
_player, player → CharacterBody2D
_label, label, text* → Label
_button, button, btn* → Button
_checkbox, check, toggle* → CheckBox/CheckButton
_input, input* → LineEdit
_progress, progress_bar, health_bar → ProgressBar
_container, *_container → Container type (H/VBox/Grid)
_light, light, lantern → PointLight2D or Light2D
_particles, particle, effect → Particles2D
_camera, camera → Camera2D/Camera3D
_audio, sound, sfx, music → AudioStreamPlayer
_navigation, nav_agent → NavigationAgent2D/3D
```

### Confidence Boost by Name

| Name Pattern | Confidence Boost | Rationale |
|---|---|---|
| Contains type name exactly | +40% | "sprite_2d", "timer" |
| Common abbreviation | +30% | "btn", "sfx", "ui" |
| Semantic name (clear usage) | +25% | "damage_area", "jump_timer" |
| Generic "obj", "node", "entity" | -20% | Insufficient information |
| Multiple meanings possible | -15% | Ambiguous pattern |

---

## Property Assignment Analysis

Analyze property assignments in the next 20 lines for context:

```
Property Pattern → Node Type
================================================
.texture = ... → Sprite2D, TextureRect, TextureButton
.sprite_frames = ... → AnimatedSprite2D
.animation = ... → AnimatedSprite2D, AnimationPlayer
.play() → AnimatedSprite2D, AudioStreamPlayer, Tween
.text = ... → Label, RichTextLabel, LineEdit
.pressed signal → Button, CheckBox, TextureButton
.modulate = ... → CanvasItem (any visual)
.position = ... → Node2D (spatial node)
.rotation = ... → Node2D (spatial node)
.velocity = ... → CharacterBody2D
.mass = ... → RigidBody2D
.wait_time = ... → Timer
.start() → Timer
.monitoring = true → Area2D
.monitorable = true → Area2D
.stream = ... → AudioStreamPlayer variants
.font, .font_size → Label, RichTextLabel, Control text nodes
.color = ... → ColorRect, Light2D, any visual
.size = ... → Control (UI node)
.anchor_*, .offset_* → Control (UI node)
.add_child() → Container (if many)
.columns = ... → GridContainer
.separation = ... → Container nodes
.shape = ... → CollisionShape2D
.collision_layer → Physics body
.navigation_layers → Navigation node
```

### Confidence by Property Count

- 1 property detected: +15% confidence
- 2-3 properties detected: +25% confidence
- 4+ properties detected: +40% confidence
- Conflicting properties: -20% confidence

---

## Method Call Analysis

Analyze method calls in the next 20 lines:

```
Method Pattern → Node Type
================================================
.start(), .stop(), .wait_time → Timer
.play(), .stop() → AnimatedSprite2D, AudioStreamPlayer
.tween_property(), .tween_method() → Tween (or via get_tree().create_tween())
.move_and_slide() → CharacterBody2D
.apply_central_force() → RigidBody2D
.add_child() + positioning → Node2D or Control
.connect() + property_changed → Control or Node
.get_overlapping_bodies() → Area2D
.set_text() → Label, RichTextLabel, LineEdit
.pressed.connect() → Button, CheckBox, TextureButton
.timeout.connect() → Timer
.value assignment → ProgressBar, Range
.columns assignment → GridContainer
```

### Confidence by Method Call Count

- 1 method detected: +10% confidence
- 2 methods detected: +25% confidence
- 3+ methods detected: +35% confidence
- Methods from different node types: -20% confidence

---

## Parent Node Context

Analyze the parent node to refine selection:

```
Parent Type → Child Node Hints
=========================================
CharacterBody2D parent → Likely: Sprite2D, CollisionShape2D, AnimatedSprite2D
RigidBody2D parent → Likely: Sprite2D, CollisionShape2D, Area2D (child trigger)
StaticBody2D parent → Likely: Sprite2D, CollisionPolygon2D
Area2D parent → Likely: CollisionShape2D, CollisionPolygon2D
Node2D parent → Could be many 2D types
Control parent (UI) → Likely: Other Control types, Container children
VBoxContainer parent → Likely: Button, Label, HBoxContainer, other UI
Node parent (no spatial) → Likely: Node (pure logic), Timer, HTTPRequest
Node3D parent → Likely: MeshInstance3D, CollisionShape3D, Light3D
```

### Confidence Adjustment

- Parent type clearly indicates child: +20% confidence
- Parent type ambiguous: No change
- Parent type contradicts child: -30% confidence

---

## Confidence Scoring System

### Calculate Total Confidence

```
Base Confidence: 50%

Variable Name Analysis:
  + Exact type in name: +40%
  + Common abbreviation: +30%
  + Semantic name: +25%
  + Generic name: -20%

Property Analysis:
  + 1 property: +15%
  + 2-3 properties: +25%
  + 4+ properties: +40%
  - Conflicting properties: -20%

Method Call Analysis:
  + 1 method: +10%
  + 2 methods: +25%
  + 3+ methods: +35%
  - Methods from different types: -20%

Parent Context Analysis:
  + Parent clearly indicates: +20%
  + Parent contradicts: -30%

Decision Tree Match:
  + Perfect match in tree: +25%
  + Close match in tree: +15%
  - No match in tree: -15%

Final Score: Sum of adjustments, capped at 99%
(Never reach 100% unless trivial like "Timer.new() with .start()")
```

### Decision by Confidence Score

| Confidence | Action | Example |
|---|---|---|
| 90-99% | Auto-select node | "Wait 0.5 seconds" = Timer at 95% |
| 75-89% | Auto-select with note | "Sprite with velocity" = CharacterBody2D at 82% |
| 60-74% | Auto-select, flag for review | Ambiguous pattern at 70% |
| 50-59% | Ask user (present top 2-3 options) | Generic pattern at 55% |
| <50% | Use safe fallback + flag | Unclear pattern at 40% = Node2D + review |

---

## Heuristic Examples

### Example 1: Timer Pattern

```gdscript
# Code:
_cooldown_timer = Timer.new()
_cooldown_timer.wait_time = 0.5
_cooldown_timer.one_shot = true
add_child(_cooldown_timer)
_cooldown_timer.timeout.connect(_on_cooldown)
```

**Analysis:**
- Variable name: "_cooldown_timer" → +30% (common abbreviation)
- Properties: wait_time, one_shot → +40% (4+ properties count)
- Methods: .timeout.connect() → +35% (3+ methods)
- Parent context: unclear → No change
- Decision tree: Perfect match → +25%

**Total: 50 + 30 + 40 + 35 + 25 = 180% → capped at 95%**

**Decision:** ✅ **Auto-select Timer** (confidence 95%)

---

### Example 2: Ambiguous Sprite

```gdscript
# Code:
_object = Node2D.new()
_object.position = Vector2(100, 100)
```

**Analysis:**
- Variable name: "_object" → -20% (generic name)
- Properties: position → +15% (1 property)
- Methods: none relevant → No change
- Parent context: unknown → No change
- Decision tree: Could be many types → No bonus

**Total: 50 - 20 + 15 = 45%**

**Decision:** ❓ **Ask User** (confidence 45%)
- Option 1: Node2D (generic spatial)
- Option 2: Sprite2D (if visual object)
- Option 3: Area2D (if detection object)

---

### Example 3: Character Movement

```gdscript
# Code:
_player = Node.new()
_player.velocity = Vector2.ZERO
add_child(_player)
# Later: _player.move_and_slide()
```

**Analysis:**
- Variable name: "_player" → +40% (exact match)
- Properties: velocity → +15% (1 property)
- Methods: move_and_slide() → +35% (specific method)
- Parent context: Root likely → No change
- Decision tree: Perfect CharacterBody2D match → +25%

**Total: 50 + 40 + 15 + 35 + 25 = 165% → capped at 95%**

**Decision:** ✅ **Auto-select CharacterBody2D** (confidence 95%)

---

### Example 4: Audio Playback

```gdscript
# Code:
_music = Node.new()
_music.stream = load("res://audio/music.ogg")
_music.play()
```

**Analysis:**
- Variable name: "_music" → +30% (semantic name)
- Properties: stream → +15% (1 property)
- Methods: play() → +10% (1 method)
- Parent context: likely Node → +15% (indicates AudioStreamPlayer)
- Decision tree: Partial match (audio type unclear) → +15%

**Total: 50 + 30 + 15 + 10 + 15 + 15 = 135% → capped at 85%**

**Decision:** ✅ **Auto-select AudioStreamPlayer** (confidence 85%)
Note: "Non-spatial audio detected. If positional needed, suggest AudioStreamPlayer2D/3D"

---

## Decision Tree Application Algorithm

```
function selectNode(code_context):
  1. Extract variable name
  2. Extract properties (next 20 lines)
  3. Extract method calls (next 20 lines)
  4. Identify parent context
  5. For each decision tree:
     - Match code_context against tree
     - If match found: Add confidence from tree
  6. Score = base(50) + name_bonus + property_bonus + method_bonus + parent_bonus + tree_bonus
  7. If score >= 90%: Return selected node
  8. Else if score >= 75%: Return selected node + note
  9. Else if score >= 60%: Return selected node + flag for review
  10. Else if score >= 50%: Ask user (present top options)
  11. Else: Return safe fallback (Node2D for spatial, Node for logic) + flag
```

---

## Safe Fallbacks

When confidence is too low:

| Context | Safe Fallback | Why |
|---|---|---|
| 2D spatial but unclear | Node2D | No physics, safe for any 2D object |
| Pure logic, no context | Node | Works for any non-visual |
| UI but unclear | Control | Works for any UI element |
| Physics but unclear | RigidBody2D | Can adjust mass/constraints |
| Audio but unclear | AudioStreamPlayer | Works for all audio |

---

## Flag for Review

When confidence is 50-75%, always create a code review comment:

```
# 🔍 REVIEW: Uncertain node type selection
# Detected: Timer or Tween (confidence: 65%)
# Decision: Timer selected
# Reason: wait_time property present, but .tween_property() also possible
# Suggestion: Verify timing behavior and adjust if needed
```

---

## Summary

Use this guide to:

1. **Recognize patterns** in variable names, properties, methods
2. **Apply decision trees** for the general category
3. **Calculate confidence** using heuristics
4. **Auto-select** when confidence ≥90%
5. **Ask user** when confidence 50-75%
6. **Flag for review** when confidence 60-75%
7. **Use safe fallbacks** when confidence <50%

This system enables intelligent, automated node selection with user involvement only when genuinely uncertain.
