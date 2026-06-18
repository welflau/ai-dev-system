---
name: godot-setup-animationtree
version: 1.0.0
displayName: 设置 AnimationTree 状态机
description: >
  用于设置 AnimationTree 节点的状态机驱动动画，
  创建 AnimationNodeStateMachine 图形，配置 BlendSpace2D/3D
  进行运动混合，实现状态过渡条件，
  或创建动画混合树进行复杂的动画混合。
  支持玩家角色动画、NPC 和复杂动画系统。
author: Asreonn
license: MIT
category: game-development
type: tool
difficulty: advanced
audience: [developers]
keywords:
  - godot
  - animation
  - animationtree
  - state-machine
  - blendspace
  - blendspace2d
  - blendspace3d
  - transitions
  - animationtreeplayer
  - locomotion
platforms: [macos, linux, windows]
repository: https://github.com/asreonn/godot-superpowers
homepage: https://github.com/asreonn/godot-superpowers#readme

permissions:
  filesystem:
    read: [".gd", ".tscn", ".tres"]
    write: [".tscn", ".tres", ".gd"]
  git: true

behavior:
  auto_rollback: true
  validation: true
  git_commits: true

outputs: "AnimationTree 节点配置、AnimationNodeStateMachine 图形、BlendSpace2D/3D 设置、过渡条件、动画控制器脚本"
requirements: "Git 仓库，Godot 4.x，AnimatedSprite3D 或带 AnimationPlayer 的 Sprite2D"
execution: "全自动场景生成和脚本更新"
integration: "与 godot-add-signals 配合处理动画事件，与 godot-extract-to-scenes 配合组织角色场景"
---

# 设置 AnimationTree 状态机

## 核心原则

**动画是状态驱动的，不是帧驱动的。** 使用 AnimationTree 管理动画状态，使用 BlendSpace 进行平滑的参数混合，使用过渡实现状态切换。避免在游戏逻辑代码中直接调用 AnimationPlayer 播放。

## 本技能的功能

设置完整的 AnimationTree 系统：

1. **AnimationTree Node 结构** - 创建树节点并绑定动画播放器
2. **AnimationNodeStateMachine** - 构建包含入口/出口状态的状态机图形
3. **BlendSpace2D/3D** - 基于速度/输入配置运动混合
4. **状态过渡** - 定义条件（布尔、表达式、基于时间）的状态切换
5. **混合树** - 使用 OneShot、Add2、Blend2 节点创建复杂的动画混合

## AnimationTree 设置

### 基本 AnimationTree 配置

**修改前（直接使用 AnimationPlayer）：**
```gdscript
# player_animation.gd - Manual animation management
extends CharacterBody2D

@onready var anim_player: AnimationPlayer = $AnimationPlayer

func _physics_process(delta):
    var velocity = Input.get_vector("ui_left", "ui_right", "ui_up", "ui_down")

    if velocity.length() > 0:
        if not anim_player.current_animation == "run":
            anim_player.play("run")
    else:
        if not anim_player.current_animation == "idle":
            anim_player.play("idle")
```

**修改后（使用 AnimationTree）：**
```gdscript
# player_animation.gd - State-driven animation
extends CharacterBody2D

@onready var animation_tree: AnimationTree = $AnimationTree
@onready var playback: AnimationNodeStateMachinePlayback

func _ready():
    animation_tree.active = true
    playback = animation_tree.get("parameters/playback")

func _physics_process(delta):
    var input_dir = Input.get_vector("ui_left", "ui_right", "ui_up", "ui_down")

    # Update blend position for BlendSpace2D
    animation_tree.set("parameters/blend_position", input_dir)

    # Transition states
    if input_dir.length() > 0.1:
        playback.travel("Locomotion")
    else:
        playback.travel("Idle")
```

