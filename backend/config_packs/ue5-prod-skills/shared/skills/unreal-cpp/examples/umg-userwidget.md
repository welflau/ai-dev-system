# Example: UI — C++ UUserWidget with BindWidget

## Use when

- A UMG widget Blueprint needs a C++ base class.
- UI should update from gameplay events instead of ticking or property bindings.
- You need safe `BindWidget` patterns for health/ammo/status widgets.

## Agent prompt template

```text
Create or update a C++ UUserWidget base.
Inspect existing widget naming and module dependencies.
Use BindWidget only for widgets that must exist; use BindWidgetOptional for optional designer widgets.
Avoid Tick and expensive Blueprint property bindings; prefer explicit update functions/events.
Run the Editor target build through the repository launcher and report any UMG/Slate module changes.
```

## Header skeleton

```cpp
#pragma once

#include "CoreMinimal.h"
#include "Blueprint/UserWidget.h"
#include "PlayerStatusWidget.generated.h"

class UProgressBar;
class UTextBlock;

UCLASS(Abstract, BlueprintType)
class YOURPROJECT_API UPlayerStatusWidget : public UUserWidget
{
    GENERATED_BODY()

public:
    UFUNCTION(BlueprintCallable, Category="Status")
    void SetHealthPercent(float Percent);

    UFUNCTION(BlueprintCallable, Category="Status")
    void SetAmmo(int32 CurrentAmmo, int32 MaxAmmo);

protected:
    virtual void NativeOnInitialized() override;

    UPROPERTY(meta=(BindWidget))
    TObjectPtr<UProgressBar> HealthBar;

    UPROPERTY(meta=(BindWidgetOptional))
    TObjectPtr<UTextBlock> AmmoText;
};
```

## CPP skeleton

```cpp
#include "PlayerStatusWidget.h"
#include "Components/ProgressBar.h"
#include "Components/TextBlock.h"

void UPlayerStatusWidget::NativeOnInitialized()
{
    Super::NativeOnInitialized();
    SetHealthPercent(1.0f);
}

void UPlayerStatusWidget::SetHealthPercent(float Percent)
{
    if (HealthBar)
    {
        HealthBar->SetPercent(FMath::Clamp(Percent, 0.0f, 1.0f));
    }
}

void UPlayerStatusWidget::SetAmmo(int32 CurrentAmmo, int32 MaxAmmo)
{
    if (AmmoText)
    {
        AmmoText->SetText(FText::Format(
            NSLOCTEXT("PlayerStatus", "AmmoFmt", "{0}/{1}"),
            FText::AsNumber(CurrentAmmo),
            FText::AsNumber(MaxAmmo)));
    }
}
```

## Build.cs notes

```csharp
PrivateDependencyModuleNames.AddRange(new[] {
    "UMG", "Slate", "SlateCore"
});
```

## Review checklist

- Widget class is `Abstract` if it is intended only as a Blueprint base.
- `BindWidget` names exactly match widget Blueprint variable names.
- `BindWidgetOptional` is used for optional widgets.
- UI updates are event-driven, not per-frame.
- Text uses `FText`, not `FString`, for user-facing display.
- Do not access gameplay actors during construction; bind after player/controller is valid.
