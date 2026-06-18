---
name: godot-setup-navigation
version: 1.0.0
displayName: 搭建 Navigation 导航系统
description: >
  用于设置 NavigationServer API、创建 NavigationRegion2D/3D 场景、
  从 TileMap 生成 NavigationPolygon、配置 NavigationAgent2D/3D、
  实现基于 RVO 的避障，或创建寻路集成模式。
  支持 2D 俯视角、3D 导航和基于 TileMap 的导航。
author: Asreonn
license: MIT
category: game-development
type: tool
difficulty: advanced
audience: [developers]
keywords:
  - godot
  - navigation
  - pathfinding
  - navmesh
  - navigationagent
  - obstacle-avoidance
  - a-star
  - 2d
  - 3d
platforms: [macos, linux, windows]
repository: https://github.com/asreonn/godot-superpowers
homepage: https://github.com/asreonn/godot-superpowers#readme

permissions:
  filesystem:
    read: [".gd", ".tscn", ".tres", ".tilemap"]
    write: [".tscn", ".tres", ".gd"]
  git: true

behavior:
  auto_rollback: true
  validation: true
  git_commits: true

outputs: "NavigationRegion2D/3D 场景、NavigationPolygon 资源、NavigationAgent2D/3D 配置、寻路集成脚本、git 提交"
requirements: "Git 仓库、Godot 4.x、NavigationServer API"
execution: "全自动，包含场景生成和脚本更新"
integration: "可与 godot-migrate-tilemap 配合进行基于 TileMap 的导航"
---

# 搭建 Navigation 导航系统

## 核心原则

**Navigation 是一种服务，而非组件。** 使用 NavigationServer 进行运行时更新，使用 NavigationRegion 定义静态导航网格，使用 NavigationAgent 发起寻路请求。避免将导航逻辑直接嵌入角色控制器中。

## 本技能的功能

设置完整的导航系统：

1. **NavigationRegion2D/3D** - 创建导航网格边界
2. **NavigationPolygon** - 从 TileMap 或几何体生成可行走区域
3. **NavigationAgent2D/3D** - 配置具有避障功能的寻路代理
4. **RVO 集成** - 实现相互速度障碍（Reciprocal Velocity Obstacles）用于动态避障
5. **寻路集成** - 创建角色移动、AI 和点击移动的模式

## Navigation 系统设置

### NavigationRegion2D 配置

**之前（手动设置）：**
```gdscript
# 没有导航设置 - 角色盲目移动
extends CharacterBody2D

func _physics_process(delta):
    var input = Input.get_vector("ui_left", "ui_right", "ui_up", "ui_down")
    velocity = input * 200
    move_and_slide()
```

**之后（Navigation Region）：**
```gdscript
# navigation_world.gd - 带导航的场景根节点
extends Node2D

@onready var navigation_region: NavigationRegion2D = $NavigationRegion2D

func _ready():
    # 关卡加载后烘焙导航网格
    await get_tree().process_frame
    navigation_region.bake_navigation_polygon()
```

**生成的场景：**
```ini
# navigation_world.tscn
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://navigation_world.gd" id="1_abc123"]

[sub_resource type="NavigationPolygon" id="NavigationPolygon_abc123"]
vertices = PackedVector2Array(0, 0, 1024, 0, 1024, 768, 0, 768)
polygons = [PackedInt32Array(0, 1, 2, 3)]
outlines = [PackedVector2Array(0, 0, 1024, 0, 1024, 768, 0, 768)]

[node name="NavigationWorld" type="Node2D"]
script = ExtResource("1_abc123")

[node name="NavigationRegion2D" type="NavigationRegion2D" parent="."]
navigation_polygon = SubResource("NavigationPolygon_abc123")
```

### NavigationRegion3D 配置

```gdscript
# navigation_world_3d.gd
extends Node3D

@onready var navigation_region: NavigationRegion3D = $NavigationRegion3D

func _ready():
    # 烘焙 3D 导航网格
    await get_tree().process_frame
    navigation_region.bake_navigation_mesh()
```