**生成的场景：**
```ini
# player.tscn
[gd_scene load_steps=6 format=3]

[ext_resource type="Script" path="res://player_animation.gd" id="1_abc123"]

[sub_resource type="AnimationNodeAnimation" id="AnimationNodeAnimation_idle"]
animation = &"idle"

[sub_resource type="AnimationNodeBlendSpace2D" id="AnimationNodeBlendSpace2D_loco"]
blend_point_0/node = SubResource("AnimationNodeAnimation_idle")
blend_point_0/pos = Vector2(0, 0)
blend_point_1/node = SubResource("AnimationNodeAnimation_walk")
blend_point_1/pos = Vector2(0, 1)
blend_point_2/node = SubResource("AnimationNodeAnimation_run")
blend_point_2/pos = Vector2(0, 1.5)

[sub_resource type="AnimationNodeStateMachine" id="AnimationNodeStateMachine_main"]
states/Idle/node = SubResource("AnimationNodeAnimation_idle")
states/Idle/position = Vector2(300, 100)
states/Locomotion/node = SubResource("AnimationNodeBlendSpace2D_loco")
states/Locomotion/position = Vector2(500, 100)

[sub_resource type="AnimationNodeStateMachinePlayback" id="AnimationNodeStateMachinePlayback_main"]

[node name="Player" type="CharacterBody2D"]
script = ExtResource("1_abc123")

[node name="AnimationPlayer" type="AnimationPlayer" parent="."]

[node name="AnimationTree" type="AnimationTree" parent="."]
anim_player = NodePath("../AnimationPlayer")
tree_root = SubResource("AnimationNodeStateMachine_main")
parameters/playback = SubResource("AnimationNodeStateMachinePlayback_main")
parameters/blend_position = Vector2(0, 0)
```

### AnimationTree 激活

```gdscript
# Essential setup for AnimationTree
func _ready():
    # Activate the tree (must be done after node is ready)
    animation_tree.active = true

    # Get reference to state machine playback
    playback = animation_tree.get("parameters/playback")

    # Optional: Set initial state
    playback.start("Idle")
```

## AnimationNodeStateMachine

### 状态机结构

**状态机图形：**
```ini
# State machine nodes in .tscn format
[sub_resource type="AnimationNodeStateMachine" id="AnimationNodeStateMachine_character"]
states/Start/position = Vector2(150, 100)
states/End/position = Vector2(800, 100)

# Idle state (single animation)
states/Idle/node = SubResource("AnimationNodeAnimation_idle")
states/Idle/position = Vector2(300, 100)

# Locomotion (blend space)
states/Locomotion/node = SubResource("AnimationNodeBlendSpace2D_loco")
states/Locomotion/position = Vector2(500, 100)

# Attack (one-shot animation)
states/Attack/node = SubResource("AnimationNodeOneShot_attack")
states/Attack/position = Vector2(500, 300)

# Death state
states/Death/node = SubResource("AnimationNodeAnimation_death")
states/Death/position = Vector2(700, 100)
```

### 状态过渡

**过渡配置：**
```ini
# Transitions between states
[sub_resource type="AnimationNodeStateMachine" id="AnimationNodeStateMachine_character"]

# Idle -> Locomotion (auto on bool parameter)
transitions = ["Idle", "Locomotion", SubResource("AnimationNodeStateMachineTransition_idle_to_loco")]

# Locomotion -> Idle
transitions = ["Locomotion", "Idle", SubResource("AnimationNodeStateMachineTransition_loco_to_idle")]

# Any State -> Attack (using Attack trigger)
transitions = ["Start", "Attack", SubResource("AnimationNodeStateMachineTransition_attack")]

# Any State -> Death
transitions = ["Start", "Death", SubResource("AnimationNodeStateMachineTransition_death")]
```

**过渡 Resource 定义：**
```gdscript
# Transition with condition
var transition = AnimationNodeStateMachineTransition.new()
transition.switch_mode = AnimationNodeStateMachineTransition.SWITCH_MODE_IMMEDIATE
transition.advance_mode = AnimationNodeStateMachineTransition.ADVANCE_MODE_AUTO
transition.advance_condition = "is_moving"

# Transition with expression (Godot 4.1+)
transition.advance_expression = "velocity.length() > 0.1"

# Transition with time condition
transition.switch_mode = AnimationNodeStateMachineTransition.SWITCH_MODE_AT_END
```

### 播放控制

```gdscript
# State machine playback script
extends CharacterBody2D

@onready var animation_tree: AnimationTree = $AnimationTree
var playback: AnimationNodeStateMachinePlayback

func _ready():
    animation_tree.active = true
    playback = animation_tree.get("parameters/playback")

func _physics_process(delta):
    # Transition to locomotion state
    if velocity.length() > 0.1:
        playback.travel("Locomotion")
    else:
        playback.travel("Idle")

    # Trigger attack (OneShot)
    if Input.is_action_just_pressed("attack"):
        playback.travel("Attack")

    # Trigger death (immediate)
    if health <= 0:
        playback.travel("Death")

func stop_movement():
    # Stop at current state
    playback.stop()

func reset_to_idle():
    # Start over from Start node
    playback.start("Idle")
```

