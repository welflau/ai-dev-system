---
name: godot-setup-multiplayer
version: 1.0.0
displayName: 搭建多人联网系统 (Godot 4.x)
description: >
  用于在 Godot 4.x 中构建需要联网对战、玩家同步或 RPC 通信的多人游戏。
  设置新版高级 Multiplayer API，包括 MultiplayerSpawner、MultiplayerSynchronizer
  和 @rpc 注解。
author: Asreonn
license: MIT
category: game-development
type: tool
difficulty: advanced
audience: [developers]
keywords:
  - godot
  - multiplayer
  - networking
  - rpc
  - multiplayerpeer
  - authority
  - host
  - client
  - server
  - replication
  - enet
  - synchronizer
  - spawner
platforms: [macos, linux, windows]
repository: https://github.com/asreonn/godot-superpowers
homepage: https://github.com/asreonn/godot-superpowers#readme

permissions:
  filesystem:
    read: [".gd", ".tscn", ".tres"]
    write: [".gd", ".tscn", ".tres"]
  git: true

behavior:
  auto_rollback: true
  validation: true
  git_commits: true

outputs: "包含 ENet 设置、RPC 注解、同步器、生成器的多人场景"
requirements: "Godot 4.x 项目，基本的网络知识"
execution: "辅助模式 - 提供模板和模式"
integration: "属于 Godot 4.x 第二阶段技能的一部分"
---

# 搭建多人联网系统 (Godot 4.x)

## 核心原则

**Godot 4.x 使用高级 Multiplayer API（包括 `MultiplayerSpawner`、`MultiplayerSynchronizer` 和 `@rpc` 注解）替换了旧的 `remote func` 系统。** Authority 决定谁控制什么——服务器 Authority 是默认的安全模式。

## Godot 3.x 到 4.x 的变更

| Godot 3.x | Godot 4.x |
|-----------|-----------|
| `remote func` | `@rpc` 注解 |
| `remotesync` | `@rpc(any_peer, call_local)` |
| `master` | `@rpc(authority)` 配合 `is_multiplayer_authority()` |
| `slave` | 从非 Authority 调用的 `@rpc` |
| `get_tree().network_peer` | `multiplayer.multiplayer_peer` |
| 自定义同步 | `MultiplayerSynchronizer` |
| 自定义生成 | `MultiplayerSpawner` |

## Multiplayer API 设置

### MultiplayerPeer 配置

Godot 4.x 中网络功能的基础：

```gdscript
extends Node

@export var port: int = 7000
@export var max_players: int = 8

func create_host() -> void:
    var peer = ENetMultiplayerPeer.new()
    var error = peer.create_server(port, max_players)

    if error == OK:
        multiplayer.multiplayer_peer = peer
        print("Server started on port ", port)
        _setup_multiplayer_signals()
    else:
        push_error("Failed to create server: ", error)

func join_host(address: String) -> void:
    var peer = ENetMultiplayerPeer.new()
    var error = peer.create_client(address, port)

    if error == OK:
        multiplayer.multiplayer_peer = peer
        print("Connecting to ", address, ":", port)
        _setup_multiplayer_signals()
    else:
        push_error("Failed to create client: ", error)
```

### 连接处理

```gdscript
func _setup_multiplayer_signals() -> void:
    multiplayer.peer_connected.connect(_on_peer_connected)
    multiplayer.peer_disconnected.connect(_on_peer_disconnected)
    multiplayer.connected_to_server.connect(_on_connected_to_server)
    multiplayer.connection_failed.connect(_on_connection_failed)
    multiplayer.server_disconnected.connect(_on_server_disconnected)

func _on_peer_connected(id: int) -> void:
    print("Player connected: ", id)
    if multiplayer.is_server():
        _spawn_player(id)

func _on_peer_disconnected(id: int) -> void:
    print("Player disconnected: ", id)
    if multiplayer.is_server():
        _despawn_player(id)

func _on_connected_to_server() -> void:
    print("Connected to server as ", multiplayer.get_unique_id())

func _on_connection_failed() -> void:
    push_error("Failed to connect to server")

func _on_server_disconnected() -> void:
    push_warning("Server disconnected")
    multiplayer.multiplayer_peer = null
```

## Node 同步

### MultiplayerSpawner 设置

