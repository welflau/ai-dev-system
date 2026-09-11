# Example: Async / Timer — UObject Lifetime-Safe Patterns

## Use when

- Scheduling delayed gameplay work.
- Calling back from async work into game thread.
- Avoiding use-after-free when lambdas capture UObjects.

## Agent prompt template

```text
Implement delayed or async gameplay work safely.
Inspect existing timer/task patterns first.
Never capture raw UObject pointers in long-lived lambdas without a validity guard.
Return to game thread before touching UObjects.
Run the Editor target build through the repository launcher and review lifetime assumptions.
```

## Timer skeleton

```cpp
#include "TimerManager.h"
#include "Engine/World.h"

void UMyComponent::StartCooldown(float Duration)
{
    UWorld* World = GetWorld();
    if (!World || Duration <= 0.0f)
    {
        return;
    }

    World->GetTimerManager().ClearTimer(CooldownTimerHandle);
    World->GetTimerManager().SetTimer(
        CooldownTimerHandle,
        this,
        &UMyComponent::HandleCooldownFinished,
        Duration,
        false);
}

void UMyComponent::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().ClearTimer(CooldownTimerHandle);
    }

    Super::EndPlay(EndPlayReason);
}
```

## Async game-thread callback skeleton

```cpp
#include "Async/Async.h"

void UMyComponent::StartBackgroundWork()
{
    TWeakObjectPtr<UMyComponent> WeakThis(this);

    Async(EAsyncExecution::ThreadPool, [WeakThis]()
    {
        // Compute non-UObject data only.
        const int32 Result = 42;

        AsyncTask(ENamedThreads::GameThread, [WeakThis, Result]()
        {
            if (!WeakThis.IsValid())
            {
                return;
            }

            WeakThis->ApplyResultOnGameThread(Result);
        });
    });
}
```

## Review checklist

- UObjects are touched only on the game thread unless the API is explicitly thread-safe.
- Long-lived callbacks capture `TWeakObjectPtr`, not raw `this`.
- Timers are cleared in `EndPlay` when appropriate.
- World context is checked before scheduling work.
- No hidden dependency on PIE/editor object lifetime.
