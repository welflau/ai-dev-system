# Example: Enhanced Input — C++ Character Binding

## Use when

- Migrating from legacy input to Enhanced Input.
- Adding input actions to a pawn/character.
- Binding movement/look/jump/fire to `UInputAction` assets.

## Agent prompt template

```text
Add Enhanced Input bindings for a character.
Inspect existing input mapping contexts and project settings first.
Only add mapping context for local players.
Do not hard-code asset paths unless existing project convention uses ConstructorHelpers.
Run the Editor target build through the repository launcher and confirm the EnhancedInput dependency.
```

## Header skeleton

```cpp
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "InputActionValue.h"
#include "PlayerCharacter.generated.h"

class UInputMappingContext;
class UInputAction;

UCLASS()
class YOURPROJECT_API APlayerCharacter : public ACharacter
{
    GENERATED_BODY()

protected:
    virtual void BeginPlay() override;
    virtual void SetupPlayerInputComponent(UInputComponent* PlayerInputComponent) override;

    UPROPERTY(EditDefaultsOnly, Category="Input")
    TObjectPtr<UInputMappingContext> DefaultMappingContext;

    UPROPERTY(EditDefaultsOnly, Category="Input")
    TObjectPtr<UInputAction> MoveAction;

    UPROPERTY(EditDefaultsOnly, Category="Input")
    TObjectPtr<UInputAction> LookAction;

    void HandleMove(const FInputActionValue& Value);
    void HandleLook(const FInputActionValue& Value);
};
```

## CPP skeleton

```cpp
#include "PlayerCharacter.h"
#include "EnhancedInputComponent.h"
#include "EnhancedInputSubsystems.h"
#include "GameFramework/PlayerController.h"

void APlayerCharacter::BeginPlay()
{
    Super::BeginPlay();

    if (const APlayerController* PC = Cast<APlayerController>(GetController()))
    {
        if (ULocalPlayer* LocalPlayer = PC->GetLocalPlayer())
        {
            if (UEnhancedInputLocalPlayerSubsystem* Subsystem =
                LocalPlayer->GetSubsystem<UEnhancedInputLocalPlayerSubsystem>())
            {
                if (DefaultMappingContext)
                {
                    Subsystem->AddMappingContext(DefaultMappingContext, 0);
                }
            }
        }
    }
}

void APlayerCharacter::SetupPlayerInputComponent(UInputComponent* PlayerInputComponent)
{
    Super::SetupPlayerInputComponent(PlayerInputComponent);

    UEnhancedInputComponent* EnhancedInput = CastChecked<UEnhancedInputComponent>(PlayerInputComponent);
    if (MoveAction)
    {
        EnhancedInput->BindAction(MoveAction, ETriggerEvent::Triggered, this, &APlayerCharacter::HandleMove);
    }
    if (LookAction)
    {
        EnhancedInput->BindAction(LookAction, ETriggerEvent::Triggered, this, &APlayerCharacter::HandleLook);
    }
}

void APlayerCharacter::HandleMove(const FInputActionValue& Value)
{
    const FVector2D Axis = Value.Get<FVector2D>();
    AddMovementInput(GetActorForwardVector(), Axis.Y);
    AddMovementInput(GetActorRightVector(), Axis.X);
}

void APlayerCharacter::HandleLook(const FInputActionValue& Value)
{
    const FVector2D Axis = Value.Get<FVector2D>();
    AddControllerYawInput(Axis.X);
    AddControllerPitchInput(Axis.Y);
}
```

## Build.cs

```csharp
PrivateDependencyModuleNames.AddRange(new[] { "EnhancedInput" });
```

## Review checklist

- Mapping context is added only for local players.
- Input assets are `EditDefaultsOnly` so designers can assign them.
- No input binding on dedicated server assumptions.
- Uses `CastChecked` only where project guarantees Enhanced Input component.
- For multiplayer, input initiates local intent, but authority validates gameplay state.