在所有客户端之间自动生成/销毁 Node：

```gdscript
# 在你的主游戏场景或世界节点中
extends Node2D

@onready var spawner: MultiplayerSpawner = $MultiplayerSpawner

func _ready() -> void:
    # 设置生成路径（生成的节点将添加到此处）
    spawner.spawn_path = "../Players"

    # 将玩家场景添加到自动生成列表
    var player_scene = preload("res://scenes/player.tscn")
    spawner.add_spawnable_scene(player_scene.resource_path)

func _spawn_player(id: int) -> void:
    # 只有服务器生成玩家
    if not multiplayer.is_server():
        return

    var player = preload("res://scenes/player.tscn").instantiate()
    player.name = str(id)  # 名称必须匹配 Peer ID 以设置 Authority
    player.set_multiplayer_authority(id)

    # 添加到生成路径 - Spawner 处理复制
    $Players.add_child(player, true)  # "true" 使其被复制
```

### MultiplayerSynchronizer 配置

自动同步属性：

```gdscript
# player.gd
extends CharacterBody2D

@export var speed: float = 200.0
@export var health: int = 100

# 要同步的属性（在编辑器中配置）
@onready var synchronizer: MultiplayerSynchronizer = $MultiplayerSynchronizer

func _ready() -> void:
    # 配置要同步的内容（也可以在编辑器中操作）
    var config = synchronizer.get_replication_config()
    config.add_property(":position")
    config.add_property(":velocity")
    config.add_property(":health")

    # 同步间隔（越低 = 越频繁，带宽消耗越大）
    synchronizer.replication_interval = 0.05  # 每秒 20 次

    # 仅在值变化时同步
    synchronizer.delta_interval = 0.0  # 0 = 始终同步

func _physics_process(delta: float) -> void:
    # 只有拥有 Authority 时才处理输入
    if not is_multiplayer_authority():
        return

    var input_dir = Input.get_vector("move_left", "move_right", "move_up", "move_down")
    velocity = input_dir * speed
    move_and_slide()
```

### 场景复制设置

在 Godot 编辑器中：

1. **添加 MultiplayerSpawner** 到你的世界/游戏场景
2. **设置 Spawn Path** 为一个 Node，玩家将被添加到此处（例如 `../Players`）
3. 在检查器中**添加可生成的场景**（player.tscn、enemy.tscn 等）
4. **添加 MultiplayerSynchronizer** 作为需要同步的 Node 的子节点
5. 在同步器检查器中**配置 ReplicationConfig**

## RPC 模式

### @rpc 注解用法

用 `@rpc` 装饰器替换 `remote func`：

```gdscript
# Godot 3.x 风格（旧版 - 不要使用）
remote func take_damage(amount: int) -> void:
    health -= amount

# Godot 4.x 风格（新版）
@rpc
def take_damage(amount: int) -> void:
    health -= amount
```

### 调用模式

控制谁可以调用以及在哪里执行：

```gdscript
# 仅 Authority（默认）- 只有 Authority Peer 可以调用
@rpc
func server_only_function() -> void:
    pass  # 在所有 Peer 上运行，但只有 Authority 可以触发

# 任何 Peer 都可以调用
@rpc(any_peer)
func any_peer_can_call() -> void:
    pass

# 也在本地 Peer 上调用（替代 'remotesync'）
@rpc(any_peer, call_local)
func synced_function() -> void:
    pass  # 在调用者和所有远程 Peer 上运行

# Authority 加本地调用
@rpc(authority, call_local)
func authority_synced() -> void:
    pass

# 不可靠传输，用于快速更新（位置、旋转）
@rpc(unreliable)
func fast_update(pos: Vector2) -> void:
    pass

# 不可靠 + 有序（适合持续的位置更新）
@rpc(unreliable, ordered)
func ordered_update(pos: Vector2) -> void:
    pass
```

### RPC 可靠性和通道

