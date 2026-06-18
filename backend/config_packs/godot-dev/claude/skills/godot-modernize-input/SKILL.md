---
name: godot-modernize-input
version: 2.0.0
displayName: 现代化输入处理
description: >
  在 Godot 4.x 项目中处理输入并需要现代化模式时使用。
  从硬编码的按键检测生成 Input Map 配置，设置手柄震动（Godot 4.x 功能），
  实现移动端陀螺仪/加速度计输入，创建不同游戏状态的上下文敏感输入处理，
  并添加输入缓冲以提升游戏响应性。将旧的 InputEvent 模式转换为
  现代 Godot 4.x 最佳实践。
author: Asreonn
license: MIT
category: game-development
type: tool
difficulty: intermediate
audience: [developers]
keywords:
  - godot
  - input-handling
  - input-map
  - joypad
  - rumble
  - haptic
  - gyroscope
  - accelerometer
  - mobile-input
  - input-buffering
  - gdscript
  - gamepad
  - controller
platforms: [macos, linux, windows, android, ios]
repository: https://github.com/asreonn/godot-superpowers
homepage: https://github.com/asreonn/godot-superpowers#readme

permissions:
  filesystem:
    read: [".gd", ".tscn", ".tres", "project.godot"]
    write: [".gd", ".tscn", "project.godot"]
  git: true

behavior:
  auto_rollback: true
  validation: true
  git_commits: true

outputs: "现代化的输入脚本、Input Map 配置、设备支持脚本、输入缓冲系统"
requirements: "Git 仓库，Godot 4.x，需要现代化的输入处理代码"
execution: "半自动执行，带检测提示和 git 提交"
integration: "与 godot-modernize-gdscript 配合使用以完成完整的代码库更新"
---

# 现代化输入处理

## 核心原则

**输入处理应该是设备无关的、响应迅速的和上下文感知的。** 硬编码的按键检测、缺失的设备支持和无缓冲的输入会在跨平台时造成糟糕的玩家体验。

## 此技能的功能

### 1. 从代码生成 Input Map

将硬编码的按键检测转换为 Input Map 动作：

**转换前：**
```gdscript
# Hardcoded key checks - NOT recommended
func _input(event):
    if event is InputEventKey:
        if event.keycode == KEY_SPACE:
            jump()
        if event.keycode == KEY_ESCAPE:
            pause_game()
    if event is InputEventMouseButton:
        if event.button_index == MOUSE_BUTTON_LEFT:
            shoot()
```

**转换后：**
```gdscript
# Modern Input Map usage
func _input(event: InputEvent) -> void:
    if event.is_action_pressed("jump"):
        jump()
    if event.is_action_pressed("pause"):
        pause_game()
    if event.is_action_pressed("shoot"):
        shoot()
```

**生成的 Input Map（project.godot）：**
```ini
[input]

jump={
"deadzone": 0.5,
"events": [Object(InputEventKey,"resource_local_to_scene":false,"resource_name":"","device":-1,"window_id":0,"alt_pressed":false,"shift_pressed":false,"ctrl_pressed":false,"meta_pressed":false,"pressed":false,"keycode":0,"physical_keycode":32,"key_label":0,"unicode":32,"echo":false,"script":null)
, Object(InputEventJoypadButton,"resource_local_to_scene":false,"resource_name":"","device":-1,"button_index":0,"pressure":0.0,"pressed":false,"script":null)
]
}

shoot={
"deadzone": 0.5,
"events": [Object(InputEventMouseButton,"resource_local_to_scene":false,"resource_name":"","device":-1,"window_id":0,"alt_pressed":false,"shift_pressed":false,"ctrl_pressed":false,"meta_pressed":false,"button_mask":0,"position":Vector2(0, 0),"global_position":Vector2(0, 0),"factor":1.0,"button_index":1,"canceled":false,"pressed":false,"double_click":false,"script":null)
, Object(InputEventJoypadMotion,"resource_local_to_scene":false,"resource_name":"","device":-1,"axis":5,"axis_value":1.0,"script":null)
]
}
```

### 2. 手柄震动设置（Godot 4.x）

为控制器实现触觉反馈：

