# Example: UI — PlayerController-Owned HUD Bridge

## Use when

- A PlayerController should create and own a HUD widget.
- Gameplay code needs to push updates to UI without hard-coding widget Blueprints in actors.
- You need a clean boundary between replicated gameplay state and local UI presentation.

## Agent prompt template

```text
Implement a PlayerController HUD bridge.
Inspect existing HUD/UI creation patterns first.
Create the widget only for the local owning player.
Bind to gameplay delegates when possible.
Do not create UI on dedicated server.
Run the Editor target build through the repository launcher and check UMG module dependencies.
```

## PlayerController header skeleton

```cpp
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/PlayerController.h"
#include "GamePlayerController.generated.h"

class UPlayerStatusWidget;

UCLASS()
class YOURPROJECT_API AGamePlayerController : public APlayerController
{
    GENERATED_BODY()

public:
    UFUNCTION(BlueprintCallable, Category="UI")
    void RefreshStatusUI(float HealthPercent, int32 Ammo, int32 MaxAmmo);

protected:
    virtual void BeginPlay() override;

    UPROPERTY(EditDefaultsOnly, Category="UI")
    TSubclassOf<UPlayerStatusWidget> StatusWidgetClass;

    UPROPERTY(Transient)
    TObjectPtr<UPlayerStatusWidget> StatusWidget;
};
```

## CPP skeleton

```cpp
#include "GamePlayerController.h"
#include "PlayerStatusWidget.h"
#include "Blueprint/UserWidget.h"

void AGamePlayerController::BeginPlay()
{
    Super::BeginPlay();

    if (!IsLocalController() || IsRunningDedicatedServer())
    {
        return;
    }

    if (StatusWidgetClass)
    {
        StatusWidget = CreateWidget<UPlayerStatusWidget>(this, StatusWidgetClass);
        if (StatusWidget)
        {
            StatusWidget->AddToViewport();
        }
    }
}

void AGamePlayerController::RefreshStatusUI(float HealthPercent, int32 Ammo, int32 MaxAmmo)
{
    if (!StatusWidget)
    {
        return;
    }

    StatusWidget->SetHealthPercent(HealthPercent);
    StatusWidget->SetAmmo(Ammo, MaxAmmo);
}
```

## Review checklist

- UI is created only on the owning local client.
- Widget reference is `UPROPERTY(Transient)` to prevent GC.
- Game state changes do not depend on UI existence.
- UI class path is configured in Blueprint/defaults, not hard-coded with `ConstructorHelpers` unless project convention requires it.
- If updates come from replicated variables, bind through `OnRep` or component delegates on the owning client.