```gdscript
# 可靠传输（默认）- 保证送达，有序
@rpc
func important_event(data: Dictionary) -> void:
    pass  # 用于：计分、死亡、状态变更

# 不可靠传输 - 更快，可能丢失
@rpc(unreliable)
func position_update(pos: Vector2) -> void:
    pass  # 用于：频繁的位置/旋转更新

# 不可靠有序 - 丢弃旧包，保持顺序
@rpc(unreliable, ordered)
func continuous_stream(data: PackedByteArray) -> void:
    pass  # 用于：语音聊天、流式数据

# 通道配置（0-9，默认 0）
@rpc(channel=1)
func chat_message(msg: String) -> void:
    pass  # 聊天使用独立通道，不会阻塞游戏数据

# 模式 + 可靠性组合
@rpc(authority, unreliable)
func server_position_update(pos: Vector2) -> void:
    pass

@rpc(any_peer, unreliable, ordered, channel=2)
func voice_data(data: PackedByteArray) -> void:
    pass
```

## Authority 模式

### 服务器 Authority（推荐）

服务器验证所有操作：

```gdscript
# player.gd
extends CharacterBody2D

@export var speed: float = 200.0
var input_vector: Vector2 = Vector2.ZERO

func _physics_process(delta: float) -> void:
    if is_multiplayer_authority():
        # Authority（通常是服务器）处理实际移动
        _process_authority(delta)
    else:
        # 非 Authority（客户端）处理预测/插值
        _process_remote(delta)

func _process_authority(delta: float) -> void:
    if multiplayer.is_server():
        # 服务器：应用从客户端接收的实际输入
        velocity = input_vector * speed
        move_and_slide()
    else:
        # 客户端：发送输入到服务器，本地预测
        input_vector = Input.get_vector("move_left", "move_right", "move_up", "move_down")
        rpc_id(1, "receive_input", input_vector)  # 发送到服务器（Peer 1）

        # 客户端预测（可选）
        velocity = input_vector * speed
        move_and_slide()

@rpc(any_peer)
func receive_input(input: Vector2) -> void:
    # 只有服务器处理输入
    if not multiplayer.is_server():
        return

    # 验证输入（防作弊）
    if input.length() > 1.0:
        input = input.normalized()

    input_vector = input

func _process_remote(delta: float) -> void:
    # 插值到同步位置
    # MultiplayerSynchronizer 自动处理
    pass
```

### 客户端预测

减少感知延迟：

```gdscript
extends CharacterBody2D

var predicted_position: Vector2
var server_position: Vector2
var reconciliation_speed: float = 10.0

func _ready() -> void:
    if is_multiplayer_authority() and not multiplayer.is_server():
        # 拥有此玩家 Authority 的客户端
        set_physics_process(true)

func _physics_process(delta: float) -> void:
    if is_multiplayer_authority() and not multiplayer.is_server():
        # 客户端预测
        var input = Input.get_vector("move_left", "move_right", "move_up", "move_down")
        velocity = input * speed
        predicted_position = position + velocity * delta

        # 与服务器对账
        position = position.lerp(server_position, reconciliation_speed * delta)
        move_and_slide()

        # 发送输入到服务器
        rpc_id(1, "update_input", input)

@rpc
func update_state(pos: Vector2, vel: Vector2) -> void:
    # 从服务器接收
    server_position = pos
    velocity = vel
```

### 状态对账

处理服务器校正：

```gdscript
var input_history: Array[Dictionary] = []
var last_processed_input: int = 0

func _physics_process(delta: float) -> void:
    if is_multiplayer_authority():
        var input = get_input()
        var input_id = Time.get_ticks_msec()

        input_history.append({"id": input_id, "input": input})

        # 应用输入
        apply_input(input, delta)

        # 带 ID 发送到服务器
        rpc_id(1, "process_input", input_id, input)

@rpc
func correction(server_state: Dictionary) -> void:
    # 服务器发送权威状态 + 最后处理的输入 ID
    position = server_state.position
    velocity = server_state.velocity
    last_processed_input = server_state.last_input_id

    # 重放未处理的输入
    for hist in input_history:
        if hist.id > last_processed_input:
            apply_input(hist.input, get_physics_process_delta_time())

    # 清除旧历史
    input_history = input_history.filter(func(h): return h.id > last_processed_input)
```

## 场景结构

### 大厅场景

