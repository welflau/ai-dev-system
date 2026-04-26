"""UE 5.3 静态规则需要的常量数据

这些数据来自 UE 5.3 源码扫描 + 实战常见坑整理。其他 UE 版本（5.4/5.5/5.6）有
差异时可以按版本维护多份（通过 context 里的 ue_engine_version 动态选），但首版
只覆盖 5.3（对应 TestFPS 当前引擎）。

维护入口：这些常量都在一处，升级 UE 版本只动本文件。
"""
from __future__ import annotations

from typing import Dict, List, Set


# ==================== R2: 父类 OnRep_* 白名单 ====================
#
# 子类如果 override 了这些父类的 OnRep_*，**不能再加 UFUNCTION() 宏**——
# UHT 会报 "Override of UFUNCTION 'OnRep_XXX' cannot have UFUNCTION() declaration above it"。
#
# 规则：正确声明是 `virtual void OnRep_XXX() override;`

UE_PARENT_ONREP_METHODS: Dict[str, List[str]] = {
    "APlayerState": [
        "OnRep_Score",
        "OnRep_PlayerName",
        "OnRep_PlayerId",
        "OnRep_UniqueId",
        "OnRep_bIsInactive",
        "OnRep_PingReplicationTimestamp",
    ],
    "AActor": [
        "OnRep_Owner",
        "OnRep_Instigator",
        "OnRep_ReplicatedMovement",
        "OnRep_AttachmentReplication",
        "OnRep_ReplicateMovement",
    ],
    "ACharacter": [
        "OnRep_IsCrouched",
        "OnRep_ReplicatedBasedMovement",
        "OnRep_ReplicatedMovementMode",
    ],
    "APawn": [
        "OnRep_PlayerState",
        "OnRep_Controller",
    ],
    "AController": [
        "OnRep_Pawn",
        "OnRep_PlayerState",
    ],
    "UActorComponent": [
        "OnRep_IsActive",
    ],
}


# ==================== R4: Builtin Modules 白名单（UE 5.3）====================
#
# Build.cs 里的 PublicDependencyModuleNames / PrivateDependencyModuleNames 里的
# 模块名必须在此白名单里，否则 UBT 会报 "Couldn't find module X"。
# 不全没关系（真项目用到的少于 50 个）——白名单外的只给 warning 不给 blocking。

UE_BUILTIN_MODULES_5_3: Set[str] = {
    # Core
    "Core", "CoreUObject", "CoreOnline", "Engine", "EngineSettings",
    "ApplicationCore", "Projects", "Json", "JsonUtilities",
    # Input
    "InputCore", "EnhancedInput", "InputDevice", "ApplicationCore",
    # Rendering
    "RenderCore", "RHI", "RHICore", "Renderer", "ShaderCore",
    # UI
    "Slate", "SlateCore", "UMG", "UMGEditor",
    # Gameplay
    "GameplayTasks", "GameplayTags", "GameplayAbilities", "NetworkReplayStreaming",
    "AIModule", "NavigationSystem", "PhysicsCore", "Chaos", "ChaosSolverEngine",
    # Media / Animation / Audio
    "MediaAssets", "MovieScene", "MovieSceneTracks", "LevelSequence",
    "AnimationCore", "AnimGraphRuntime", "AudioMixer", "AudioExtensions",
    # Networking / Online
    "Networking", "Sockets", "OnlineSubsystem", "OnlineSubsystemUtils",
    "HTTP", "HTTPServer", "WebSockets",
    # Editor（仅 Editor target 可用）
    "UnrealEd", "EditorStyle", "EditorWidgets", "ToolMenus", "ToolWidgets",
    "PropertyEditor", "WorkspaceMenuStructure", "ContentBrowser", "ContentBrowserData",
    "AssetTools", "AssetRegistry", "KismetCompiler", "BlueprintGraph",
    "Kismet", "EditorFramework", "GraphEditor", "DetailCustomizations",
    # Async / Threading
    "Tasks", "Concurrency", "TraceLog",
    # Util
    "DeveloperSettings", "CinematicCamera", "Cinematics", "Foliage",
    "Landscape", "ProceduralMeshComponent", "MeshDescription",
    "StaticMeshDescription", "SkeletalMeshUtilitiesCommon",
    # Components 常出现但其实是 Engine 子模块的也列进来（Build.cs 允许用）
    # 注：像 Components/CapsuleComponent 不是独立 module，是 Engine 模块的一部分
    # 这里不列 Components，因为它不是合法模块名
}