**生成的场景：**
```ini
# navigation_world_3d.tscn
[gd_scene load_steps=3 format=3]

[ext_resource type="Script" path="res://navigation_world_3d.gd" id="1_abc123"]

[sub_resource type="NavigationMesh" id="NavigationMesh_abc123"]
vertices = PackedVector3Array(-10, 0, -10, 10, 0, -10, 10, 0, 10, -10, 0, 10)
polygons = [PackedInt32Array(0, 1, 2), PackedInt32Array(0, 2, 3)]
cell_size = 0.25
cell_height = 0.25
agent_radius = 0.5
agent_height = 2.0

[node name="NavigationWorld3D" type="Node3D"]
script = ExtResource("1_abc123")

[node name="NavigationRegion3D" type="NavigationRegion3D" parent="."]
navigation_mesh = SubResource("NavigationMesh_abc123")
```

### NavigationPolygon 生成

**从几何体生成（2D）：**
```gdscript
# 从 StaticBody2D 碰撞形状生成 NavigationPolygon
func generate_from_collision_shapes():
    var navigation_polygon = NavigationPolygon.new()
    var outline = PackedVector2Array()

    # 收集所有碰撞多边形的点
    for body in get_tree().get_nodes_in_group("navigation_obstacles"):
        if body is StaticBody2D:
            for child in body.get_children():
                if child is CollisionPolygon2D:
                    for point in child.polygon:
                        outline.append(body.to_global(point))

    # 创建避开障碍物的导航网格
    navigation_polygon.add_outline(outline)
    navigation_polygon.make_polygons_from_outlines()

    $NavigationRegion2D.navigation_polygon = navigation_polygon
    $NavigationRegion2D.bake_navigation_polygon()
```

### 烘焙导航网格

**编辑器时烘焙：**
```gdscript
@tool
extends EditorScript

func _run():
    var nav_region = get_scene().find_child("NavigationRegion2D")
    if nav_region:
        nav_region.bake_navigation_polygon()
        print("Navigation mesh baked successfully")
```

**运行时烘焙：**
```gdscript
# 用于动态关卡或程序化生成
func bake_dynamic_navigation():
    var navigation_polygon = NavigationPolygon.new()

    # 定义可行走区域
    var walkable_outline = PackedVector2Array([
        Vector2(0, 0),
        Vector2(1024, 0),
        Vector2(1024, 768),
        Vector2(0, 768)
    ])

    navigation_polygon.add_outline(walkable_outline)

    # 挖去障碍物
    for obstacle in obstacles:
        var obstacle_outline = PackedVector2Array()
        for point in obstacle.shape:
            obstacle_outline.append(obstacle.global_position + point)
        navigation_polygon.add_outline(obstacle_outline)

    navigation_polygon.make_polygons_from_outlines()
    $NavigationRegion2D.navigation_polygon = navigation_polygon
```

### 运行时导航更新

**使用 NavigationServer：**
```gdscript
# 用于频繁更新而无需重新烘焙
func update_navigation_obstacle(obstacle: CollisionShape2D, enabled: bool):
    var map_rid = NavigationServer2D.get_maps()[0]
    var obstacle_rid = obstacle.get_rid()

    if enabled:
        NavigationServer2D.obstacle_set_map(obstacle_rid, map_rid)
    else:
        NavigationServer2D.obstacle_set_map(obstacle_rid, RID())

    NavigationServer2D.map_force_update(map_rid)
```

## NavigationAgent 设置

### 2D Agent 配置

**之前（直接移动）：**
```gdscript
# enemy.gd - 没有寻路
extends CharacterBody2D

@export var target: Node2D
@export var speed: float = 100.0

func _physics_process(delta):
    if target:
        var direction = (target.global_position - global_position).normalized()
        velocity = direction * speed
        move_and_slide()
```