```gdscript
# lobby.gd
extends Control

@onready var host_button: Button = $HostButton
@onready var join_button: Button = $JoinButton
@onready var address_input: LineEdit = $AddressInput
@onready var status_label: Label = $StatusLabel

func _ready() -> void:
    host_button.pressed.connect(_on_host_pressed)
    join_button.pressed.connect(_on_join_pressed)

    multiplayer.connected_to_server.connect(_on_connection_success)
    multiplayer.connection_failed.connect(_on_connection_failed)

func _on_host_pressed() -> void:
    var peer = ENetMultiplayerPeer.new()
    var err = peer.create_server(7000, 4)

    if err == OK:
        multiplayer.multiplayer_peer = peer
        status_label.text = "Hosting on port 7000"
        _start_game()
    else:
        status_label.text = "Failed to host: " + str(err)

func _on_join_pressed() -> void:
    var address = address_input.text if address_input.text else "localhost"
    var peer = ENetMultiplayerPeer.new()
    var err = peer.create_client(address, 7000)

    if err == OK:
        multiplayer.multiplayer_peer = peer
        status_label.text = "Connecting..."
    else:
        status_label.text = "Failed to connect: " + str(err)

func _on_connection_success() -> void:
    status_label.text = "Connected!"
    _start_game()

func _on_connection_failed() -> void:
    status_label.text = "Connection failed"

func _start_game() -> void:
    get_tree().change_scene_to_file("res://scenes/game.tscn")
```

### 带 Multiplayer 的游戏场景

```gdscript
# game.gd
extends Node2D

@onready var spawner: MultiplayerSpawner = $MultiplayerSpawner
@onready var players_container: Node2D = $Players

func _ready() -> void:
    spawner.spawn_function = _spawn_player_custom

    if multiplayer.is_server():
        multiplayer.peer_connected.connect(_on_peer_connected)
        multiplayer.peer_disconnected.connect(_on_peer_disconnected)

        # 生成主机玩家
        _spawn_player(1)

func _on_peer_connected(id: int) -> void:
    _spawn_player(id)

func _on_peer_disconnected(id: int) -> void:
    var player = players_container.get_node_or_null(str(id))
    if player:
        player.queue_free()

func _spawn_player(id: int) -> void:
    var player_data = {
        "player_id": id,
        "spawn_position": get_random_spawn_point()
    }
    spawner.spawn(player_data)

func _spawn_player_custom(data: Dictionary) -> Node:
    var player = preload("res://scenes/player.tscn").instantiate()
    player.name = str(data.player_id)
    player.set_multiplayer_authority(data.player_id)
    player.position = data.spawn_position
    return player
```

### 玩家场景

```gdscript
# player.gd
extends CharacterBody2D

@export var speed: float = 200.0
@export var health: int = 100

@onready var synchronizer: MultiplayerSynchronizer = $MultiplayerSynchronizer
@onready var label: Label = $Label

func _ready() -> void:
    label.text = str(get_multiplayer_authority())

    # 只有拥有 Authority 时才处理
    set_physics_process(is_multiplayer_authority())
    set_process_input(is_multiplayer_authority())

func _physics_process(delta: float) -> void:
    var input_dir = Input.get_vector("move_left", "move_right", "move_up", "move_down")
    velocity = input_dir * speed
    move_and_slide()

@rpc(any_peer)
func take_damage(amount: int) -> void:
    # 只有服务器处理伤害
    if not multiplayer.is_server():
        return

    health -= amount

    if health <= 0:
        rpc("died")
        _respawn()

@rpc(call_local)
func died() -> void:
    visible = false
    set_physics_process(false)

func _respawn() -> void:
    health = 100
    position = Vector2.ZERO
    rpc("respawned")

@rpc(call_local)
func respawned() -> void:
    visible = true
    set_physics_process(is_multiplayer_authority())
```

### 断线处理

```gdscript
func _setup_disconnection_handling() -> void:
    multiplayer.server_disconnected.connect(_on_server_disconnected)
    multiplayer.peer_disconnected.connect(_on_peer_disconnected)
    get_tree().auto_accept_quit = false

func _notification(what: int) -> void:
    if what == NOTIFICATION_WM_CLOSE_REQUEST:
        _cleanup_and_quit()

func _cleanup_and_quit() -> void:
    if multiplayer.multiplayer_peer:
        multiplayer.multiplayer_peer.close()
        multiplayer.multiplayer_peer = null
    get_tree().quit()

func _on_server_disconnected() -> void:
    push_warning("Server disconnected")
    multiplayer.multiplayer_peer = null
    get_tree().change_scene_to_file("res://scenes/lobby.tscn")

func _on_peer_disconnected(id: int) -> void:
    var player = get_node_or_null("Players/" + str(id))
    if player:
        player.queue_free()
```

