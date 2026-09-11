# Example: AI — AIController + Blackboard + Behavior Tree Bootstrap

## Use when

- Adding C++ AI controller for NPCs.
- Bootstrapping Behavior Tree/Blackboard assets from C++ defaults.
- Avoiding fragile Blueprint-only initialization.

## Agent prompt template

```text
Add or update an AIController that starts a behavior tree on possess.
Inspect existing AI module and BehaviorTree asset conventions.
Do not create asset files directly; expose asset references for designers.
Run the Editor target build through the repository launcher and verify AIModule/GameplayTasks dependencies if needed.
```

## Header skeleton

```cpp
#pragma once

#include "CoreMinimal.h"
#include "AIController.h"
#include "GuardAIController.generated.h"

class UBehaviorTree;

UCLASS()
class YOURPROJECT_API AGuardAIController : public AAIController
{
    GENERATED_BODY()

protected:
    virtual void OnPossess(APawn* InPawn) override;

    UPROPERTY(EditDefaultsOnly, Category="AI")
    TObjectPtr<UBehaviorTree> DefaultBehaviorTree;
};
```

## CPP skeleton

```cpp
#include "GuardAIController.h"
#include "BehaviorTree/BehaviorTree.h"

void AGuardAIController::OnPossess(APawn* InPawn)
{
    Super::OnPossess(InPawn);

    if (!DefaultBehaviorTree)
    {
        UE_LOG(LogTemp, Warning, TEXT("%s has no DefaultBehaviorTree"), *GetName());
        return;
    }

    RunBehaviorTree(DefaultBehaviorTree);
}
```

## Build.cs

```csharp
PrivateDependencyModuleNames.AddRange(new[] {
    "AIModule",
    "GameplayTasks"
});
```

## Review checklist

- AI asset references are editable, not hard-coded unless project convention requires it.
- Controller handles null BehaviorTree safely.
- Blackboard keys are not stringly-typed in many places; centralize key names if needed.
- AI initialization is server-side unless using client-only cosmetic AI.
- Do not run expensive perception/traces every Tick without budget.