**之后（NavigationAgent）：**
```gdscript
# enemy.gd - 带寻路
extends CharacterBody2D

@export var target: Node2D
@export var speed: float = 100.0

@onready var nav_agent: NavigationAgent2D = $NavigationAgent2D

func _ready():
    # 配置 Agent
    nav_agent.path_desired_distance = 10.0
    nav_agent.target_desired_distance = 10.0
    nav_agent.radius = 20.0
    nav_agent.max_speed = speed
    nav_agent.avoidance_enabled = true

    # 连接 Signal
    nav_agent.velocity_computed.connect(_on_velocity_computed)

func _physics_process(delta):
    if not target:
        return

    if nav_agent.is_navigation_finished():
        velocity = Vector2.ZERO
        return

    # 更新目标位置
    nav_agent.target_position = target.global_position

    # 获取下一个路径点
    var next_path_position = nav_agent.get_next_path_position()
    var direction = (next_path_position - global_position).normalized()

    # 设置速度（NavigationServer 将计算避障）
    nav_agent.velocity = direction * speed

func _on_velocity_computed(safe_velocity: Vector2):
    velocity = safe_velocity
    move_and_slide()
```

**生成的场景：**
```ini
# enemy.tscn
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://enemy.gd" id="1_abc123"]

[node name="Enemy" type="CharacterBody2D"]
script = ExtResource("1_abc123")

[node name="CollisionShape2D" type="CollisionShape2D" parent="."]
shape = SubResource("CircleShape2D_abc123")

[node name="NavigationAgent2D" type="NavigationAgent2D" parent="."]
path_desired_distance = 10.0
target_desired_distance = 10.0
radius = 20.0
max_speed = 100.0
avoidance_enabled = true
time_horizon = 5.0
path_postprocessing = 1
```

### 3D Agent 配置

```gdscript
# enemy_3d.gd
extends CharacterBody3D

@export var target: Node3D
@export var speed: float = 5.0

@onready var nav_agent: NavigationAgent3D = $NavigationAgent3D

func _ready():
    nav_agent.path_desired_distance = 1.0
    nav_agent.target_desired_distance = 1.0
    nav_agent.radius = 0.5
    nav_agent.height = 2.0
    nav_agent.max_speed = speed
    nav_agent.avoidance_enabled = true
    nav_agent.velocity_computed.connect(_on_velocity_computed)

func _physics_process(delta):
    if not target or nav_agent.is_navigation_finished():
        velocity.x = 0
        velocity.z = 0
        return

    nav_agent.target_position = target.global_position
    var next_path_position = nav_agent.get_next_path_position()
    var direction = (next_path_position - global_position).normalized()

    nav_agent.velocity = direction * speed

func _on_velocity_computed(safe_velocity: Vector3):
    velocity.x = safe_velocity.x
    velocity.z = safe_velocity.z
    move_and_slide()
```

### 跟随目标

**简单跟随：**
```gdscript
# follow_target.gd
extends CharacterBody2D

@export var target: Node2D
@export var follow_distance: float = 50.0

@onready var nav_agent: NavigationAgent2D = $NavigationAgent2D

func _physics_process(delta):
    if not target:
        return

    var distance_to_target = global_position.distance_to(target.global_position)

    if distance_to_target > follow_distance:
        nav_agent.target_position = target.global_position

        if not nav_agent.is_navigation_finished():
            var next_position = nav_agent.get_next_path_position()
            var direction = (next_position - global_position).normalized()
            velocity = direction * 100.0
            move_and_slide()
    else:
        velocity = Vector2.ZERO
```

**预测性跟随：**
```gdscript
# 预测目标将到达的位置
func get_predicted_target_position(look_ahead_time: float = 0.5) -> Vector2:
    if target is CharacterBody2D:
        return target.global_position + (target.velocity * look_ahead_time)
    return target.global_position
```

### 路径请求

**手动路径查询：**
```gdscript
# 不使用 NavigationAgent 请求路径
func request_path(from: Vector2, to: Vector2) -> PackedVector2Array:
    var map_rid = NavigationServer2D.get_maps()[0]
    return NavigationServer2D.map_get_path(map_rid, from, to, true)

# 用法
var path = request_path(global_position, target_position)
for point in path:
    print("Path point: ", point)
```

**带优化的路径查询：**
```gdscript
func request_optimized_path(from: Vector2, to: Vector2) -> PackedVector2Array:
    var map_rid = NavigationServer2D.get_maps()[0]

    # 查询路径并简化
    var path = NavigationServer2D.map_get_path(
        map_rid,
        from,
        to,
        true  # 优化路径
    )

    return path
```

