# Unreal Engine C++ 开发规范

> 适用于 engine:ue5 / ue4 项目。所有 C++ 代码要让 UnrealBuildTool + UnrealHeaderTool 通过。

## 命名约定（强制）

| 前缀 | 用途 | 例 |
|---|---|---|
| `A` | Actor 派生类 | `AMyCharacter`, `AWeaponBase` |
| `U` | UObject 派生类（非 Actor） | `UMyComponent`, `UPlayerData` |
| `F` | 普通 struct / 值类型 | `FVector`, `FPlayerStats` |
| `E` | enum | `EWeaponType` |
| `I` | Interface | `IInteractable` |
| `S` | Slate widget | `SMyButton` |
| `T` | Template | `TArray`, `TMap` |

**类名必须和文件名一致**。例：`AMyCharacter` 放在 `MyCharacter.h / MyCharacter.cpp`。`.generated.h` 文件名也必须对上（`MyCharacter.generated.h`）。

## UCLASS / UFUNCTION / UPROPERTY 宏（强制）

任何让蓝图可见、可反射、可 GC 的类/函数/属性，都必须带对应宏。**漏宏是 UHT 错误最常见来源**。

### 类声明模板

```cpp
// MyCharacter.h
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "MyCharacter.generated.h"     // ← 必须最后一个 include

UCLASS()
class MYPROJECT_API AMyCharacter : public ACharacter
{
    GENERATED_BODY()                    // ← 必须第一行（构造函数前）

public:
    AMyCharacter();

protected:
    virtual void BeginPlay() override;

public:
    virtual void Tick(float DeltaTime) override;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stats")
    float Health = 100.0f;

    UFUNCTION(BlueprintCallable, Category = "Actions")
    void Attack();
};
```

**关键点**：
- `#include "<ClassName>.generated.h"` 永远是 `.h` 文件的**最后一个** include
- `GENERATED_BODY()` 放在 class 体的**最开头**（public 之前）
- `<MODULE>_API` 宏（全大写模块名 + `_API`）让符号能被别的模块引用
- 不带 UCLASS 的 UObject 派生类无法被 GC 管理，new 出来会泄漏

### UPROPERTY 修饰符

- `EditAnywhere` — 可在 BP 编辑器里改
- `BlueprintReadWrite` — BP 脚本可读写
- `BlueprintReadOnly` — BP 只读
- `VisibleAnywhere` — 只能看不能改（component 引用常用）
- `Category = "X"` — 分组
- `Transient` — 不序列化
- `meta = (ClampMin="0", ClampMax="100")` — 数值范围

### UFUNCTION 修饰符

- `BlueprintCallable` — BP 脚本可调用
- `BlueprintPure` — 无副作用的纯函数
- `BlueprintImplementableEvent` — 只声明，由 BP 实现
- `BlueprintNativeEvent` — C++ 默认实现 + BP 可重写
- `Server` / `Client` / `NetMulticast` — RPC

## 类型规则

### 字符串（三选一，别混淆）

| 类型 | 用途 |
|---|---|
| `FString` | 可变字符串，运行时拼接用 |
| `FName` | 不可变、哈希化的标识符（资产名 / tag） |
| `FText` | 本地化文本（UI 显示给玩家看的） |

```cpp
FString Name = TEXT("Player");              // 用 TEXT() 包裹字面量
FString Msg = FString::Printf(TEXT("HP: %d"), Health);
UE_LOG(LogTemp, Log, TEXT("Value = %s"), *Msg);    // 格式化要加 * 解引用

FName AssetId = FName(TEXT("WeaponRifle"));
FText Label = NSLOCTEXT("UI", "StartGame", "开始游戏");
```

### 引用类型

- `TObjectPtr<UType>` — UE5 推荐，替代裸指针 `UType*`
- `TSubclassOf<AType>` — "类引用"（持有一个 AType 的派生类），BP 可配
- `TSoftObjectPtr<UType>` — 软引用，延迟加载，不强持
- `TWeakObjectPtr<UType>` — 弱引用
- `TSharedPtr<FType>` — 非 UObject 智能指针（给 FStruct / Slate 用）

```cpp
UPROPERTY(EditAnywhere, BlueprintReadWrite)
TSubclassOf<AWeaponBase> DefaultWeaponClass;

UPROPERTY()
TObjectPtr<UStaticMeshComponent> MeshComp;
```

### 容器

- `TArray<T>` — 动态数组（UE 版 `std::vector`）
- `TMap<K, V>` — 哈希表
- `TSet<T>` — 集合

## Build.cs 模块依赖（强制）

编译链接错误几乎都是 Build.cs 漏模块。**每用一类功能就补对应模块**：

```csharp
// MyProject.Build.cs
public class MyProject : ModuleRules
{
    public MyProject(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        PublicDependencyModuleNames.AddRange(new string[] {
            "Core", "CoreUObject", "Engine", "InputCore",    // 基础 4 件套
            "EnhancedInput",                                  // UE5 新输入
            // 按需加：
            // "UMG"           - UI widget
            // "Slate", "SlateCore" - Slate framework
            // "AIModule"      - BehaviorTree / Perception
            // "GameplayAbilities", "GameplayTags", "GameplayTasks" - GAS
            // "OnlineSubsystem", "OnlineSubsystemUtils"  - multiplayer
            // "PhysicsCore", "Chaos" - 物理
            // "Niagara"       - VFX
        });

        PrivateDependencyModuleNames.AddRange(new string[] {
            // 仅 cpp 里用到的，不出现在 public 头文件
        });
    }
}
```

## 常见坑

### 1. 同名头文件（UHT 会拒）

