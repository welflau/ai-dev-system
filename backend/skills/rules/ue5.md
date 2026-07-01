---
alwaysApply: false
pack: ue5-dev
traits_match:
  any_of: [ue5, unreal, game-ue]
priority: high
description: UE5 项目专属规范（资产命名 / Blueprint / C++ UE 约定）
---

# UE5 项目编码规范

## 一、资产命名

按前缀表严格命名，禁止使用默认名（NewBlueprint、Untitled）：

| 前缀 | 类型 |
|------|------|
| `BP_` | Blueprint 类 |
| `SM_` / `SK_` | Static / Skeletal Mesh |
| `ABP_` | Animation Blueprint |
| `T_` | Texture（后缀：D=BaseColor, N=Normal, M=Mask/ORM） |
| `M_` / `MI_` | Material / Material Instance |
| `NS_` / `NE_` | Niagara System / Emitter |
| `WBP_` | Widget Blueprint |
| `DT_` / `DA_` | Data Table / Data Asset |
| `GA_` / `GE_` | Gameplay Ability / Effect |

**禁止**：
- 空格（用 `_` 分隔）
- 中文路径或文件名
- 在 `Content/` 根目录直接放资产

## 二、C++ UE 约定

- 使用 UE 宏：`UCLASS()`, `UPROPERTY()`, `UFUNCTION()`, `GENERATED_BODY()`
- 类名前缀：`A`=Actor, `U`=UObject, `F`=Struct/Plain, `I`=Interface, `E`=Enum
- **禁用** `LogTemp`，必须定义模块专属 log 类别：`DEFINE_LOG_CATEGORY_STATIC(LogMyModule, Log, All)`
- 引擎修改必须用标记包裹：
  ```cpp
  // OG2 Modification Begin — <原因>
  <修改内容>
  // OG2 Modification End
  ```
- `UPROPERTY` 的 `Replicated` 属性配合 Iris Push Model 时必须调用 `MARK_PROPERTY_DIRTY`

## 三、Blueprint

- 节点注释覆盖所有复杂逻辑块
- 禁止在 Blueprint 中硬编码数值，通过 DataAsset 或 DataTable 配置
- 不要在 Tick 函数中每帧做高开销操作（射线检测、GetAllActorsOfClass 等）

## 四、网络同步决策

- **一次性事件** → Server RPC（技能释放、伤害申请）
- **持续状态** → Replicated 属性（血量、Buff 列表）
- 新加 Replicated 属性时，在 `GetLifetimeReplicatedProps` 中用 `DOREPLIFETIME_CONDITION` 精细控制
- 客户端不能直接修改 Replicated 属性（会被服务端覆盖）

## 五、Python 脚本（UE Editor 执行）

- 每次调用包含完整闭环：查询 → 操作 → 验证 → 保存
- 资产操作必须包在 `unreal.ScopedEditorTransaction` 中
- 禁止 `import os` / `import subprocess`
- 操作完成后调用 `unreal.EditorAssetLibrary.save_all_dirty_assets()`