## 避障系统

### 动态障碍物

**障碍物 Node 设置：**
```gdscript
# dynamic_obstacle.gd
extends StaticBody2D

@export var obstacle_radius: float = 30.0

@onready var obstacle: NavigationObstacle2D = $NavigationObstacle2D

func _ready():
    obstacle.radius = obstacle_radius
    obstacle.velocity = Vector2.ZERO

    # 连接避障 Signal
    obstacle.avoidance_enabled = true

func set_avoidance_velocity(velocity: Vector2):
    obstacle.velocity = velocity
```

**生成的场景：**
```ini
# moving_obstacle.tscn
[node name="MovingObstacle" type="StaticBody2D"]

[node name="CollisionShape2D" type="CollisionShape2D" parent="."]
shape = SubResource("CircleShape2D_abc123")

[node name="NavigationObstacle2D" type="NavigationObstacle2D" parent="."]
radius = 30.0
avoidance_enabled = true
```

### RVO（相互速度障碍）

**RVO 配置：**
```gdscript
# 配置 RVO 参数以实现逼真的避障
func configure_rvo(agent: NavigationAgent2D):
    agent.avoidance_enabled = true
    agent.radius = 20.0  # Agent 尺寸
    agent.neighbor_distance = 100.0  # 搜索邻居的距离
    agent.max_neighbors = 10  # 考虑的最大 Agent 数
    agent.time_horizon = 2.0  # 预测碰撞的时间范围
    agent.time_horizon_obstacles = 1.0  # 静态障碍物的预测时间
```

**带优先级的 RVO：**
```gdscript
# 某些 Agent 具有通行优先权
func configure_priority_agent(agent: NavigationAgent2D, priority: int):
    agent.avoidance_enabled = true
    agent.avoidance_layers = 1
    agent.avoidance_mask = 1

    # 高优先级 Agent 会推开低优先级的 Agent
    # 使用 time_horizon 来控制
    match priority:
        0: agent.time_horizon = 1.0  # 低优先级 - 快速让路
        1: agent.time_horizon = 2.0  # 正常优先级
        2: agent.time_horizon = 5.0  # 高优先级 - 其他人让路
```

### Navigation 图层

**图层配置：**
```gdscript
# 定义不同的导航图层
enum NavigationLayers {
    GROUND = 1,
    WATER = 2,
    AIR = 4
}

# 为特定图层配置 Agent
func configure_agent_layers(agent: NavigationAgent2D, layers: int):
    agent.navigation_layers = layers

# 为特定图层配置区域
func configure_region_layers(region: NavigationRegion2D, layers: int):
    region.navigation_layers = layers
```

**基于图层的寻路：**
```gdscript
# 地面单位只能在地面行走
configure_agent_layers($GroundUnit/NavigationAgent2D, NavigationLayers.GROUND)

# 飞行单位可以使用空中路径
configure_agent_layers($FlyingUnit/NavigationAgent2D, NavigationLayers.AIR)

# 两栖单位可以使用地面和水路
configure_agent_layers($AmphibiousUnit/NavigationAgent2D,
    NavigationLayers.GROUND | NavigationLayers.WATER)
```

## 集成模式

### 角色移动

**状态机集成：**
```gdscript
# character_controller.gd
extends CharacterBody2D

enum State { IDLE, MOVING, ATTACKING }

@onready var nav_agent: NavigationAgent2D = $NavigationAgent2D
var current_state: State = State.IDLE
var target_position: Vector2

func set_target(pos: Vector2):
    target_position = pos
    nav_agent.target_position = pos
    current_state = State.MOVING

func _physics_process(delta):
    match current_state:
        State.IDLE:
            velocity = Vector2.ZERO

        State.MOVING:
            if nav_agent.is_navigation_finished():
                current_state = State.IDLE
                velocity = Vector2.ZERO
            else:
                var next_pos = nav_agent.get_next_path_position()
                var direction = (next_pos - global_position).normalized()
                nav_agent.velocity = direction * 150.0

        State.ATTACKING:
            # 攻击逻辑
            pass

    if current_state == State.MOVING:
        move_and_slide()

func _on_velocity_computed(safe_velocity: Vector2):
    velocity = safe_velocity
```