```
Source/Game/Player/MyController.h
Source/Game/Controllers/MyController.h    ← UHT 直接报错 "same name not allowed"
```

**规则**：整个项目里，`.h` 文件**全名**必须唯一。不同类放不同目录也不行。重名必须改名。

### 2. 循环 include

头文件互相 include 自己 → 编译不过。解决：

```cpp
// A.h
#pragma once
class UB;                  // 前向声明，而非 #include "B.h"
UCLASS()
class MYMOD_API UA : public UObject {
    UPROPERTY()
    TObjectPtr<UB> Ref;    // 指针/引用可以前向声明
};

// A.cpp
#include "A.h"
#include "B.h"              // 实现文件里再 include
```

### 3. UObject 派生类不能 `new`

```cpp
// 错 — UObject 不归 C++ 管，会被 GC 二次释放
UMyObj* obj = new UMyObj();

// 对 — 用 NewObject 走 UE 的对象系统
UMyObj* obj = NewObject<UMyObj>(this);

// Actor 用 SpawnActor
AMyActor* actor = GetWorld()->SpawnActor<AMyActor>(AMyActor::StaticClass(), Location, Rotation);
```

### 4. .generated.h include 顺序错

`.generated.h` 必须是**最后一个** include，否则 UHT 报"Missing generated include"。

### 5. 忘记 GENERATED_BODY

class 体第一行漏 `GENERATED_BODY()` → UHT 报 "Missing GENERATED_BODY macro"。

### 6. UFUNCTION 签名限制

- BlueprintCallable 的函数**参数和返回类型**必须是 BP 可识别的（int / float / FString / FVector / UObject* / TSubclassOf / TArray<T> / USTRUCT…）
- 不能用 `std::vector` / `std::function` / `std::map` 等 STL 类型 — BP 认不出

### 7. const correctness（UE 风格）

```cpp
UFUNCTION(BlueprintPure, Category = "Queries")
int32 GetHealth() const { return Health; }              // ← const 函数 + BlueprintPure
```

### 8. 委托（Delegate）

```cpp
// 头文件声明
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FOnHealthChanged, float, NewHealth);

UPROPERTY(BlueprintAssignable, Category = "Events")
FOnHealthChanged OnHealthChanged;

// 广播
OnHealthChanged.Broadcast(Health);
```

`DYNAMIC` 才能被 BP 绑定；不带 `DYNAMIC` 的只能 C++ 绑。

## 自测 checklist（写完代码后自查）

1. `.h` 末尾是不是 `#include "<ClassName>.generated.h"`？
2. class 体第一行是不是 `GENERATED_BODY()`？
3. UCLASS / UPROPERTY / UFUNCTION 宏该加的都加了？
4. 类名和文件名对得上？没跟其他 `.h` 重名？
5. Build.cs 里用到的模块都在 `PublicDependencyModuleNames` / `PrivateDependencyModuleNames` 里？
6. 用了 UObject 就走 NewObject，不 `new`？
7. `.generated.h` 是最后一个 include？
8. 头文件里的裸引用尽量前向声明，.cpp 再 include？

## ⚠️ 静态预检会拦的 7 类错（v0.19.x Layer 1，务必提前避开）

DevAgent 写完会过 7 条 UE 静态规则（`actions/ue_lint/rules.py`），违反的工单会
立刻回 fix_issues。写代码时主动避开能省 3-5 分钟 UBT fail 循环：

**R1** UCLASS/USTRUCT 下 10 行内必须有 `GENERATED_BODY()`。

**R2** 子类 override 父类已有的 `OnRep_*` 时**不要加 `UFUNCTION()` 宏**，写
`virtual void OnRep_Score() override;` 即可。常见父类 OnRep：APlayerState.OnRep_Score/
OnRep_PlayerName、AActor.OnRep_Owner、ACharacter.OnRep_IsCrouched。反之子类
**新增**的 OnRep_MyVar 必须加 UFUNCTION()。

**R3** `#include "XXX.h"` 的 XXX.h 必须可被 UE 找到。**文件在子目录时必须写
路径前缀**：`#include "Character/FPSCharacterBase.h"` 而不是 `"FPSCharacterBase.h"`。

**R4** Build.cs 的 module 名要是合法 UE 模块。`"Components"` 不是模块是
Engine 子目录。常用：`Core CoreUObject Engine InputCore EnhancedInput Slate
SlateCore UMG GameplayTasks AIModule NavigationSystem UnrealEd`。

**R5** `.uproject` 的 `"Modules"` 数组必须覆盖 Source/ 下所有 `*.Build.cs`。
漏声明会让 UBT 不编译该模块。

**R6** Target.cs 的 `IncludeOrderVersion` 跟引擎对齐：UE 5.3 下用
`EngineIncludeOrderVersion.Unreal5_3`，用 Unreal5_1 会 deprecate warning。

**R7** 用到 UE 类型必需对应 `#include`（forward decl 够不上实例化）：
- `UCapsuleComponent` → `#include "Components/CapsuleComponent.h"`
- `USpringArmComponent` → `#include "GameFramework/SpringArmComponent.h"`
- `UCameraComponent` → `#include "Camera/CameraComponent.h"`
- `UCharacterMovementComponent` → `#include "GameFramework/CharacterMovementComponent.h"`
- `UEnhancedInputComponent` → `#include "EnhancedInputComponent.h"`
- `UInputAction/UInputMappingContext` → 同名 header
- `FInputActionValue` → `#include "InputActionValue.h"`
- `UGameplayStatics` → `#include "Kismet/GameplayStatics.h"`

误报时可加 `// @ue-lint-skip R2` 注释关单条规则。