```gdscript
# InputRumbler.gd - Autoload singleton
extends Node

const WEAK_RUMBLE: float = 0.3
const MEDIUM_RUMBLE: float = 0.6
const STRONG_RUMBLE: float = 1.0
const SHORT_DURATION: float = 0.1
const MEDIUM_DURATION: float = 0.3
const LONG_DURATION: float = 0.8

var current_device: int = 0

func _ready() -> void:
    Input.joy_connection_changed.connect(_on_joy_connection_changed)

func _on_joy_connection_changed(device: int, connected: bool) -> void:
    if connected:
        current_device = device
        print("Controller connected: ", Input.get_joy_name(device))

func rumble(weak_magnitude: float, strong_magnitude: float, duration: float) -> void:
    if Input.get_joy_name(current_device).is_empty():
        return

    Input.start_joy_vibration(current_device, weak_magnitude, strong_magnitude, duration)

func rumble_impact() -> void:
    rumble(WEAK_RUMBLE, STRONG_RUMBLE, SHORT_DURATION)

func rumble_damage() -> void:
    rumble(MEDIUM_RUMBLE, MEDIUM_RUMBLE, MEDIUM_DURATION)

func rumble_explosion() -> void:
    rumble(STRONG_RUMBLE, STRONG_RUMBLE, LONG_DURATION)

func rumble_heartbeat() -> void:
    rumble(WEAK_RUMBLE, 0.0, 0.5)
    await get_tree().create_timer(0.6).timeout
    rumble(WEAK_RUMBLE, 0.0, 0.5)
```

### 3. 陀螺仪/加速度计输入（移动端）

为移动设备实现运动控制：

```gdscript
# MotionController.gd
extends Node

@export var tilt_sensitivity: float = 2.0
@export var shake_threshold: float = 15.0

signal tilt_detected(direction: Vector2)
signal shake_detected

var accelerometer_enabled: bool = false
var gyroscope_enabled: bool = false

func _ready() -> void:
    # Check if running on mobile
    if OS.has_feature("mobile") or OS.has_feature("android") or OS.has_feature("ios"):
        enable_motion_sensors()

func enable_motion_sensors() -> void:
    if DisplayServer.has_feature(DisplayServer.FEATURE_TOUCHSCREEN):
        # Enable accelerometer (gravity + user acceleration)
        if DisplayServer.has_feature(DisplayServer.FEATURE_SENSOR_ACCELEROMETER):
            DisplayServer.accelerometer_set_mode(DisplayServer.ACCELEROMETER_MODE_COMBINED)
            accelerometer_enabled = true

        # Enable gyroscope for rotation rate
        if DisplayServer.has_feature(DisplayServer.FEATURE_SENSOR_GYROSCOPE):
            gyroscope_enabled = true

func _process(delta: float) -> void:
    if not (accelerometer_enabled or gyroscope_enabled):
        return

    # Handle tilt-based movement
    if accelerometer_enabled:
        var accel: Vector3 = Input.get_accelerometer()
        var tilt: Vector2 = Vector2(accel.x, -accel.y) * tilt_sensitivity

        if tilt.length() > 0.1:
            tilt_detected.emit(tilt)

    # Handle shake detection
    if gyroscope_enabled:
        var gyro: Vector3 = Input.get_gyroscope()
        if gyro.length() > shake_threshold:
            shake_detected.emit()

func get_tilt_direction() -> Vector2:
    if not accelerometer_enabled:
        return Vector2.ZERO

    var accel: Vector3 = Input.get_accelerometer()
    # Normalize for device orientation
    return Vector2(accel.x, -accel.y).normalized()

func calibrate_center() -> void:
    # Store current orientation as neutral position
    var current_accel: Vector3 = Input.get_accelerometer()
    # Implementation: Store offset and apply to future readings
```

### 4. 上下文敏感输入处理

管理不同输入上下文（游戏、菜单、对话等）：

