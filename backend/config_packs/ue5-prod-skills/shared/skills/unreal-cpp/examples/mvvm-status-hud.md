# MVVM Status HUD (UMG Viewmodel)

This example shows a minimal MVVM status HUD:
- C++ owns authoritative state and mutation entry points.
- Blueprints own data-driven tuning, presentation, and UI layout/animation.

## Dependencies and setup

- Enable the plugin: ModelViewViewModel (UMG Viewmodel).
- Build.cs:

```csharp
PrivateDependencyModuleNames.AddRange(new string[] { "UMG", "ModelViewViewModel" });
```

## C++: Authoritative status component

`UStatusComponent` owns Health/Energy/Score and mutation entry points only. Keep UI logic out.

```cpp
// StatusComponent.h
#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "StatusComponent.generated.h"

DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FOnStatusFloatChanged, float, NewValue, float, NewMaxValue);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FOnStatusIntChanged, int32, NewValue);

UCLASS(ClassGroup=(Custom), meta=(BlueprintSpawnableComponent))
class UStatusComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UFUNCTION(BlueprintCallable, Category="Status")
	void ApplyDamage(float Amount);

	UFUNCTION(BlueprintCallable, Category="Status")
	void ConsumeEnergy(float Amount);

	UFUNCTION(BlueprintCallable, Category="Status")
	void AddScore(int32 Amount);

	UPROPERTY(BlueprintAssignable, Category="Status")
	FOnStatusFloatChanged OnHealthChanged;

	UPROPERTY(BlueprintAssignable, Category="Status")
	FOnStatusFloatChanged OnEnergyChanged;

	UPROPERTY(BlueprintAssignable, Category="Status")
	FOnStatusIntChanged OnScoreChanged;

protected:
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Status", meta=(ClampMin="0"))
	float Health = 100.0f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Status", meta=(ClampMin="1"))
	float MaxHealth = 100.0f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Status", meta=(ClampMin="0"))
	float Energy = 100.0f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Status", meta=(ClampMin="1"))
	float MaxEnergy = 100.0f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Status", meta=(ClampMin="0"))
	int32 Score = 0;

private:
	void SetHealth(float NewHealth);
	void SetEnergy(float NewEnergy);
	void SetScore(int32 NewScore);
};
```

```cpp
// StatusComponent.cpp
#include "StatusComponent.h"
#include "Math/UnrealMathUtility.h"

void UStatusComponent::ApplyDamage(float Amount)
{
	if (Amount <= 0.0f)
	{
		return;
	}

	SetHealth(Health - Amount);
}

void UStatusComponent::ConsumeEnergy(float Amount)
{
	if (Amount <= 0.0f)
	{
		return;
	}

	SetEnergy(Energy - Amount);
}

void UStatusComponent::AddScore(int32 Amount)
{
	if (Amount == 0)
	{
		return;
	}

	SetScore(Score + Amount);
}

void UStatusComponent::SetHealth(float NewHealth)
{
	const float Clamped = FMath::Clamp(NewHealth, 0.0f, MaxHealth);
	if (Clamped == Health)
	{
		return;
	}

	Health = Clamped;
	OnHealthChanged.Broadcast(Health, MaxHealth);
}

void UStatusComponent::SetEnergy(float NewEnergy)
{
	const float Clamped = FMath::Clamp(NewEnergy, 0.0f, MaxEnergy);
	if (Clamped == Energy)
	{
		return;
	}

	Energy = Clamped;
	OnEnergyChanged.Broadcast(Energy, MaxEnergy);
}

void UStatusComponent::SetScore(int32 NewScore)
{
	if (NewScore == Score)
	{
		return;
	}

	Score = NewScore;
	OnScoreChanged.Broadcast(Score);
}
```

## C++: Viewmodel

`UStatusViewModel` only exposes derived values needed by UI and pushes FieldNotify in delegate callbacks.

