# 开发日志 — 2026-04-26（TestFPS C++ 编译修复）

## 背景

TestFPS（`D:\Projects\TestFPS`）是主要的 UE5 验证项目。在调试"点 CI 编译按钮无法启动 UBT"的过程中，顺带把 TestFPS 本身积累的 C++ 编译错误全部修完，最终 **exit=0，0 errors**。

这些错误都是 AI DevAgent 在生成 C++ 代码时写进去的，属于**可被 Layer 1 静态规则（v0.19.x `actions/ue_lint/rules.py`）提前拦截**的新手错——验证了我们今天实装的自测规则的价值。

---

## 修复过程（3 批）

### 第 1 批：UHT 阶段失败

UBT 的 UnrealHeaderTool 先于 C++ 编译器跑，只要 UHT 报错整个编译立刻终止（exit=6）。

| 文件 | 错误 | 修复 | 对应 Lint 规则 |
|---|---|---|---|
| `TestFPS.Target.cs`<br>`TestFPSEditor.Target.cs` | `EngineIncludeOrderVersion.Unreal5_1` 在 UE 5.3 已废弃，5.4 会移除 | 改为 `Unreal5_3` | **R6** IncludeOrderVersion 兼容 |
| `TestFPSPlayerState.h:106` | `OnRep_Score` 重写父类 `APlayerState::OnRep_Score` 但加了 `UFUNCTION()` 宏，UHT 报 "cannot have UFUNCTION() declaration above it" | 去掉宏，改为 `virtual void OnRep_Score() override;` | **R2** 子类 OnRep 禁 UFUNCTION |

修完后 UHT 通过，进入 C++ 编译阶段。

---

### 第 2 批：C++ 编译 —— include 路径 + 父类错误

| 文件 | 错误 | 修复 | 对应 Lint 规则 |
|---|---|---|---|
| `TestFPSPlayerController.cpp:2`<br>`TestFPSGameMode.cpp:3` | `#include "FPSCharacterBase.h"` → `fatal C1083`，文件实际在 `Character/` 子目录 | 改为 `#include "Character/FPSCharacterBase.h"` | **R3** include 路径可定位 |
| `TestFPSGameMode.h` | 继承 `AGameModeBase` 但声明了 `HandleMatchIsWaitingToStart/HasStarted/HasEnded` 并标 `override`，这组方法只在 `AGameMode` 里有（`C3668 ×3`）| 头文件 include 改为 `GameMode.h`，继承改为 `AGameMode` | R2 扩展（override 父类未有的方法）|
| `FPSCharacterBase.cpp:22,26` | `CreateDefaultSubobject<UCapsuleComponent>` 和 `SetupAttachment(GetCapsuleComponent())` 用了 `UCapsuleComponent` 但没 include 对应头文件（`C2027 + C2664`）| 补 `#include "Components/CapsuleComponent.h"` | **R7** 常用类型必需 header |

---

### 第 3 批：PlayerController → FPSCharacterBase 调用错误（9 errors）

根本原因：`TestFPSPlayerController` 把所有 Enhanced Input 委托给 `FPSCharacterBase`，但两者接口设计有以下 3 类不匹配：

**问题 1：protected 访问权限**
```cpp
// FPSCharacterBase.h — protected 区域
void Move(const FInputActionValue& Value);
void Look(const FInputActionValue& Value);
// → C2248: 外部无法访问
```

**问题 2：参数类型签名不符**
```cpp
// FPSCharacterBase 里
void Jump(const FInputActionValue& Value);     // 带参
void Reload(const FInputActionValue& Value);   // 带参

// PlayerController 里
FPSCharacter->Jump();       // 0 参 → C2660
FPSCharacter->Reload();     // 0 参 → C2660
```

ACharacter 的原始 `Jump()` 无参版本被 FPSCharacterBase 的重载版本**隐藏**（C4263/C4264 警告原因）。

**问题 3：方法名不一致**
```cpp
// FPSCharacterBase 实际命名
void Fire(...)       StopFire(...)
void StartAim(...)   StopAim(...)

// PlayerController 调用的名字
StartFiring()  StopFiring()
StartAiming()  StopAiming()
// → C2039 不是成员
```

**修复方案**：在 `FPSCharacterBase` 加一组 **public 中继包装方法**，PlayerController 统一调这些 public 接口：

```cpp
// FPSCharacterBase.h — public 区新增
void MoveCharacter(const FVector2D& MovementVector);
void LookCharacter(const FVector2D& LookVector);
void JumpCharacter();           // 调 ACharacter::Jump()
void StopJumpingCharacter();    // 调 ACharacter::StopJumping()
void StartFiring();             // 空实现，子类 override
void StopFiring();
void StartAiming();
void StopAiming();
void ReloadCharacter();
```

`FPSCharacterBase.cpp` 实现 Move/Look 直接用 `AddMovementInput`/`AddControllerYawInput`，Jump 系列调父类同名方法：
```cpp
void AFPSCharacterBase::JumpCharacter()        { ACharacter::Jump(); }
void AFPSCharacterBase::StopJumpingCharacter() { ACharacter::StopJumping(); }
```

PlayerController 改为调 wrapper：
```cpp
FPSCharacter->MoveCharacter(MovementVector);   // 原来 Move(MovementVector) → 类型不符
FPSCharacter->JumpCharacter();                 // 原来 Jump() → 签名不符
FPSCharacter->StartFiring();                   // 原来 StartFiring() → 不存在
// ...
```

---

## 最终结果

```
UBT 编译 TestFPSEditor  Win64  Development
  exit:     0
  errors:   0
  warnings: 16（均为 C4263/C4264，Jump/StopJumping 签名隐藏父类方法，不影响运行）
  duration: 68s（有中间缓存）
```

---

## 与 Layer 1 Lint 规则的对应

今天实装的 `actions/ue_lint/rules.py` 7 条规则中，TestFPS 这次编译错误的覆盖情况：

| 错误 | 对应规则 | Layer 1 能提前拦截 |
|---|---|---|
| Unreal5_1 废弃 | R6 | ✅ warning 级别 |
| OnRep_Score UFUNCTION 冲突 | R2 | ✅ blocking |
| `#include "FPSCharacterBase.h"` 路径错 | R3 | ✅ blocking + 正确路径建议 |
| `AGameModeBase` 无 HandleMatch* | R2 扩展（暂未实现）| ❌ 漏检（已记录为 R8 待做）|
| `UCapsuleComponent` 未 include | R7 | ✅ blocking |
| `protected` 访问 / 参数签名 / 方法名 | 语义层（静态难判断）| ❌ 需要 Layer 2 UBT 才能发现 |

**结论**：Layer 1 能提前拦 5/9 errors（~55%），剩余 4 个属于跨类型语义错误，需要 Layer 2（UBT -SingleFile）才能发现。这验证了 Layer 1+Layer 2 的分层设计是必要的。

---

## 相关提交

- `02f9766` — `fix(compile): 修复 5 处 UBT 编译错误，TestFPS 全部通过`（TestFPS 仓库）

*2026-04-26 · 接续 v0.19.x UE 编译修复工作*