### AI 寻路

**带 Navigation 的 AI 控制器：**
```gdscript
# ai_controller.gd
extends CharacterBody2D

@export var patrol_points: Array[Marker2D]
@export var detection_range: float = 200.0

@onready var nav_agent: NavigationAgent2D = $NavigationAgent2D
@onready var vision: Area2D = $VisionArea

enum AIState { PATROL, CHASE, ATTACK, RETURN }

var current_state: AIState = AIState.PATROL
var current_patrol_index: int = 0
var home_position: Vector2
var target: Node2D

func _ready():
    home_position = global_position
    vision.body_entered.connect(_on_body_entered_vision)

    nav_agent.velocity_computed.connect(_on_velocity_computed)
    nav_agent.navigation_finished.connect(_on_navigation_finished)

func _physics_process(delta):
    match current_state:
        AIState.PATROL:
            process_patrol()
        AIState.CHASE:
            process_chase()
        AIState.ATTACK:
            process_attack()
        AIState.RETURN:
            process_return()

func process_patrol():
    if nav_agent.is_navigation_finished():
        current_patrol_index = (current_patrol_index + 1) % patrol_points.size()
        nav_agent.target_position = patrol_points[current_patrol_index].global_position

    var next_pos = nav_agent.get_next_path_position()
    var direction = (next_pos - global_position).normalized()
    nav_agent.velocity = direction * 80.0

func process_chase():
    if target:
        nav_agent.target_position = target.global_position
        var next_pos = nav_agent.get_next_path_position()
        var direction = (next_pos - global_position).normalized()
        nav_agent.velocity = direction * 150.0

        if global_position.distance_to(target.global_position) > detection_range * 1.5:
            current_state = AIState.RETURN

func process_return():
    nav_agent.target_position = home_position
    if nav_agent.is_navigation_finished():
        current_state = AIState.PATROL

func _on_body_entered_vision(body):
    if body.is_in_group("player"):
        target = body
        current_state = AIState.CHASE

func _on_velocity_computed(safe_velocity: Vector2):
    velocity = safe_velocity
    move_and_slide()
```

### 点击移动

**RTS 风格移动：**
```gdscript
# click_to_move.gd
extends CharacterBody2D

@export var speed: float = 150.0

@onready var nav_agent: NavigationAgent2D = $NavigationAgent2D
@onready var selection_indicator: Sprite2D = $SelectionIndicator

var is_selected: bool = false

func _ready():
    nav_agent.velocity_computed.connect(_on_velocity_computed)
    selection_indicator.visible = false

func _unhandled_input(event):
    if not is_selected:
        return

    if event is InputEventMouseButton:
        if event.button_index == MOUSE_BUTTON_LEFT and event.pressed:
            var target = get_global_mouse_position()
            set_movement_target(target)

func set_movement_target(target: Vector2):
    nav_agent.target_position = target

func _physics_process(delta):
    if nav_agent.is_navigation_finished():
        velocity = Vector2.ZERO
        return

    var next_pos = nav_agent.get_next_path_position()
    var direction = (next_pos - global_position).normalized()
    nav_agent.velocity = direction * speed

func _on_velocity_computed(safe_velocity: Vector2):
    velocity = safe_velocity
    move_and_slide()

func select():
    is_selected = true
    selection_indicator.visible = true

func deselect():
    is_selected = false
    selection_indicator.visible = false
```

**选择管理器：**
```gdscript
# selection_manager.gd
extends Node2D

var selected_units: Array[CharacterBody2D] = []

func _unhandled_input(event):
    if event is InputEventMouseButton:
        if event.button_index == MOUSE_BUTTON_LEFT and event.pressed:
            if not Input.is_key_pressed(KEY_SHIFT):
                deselect_all()

            var click_pos = get_global_mouse_position()
            select_at_position(click_pos)

        elif event.button_index == MOUSE_BUTTON_RIGHT and event.pressed:
            var target_pos = get_global_mouse_position()
            move_selected_to(target_pos)

func select_at_position(pos: Vector2):
    var space_state = get_world_2d().direct_space_state
    var query = PhysicsPointQueryParameters2D.new()
    query.position = pos
    query.collide_with_areas = true

    var results = space_state.intersect_point(query)
    for result in results:
        var node = result.collider
        if node.has_method("select"):
            node.select()
            selected_units.append(node)

func deselect_all():
    for unit in selected_units:
        if is_instance_valid(unit) and unit.has_method("deselect"):
            unit.deselect()
    selected_units.clear()

func move_selected_to(target: Vector2):
    for unit in selected_units:
        if is_instance_valid(unit) and unit.has_method("set_movement_target"):
            unit.set_movement_target(target)
```

