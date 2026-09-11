# Example: Gameplay Actor Component — Health/Damage State

## Use when

- Adding local health, stamina, shield, durability, or resource logic.
- Moving gameplay state out of an `AActor` into a reusable `UActorComponent`.
- Creating a foundation that may later become replicated, but is not replicated yet.

For multiplayer, combine this local state pattern with [network-replication.md](./network-replication.md) and define server authority explicitly.

## Agent prompt template

```text
Add a reusable Unreal C++ health component.
First inspect existing component patterns and naming conventions.
Implement the smallest change under Source/**.
Expose safe Blueprint read functions and event delegates.
Do not add replication unless the task explicitly asks for multiplayer.
After editing, run the Editor target build through the repository launcher and inspect git diff.
```

## Expected files

```text
Source/<Project>/<Feature>/HealthComponent.h
Source/<Project>/<Feature>/HealthComponent.cpp
```

## Header skeleton

```cpp
#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "HealthComponent.generated.h"

DECLARE_DYNAMIC_MULTICAST_DELEGATE_ThreeParams(
    FOnHealthChanged,
    UHealthComponent*, Component,
    float, OldHealth,
    float, NewHealth);

DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(
    FOnHealthDepleted,
    UHealthComponent*, Component);

UCLASS(ClassGroup=(Gameplay), meta=(BlueprintSpawnableComponent))
class YOURPROJECT_API UHealthComponent : public UActorComponent
{
    GENERATED_BODY()

public:
    UHealthComponent();

    UFUNCTION(BlueprintCallable, Category="Health")
    void ApplyDamage(float DamageAmount);

    UFUNCTION(BlueprintCallable, Category="Health")
    void Heal(float HealAmount);

    UFUNCTION(BlueprintPure, Category="Health")
    float GetHealth() const { return Health; }

    UFUNCTION(BlueprintPure, Category="Health")
    float GetMaxHealth() const { return MaxHealth; }

    UFUNCTION(BlueprintPure, Category="Health")
    bool IsAlive() const { return Health > 0.0f; }

    UPROPERTY(BlueprintAssignable, Category="Health")
    FOnHealthChanged OnHealthChanged;

    UPROPERTY(BlueprintAssignable, Category="Health")
    FOnHealthDepleted OnHealthDepleted;

protected:
    virtual void BeginPlay() override;

    UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category="Health", meta=(ClampMin="1.0"))
    float MaxHealth = 100.0f;

    UPROPERTY(VisibleInstanceOnly, BlueprintReadOnly, Category="Health")
    float Health = 0.0f;

private:
    void SetHealth(float NewHealth);
};
```

## CPP skeleton

```cpp
#include "HealthComponent.h"
#include "Math/UnrealMathUtility.h"

UHealthComponent::UHealthComponent()
{
    PrimaryComponentTick.bCanEverTick = false;
}

void UHealthComponent::BeginPlay()
{
    Super::BeginPlay();
    Health = MaxHealth;
}

void UHealthComponent::ApplyDamage(float DamageAmount)
{
    if (DamageAmount <= 0.0f || !IsAlive())
    {
        return;
    }

    SetHealth(Health - DamageAmount);
}

void UHealthComponent::Heal(float HealAmount)
{
    if (HealAmount <= 0.0f || !IsAlive())
    {
        return;
    }

    SetHealth(Health + HealAmount);
}

void UHealthComponent::SetHealth(float NewHealth)
{
    const float OldHealth = Health;
    Health = FMath::Clamp(NewHealth, 0.0f, MaxHealth);

    if (!FMath::IsNearlyEqual(OldHealth, Health))
    {
        OnHealthChanged.Broadcast(this, OldHealth, Health);

        if (OldHealth > 0.0f && Health <= 0.0f)
        {
            OnHealthDepleted.Broadcast(this);
        }
    }
}
```

## Build/test gate

Run the discovered Editor target build through the repository launcher. Add a focused Automation test for clamp/depletion behavior when this becomes production logic.

## Review checklist

- `*.generated.h` include is last in the header.
- Delegates are `UPROPERTY(BlueprintAssignable)` so Blueprint can bind safely.
- Component does not Tick unnecessarily.
- No raw owning UObject pointers.
- No hidden multiplayer assumption; server authority is not claimed unless implemented.
- If later made replicated, convert this through the network example rather than patching ad hoc.

## Common failure fixes

- `Unrecognized type FOnHealthChanged`: delegate declaration must appear before the UCLASS that uses it.
- `generated.h must be last`: move `#include "HealthComponent.generated.h"` to the final include.
- Linker errors on module API macro: replace `YOURPROJECT_API` with the module's actual exported API macro.
