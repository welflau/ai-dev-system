# Example: Gameplay DataAsset — Data-Driven Weapon Config

## Use when

- Designers need to tune gameplay values without changing C++.
- Multiple weapons/items share runtime code but vary by data.
- Assets should be referenced softly to avoid loading everything at startup.

## Agent prompt template

```text
Create a data-driven weapon config and component.
Use UPrimaryDataAsset or UDataAsset according to existing project conventions.
Prefer TSoftObjectPtr/TSoftClassPtr for large assets.
Do not load assets synchronously in hot gameplay code unless existing project policy allows it.
Run the Editor target build through the repository launcher and list required module dependencies.
```

## Data asset skeleton

```cpp
#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "GameplayTagContainer.h"
#include "WeaponConfig.generated.h"

class UAnimMontage;
class USoundBase;
class UParticleSystem;

UCLASS(BlueprintType)
class YOURPROJECT_API UWeaponConfig : public UPrimaryDataAsset
{
    GENERATED_BODY()

public:
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category="Weapon", meta=(ClampMin="0.0"))
    float Damage = 25.0f;

    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category="Weapon", meta=(ClampMin="0.01"))
    float FireInterval = 0.2f;

    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category="Weapon")
    FGameplayTag WeaponTag;

    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category="Weapon|Assets")
    TSoftObjectPtr<UAnimMontage> FireMontage;

    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category="Weapon|Assets")
    TSoftObjectPtr<USoundBase> FireSound;

    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category="Weapon|Assets")
    TSoftObjectPtr<UParticleSystem> MuzzleFX;
};
```

## Component skeleton

```cpp
#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "WeaponComponent.generated.h"

class UWeaponConfig;

UCLASS(ClassGroup=(Gameplay), meta=(BlueprintSpawnableComponent))
class YOURPROJECT_API UWeaponComponent : public UActorComponent
{
    GENERATED_BODY()

public:
    UWeaponComponent();

    UFUNCTION(BlueprintCallable, Category="Weapon")
    void SetWeaponConfig(UWeaponConfig* NewConfig);

    UFUNCTION(BlueprintCallable, Category="Weapon")
    bool TryFire();

protected:
    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category="Weapon")
    TObjectPtr<UWeaponConfig> DefaultConfig;

    UPROPERTY(Transient, BlueprintReadOnly, Category="Weapon")
    TObjectPtr<UWeaponConfig> ActiveConfig;

private:
    double LastFireTimeSeconds = -DBL_MAX;
};
```

```cpp
#include "WeaponComponent.h"
#include "WeaponConfig.h"
#include "Engine/World.h"

UWeaponComponent::UWeaponComponent()
{
    PrimaryComponentTick.bCanEverTick = false;
}

void UWeaponComponent::SetWeaponConfig(UWeaponConfig* NewConfig)
{
    ActiveConfig = NewConfig ? NewConfig : DefaultConfig;
}

bool UWeaponComponent::TryFire()
{
    const UWorld* World = GetWorld();
    const UWeaponConfig* Config = ActiveConfig ? ActiveConfig.Get() : DefaultConfig.Get();
    if (!World || !Config)
    {
        return false;
    }

    const double Now = World->GetTimeSeconds();
    if (Now - LastFireTimeSeconds < Config->FireInterval)
    {
        return false;
    }

    LastFireTimeSeconds = Now;

    // Apply trace/projectile/spawn logic here. Keep asset loading outside hot path.
    return true;
}
```

## Build.cs notes

```csharp
PublicDependencyModuleNames.AddRange(new[] {
    "Core", "CoreUObject", "Engine", "GameplayTags"
});
```

## Review checklist

- Large assets use soft references unless project convention differs.
- Runtime component does not synchronously load assets in a firing loop.
- Data asset is designer-editable but not responsible for runtime state.
- GameplayTags dependency is added if `FGameplayTag` is used.
- Networked weapons require separate server-authoritative fire validation.