## BlendSpace2D 配置

### 运动混合空间

**修改前（无混合）：**
```gdscript
# Discrete animations - jarring transitions
func update_animation():
    if velocity.length() < 0.1:
        anim_player.play("idle")
    elif velocity.length() < 100:
        anim_player.play("walk")
    else:
        anim_player.play("run")
```

**修改后（使用 BlendSpace2D）：**
```gdscript
# Smooth blending between all animations
func _physics_process(delta):
    # Normalize velocity for blend position (-1 to 1)
    var blend_pos = velocity / max_speed
    animation_tree.set("parameters/Locomotion/blend_position", blend_pos)
```

**生成的 BlendSpace2D：**
```ini
# BlendSpace2D resource
[sub_resource type="AnimationNodeBlendSpace2D" id="AnimationNodeBlendSpace2D_loco"]

# Center - Idle
blend_point_0/node = SubResource("AnimationNodeAnimation_idle")
blend_point_0/pos = Vector2(0, 0)

# Up - Walk North
blend_point_1/node = SubResource("AnimationNodeAnimation_walk_north")
blend_point_1/pos = Vector2(0, -1)

# Down - Walk South
blend_point_2/node = SubResource("AnimationNodeAnimation_walk_south")
blend_point_2/pos = Vector2(0, 1)

# Left - Walk West
blend_point_3/node = SubResource("AnimationNodeAnimation_walk_west")
blend_point_3/pos = Vector2(-1, 0)

# Right - Walk East
blend_point_4/node = SubResource("AnimationNodeAnimation_walk_east")
blend_point_4/pos = Vector2(1, 0)

# Diagonal blends (automatically interpolated)
blend_point_5/node = SubResource("AnimationNodeAnimation_walk_northeast")
blend_point_5/pos = Vector2(0.707, -0.707)

# Blend mode
blend_mode = 1  # BLEND_MODE_INTERPOLATED
min_space = Vector2(-1.5, -1.5)
max_space = Vector2(1.5, 1.5)
```

### BlendSpace2D 设置脚本

```gdscript
# Programmatically create BlendSpace2D
func create_locomotion_blend_space() -> AnimationNodeBlendSpace2D:
    var blend_space = AnimationNodeBlendSpace2D.new()

    # Add idle animation at center
    var idle_node = AnimationNodeAnimation.new()
    idle_node.animation = "idle"
    blend_space.add_blend_point(idle_node, Vector2.ZERO)

    # Add directional walks
    var walk_north = AnimationNodeAnimation.new()
    walk_north.animation = "walk_north"
    blend_space.add_blend_point(walk_north, Vector2(0, -1))

    var walk_south = AnimationNodeAnimation.new()
    walk_south.animation = "walk_south"
    blend_space.add_blend_point(walk_south, Vector2(0, 1))

    var walk_east = AnimationNodeAnimation.new()
    walk_east.animation = "walk_east"
    blend_space.add_blend_point(walk_east, Vector2(1, 0))

    var walk_west = AnimationNodeAnimation.new()
    walk_west.animation = "walk_west"
    blend_space.add_blend_point(walk_west, Vector2(-1, 0))

    # Configure blend triangles for proper interpolation
    blend_space.add_triangle(0, 1, 4)  # Idle, North, East
    blend_space.add_triangle(0, 4, 2)  # Idle, East, South
    blend_space.add_triangle(0, 2, 3)  # Idle, South, West
    blend_space.add_triangle(0, 3, 1)  # Idle, West, North

    return blend_space
```

### 参数驱动的混合空间

```gdscript
# Update blend space based on input/velocity
func update_locomotion_blend():
    var input_dir = Input.get_vector("move_left", "move_right", "move_up", "move_down")

    # Calculate blend position based on input
    var blend_position = input_dir

    # Apply to AnimationTree
    animation_tree.set("parameters/Locomotion/blend_position", blend_position)

    # Also update speed scale for walk/run distinction
    var speed = velocity.length()
    var speed_scale = clamp(speed / base_speed, 0.5, 2.0)
    animation_tree.set("parameters/Locomotion/speed_scale", speed_scale)
```