# ==================== R6: Target.cs IncludeOrderVersion 兼容矩阵 ====================
#
# 某 UE 版本下 IncludeOrderVersion 可用值。传入 engine_version="5.3.2" 时只看
# Major.Minor（"5.3"）。列表外的值 = blocking；deprecated 标记的 = warning。

# value: set of valid order names; value2: set of deprecated (still works but warns)
UE_INCLUDE_ORDER_VALID: Dict[str, Set[str]] = {
    "5.0": {"Unreal5_0"},
    "5.1": {"Unreal5_0", "Unreal5_1"},
    "5.2": {"Unreal5_0", "Unreal5_1", "Unreal5_2"},
    "5.3": {"Unreal5_1", "Unreal5_2", "Unreal5_3"},    # 5.0 在 5.3 被移除
    "5.4": {"Unreal5_2", "Unreal5_3", "Unreal5_4"},    # 5.1 在 5.4 被移除
    "5.5": {"Unreal5_3", "Unreal5_4", "Unreal5_5"},
    "5.6": {"Unreal5_4", "Unreal5_5", "Unreal5_6"},
    "5.7": {"Unreal5_5", "Unreal5_6", "Unreal5_7"},
}

UE_INCLUDE_ORDER_DEPRECATED: Dict[str, Set[str]] = {
    "5.3": {"Unreal5_1"},       # 5.3 里还能用但会 deprecate warning
    "5.4": {"Unreal5_2"},
    "5.5": {"Unreal5_3"},
}


# ==================== R7: 常用类型 → 必需 header 映射 ====================
#
# C++ 里用到某 UE 类型（NewObject<X> / Cast<X> / X* var->Method()）时必需的
# include。.cpp 缺则 blocking（C2027/C2664 级错误）。

