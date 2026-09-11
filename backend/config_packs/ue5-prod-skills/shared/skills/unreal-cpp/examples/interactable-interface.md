# Example: Gameplay Interaction — UINTERFACE + Interaction Component

## Use when

- The player can look at or overlap interactable actors.
- C++ should define a stable interaction contract while Blueprints can implement specific behavior.
- You need a clean boundary between “detect interaction target” and “execute interaction.”

## Agent prompt template

```text
Add a C++ interaction interface and a reusable interaction component.
Inspect existing trace channels and input conventions first.
Keep the interface minimal and Blueprint-friendly.
Do not add Tick unless the project already uses continuous targeting.
Run the Editor target build through the repository launcher and report any collision/input assumptions.
```

## Files

```text
Source/<Project>/Interaction/Interactable.h
Source/<Project>/Interaction/InteractionComponent.h
Source/<Project>/Interaction/InteractionComponent.cpp
```

## Interface skeleton

```cpp
#pragma once

#include "CoreMinimal.h"
#include "UObject/Interface.h"
#include "Interactable.generated.h"

UINTERFACE(BlueprintType)
class YOURPROJECT_API UInteractable : public UInterface
{
    GENERATED_BODY()
};

class YOURPROJECT_API IInteractable
{
    GENERATED_BODY()

public:
    UFUNCTION(BlueprintNativeEvent, BlueprintCallable, Category="Interaction")
    bool CanInteract(APawn* InstigatorPawn) const;

    UFUNCTION(BlueprintNativeEvent, BlueprintCallable, Category="Interaction")
    void Interact(APawn* InstigatorPawn);
};
```

## Component header skeleton

```cpp
#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "InteractionComponent.generated.h"

UCLASS(ClassGroup=(Gameplay), meta=(BlueprintSpawnableComponent))
class YOURPROJECT_API UInteractionComponent : public UActorComponent
{
    GENERATED_BODY()

public:
    UInteractionComponent();

    UFUNCTION(BlueprintCallable, Category="Interaction")
    bool TryInteract();

protected:
    UPROPERTY(EditDefaultsOnly, Category="Interaction", meta=(ClampMin="10.0"))
    float TraceDistance = 300.0f;

    UPROPERTY(EditDefaultsOnly, Category="Interaction")
    TEnumAsByte<ECollisionChannel> TraceChannel = ECC_Visibility;

private:
    bool FindInteractable(FHitResult& OutHit) const;
};
```

## Component CPP skeleton

```cpp
#include "InteractionComponent.h"
#include "Interactable.h"
#include "Camera/CameraComponent.h"
#include "GameFramework/Pawn.h"

UInteractionComponent::UInteractionComponent()
{
    PrimaryComponentTick.bCanEverTick = false;
}

bool UInteractionComponent::TryInteract()
{
    FHitResult Hit;
    if (!FindInteractable(Hit))
    {
        return false;
    }

    AActor* Target = Hit.GetActor();
    APawn* PawnOwner = Cast<APawn>(GetOwner());
    if (!Target || !Target->GetClass()->ImplementsInterface(UInteractable::StaticClass()))
    {
        return false;
    }

    if (!IInteractable::Execute_CanInteract(Target, PawnOwner))
    {
        return false;
    }

    IInteractable::Execute_Interact(Target, PawnOwner);
    return true;
}

bool UInteractionComponent::FindInteractable(FHitResult& OutHit) const
{
    const APawn* PawnOwner = Cast<APawn>(GetOwner());
    if (!PawnOwner)
    {
        return false;
    }

    const UWorld* World = GetWorld();
    if (!World)
    {
        return false;
    }

    FVector ViewLocation;
    FRotator ViewRotation;
    PawnOwner->GetActorEyesViewPoint(ViewLocation, ViewRotation);

    const FVector End = ViewLocation + ViewRotation.Vector() * TraceDistance;

    FCollisionQueryParams Params(SCENE_QUERY_STAT(InteractionTrace), false, PawnOwner);
    return World->LineTraceSingleByChannel(OutHit, ViewLocation, End, TraceChannel, Params)
        && OutHit.GetActor()
        && OutHit.GetActor()->GetClass()->ImplementsInterface(UInteractable::StaticClass());
}
```

## Review checklist

- Interface functions are `BlueprintNativeEvent` if Blueprint actors need custom behavior.
- Uses `Execute_` calls for interface dispatch.
- No raw interface cast assumption on Blueprint-only implementers.
- Trace channel is project-approved.
- In multiplayer, interaction execution should route to server authority before changing game state.