## 示例

### 基本主机/客户端设置

```gdscript
# network_manager.gd - Autoload 单例
extends Node

signal player_connected(id: int)
signal player_disconnected(id: int)
signal server_started
signal connection_failed

@export var default_port: int = 7000
@export var max_players: int = 4

var peer: ENetMultiplayerPeer = null

func create_server(port: int = default_port) -> Error:
    peer = ENetMultiplayerPeer.new()
    var err = peer.create_server(port, max_players)

    if err == OK:
        multiplayer.multiplayer_peer = peer
        _setup_signals()
        server_started.emit()

    return err

func join_server(address: String, port: int = default_port) -> Error:
    peer = ENetMultiplayerPeer.new()
    var err = peer.create_client(address, port)

    if err == OK:
        multiplayer.multiplayer_peer = peer
        _setup_signals()
    else:
        connection_failed.emit()

    return err

func _setup_signals() -> void:
    multiplayer.peer_connected.connect(func(id): player_connected.emit(id))
    multiplayer.peer_disconnected.connect(func(id): player_disconnected.emit(id))

func close_connection() -> void:
    if peer:
        peer.close()
        multiplayer.multiplayer_peer = null
        peer = null
```

### 玩家同步

```gdscript
# synced_player.gd
extends CharacterBody2D

@export var sync_position: Vector2:
    set(value):
        sync_position = value
        if not is_multiplayer_authority():
            position = sync_position

@export var sync_rotation: float:
    set(value):
        sync_rotation = value
        if not is_multiplayer_authority():
            rotation = sync_rotation

func _physics_process(delta: float) -> void:
    if is_multiplayer_authority():
        # 更新同步变量（MultiplayerSynchronizer 负责发送）
        sync_position = position
        sync_rotation = rotation

        var input = Input.get_vector("move_left", "move_right", "move_up", "move_down")
        velocity = input * 200
        move_and_slide()
```

### 状态复制

```gdscript
# game_state.gd - 服务器权威的游戏状态
extends Node

# 复制到所有客户端
@export var game_time: float = 0.0
@export var scores: Dictionary = {}
@export var game_phase: String = "lobby"

func _physics_process(delta: float) -> void:
    if multiplayer.is_server():
        game_time += delta
        _check_win_conditions()

func add_score(player_id: int, points: int) -> void:
    # 只有服务器修改状态
    if not multiplayer.is_server():
        return

    if not scores.has(player_id):
        scores[player_id] = 0

    scores[player_id] += points

    # 状态通过 MultiplayerSynchronizer 自动同步
    rpc("score_updated", player_id, scores[player_id])

@rpc(call_local)
func score_updated(player_id: int, new_score: int) -> void:
    print("Player ", player_id, " score: ", new_score)

func _check_win_conditions() -> void:
    for player_id in scores:
        if scores[player_id] >= 100:
            end_game(player_id)

func end_game(winner_id: int) -> void:
    game_phase = "ended"
    rpc("game_ended", winner_id)

@rpc(call_local)
func game_ended(winner_id: int) -> void:
    print("Game over! Winner: ", winner_id)
    get_tree().change_scene_to_file("res://scenes/victory.tscn")
```

### 聊天系统

```gdscript
# chat_system.gd
extends Control

@onready var chat_display: RichTextLabel = $ChatDisplay
@onready var chat_input: LineEdit = $ChatInput
@onready var send_button: Button = $SendButton

func _ready() -> void:
    send_button.pressed.connect(_send_message)
    chat_input.text_submitted.connect(func(_t): _send_message())

func _send_message() -> void:
    var message = chat_input.text.strip_edges()
    if message.is_empty():
        return

    var sender_id = multiplayer.get_unique_id()
    var sender_name = "Player " + str(sender_id)

    # 发送给所有 Peer（包括服务器）
    rpc("receive_message", sender_name, message)

    chat_input.clear()

@rpc(any_peer, call_local)
func receive_message(sender: String, message: String) -> void:
    var formatted = "[b]%s:[/b] %s\n" % [sender, message]
    chat_display.append_text(formatted)

    # 自动滚动到底部
    chat_display.scroll_to_line(chat_display.get_line_count())
```