```gdscript
# InputContextManager.gd - Autoload singleton
extends Node

enum Context {
    GAMEPLAY,
    MENU,
    DIALOGUE,
    PAUSED,
    INVENTORY
}

var current_context: Context = Context.GAMEPLAY
var context_stack: Array[Context] = []

# Context-specific action mappings
var context_actions: Dictionary = {
    Context.GAMEPLAY: ["move_left", "move_right", "jump", "shoot", "interact"],
    Context.MENU: ["ui_up", "ui_down", "ui_accept", "ui_cancel", "ui_left", "ui_right"],
    Context.DIALOGUE: ["ui_accept", "ui_cancel", "skip_dialogue"],
    Context.PAUSED: ["ui_accept", "ui_cancel", "resume"],
    Context.INVENTORY: ["inventory_navigate", "inventory_use", "inventory_close"]
}

func set_context(new_context: Context) -> void:
    context_stack.push_back(current_context)
    current_context = new_context
    _update_input_processing()
    print("Input context changed to: ", Context.keys()[new_context])

func restore_previous_context() -> void:
    if context_stack.size() > 0:
        current_context = context_stack.pop_back()
        _update_input_processing()

func reset_to_gameplay() -> void:
    context_stack.clear()
    current_context = Context.GAMEPLAY
    _update_input_processing()

func _update_input_processing() -> void:
    # Enable/disable action processing based on context
    var enabled_actions: Array = context_actions.get(current_context, [])

    # This works with built-in UI actions too
    match current_context:
        Context.GAMEPLAY:
            get_tree().paused = false
        Context.PAUSED:
            get_tree().paused = true
        Context.MENU, Context.INVENTORY:
            get_viewport().set_input_as_handled()

func is_action_allowed(action: StringName) -> bool:
    var enabled_actions: Array = context_actions.get(current_context, [])
    return action in enabled_actions or action.begins_with("ui_")

# Example usage in player controller
func _input(event: InputEvent) -> void:
    if not InputContextManager.is_action_allowed("jump"):
        return

    if event.is_action_pressed("jump"):
        jump()
```

### 5. 输入缓冲

为响应灵敏的游戏体验添加输入缓冲：

```gdscript
# InputBuffer.gd - Component for responsive input
extends Node

@export var buffer_duration: float = 0.15  # 150ms buffer window

var buffered_actions: Dictionary = {}

func _ready() -> void:
    # Initialize buffer for common actions
    buffered_actions = {
        "jump": 0.0,
        "shoot": 0.0,
        "dash": 0.0,
        "interact": 0.0
    }

func _process(delta: float) -> void:
    # Decay buffer timers
    for action in buffered_actions.keys():
        if buffered_actions[action] > 0:
            buffered_actions[action] -= delta

func _input(event: InputEvent) -> void:
    for action in buffered_actions.keys():
        if event.is_action_pressed(action):
            buffer_action(action)

func buffer_action(action: StringName) -> void:
    if action in buffered_actions:
        buffered_actions[action] = buffer_duration

func is_buffered(action: StringName) -> bool:
    return action in buffered_actions and buffered_actions[action] > 0

func consume_buffer(action: StringName) -> bool:
    if is_buffered(action):
        buffered_actions[action] = 0.0
        return true
    return false

# Example usage in player controller
func _physics_process(delta: float) -> void:
    # Check buffered jump (allows jump before hitting ground)
    if input_buffer.is_buffered("jump") and is_on_floor():
        input_buffer.consume_buffer("jump")
        velocity.y = jump_velocity
```

## 检测模式

### 硬编码输入检测

扫描以下模式：
- 带有特定 `keycode` 值的 `InputEventKey`
- 带有特定 `button_index` 值的 `InputEventMouseButton`
- `Input.is_key_pressed()` 调用
- 不使用动作映射的直接手柄按钮检测

### 需要现代化的旧模式

**旧版 Godot 3.x 模式：**
```gdscript
if event is InputEventKey and event.scancode == KEY_SPACE:
    jump()
```

**现代 Godot 4.x：**
```gdscript
if event.is_action_pressed("jump"):
    jump()
```

## 设备支持矩阵

| 输入类型 | 桌面端 | 移动端 | 主机 | 实现方式 |
|------------|---------|--------|---------|----------------|
| 键盘 | 支持 | 不支持 | 不支持 | Input Map |
| 鼠标 | 支持 | 触摸模拟 | 不支持 | Input Map + 触摸模拟 |
| 触摸 | 不支持 | 支持 | 不支持 | 触摸事件 + 虚拟摇杆 |
| 手柄 | 支持 | 支持（MFi） | 支持 | Input Map 带死区 |
| 陀螺仪 | 不支持 | 支持 | 不支持（仅 PS） | MotionController 单例 |
| 震动 | 支持 | 不支持 | 支持 | InputRumbler 单例 |