UE_TYPE_REQUIRED_HEADERS: Dict[str, str] = {
    # Components（最坑）
    "UCapsuleComponent": "Components/CapsuleComponent.h",
    "USphereComponent": "Components/SphereComponent.h",
    "UBoxComponent": "Components/BoxComponent.h",
    "UStaticMeshComponent": "Components/StaticMeshComponent.h",
    "USkeletalMeshComponent": "Components/SkeletalMeshComponent.h",
    "USceneComponent": "Components/SceneComponent.h",
    "UPrimitiveComponent": "Components/PrimitiveComponent.h",
    "UChildActorComponent": "Components/ChildActorComponent.h",
    "UArrowComponent": "Components/ArrowComponent.h",
    "UAudioComponent": "Components/AudioComponent.h",
    "UDecalComponent": "Components/DecalComponent.h",
    "UParticleSystemComponent": "Particles/ParticleSystemComponent.h",
    "UNiagaraComponent": "NiagaraComponent.h",
    "UWidgetComponent": "Components/WidgetComponent.h",
    "USplineComponent": "Components/SplineComponent.h",
    "USplineMeshComponent": "Components/SplineMeshComponent.h",
    "UInstancedStaticMeshComponent": "Components/InstancedStaticMeshComponent.h",
    "UHierarchicalInstancedStaticMeshComponent": "Components/HierarchicalInstancedStaticMeshComponent.h",
    # GameFramework
    "UCharacterMovementComponent": "GameFramework/CharacterMovementComponent.h",
    "UFloatingPawnMovement": "GameFramework/FloatingPawnMovement.h",
    "UProjectileMovementComponent": "GameFramework/ProjectileMovementComponent.h",
    "UPawnMovementComponent": "GameFramework/PawnMovementComponent.h",
    "UNavMovementComponent": "GameFramework/NavMovementComponent.h",
    "ACharacter": "GameFramework/Character.h",
    "APawn": "GameFramework/Pawn.h",
    "APlayerController": "GameFramework/PlayerController.h",
    "APlayerStart": "GameFramework/PlayerStart.h",
    "AGameMode": "GameFramework/GameMode.h",
    "AGameModeBase": "GameFramework/GameModeBase.h",
    "AGameState": "GameFramework/GameState.h",
    "AGameStateBase": "GameFramework/GameStateBase.h",
    "APlayerState": "GameFramework/PlayerState.h",
    "AHUD": "GameFramework/HUD.h",
    "AController": "GameFramework/Controller.h",
    "USpringArmComponent": "GameFramework/SpringArmComponent.h",
    # Camera
    "UCameraComponent": "Camera/CameraComponent.h",
    # Input
    "UInputComponent": "Components/InputComponent.h",
    "UEnhancedInputComponent": "EnhancedInputComponent.h",
    "UInputAction": "InputAction.h",
    "UInputMappingContext": "InputMappingContext.h",
    "UEnhancedInputLocalPlayerSubsystem": "EnhancedInputSubsystems.h",
    "FInputActionValue": "InputActionValue.h",
    # Engine
    "UWorld": "Engine/World.h",
    "ULevel": "Engine/Level.h",
    "UGameInstance": "Engine/GameInstance.h",
    "ULocalPlayer": "Engine/LocalPlayer.h",
    "UEngine": "Engine/Engine.h",
    # Kismet Helpers
    "UGameplayStatics": "Kismet/GameplayStatics.h",
    "UKismetMathLibrary": "Kismet/KismetMathLibrary.h",
    "UKismetSystemLibrary": "Kismet/KismetSystemLibrary.h",
    "UKismetStringLibrary": "Kismet/KismetStringLibrary.h",
    # AI
    "AAIController": "AIController.h",
    "UBlackboardComponent": "BehaviorTree/BlackboardComponent.h",
    "UBehaviorTreeComponent": "BehaviorTree/BehaviorTreeComponent.h",
    # Physics
    "UPhysicalMaterial": "PhysicalMaterials/PhysicalMaterial.h",
    # Timer
    "FTimerHandle": "Engine/EngineBaseTypes.h",       # 其实 CoreMinimal 里也有 forward decl
    "FTimerManager": "TimerManager.h",
    # Net
    "FLifetimeProperty": "Net/UnrealNetwork.h",
    # UI
    "UUserWidget": "Blueprint/UserWidget.h",
}


# ==================== R4 扩展：已知插件模块（启用插件后可用）====================
#
# 这些模块来自 Engine/Plugins/ 下，用户如果在 .uproject 启用了对应插件，
# Build.cs 就可以依赖。我们不强制校验插件是否启用（太复杂），只把它们列进白名单
# 避免误报。

UE_PLUGIN_MODULES_5_3: Set[str] = {
    "EnhancedInput",
    "ModelingToolsEditorMode",
    "CommonUI", "CommonInput",
    "GameplayAbilities", "GameplayTags", "GameplayTasks",
    "OnlineSubsystemSteam", "OnlineSubsystemEOS",
    "Niagara", "NiagaraCore", "NiagaraAnimNotifies",
    "ChaosVehicles", "ChaosVehiclesEngine",
    "MetaHuman",
    "DataValidation",
    "ProceduralContentGeneration",
    "LiveLink", "LiveLinkAnimationCore",
    "DataRegistry",
    "ModelingComponents",
    "GeometryFramework",
    "GameplayStateTree", "StateTreeModule",
}


def all_known_modules_5_3() -> Set[str]:
    """Builtin + 常见插件的合集"""
    return UE_BUILTIN_MODULES_5_3 | UE_PLUGIN_MODULES_5_3