## BlendSpace3D 配置

### 3D 运动混合空间

```ini
# BlendSpace3D for 3D characters
[sub_resource type="AnimationNodeBlendSpace3D" id="AnimationNodeBlendSpace3D_loco3d"]

# Idle at center
blend_point_0/node = SubResource("AnimationNodeAnimation_idle_3d")
blend_point_0/pos = Vector3(0, 0, 0)

# Cardinal directions
blend_point_1/node = SubResource("AnimationNodeAnimation_walk_forward")
blend_point_1/pos = Vector3(0, 0, 1)

blend_point_2/node = SubResource("AnimationNodeAnimation_walk_backward")
blend_point_2/pos = Vector3(0, 0, -1)

blend_point_3/node = SubResource("AnimationNodeAnimation_strafe_left")
blend_point_3/pos = Vector3(-1, 0, 0)

blend_point_4/node = SubResource("AnimationNodeAnimation_strafe_right")
blend_point_4/pos = Vector3(1, 0, 0)

# Run variants at higher magnitude
blend_point_5/node = SubResource("AnimationNodeAnimation_run_forward")
blend_point_5/pos = Vector3(0, 0, 1.5)
```

**3D 角色动画脚本：**
```gdscript
# character_3d.gd
extends CharacterBody3D

@onready var animation_tree: AnimationTree = $AnimationTree

func _physics_process(delta):
    # Get local velocity relative to character rotation
    var local_velocity = transform.basis.inverse() * velocity

    # Normalize for blend position
    var blend_pos = Vector3(
        clamp(local_velocity.x / max_speed, -1, 1),
        0,
        clamp(local_velocity.z / max_speed, -1, 1)
    )

    # Update blend space
    animation_tree.set("parameters/Locomotion3D/blend_position", blend_pos)

    # Update animation speed based on actual velocity
    var speed_factor = velocity.length() / max_speed
    animation_tree.set("parameters/Locomotion3D/speed_scale", clamp(speed_factor, 0.5, 1.5))
```

## 状态过渡

### 布尔条件过渡

```gdscript
# Setup boolean condition in AnimationTree
func setup_conditions():
    # Set condition values
    animation_tree.set("parameters/conditions/is_moving", velocity.length() > 0.1)
    animation_tree.set("parameters/conditions/is_attacking", Input.is_action_pressed("attack"))
    animation_tree.set("parameters/conditions/is_grounded", is_on_floor())
    animation_tree.set("parameters/conditions/is_dead", health <= 0)
```

**对应的场景配置：**
```ini
[sub_resource type="AnimationNodeStateMachineTransition" id="AnimationNodeStateMachineTransition_idle_to_move"]
advance_mode = 1  # ADVANCE_MODE_AUTO
advance_condition = "is_moving"

[sub_resource type="AnimationNodeStateMachineTransition" id="AnimationNodeStateMachineTransition_move_to_idle"]
advance_mode = 1
advance_condition = "is_moving"
negated = true

[sub_resource type="AnimationNodeStateMachineTransition" id="AnimationNodeStateMachineTransition_attack"]
advance_mode = 1
advance_condition = "is_attacking"
```

### 基于表达式的过渡

```gdscript
# Godot 4.1+ expression transitions
# No need for manual condition setting

# Transition expression examples:
# "velocity.length() > 0.1"
# "health <= 0"
# "is_on_floor() and Input.is_action_pressed(\"jump\")"
# "anim_time >= 0.8" (requires anim_time parameter tracking)
```

**设置表达式过渡：**
```gdscript
func create_expression_transition(expression: String) -> AnimationNodeStateMachineTransition:
    var transition = AnimationNodeStateMachineTransition.new()
    transition.advance_mode = AnimationNodeStateMachineTransition.ADVANCE_MODE_AUTO
    transition.advance_expression = expression
    return transition

# Usage
var jump_transition = create_expression_transition("is_on_floor() and Input.is_action_pressed('jump')")
state_machine.add_transition("Idle", "Jump", jump_transition)
```

### 基于时间的过渡

