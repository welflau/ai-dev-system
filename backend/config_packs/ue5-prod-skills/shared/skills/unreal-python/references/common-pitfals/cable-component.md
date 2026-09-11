# UE5 Python CableComponent 关键代码参考

> 本文档总结了使用 Python 操作 UE5 CableComponent 时最容易犯错的3个关键点。

## 1. ComponentReference 正确设置方式

```python
# ❌ 错误方式 - set_attach_end_to_component() 是运行时方法，不会持久化到蓝图
cable_component.set_attach_end_to_component(bag_component, "")
# 结果: attach_end_to.component_property 仍然是空字符串

# ✅ 正确方式 - 创建 ComponentReference 结构体并设置
comp_ref = unreal.ComponentReference(
    component_property="PunchingBagMesh",  # 组件的变量名，不是显示名
    other_actor=None  # 同一Actor内的组件用None
)
cable_component.set_editor_property("attach_end_to", comp_ref)
# 结果: attach_end_to.component_property = "PunchingBagMesh"
```

## 2. 获取蓝图组件的变量名

```python
# 蓝图组件有两个名字：显示名 (obj.get_name()) 和 变量名 (用于ComponentReference)
# ❌ 错误: 使用 get_name() 返回的是 "PunchingBagMesh_GEN_VARIABLE"
# ✅ 正确: 使用 get_variable_name() 返回 "PunchingBagMesh"

subsystem = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
helper = unreal.SubobjectDataBlueprintFunctionLibrary

handles = subsystem.k2_gather_subobject_data_for_blueprint(blueprint)
for handle in handles:
    data = subsystem.k2_find_subobject_data_from_handle(handle)
    if data:
        obj = helper.get_object_for_blueprint(data, blueprint)
        var_name = helper.get_variable_name(data)  # ← 这才是正确的变量名
        # var_name = "PunchingBagMesh" (用于ComponentReference)
        # obj.get_name() = "PunchingBagMesh_GEN_VARIABLE" (不能用于ComponentReference)
```

## 3. end_location 的相对性取决于 attach_end_to

```python
# CableComponent.end_location 的含义取决于 attach_end_to 是否设置

# 情况1: attach_end_to 为空 → end_location 相对于 Cable 组件自身位置
# Cable在(0,0,0), end_location=(0,0,35) → 线缆指向上方 ↑ (错误!)
# Cable在(0,0,0), end_location=(0,0,-65) → 线缆指向下方 ↓ (正确)

# 情况2: attach_end_to 已设置 → end_location 相对于被附着组件的位置
# 附着到 PunchingBagMesh (位于0,0,-100), end_location=(0,0,35)
# → 线缆终点在 bag 中心上方35单位 = bag顶部 (正确)

# ⚠️ 关键检查: 设置后必须验证 attach_end_to 是否真的生效
attach_ref = cable_component.get_editor_property("attach_end_to")
component_prop = str(attach_ref.component_property) if hasattr(attach_ref, 'component_property') else ""

if component_prop and component_prop != "None":
    # 附着生效，使用相对于目标组件的偏移
    cable_component.set_editor_property("end_location", unreal.Vector(0, 0, 35))
else:
    # 附着未生效，使用静态世界位置
    cable_component.set_editor_property("end_location", unreal.Vector(0, 0, -65))
```

---

## 总结要点

| 问题 | 错误做法 | 正确做法 |
|------|---------|---------|
| 设置组件引用 | `set_attach_end_to_component()` | `ComponentReference()` + `set_editor_property()` |
| 获取变量名 | `obj.get_name()` | `helper.get_variable_name(data)` |
| 设置终点位置 | 假设附着总是成功 | 检查后根据附着状态设置不同值 |