## 使用时机

### 你正在添加控制器支持
你的游戏只支持键鼠，需要添加手柄兼容性。

### 你正在移植到移动端
需要添加触摸控制、运动传感器，并为移动设备适配输入。

### 输入感觉不灵敏
玩家抱怨输入丢失；需要缓冲来实现精确的时机。

### 存在上下文冲突
菜单导航干扰了游戏操作；需要上下文敏感的处理。

## 现代输入最佳实践

### 1. 始终使用 Input Map 动作
永远不要在游戏代码中硬编码按键检测。使用动作可以实现：
- 按键重映射支持
- 本地化（不同键盘布局）
- 无障碍功能（自适应控制器）
- 多设备类型支持

### 2. 实现死区
```gdscript
# In Input Map configuration (project.godot)
move_left={
"deadzone": 0.2,
"events": [Object(InputEventJoypadMotion,"resource_local_to_scene":false,"resource_name":"","device":-1,"axis":0,"axis_value":-1.0,"script":null)
]
}
```

### 3. 同时支持多种输入类型
```gdscript
func _input(event: InputEvent) -> void:
    # Handle keyboard/controller
    if event.is_action_pressed("jump"):
        jump()

    # Handle touch (mobile)
    if event is InputEventScreenTouch and event.pressed:
        if _is_touch_in_jump_zone(event.position):
            jump()
```

### 4. 一次性操作使用 InputEvent，持续操作使用 _process
```gdscript
# One-shot actions (button presses)
func _input(event: InputEvent) -> void:
    if event.is_action_pressed("shoot"):
        shoot()

# Continuous actions (held buttons)
func _process(delta: float) -> void:
    var move_direction := Input.get_vector("move_left", "move_right", "move_up", "move_down")
    velocity.x = move_direction.x * speed
```

## 集成

可与以下技能配合使用：
- **godot-modernize-gdscript** - 转换旧版 GDScript 模式
- **godot-setup-multiplayer** - 跨网络同步输入
- **godot-extract-to-scenes** - 将输入组件提取为可复用场景

## 安全性

- 每个输入现代化步骤一次 git 提交
- 应用变更前进行检测审查
- 每次转换都有回滚能力
- 保留手动 Input Map 条目

## 不应使用的情况

以下情况不要现代化：
- 输入处理已经正确使用 Input Map 动作
- 你正在实现平台特定的输入（需要原始访问）
- 旧版输入是为了兼容性而有意保留的

## 示例

### 完整的移动端设置
```gdscript
# MobileInputHandler.gd
extends Node

@onready var virtual_joystick: VirtualJoystick = $VirtualJoystick
@onready var touch_buttons: Control = $TouchButtons

func _ready() -> void:
    # Only show touch UI on mobile
    var is_mobile: bool = OS.has_feature("mobile") or OS.has_feature("android") or OS.has_feature("ios")
    virtual_joystick.visible = is_mobile
    touch_buttons.visible = is_mobile

func get_movement_input() -> Vector2:
    # Combine gamepad and touch input
    var input := Input.get_vector("move_left", "move_right", "move_up", "move_down")

    if virtual_joystick.visible:
        input += virtual_joystick.output

    return input.normalized()
```

### 输入重映射 UI
```gdscript
# RemapButton.gd
extends Button

@export var action: StringName

func _ready() -> void:
    pressed.connect(_on_pressed)
    update_display()

func _on_pressed() -> void:
    text = "Press any key..."
    set_process_input(true)

func _input(event: InputEvent) -> void:
    if event.is_pressed() and not event.is_echo():
        # Clear existing events for this action
        InputMap.action_erase_events(action)
        InputMap.action_add_event(action, event)
        set_process_input(false)
        update_display()

func update_display() -> void:
    var events: Array[InputEvent] = InputMap.action_get_events(action)
    if events.size() > 0:
        text = events[0].as_text()
    else:
        text = "Not assigned"
```