```gdscript
# Transition at end of animation
var end_transition = AnimationNodeStateMachineTransition.new()
end_transition.switch_mode = AnimationNodeStateMachineTransition.SWITCH_MODE_AT_END
end_transition.advance_mode = AnimationNodeStateMachineTransition.ADVANCE_MODE_AUTO

# Transition after specific time
var time_transition = AnimationNodeStateMachineTransition.new()
time_transition.switch_mode = AnimationNodeStateMachineTransition.SWITCH_MODE_AT_END
time_transition.advance_mode = AnimationNodeStateMachineTransition.ADVANCE_MODE_AUTO
# Add custom wait time via expression
```

## 混合树

### 复杂动画混合

**用于动作的 OneShot：**
```ini
[sub_resource type="AnimationNodeOneShot" id="AnimationNodeOneShot_attack"]
animation = SubResource("AnimationNodeAnimation_attack")
fadein_time = 0.1
fadeout_time = 0.15
mix_mode = 0  # ONE_SHOT_MIX_MODE_BLEND
```

**用于平滑过渡的 Blend2：**
```ini
[sub_resource type="AnimationNodeBlend2" id="AnimationNodeBlend2_action"]
```

**用于叠加的 Add2：**
```ini
[sub_resource type="AnimationNodeAdd2" id="AnimationNodeAdd2_recoil"]
# Adds recoil on top of base animation
```

**用于速度控制的 TimeScale：**
```ini
[sub_resource type="AnimationNodeTimeScale" id="AnimationNodeTimeScale_run"]
scale = 1.0  # Modified at runtime
```

### 完整混合树示例

```ini
# Complex blend tree with layering
[sub_resource type="AnimationNodeBlendTree" id="AnimationNodeBlendTree_complex"]

# Input animations
nodes/Animation/node = SubResource("AnimationNodeAnimation_idle")
nodes/Animation/position = Vector2(100, 100)

# Time scale for speed control
nodes/TimeScale/node = SubResource("AnimationNodeTimeScale_var")
nodes/TimeScale/position = Vector2(300, 100)
nodes/TimeScale/input_0 = SubResource("AnimationNodeAnimation_idle")

# OneShot for hit reaction (layered on top)
nodes/HitReaction/node = SubResource("AnimationNodeOneShot_hit")
nodes/HitReaction/position = Vector2(500, 100)
nodes/HitReaction/input_0 = SubResource("AnimationNodeTimeScale_var")

# Add2 for weapon sway
nodes/WeaponSway/node = SubResource("AnimationNodeAdd2_sway")
nodes/WeaponSway/position = Vector2(700, 100)
nodes/WeaponSway/input_0 = SubResource("AnimationNodeOneShot_hit")
nodes/WeaponSway/input_1 = SubResource("AnimationNodeAnimation_sway")

# Output
nodes/Output/position = Vector2(900, 100)
node_connections = [&"output", 0, &"WeaponSway"]
```

**混合树脚本控制：**
```gdscript
# Control blend tree parameters
func update_blend_tree():
    # Update time scale based on movement speed
    var speed = velocity.length()
    var time_scale = clamp(speed / base_speed, 0.5, 2.0)
    animation_tree.set("parameters/TimeScale/scale", time_scale)

    # Trigger OneShot
    if is_hit:
        animation_tree.set("parameters/HitReaction/active", true)
        animation_tree.set("parameters/HitReaction/internal_active", true)

    # Control Add2 amount (0.0 = no sway, 1.0 = full sway)
    var sway_amount = clamp(speed / max_speed, 0.0, 1.0)
    animation_tree.set("parameters/WeaponSway/add_amount", sway_amount)
```

## 示例

### 2D 角色动画系统

**完整设置：**
```gdscript
# character_animator.gd
extends CharacterBody2D

@onready var animation_tree: AnimationTree = $AnimationTree
@onready var playback: AnimationNodeStateMachinePlayback

@export var max_speed: float = 200.0
@export var blend_smoothness: float = 5.0

var target_blend_position: Vector2 = Vector2.ZERO
var current_blend_position: Vector2 = Vector2.ZERO

func _ready():
    animation_tree.active = true
    playback = animation_tree.get("parameters/playback")

func _physics_process(delta):
    # Get input
    var input_dir = Input.get_vector("move_left", "move_right", "move_up", "move_down")

    # Calculate target blend position
    if input_dir.length() > 0.1:
        target_blend_position = input_dir
        playback.travel("Locomotion")
    else:
        target_blend_position = Vector2.ZERO
        playback.travel("Idle")

    # Smooth blend position transition
    current_blend_position = current_blend_position.lerp(target_blend_position, blend_smoothness * delta)
    animation_tree.set("parameters/Locomotion/blend_position", current_blend_position)

    # Handle actions
    if Input.is_action_just_pressed("attack"):
        playback.travel("Attack")

    if Input.is_action_just_pressed("interact"):
        playback.travel("Interact")

func take_damage():
    playback.travel("Hit")

func die():
    playback.travel("Death")
```