## 从 Godot 3.x 迁移

### 远程函数

```gdscript
# Godot 3.x（旧版）
remote func attack(target_id: int, damage: int) -> void:
    var target = get_node("../Players/" + str(target_id))
    if target:
        target.health -= damage

remotesync func update_position(pos: Vector2) -> void:
    position = pos

master func validate_movement(pos: Vector2) -> bool:
    return is_valid_position(pos)

slave func receive_correction(pos: Vector2) -> void:
    position = pos

# Godot 4.x（新版）
@rpc(any_peer)
func attack(target_id: int, damage: int) -> void:
    var target = get_node("../Players/" + str(target_id))
    if target:
        target.health -= damage

@rpc(any_peer, call_local)
func update_position(pos: Vector2) -> void:
    position = pos

@rpc(authority)
func validate_movement(pos: Vector2) -> bool:
    return is_valid_position(pos)

@rpc
func receive_correction(pos: Vector2) -> void:
    position = pos
```

### RPC 调用

```gdscript
# Godot 3.x（旧版）
rpc("function_name", arg1, arg2)
rpc_id(peer_id, "function_name", arg1, arg2)
rpc_unreliable("function_name", arg1)

# Godot 4.x（新版）
rpc("function_name", arg1, arg2)           # 可靠传输，默认
rpc_id(peer_id, "function_name", arg1, arg2)

# 对于不可靠传输，在函数上使用注解：
@rpc(unreliable)
func fast_update() -> void:
    pass
```

### 网络 Peer 访问

```gdscript
# Godot 3.x（旧版）
var peer = get_tree().network_peer
var my_id = get_tree().get_network_unique_id()
var is_server = get_tree().is_network_server()

# Godot 4.x（新版）
var peer = multiplayer.multiplayer_peer
var my_id = multiplayer.get_unique_id()
var is_server = multiplayer.is_server()
```

### 自定义 Multiplayer

```gdscript
# Godot 3.x（旧版）- 自定义 MultiplayerAPI
var custom_multiplayer = MultiplayerAPI.new()
custom_multiplayer.set_root_node(self)
set_custom_multiplayer(custom_multiplayer)

# Godot 4.x（新版）- SceneMultiplayer
var scene_multiplayer = SceneMultiplayer.new()
get_tree().set_multiplayer(scene_multiplayer, get_path())
```

## 使用场景

### 构建新的多人游戏
在 Godot 4.x 中从零开始搭建网络系统。

### 迁移现有游戏
将 Godot 3.x 的多人代码转换为 4.x 语法。

### 为单人游戏添加多人功能
为现有游戏改装网络功能。

## 常见错误

| 错误 | 修复方法 |
|---------|-----|
| `remote func` 语法 | 使用 `@rpc` 注解 |
| 在 Peer 设置之前调用 RPC | 先设置 `multiplayer.multiplayer_peer` |
| 未设置 Authority | 使用 `set_multiplayer_authority(id)` |
| 服务器直接处理客户端输入 | 验证所有客户端输入 |
| 同步所有内容 | 只同步必要的内容 |
| 位置更新使用可靠 RPC | 频繁更新使用 `@rpc(unreliable)` |
| 忘记 `call_local` | 如果函数也应在调用者上运行，请添加 |
| 不使用 Spawner 生成节点 | 对复制的 Node 使用 `MultiplayerSpawner` |

## 集成

可搭配使用：
- **godot-modernize-gdscript** - 与现代 GDScript 特性结合使用
- **godot-profile-performance** - 优化网络带宽
- **godot-setup-navigation** - 多人 AI 寻路

## 安全性

- 始终在服务器端验证客户端输入
- 对关键游戏状态使用服务器 Authority
- 清理聊天消息（防止注入）
- 限制 RPC 调用频率（速率限制）
- 对非关键数据使用不可靠通道

## 参考资源

- Godot 4.x 高级 Multiplayer：https://docs.godotengine.org/en/stable/tutorials/networking/high_level_multiplayer.html
- RPC 教程：https://docs.godotengine.org/en/stable/tutorials/networking/rpc.html
- MultiplayerSynchronizer：https://docs.godotengine.org/en/stable/classes/class_multiplayersynchronizer.html
