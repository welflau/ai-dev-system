# P111 角色蓝图组织方式调查报告

**调查日期**: 2026-07-08
**调查工具**: UE Editor MCP (editor.list_assets + blueprint.get_summary)

---

## 一、内容目录结构

```
/Game/P111/
├── Blueprints/
│   ├── Characters/
│   │   ├── BP_Black_Character          ← 核心角色蓝图
│   │   └── Child/
│   │       └── BP_Child_HammerAttack   ← 子功能蓝图
│   ├── Crash/
│   │   ├── BP_PC_Crash                 ← Player Controller
│   │   ├── BP_GS_Crash                 ← Game State
│   │   └── BP_GM_Crash                 ← Game Mode
│   ├── Weapons/
│   │   ├── Common/                     ← 公共武器基类
│   │   │   ├── BP_BaseWeapon
│   │   │   ├── BP_WeaponViewer
│   │   │   ├── GA_*/GE_*               ← 武器通用 Gameplay Ability/Effect
│   │   ├── Chainsaw/                   ← 电锯武器
│   │   ├── Cleaner/                    ← 清洁器武器
│   │   ├── Hammer/                     ← 锤子武器
│   │   ├── ModuleWeapon/               ← 模块武器
│   │   ├── SteerPipe/                  ← 钢管武器
│   │   ├── Tablet/                     ← 平板武器
│   │   └── Welding/                    ← 焊枪武器
│   ├── UserWidgets/
│   │   └── CharacterHUD/               ← 角色 HUD
│   ├── Lobby/                          ← 大厅系统
│   └── BP_SplashGameMode               ← 启动 GameMode
├── Characters/
│   ├── BLACK/
│   │   ├── SK_Black                    ← Skeleton
│   │   ├── SKM_Black_PhysicsAsset      ← Physics Asset
│   │   ├── SKM_BLK                     ← Skeletal Mesh
│   │   └── Animations/
│   │       ├── Attack/                 ← 按武器分类的攻击动画
│   │       │   ├── Chainsaw/
│   │       │   ├── Cleaner/
│   │       │   ├── HammerAttack/
│   │       │   ├── SteerPipe/
│   │       │   ├── Tablet/
│   │       │   └── Welding/
│   │       ├── Combat/                 ← 受击/击倒动画
│   │       └── Locomotion/             ← 移动/跳跃/落地动画
│   └── NewMaterial
├── Data/DataTables/GameplayTags/       ← Gameplay Tag 数据表
├── UI/                                 ← UI 系统
├── VFX/                                ← 特效
├── Audio/                              ← 音频
└── Levels/                             ← 关卡
```

---

## 二、核心角色蓝图 BP_Black_Character

### 继承链
```
BP_Black_Character
  └── InstancedCharacter (C++, /Script/P111.InstancedCharacter)
```

### 变量 (15个, 全部 Instance Editable)

| 变量名 | 类型 | 分类 | 说明 |
|--------|------|------|------|
| bUseGunBoneForOverlayObjects | bool | Settings\Als Character | ALS 覆盖层是否使用枪骨骼 |
| OverlayAnimationInstanceClasses | Map<GameplayTag, Class> | Settings\Als Character | 覆盖层动画实例类映射 |
| CurrentSkeletalMesh | SkeletalMesh | Default | 当前骨骼网格体 |
| CurrentHatSlot | StaticMesh | Default | 当前帽子槽位 |
| PrmaryWeaponNames | Array<Name> | Default | 主武器名称列表 |
| PrimaryWeaponNumber | int | Default | 当前主武器编号 |
| Optional Object 2 | Object | Default | 可选物体 |
| ShouldSHowGASLog | bool | Default | 是否显示 GAS 日志 |
| ShouldCameraFollowCharacter | bool | Default | 相机是否跟随角色 |
| CameraWorldTransform | Transform | Default | 相机世界变换 |
| Default2DFollow | EAlsLocomotionCameraMode | Default | 默认 2D 跟随模式 |
| AvaliableLocomotionMode | Array<EAlsLocomotionCameraMode> | Default | 可用移动模式列表 |
| CurrentLocomotionMode | int | Default | 当前移动模式 |
| AimingUI | BP_UW_Aiming_C | Default | 瞄准 UI 引用 |
| AimmingUIIsAdded | bool | Default | 瞄准 UI 是否已添加 |