**生成的场景：**
```ini
# animated_character.tscn
[gd_scene load_steps=10 format=3]

[ext_resource type="Script" path="res://character_animator.gd" id="1_anim123"]

# Animation nodes
[sub_resource type="AnimationNodeAnimation" id="AnimationNodeAnimation_idle"]
animation = &"idle"

[sub_resource type="AnimationNodeAnimation" id="AnimationNodeAnimation_attack"]
animation = &"attack"

[sub_resource type="AnimationNodeBlendSpace2D" id="AnimationNodeBlendSpace2D_loco"]
blend_point_0/node = SubResource("AnimationNodeAnimation_idle")
blend_point_0/pos = Vector2(0, 0)
# ... more blend points

# State machine
[sub_resource type="AnimationNodeStateMachine" id="AnimationNodeStateMachine_main"]
states/Start/position = Vector2(150, 100)
states/Idle/node = SubResource("AnimationNodeAnimation_idle")
states/Idle/position = Vector2(300, 100)
states/Locomotion/node = SubResource("AnimationNodeBlendSpace2D_loco")
states/Locomotion/position = Vector2(500, 100)
states/Attack/node = SubResource("AnimationNodeAnimation_attack")
states/Attack/position = Vector2(500, 300)
states/End/position = Vector2(700, 100)

# Transitions
[sub_resource type="AnimationNodeStateMachineTransition" id="AnimationNodeStateMachineTransition_to_loco"]
advance_condition = "is_moving"

[sub_resource type="AnimationNodeStateMachineTransition" id="AnimationNodeStateMachineTransition_to_idle"]
advance_condition = "is_moving"
negated = true

[node name="AnimatedCharacter" type="CharacterBody2D"]
script = ExtResource("1_anim123")

[node name="Sprite2D" type="Sprite2D" parent="."]

[node name="AnimationPlayer" type="AnimationPlayer" parent="."]

[node name="AnimationTree" type="AnimationTree" parent="."]
anim_player = NodePath("../AnimationPlayer")
tree_root = SubResource("AnimationNodeStateMachine_main")
parameters/playback = SubResource("AnimationNodeStateMachinePlayback_main")
parameters/Locomotion/blend_position = Vector2(0, 0)
parameters/conditions/is_moving = false
```

### 战斗动画系统

**攻击连招系统：**
```gdscript
# combat_animator.gd
extends CharacterBody2D

@onready var animation_tree: AnimationTree = $AnimationTree
@onready var playback: AnimationNodeStateMachinePlayback

var combo_count: int = 0
var max_combo: int = 3
var combo_window: float = 0.5
var combo_timer: float = 0.0

func _ready():
    animation_tree.active = true
    playback = animation_tree.get("parameters/playback")

func _physics_process(delta):
    # Update combo timer
    if combo_timer > 0:
        combo_timer -= delta
        if combo_timer <= 0:
            combo_count = 0

    # Handle attack input
    if Input.is_action_just_pressed("attack"):
        perform_attack()

    # Update animation conditions
    animation_tree.set("parameters/conditions/in_combo", combo_count > 0)

func perform_attack():
    match combo_count:
        0:
            playback.travel("Attack1")
        1:
            playback.travel("Attack2")
        2:
            playback.travel("Attack3")
        _:
            combo_count = 0
            playback.travel("Attack1")

    combo_count = (combo_count + 1) % max_combo
    combo_timer = combo_window

func reset_combo():
    combo_count = 0
    combo_timer = 0.0
```