## 示例

### 2D 俯视角导航

**完整设置：**
```gdscript
# player_topdown.gd
extends CharacterBody2D

@export var speed: float = 200.0

@onready var nav_agent: NavigationAgent2D = $NavigationAgent2D

func _ready():
    nav_agent.path_desired_distance = 8.0
    nav_agent.target_desired_distance = 8.0
    nav_agent.radius = 12.0
    nav_agent.max_speed = speed
    nav_agent.avoidance_enabled = true
    nav_agent.velocity_computed.connect(_on_velocity_computed)

func _input(event):
    if event is InputEventMouseButton:
        if event.button_index == MOUSE_BUTTON_RIGHT and event.pressed:
            nav_agent.target_position = get_global_mouse_position()

func _physics_process(delta):
    if nav_agent.is_navigation_finished():
        velocity = Vector2.ZERO
        return

    var next_pos = nav_agent.get_next_path_position()
    var direction = (next_pos - global_position).normalized()
    nav_agent.velocity = direction * speed

func _on_velocity_computed(safe_velocity: Vector2):
    velocity = safe_velocity
    move_and_slide()
```

**场景结构：**
```ini
# topdown_level.tscn
[gd_scene load_steps=4 format=3]

[sub_resource type="NavigationPolygon" id="NavigationPolygon_level"]
vertices = PackedVector2Array(0, 0, 1024, 0, 1024, 768, 0, 768)
polygons = [PackedInt32Array(0, 1, 2, 3)]

[sub_resource type="CircleShape2D" id="CircleShape2D_player"]
radius = 12.0

[node name="TopdownLevel" type="Node2D"]

[node name="NavigationRegion2D" type="NavigationRegion2D" parent="."]
navigation_polygon = SubResource("NavigationPolygon_level")

[node name="Player" type="CharacterBody2D" parent="."]
position = Vector2(512, 384)

[node name="CollisionShape2D" type="CollisionShape2D" parent="Player"]
shape = SubResource("CircleShape2D_player")

[node name="NavigationAgent2D" type="NavigationAgent2D" parent="Player"]
radius = 12.0
max_speed = 200.0
avoidance_enabled = true

[node name="Obstacles" type="Node2D" parent="."]

[node name="Wall1" type="StaticBody2D" parent="Obstacles"]

[node name="CollisionPolygon2D" type="CollisionPolygon2D" parent="Obstacles/Wall1"]
polygon = PackedVector2Array(200, 200, 300, 200, 300, 300, 200, 300)
```

### 3D 导航

**3D 角色控制器：**
```gdscript
# player_3d.gd
extends CharacterBody3D

@export var speed: float = 5.0
@export var jump_velocity: float = 4.5

@onready var nav_agent: NavigationAgent3D = $NavigationAgent3D
@onready var camera: Camera3D = $Camera3D

var gravity = ProjectSettings.get_setting("physics/3d/default_gravity")

func _ready():
    nav_agent.path_desired_distance = 0.5
    nav_agent.target_desired_distance = 0.5
    nav_agent.radius = 0.3
    nav_agent.height = 1.8
    nav_agent.max_speed = speed
    nav_agent.avoidance_enabled = true
    nav_agent.velocity_computed.connect(_on_velocity_computed)

func _input(event):
    if event is InputEventMouseButton:
        if event.button_index == MOUSE_BUTTON_LEFT and event.pressed:
            var mouse_pos = event.position
            var from = camera.project_ray_origin(mouse_pos)
            var to = from + camera.project_ray_normal(mouse_pos) * 1000

            var space_state = get_world_3d().direct_space_state
            var query = PhysicsRayQueryParameters3D.new()
            query.from = from
            query.to = to

            var result = space_state.intersect_ray(query)
            if result:
                nav_agent.target_position = result.position

func _physics_process(delta):
    if not is_on_floor():
        velocity.y -= gravity * delta

    if Input.is_action_just_pressed("ui_accept") and is_on_floor():
        velocity.y = jump_velocity

    if nav_agent.is_navigation_finished():
        velocity.x = 0
        velocity.z = 0
        return

    var next_pos = nav_agent.get_next_path_position()
    var direction = (next_pos - global_position).normalized()

    nav_agent.velocity = direction * speed

func _on_velocity_computed(safe_velocity: Vector3):
    velocity.x = safe_velocity.x
    velocity.z = safe_velocity.z
    move_and_slide()
```