### 函数 (16个)

- **外观管理**: RefreshOverlayLinkedAnimationLayer, RefreshOverlayObject, AttachOverlayObject, ClearOverlayObject
- **外观获取**: Get_SkeletalMesh, Get_Hat, Get_Player_Appearance
- **武器切换**: PrimaryWeaponSwitch, OnSwitchPrimaryWeapon, OnSwitchSecondaryWeapon, OnSwitchNoneWeapon
- **移动模式**: SelectMantlingSettings, SetAvaliableLocomotionMode
- **UI 相关**: BuffDisplay, AimmingUIDisplayCheck
- **复制回调**: OnRep_CurrentSkeletalMesh, OnRep_CurrentHatSlot
- **调试**: DebugTest

### Event Graph (127 个节点)

关键事件:
- BeginPlay, Tick
- ALS 回调: OnOverlayModeChanged, OnMantlingStarted/Ended, OnRagdollingStarted/Ended
- 外观更新: SR_Update_SkeletalMesh, SR_Update_Hat, OC_Init_Appearance
- 武器切换: OnSwitchPrimary/Secondary/NoneWeapon
- 攻击回调: OnAttackStart, OnAttackTrigger

### 组件 (5个)

| 组件名 | 类型 | 父级 | 说明 |
|--------|------|------|------|
| OverlaySkeletalMesh | SkeletalMeshComponent | CharacterMesh0 | 覆盖层骨骼网格 |
| OverlayStaticMesh | StaticMeshComponent | CharacterMesh0 | 覆盖层静态网格 |
| HatSlot | StaticMeshComponent | CharacterMesh0 | 帽子槽位 |
| Scene | SceneComponent | CollisionCylinder | 场景组件 |
| Sphere | StaticMeshComponent | - | 球体装饰 |

---

## 三、Player Controller: BP_PC_Crash

### 继承链
```
BP_PC_Crash
  └── P111LevelPlayerController (C++, /Script/P111.P111LevelPlayerController)
```

### 组件
- **BuffClient**: P111BuffClientComponent (自定义 buff 客户端组件)

### Event Graph
仅 BeginPlay + Tick，逻辑极简，核心逻辑在 C++ 基类中。

---

## 四、武器蓝图组织模式

每个武器遵循统一的目录结构:
```
Weapons/<WeaponName>/
├── BP_<WeaponName>              ← 武器 Actor 蓝图
├── BP_Viewer_<WeaponName>       ← 武器预览/展示蓝图
├── GA_<WeaponName>*             ← Gameplay Ability (攻击/启动/恢复/循环)
└── GE_<WeaponName>*             ← Gameplay Effect (伤害/消耗/冷却/Buff)
```

武器种类: Chainsaw, Cleaner, Hammer, ModuleWeapon, SteerPipe, Tablet, Welding

---

## 五、动画命名规范

| 前缀 | 含义 |
|------|------|
| SQ_ | 动画序列 (Sequence, 旧命名) |
| AS_ | 动画序列 (AnimSequence, 新命名) |
| AM_ | 动画蒙太奇 (AnimMontage) |
| BS_ | 混合空间 (BlendSpace) |
| SK_ | 骨架 (Skeleton) |
| SKM_ | 骨骼网格体 (SkeletalMesh) |

---

## 六、关键发现

1. **C++ 基类驱动**: 角色核心逻辑在 `InstancedCharacter` (C++) 中，蓝图仅做外观定制和 UI 绑定
2. **ALS 集成**: 使用 Advanced Locomotion System (ALS) 处理移动/攀爬/倒地动画
3. **GAS 驱动战斗**: Gameplay Ability System 管理武器能力 (GA_*) 和效果 (GE_*)
4. **外观系统**: 通过 SkeletalMesh + StaticMesh 覆盖层实现角色换装
5. **武器模块化**: 每把武器独立目录，含 GA/GE/Viewer 三件套
6. **Blueprint 继承自 C++**: BP_PC_Crash, BP_GS_Crash, BP_GM_Crash 均继承自 P111 C++ 类