**连招状态机：**
```ini
[sub_resource type="AnimationNodeStateMachine" id="AnimationNodeStateMachine_combat"]
states/Idle/position = Vector2(300, 100)
states/Attack1/position = Vector2(500, 100)
states/Attack2/position = Vector2(500, 200)
states/Attack3/position = Vector2(500, 300)

# Attack1 -> Attack2 transition
[sub_resource type="AnimationNodeStateMachineTransition" id="AnimationNodeStateMachineTransition_a1_a2"]
switch_mode = 1  # SWITCH_MODE_AT_END
advance_mode = 1
advance_condition = "in_combo"

# Attack2 -> Attack3 transition
[sub_resource type="AnimationNodeStateMachineTransition" id="AnimationNodeStateMachineTransition_a2_a3"]
switch_mode = 1
advance_mode = 1
advance_condition = "in_combo"

# All attacks -> Idle (when combo ends)
[sub_resource type="AnimationNodeStateMachineTransition" id="AnimationNodeStateMachineTransition_end"]
switch_mode = 1
advance_mode = 1
negated = true
advance_condition = "in_combo"
```

### NPC 随机待机变体动画

```gdscript
# npc_animator.gd
extends CharacterBody2D

@onready var animation_tree: AnimationTree = $AnimationTree
@onready var playback: AnimationNodeStateMachinePlayback

var idle_variations: Array[String] = ["Idle", "Idle2", "Idle3"]
var idle_timer: float = 0.0
var next_idle_change: float = 5.0

func _ready():
    animation_tree.active = true
    playback = animation_tree.get("parameters/playback")
    pick_random_idle()

func _physics_process(delta):
    # Random idle variation
    idle_timer += delta
    if idle_timer >= next_idle_change and velocity.length() < 0.1:
        idle_timer = 0.0
        next_idle_change = randf_range(3.0, 8.0)
        pick_random_idle()

    # Movement
    if velocity.length() > 0.1:
        playback.travel("Walk")

func pick_random_idle():
    var random_idle = idle_variations[randi() % idle_variations.size()]
    playback.travel(random_idle)
```

## 常用模式

### 动画事件集成

```gdscript
# Connect animation events to gameplay
func _ready():
    animation_tree.animation_started.connect(_on_animation_started)
    animation_tree.animation_finished.connect(_on_animation_finished)

func _on_animation_started(anim_name: StringName):
    match anim_name:
        "attack":
            # Disable movement during attack
            can_move = false
        "dash":
            # Make invincible
            is_invincible = true

func _on_animation_finished(anim_name: StringName):
    match anim_name:
        "attack":
            can_move = true
        "dash":
            is_invincible = false
```

### 动画驱动的移动

```gdscript
# Root motion implementation
func _on_animation_tree_animation_started(anim_name: StringName):
    if anim_name == &"attack":
        # Enable root motion tracking
        animation_tree.set("parameters/Attack/active", true)

func _physics_process(delta):
    # Apply root motion from animation
    var root_motion: Transform3D = animation_tree.get_root_motion()
    global_transform *= root_motion
```

### 平滑状态过渡

```gdscript
# Crossfade duration configuration
var transition = AnimationNodeStateMachineTransition.new()
transition.fade_duration = 0.2  # 200ms crossfade
```

## 安全注意事项

- 访问参数前始终检查 AnimationTree 是否处于激活状态
- 设置树之前验证 AnimationPlayer 包含所有需要的动画
- 优雅处理缺失的混合位置（默认为中心）
- 重新父级或切换场景时重置 AnimationTree
- 在 queue_free() 前断开信号连接

## 不适用场景

在以下情况不要使用 AnimationTree：
- 只有 2-3 个简单动画（过度设计）
- 动画逻辑非常简单（仅播放/停止）
- 低端设备上性能至关重要
- 需要逐帧直接控制

改用直接 AnimationPlayer 控制：
```gdscript
# Simple animation control
func _physics_process(delta):
    if is_moving:
        anim_player.play("walk")
    else:
        anim_player.play("idle")
```

## 集成

可配合以下技能使用：
- **godot-add-signals** - 将动画事件连接到游戏系统
- **godot-extract-to-scenes** - 创建可复用的动画角色场景
- **godot-setup-navigation** - 导航代理配合移动动画
- **godot-migrate-tilemap** - 动画 TileMap 角色

## 性能提示

1. **限制混合点数量** - 通常 4-8 个点就足够
2. **缓存参数路径** - 将参数路径存储为常量
3. **禁用未使用的树** - 不在屏幕上时设置 `active = false`
4. **使用 TimeScale** - 而非直接修改动画速度
5. **批量过渡** - 尽可能将状态变化合并处理
