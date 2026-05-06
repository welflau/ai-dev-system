# UE 编辑态控制（UCP）

> **前提**：UE Editor 必须开着，且 UnrealClientProtocol 插件已启用（端口 9876）。
> 若 `context["ucp_available"]` 为 False，跳过本节所有操作，走纯 C++ 路径。

## 何时使用编辑态控制

| 场景 | 推荐做法 |
|---|---|
| 读取当前关卡 Actor 列表 / 位置 | `get_actors`（无需重编） |
| 修改 Actor 的 UPROPERTY 值 | `set_property`（无需重编，秒级） |
| Reflexion 反思时需要了解 Editor 现状 | 先调 `get_actors`，再分析 |
| 生成测试场景（Spawn Actor） | `spawn_actor` |
| 改材质参数 | `call` → UMaterialInstanceDynamic::SetScalarParameterValue |
| 修改 Blueprint 变量 | `get_property` / `set_property` 在 CDO 上操作 |

## 通过 UEEditorControlAction 调用

```python
context["op"]   = "get_actors"       # 操作名
context["args"] = {}                  # 参数
result = await UEEditorControlAction().run(context)
# result.data["result"] -> Actor 路径列表
```

## 支持的操作

### get_actors
取当前关卡所有 Actor 路径列表。
```python
{"op": "get_actors"}
# result: ["/Game/Maps/Main.Main:PersistentLevel.BP_Hero_C_0", ...]
```

### get_actors_of_class
取指定 class 的 Actor。
```python
{"op": "get_actors_of_class", "args": {"class_path": "/Script/Engine.StaticMeshActor"}}
```

### get_property
读取 UObject 属性值。
```python
{"op": "get_property", "args": {
    "object_path": "/Game/Maps/Main.Main:PersistentLevel.MyActor_0",
    "property_name": "MaxHealth"
}}
# result: 100.0
```

### set_property
写入属性值（自动 git stash 兜底）。
```python
{"op": "set_property", "args": {
    "object_path": "/Game/Maps/Main.Main:PersistentLevel.MyActor_0",
    "property_name": "MaxHealth",
    "value": 200
}}
```

### spawn_actor
在关卡里生成 Actor。
```python
{"op": "spawn_actor", "args": {
    "class_path": "/Script/Engine.PointLight",
    "location": {"X": 0, "Y": 0, "Z": 300},
    "rotation": {"Pitch": 0, "Yaw": 0, "Roll": 0}
}}
```

### destroy_actor
删除 Actor（自动 git stash 兜底）。
```python
{"op": "destroy_actor", "args": {"object_path": "/Game/Maps/Main.Main:PersistentLevel.BP_Enemy_0"}}
```

### call（原始 UCP 调用）
直接调用任意 UFunction：
```python
{"op": "call", "args": {
    "object": "/Script/UnrealEd.Default__EditorActorSubsystem",
    "function": "SelectNothing"
}}
```

## 对象路径约定

| 类型 | 格式 | 示例 |
|---|---|---|
| 静态库/CDO | `/Script/<Module>.Default__<Class>` | `/Script/UnrealEd.Default__EditorActorSubsystem` |
| 关卡 Actor | `/Game/Maps/<Level>.<Level>:PersistentLevel.<Name>` | `.../Main.Main:PersistentLevel.BP_Hero_C_0` |
| 蓝图 CDO | `/Game/<Path>/<BP>.<BP>_C:CDO` | - |

## 安全规则

- **写操作**（set_property / spawn / destroy）：系统自动 git stash，失败时自动 pop 回滚
- 不要在不了解影响的情况下写 CDO 属性（会影响所有实例）
- 每次写操作后在 reply 里告诉用户修改了什么，方便 revert