### 基于 TileMap 的导航

**自动导航生成：**
```gdscript
# tilemap_navigation.gd
extends Node2D

@onready var tile_map: TileMap = $TileMap
@onready var navigation_region: NavigationRegion2D = $NavigationRegion2D

func _ready():
    generate_navigation_from_tilemap()

func generate_navigation_from_tilemap():
    var navigation_polygon = NavigationPolygon.new()
    var used_cells = tile_map.get_used_cells(0)  # 第 0 层

    # 获取 TileSet 的导航多边形
    var tile_set = tile_map.tile_set

    for cell in used_cells:
        var atlas_coords = tile_map.get_cell_atlas_coords(0, cell)
        var tile_data = tile_map.get_cell_tile_data(0, cell)

        if tile_data and tile_data.get_navigation_polygon(0):
            var nav_poly = tile_data.get_navigation_polygon(0)
            var vertices = nav_poly.vertices

            # 将顶点转换为世界坐标
            var world_vertices = PackedVector2Array()
            for vertex in vertices:
                var world_pos = tile_map.map_to_local(cell) + vertex
                world_vertices.append(world_pos)

            # 添加到导航多边形
            navigation_polygon.add_polygon(world_vertices)

    navigation_region.navigation_polygon = navigation_polygon
    navigation_region.bake_navigation_polygon()
```

**使用 TileMap V2 的 Navigation 图层：**
```gdscript
# tilemap_v2_navigation.gd
extends Node2D

@onready var tile_map: TileMapLayer = $TileMapLayer
@onready var navigation_region: NavigationRegion2D = $NavigationRegion2D

func _ready():
    # 用于 Godot 4.3+ TileMapLayer
    generate_navigation_from_layer()

func generate_navigation_from_layer():
    var navigation_polygon = NavigationPolygon.new()
    var used_cells = tile_map.get_used_cells()
    var tile_set = tile_map.tile_set

    for cell in used_cells:
        var tile_data = tile_map.get_cell_tile_data(cell)

        if tile_data:
            # 检查图块是否有导航
            var nav_poly = tile_data.get_navigation_polygon()
            if nav_poly:
                var vertices = nav_poly.vertices
                var world_vertices = PackedVector2Array()

                for vertex in vertices:
                    var world_pos = tile_map.map_to_local(cell) + vertex
                    world_vertices.append(world_pos)

                navigation_polygon.add_outline(world_vertices)

    navigation_polygon.make_polygons_from_outlines()
    navigation_region.navigation_polygon = navigation_polygon
```

## TileMap 集成（来自 TileMap V2）

**启用 Navigation 的 TileMap 设置：**
```gdscript
# 创建带导航多边形的 TileSet
func create_navigation_tileset() -> TileSet:
    var tile_set = TileSet.new()
    tile_set.tile_size = Vector2i(32, 32)

    # 添加地形图集源
    var atlas_source = TileSetAtlasSource.new()
    atlas_source.texture = preload("res://assets/tiles.png")
    atlas_source.texture_region_size = Vector2i(32, 32)

    # 添加带导航的地面图块
    var ground_atlas = Vector2i(0, 0)
    atlas_source.create_tile(ground_atlas)

    var ground_data = atlas_source.get_tile_data(ground_atlas, 0)
    var nav_poly = NavigationPolygon.new()
    nav_poly.vertices = PackedVector2Array([
        Vector2(0, 0), Vector2(32, 0),
        Vector2(32, 32), Vector2(0, 32)
    ])
    nav_poly.add_polygon(PackedInt32Array([0, 1, 2, 3]))
    ground_data.set_navigation_polygon(0, nav_poly)

    # 添加不带导航的墙壁图块
    var wall_atlas = Vector2i(1, 0)
    atlas_source.create_tile(wall_atlas)
    # 没有导航多边形 = 不可行走

    tile_set.add_source(atlas_source, 0)
    return tile_set
```