```cpp
// StatusViewModel.h
#pragma once

#include "CoreMinimal.h"
#include "MVVMViewModelBase.h"
#include "StatusViewModel.generated.h"

class UStatusComponent;

UCLASS(BlueprintType)
class UStatusViewModel : public UMVVMViewModelBase
{
	GENERATED_BODY()

public:
	void BindToStatusComponent(UStatusComponent* InStatus);
	void Unbind();

private:
	UFUNCTION()
	void HandleHealthChanged(float NewValue, float NewMaxValue);

	UFUNCTION()
	void HandleEnergyChanged(float NewValue, float NewMaxValue);

	UFUNCTION()
	void HandleScoreChanged(int32 NewValue);

	UPROPERTY(BlueprintReadOnly, FieldNotify, meta=(AllowPrivateAccess="true"))
	float HealthPercent = 1.0f;

	UPROPERTY(BlueprintReadOnly, FieldNotify, meta=(AllowPrivateAccess="true"))
	float EnergyPercent = 1.0f;

	UPROPERTY(BlueprintReadOnly, FieldNotify, meta=(AllowPrivateAccess="true"))
	FText ScoreText = FText::FromString(TEXT("0"));

	TWeakObjectPtr<UStatusComponent> StatusComponent;
};
```

```cpp
// StatusViewModel.cpp
#include "StatusViewModel.h"
#include "StatusComponent.h"

void UStatusViewModel::BindToStatusComponent(UStatusComponent* InStatus)
{
	Unbind();

	StatusComponent = InStatus;
	if (!StatusComponent.IsValid())
	{
		return;
	}

	StatusComponent->OnHealthChanged.AddDynamic(this, &UStatusViewModel::HandleHealthChanged);
	StatusComponent->OnEnergyChanged.AddDynamic(this, &UStatusViewModel::HandleEnergyChanged);
	StatusComponent->OnScoreChanged.AddDynamic(this, &UStatusViewModel::HandleScoreChanged);
}

void UStatusViewModel::Unbind()
{
	if (!StatusComponent.IsValid())
	{
		return;
	}

	StatusComponent->OnHealthChanged.RemoveAll(this);
	StatusComponent->OnEnergyChanged.RemoveAll(this);
	StatusComponent->OnScoreChanged.RemoveAll(this);
	StatusComponent.Reset();
}

void UStatusViewModel::HandleHealthChanged(float NewValue, float NewMaxValue)
{
	const float Percent = (NewMaxValue > 0.0f) ? (NewValue / NewMaxValue) : 0.0f;
	UE_MVVM_SET_PROPERTY_VALUE(HealthPercent, Percent);
}

void UStatusViewModel::HandleEnergyChanged(float NewValue, float NewMaxValue)
{
	const float Percent = (NewMaxValue > 0.0f) ? (NewValue / NewMaxValue) : 0.0f;
	UE_MVVM_SET_PROPERTY_VALUE(EnergyPercent, Percent);
}

void UStatusViewModel::HandleScoreChanged(int32 NewValue)
{
	UE_MVVM_SET_PROPERTY_VALUE(ScoreText, FText::AsNumber(NewValue));
}
```

## C++: UI creator (PlayerController / HUD / UI Manager)

Use the MVVM blueprint library to set the viewmodel at runtime and keep UI logic out of widgets.

```cpp
#include "MVVMBlueprintLibrary.h"
#include "Blueprint/UserWidget.h"
#include "StatusViewModel.h"
#include "StatusComponent.h"

void AMyPlayerController::InitHUD()
{
	UUserWidget* Widget = CreateWidget<UUserWidget>(this, StatusHudWidgetClass);
	if (!Widget)
	{
		return;
	}

	UStatusViewModel* ViewModel = NewObject<UStatusViewModel>(this);
	ViewModel->BindToStatusComponent(PlayerStatusComponent);

	UMVVMBlueprintLibrary::SetViewModelByClass(Widget, ViewModel);
	Widget->AddToViewport();
}
```

## Blueprint: what you and the team do

- `BP_Character`:
	- Add `StatusComponent`.
	- When changing health/energy/score, call the component API only (do not write variables directly).
- `WBP_StatusHUD`:
	- Two `ProgressBar` widgets and one `TextBlock`.
	- Three bindings: `Percent/Text` bound to viewmodel fields.
	- No manual refresh logic and no Tick.

## Ownership boundaries

- Initial values/max values/regen rates/thresholds -> `DataAsset` / `Curve` / data tables.
- Character presentation/animation/input/VFX -> Blueprint Character.
- UI layout/animation -> Widget Blueprint.
