# Example: Delegates (Event System)

Delegates are UE's type-safe callback mechanism for event-driven programming.

## Delegate Types Overview

| Type | Binding | Use Case |
|------|---------|----------|
| `DECLARE_DELEGATE` | Single | One listener, C++ only |
| `DECLARE_MULTICAST_DELEGATE` | Multiple | Many listeners, C++ only |
| `DECLARE_DYNAMIC_DELEGATE` | Single | One listener, Blueprint compatible |
| `DECLARE_DYNAMIC_MULTICAST_DELEGATE` | Multiple | Many listeners, Blueprint compatible |

## Single-cast Delegate (C++ Only)

```cpp
// In header file
#pragma once

#include "CoreMinimal.h"

// Declare delegate types (outside class)
DECLARE_DELEGATE(FSimpleCallback);                           // No params
DECLARE_DELEGATE_OneParam(FOnValueChanged, int32);           // One param
DECLARE_DELEGATE_TwoParams(FOnItemPickup, FName, int32);     // Two params
DECLARE_DELEGATE_RetVal(bool, FCanPerformAction);            // Return value
DECLARE_DELEGATE_RetVal_OneParam(bool, FValidateInput, const FString&);

class FInventoryManager
{
public:
    /** Bind a callback for when gold changes */
    void SetOnGoldChanged(FOnValueChanged InDelegate)
    {
        OnGoldChanged = InDelegate;
    }

    void AddGold(int32 Amount)
    {
        Gold += Amount;
        // Execute if bound
        OnGoldChanged.ExecuteIfBound(Gold);
    }

private:
    FOnValueChanged OnGoldChanged;
    int32 Gold = 0;
};

// Usage:
// Manager.SetOnGoldChanged(FOnValueChanged::CreateLambda([](int32 NewGold) {
//     UE_LOG(LogTemp, Log, TEXT("Gold: %d"), NewGold);
// }));
```

## Multicast Delegate (C++ Only)

```cpp
// Declaration
DECLARE_MULTICAST_DELEGATE_OneParam(FOnHealthChanged, float);
DECLARE_MULTICAST_DELEGATE_TwoParams(FOnDamageReceived, float, AActor*);

class UHealthComponent : public UActorComponent
{
public:
    /** Event broadcast when health changes */
    FOnHealthChanged OnHealthChanged;

    void SetHealth(float NewHealth)
    {
        Health = FMath::Clamp(NewHealth, 0.0f, MaxHealth);
        // Broadcast to all listeners
        OnHealthChanged.Broadcast(Health);
    }

private:
    float Health = 100.0f;
    float MaxHealth = 100.0f;
};

// Binding in another class:
// FDelegateHandle Handle = HealthComp->OnHealthChanged.AddUObject(
//     this, &AMyCharacter::HandleHealthChanged);
// 
// // Later, to unbind:
// HealthComp->OnHealthChanged.Remove(Handle);
// 
// // Or unbind all from an object:
// HealthComp->OnHealthChanged.RemoveAll(this);
```

## Dynamic Delegate (Blueprint Compatible)

```cpp
// In header file
#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "InteractionComponent.generated.h"

// Dynamic delegates must be declared with these macros
DECLARE_DYNAMIC_DELEGATE(FOnInteractSimple);
DECLARE_DYNAMIC_DELEGATE_OneParam(FOnInteractWithActor, AActor*, InteractedActor);
DECLARE_DYNAMIC_DELEGATE_RetVal(bool, FCanInteract);

UCLASS(ClassGroup=(Custom), meta=(BlueprintSpawnableComponent))
class MYGAME_API UInteractionComponent : public UActorComponent
{
    GENERATED_BODY()

public:
    /** Single callback when interaction occurs */
    UPROPERTY(BlueprintReadWrite, Category = "Interaction")
    FOnInteractWithActor OnInteract;

    UFUNCTION(BlueprintCallable, Category = "Interaction")
    void Interact(AActor* Target)
    {
        if (OnInteract.IsBound())
        {
            OnInteract.Execute(Target);
        }
    }
};
```

## Dynamic Multicast Delegate (Blueprint Events)

```cpp
// Header
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "Chest.generated.h"

// Must match param types exactly
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FOnChestOpened, AChest*, Chest);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FOnItemLooted, FName, ItemId, int32, Quantity);

UCLASS()
class MYGAME_API AChest : public AActor
{
    GENERATED_BODY()

public:
    /** Broadcast when chest is opened - bind in Blueprint Event Graph */
    UPROPERTY(BlueprintAssignable, Category = "Events")
    FOnChestOpened OnChestOpened;

    /** Broadcast for each item looted */
    UPROPERTY(BlueprintAssignable, Category = "Events")
    FOnItemLooted OnItemLooted;

    /** Call to open the chest */
    UFUNCTION(BlueprintCallable, Category = "Chest")
    void Open()
    {
        if (bIsOpen)
        {
            return;
        }

        bIsOpen = true;
        
        // Broadcast to all listeners (Blueprint and C++)
        OnChestOpened.Broadcast(this);

        // Spawn loot and broadcast each item
        for (const auto& Item : LootTable)
        {
            OnItemLooted.Broadcast(Item.Key, Item.Value);
        }
    }

private:
    bool bIsOpen = false;

    UPROPERTY(EditAnywhere, Category = "Loot")
    TMap<FName, int32> LootTable;
};
```

## Binding Methods Reference

### For Multicast Delegates (C++)

```cpp
// Method 1: Bind to UObject member function (prevents dangling)
FDelegateHandle Handle = Delegate.AddUObject(this, &UMyClass::HandleEvent);

// Method 2: Bind to raw C++ object (be careful with lifetimes!)
Delegate.AddRaw(RawPointer, &FMyClass::HandleEvent);

// Method 3: Bind to shared pointer member
Delegate.AddSP(SharedPtr, &FMyClass::HandleEvent);

// Method 4: Bind lambda
Delegate.AddLambda([this](int32 Value) {
    // Handle event
});

// Method 5: Bind weak lambda (safe if UObject is destroyed)
Delegate.AddWeakLambda(this, [this](int32 Value) {
    // Handle event - won't crash if 'this' is destroyed
});

// Unbind
Delegate.Remove(Handle);
Delegate.RemoveAll(this);
```

### For Dynamic Multicast Delegates (Blueprint Compatible)

```cpp
// Bind to UFUNCTION
Delegate.AddDynamic(this, &UMyClass::HandleEvent);

// Unbind
Delegate.RemoveDynamic(this, &UMyClass::HandleEvent);

// Check if bound
Delegate.IsBound();

// Clear all
Delegate.Clear();
```

## UPROPERTY Specifiers for Delegates

| Specifier | Purpose |
|-----------|---------|
| `BlueprintAssignable` | Can bind in Blueprint Event Graph |
| `BlueprintCallable` | Can execute from Blueprint |
| `BlueprintAuthorityOnly` | Server-only in multiplayer |

## Best Practices

1. **Use `AddUObject`** for UObject member functions - automatically unbinds if object is destroyed
2. **Store `FDelegateHandle`** if you need to unbind later
3. **Use `ExecuteIfBound`** for single-cast delegates to avoid crashes
4. **Use Dynamic delegates** only when Blueprint binding is required (slower)
5. **Clear delegates** in `BeginDestroy()` or destructor if broadcasting from other threads
6. **Prefer multicast** for events that multiple systems might care about
7. **Name convention**: `OnEventName` for the delegate instance, `FOnEventName` for the type