**运行时 TileMap Navigation 更新：**
```gdscript
# 当图块发生变化时更新导航
func update_navigation_at_position(map_pos: Vector2i):
    # 移除旧的导航数据
    var nav_poly = NavigationPolygon.new()

    # 从当前 TileMap 状态重建
    var used_cells = tile_map.get_used_cells(0)

    for cell in used_cells:
        var tile_data = tile_map.get_cell_tile_data(0, cell)
        if tile_data and tile_data.get_navigation_polygon(0):
            var local_nav = tile_data.get_navigation_polygon(0)
            var world_verts = PackedVector2Array()

            for vert in local_nav.vertices:
                world_verts.append(tile_map.map_to_local(cell) + vert)

            nav_poly.add_outline(world_verts)

    nav_poly.make_polygons_from_outlines()
    navigation_region.navigation_polygon = nav_poly
```

## 常见模式

### 多 Agent 协同
```gdscript
# 编队移动
func move_formation_to(target: Vector2, units: Array[CharacterBody2D]):
    var leader = units[0]
    leader.nav_agent.target_position = target

    # 其他单位以偏移跟随
    for i in range(1, units.size()):
        var offset = Vector2(i * 30, 0)
        units[i].nav_agent.target_position = target + offset
```

### 动态路径代价
```gdscript
# 不同地形代价
func calculate_path_cost(path: PackedVector2Array, terrain_map: TileMap) -> float:
    var cost = 0.0
    for i in range(path.size() - 1):
        var terrain_type = get_terrain_at(path[i], terrain_map)
        match terrain_type:
            "grass": cost += 1.0
            "mud": cost += 2.0
            "road": cost += 0.5
    return cost
```

### Navigation 调试可视化
```gdscript
# 绘制路径用于调试
func _draw():
    if nav_agent.is_navigation_finished():
        return

    var path = nav_agent.get_current_navigation_path()
    if path.size() > 0:
        var local_path = PackedVector2Array()
        for point in path:
            local_path.append(to_local(point))

        draw_polyline(local_path, Color.GREEN, 2.0)

        for point in local_path:
            draw_circle(point, 3.0, Color.RED)
```

## 安全性

- 访问路径之前始终检查 `is_navigation_finished()`
- 使用 `velocity_computed` Signal 进行 RVO 避障
- 在查询之前验证 NavigationServer 地图是否存在
- 处理路径不存在的情况（Agent 返回空路径）
- 在关卡生成完成后再烘焙导航

## 何时不使用

以下情况不要使用 NavigationAgent：
- 移动简单且直接（没有障碍物）
- 性能要求极高（NavigationServer 有开销）
- 需要自定义寻路算法（直接使用 A*）
- Agent 不需要避障

改用直接移动：
```gdscript
# 简单直接移动 - 不需要导航
func _physics_process(delta):
    var direction = (target.global_position - global_position).normalized()
    velocity = direction * speed
    move_and_slide()
```

## 集成

可搭配使用：
- **godot-migrate-tilemap** - 将 TileMap V1 转换为带导航的 V2
- **godot-refactor** - 包含导航在内的完整项目重构
- **godot-add-signals** - 通过 Signal 连接导航事件

## 性能建议

1. **批量 Navigation 更新** - 不要每帧都烘焙
2. **使用 NavigationLayers** - 按图层分离 Agent 以提高效率
3. **限制最大邻居数** - RVO 性能随邻居数量增长
4. **静态 vs 动态** - 静态使用 NavigationRegion，动态使用 Obstacles
5. **路径缓存** - 缓存不常变化的路径
