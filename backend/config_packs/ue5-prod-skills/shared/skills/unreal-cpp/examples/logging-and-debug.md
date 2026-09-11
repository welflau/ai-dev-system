# Example: Logging and Debug

This example covers UE_LOG, custom log categories, and common debugging techniques.

## Custom Log Category

### Declaration (Header)

```cpp
// MyGame.h or a dedicated LogCategories.h
#pragma once

#include "CoreMinimal.h"

// Declare log categories
DECLARE_LOG_CATEGORY_EXTERN(LogMyGame, Log, All);
DECLARE_LOG_CATEGORY_EXTERN(LogInventory, Log, All);
DECLARE_LOG_CATEGORY_EXTERN(LogCombat, Log, All);
DECLARE_LOG_CATEGORY_EXTERN(LogAI, Log, All);
DECLARE_LOG_CATEGORY_EXTERN(LogNetworking, Log, All);
```

### Definition (Source)

```cpp
// MyGame.cpp
#include "MyGame.h"

// Define log categories
DEFINE_LOG_CATEGORY(LogMyGame);
DEFINE_LOG_CATEGORY(LogInventory);
DEFINE_LOG_CATEGORY(LogCombat);
DEFINE_LOG_CATEGORY(LogAI);
DEFINE_LOG_CATEGORY(LogNetworking);
```

## Log Verbosity Levels

| Level | Macro | Description | Default Visibility |
|-------|-------|-------------|-------------------|
| Fatal | `UE_LOG(..., Fatal, ...)` | Crashes immediately | Always |
| Error | `UE_LOG(..., Error, ...)` | Red text, serious issue | Always |
| Warning | `UE_LOG(..., Warning, ...)` | Yellow text, potential issue | Always |
| Display | `UE_LOG(..., Display, ...)` | Important info | Always |
| Log | `UE_LOG(..., Log, ...)` | General info | Default |
| Verbose | `UE_LOG(..., Verbose, ...)` | Detailed debug info | Hidden |
| VeryVerbose | `UE_LOG(..., VeryVerbose, ...)` | Extremely detailed | Hidden |

## Usage Examples

```cpp
#include "LogCategories.h"

void UInventoryComponent::AddItem(const FName& ItemId, int32 Quantity)
{
    // Basic logging
    UE_LOG(LogInventory, Log, TEXT("Adding item: %s x%d"), *ItemId.ToString(), Quantity);

    // Warning
    if (Quantity <= 0)
    {
        UE_LOG(LogInventory, Warning, TEXT("Invalid quantity %d for item %s"), Quantity, *ItemId.ToString());
        return;
    }

    // Error
    if (!IsValid())
    {
        UE_LOG(LogInventory, Error, TEXT("Inventory component is invalid!"));
        return;
    }

    // Verbose (only shown when explicitly enabled)
    UE_LOG(LogInventory, Verbose, TEXT("Current inventory size: %d"), Items.Num());

    // Conditional logging (compiled out in Shipping builds)
    UE_CLOG(bDebugInventory, LogInventory, Log, TEXT("Debug: Slot %d selected"), CurrentSlot);

    // Fatal (crashes with callstack)
    // UE_LOG(LogInventory, Fatal, TEXT("Critical failure!"));
}
```

## Formatted Output

```cpp
// Object names
UE_LOG(LogMyGame, Log, TEXT("Actor: %s"), *GetNameSafe(MyActor));
UE_LOG(LogMyGame, Log, TEXT("Object path: %s"), *GetPathNameSafe(MyObject));

// Vectors and transforms
FVector Location = GetActorLocation();
UE_LOG(LogMyGame, Log, TEXT("Location: %s"), *Location.ToString());
UE_LOG(LogMyGame, Log, TEXT("Location: X=%.2f Y=%.2f Z=%.2f"), Location.X, Location.Y, Location.Z);

// Rotators
FRotator Rotation = GetActorRotation();
UE_LOG(LogMyGame, Log, TEXT("Rotation: %s"), *Rotation.ToString());

// Booleans
UE_LOG(LogMyGame, Log, TEXT("IsValid: %s"), bIsValid ? TEXT("true") : TEXT("false"));

// Enums (with UENUM)
UE_LOG(LogMyGame, Log, TEXT("State: %s"), *UEnum::GetValueAsString(CurrentState));

// Class names
UE_LOG(LogMyGame, Log, TEXT("Class: %s"), *GetClass()->GetName());

// Function name (useful for debugging)
UE_LOG(LogMyGame, Log, TEXT("[%s] Called"), ANSI_TO_TCHAR(__FUNCTION__));
```

## On-Screen Debug Messages

```cpp
// Simple message (default 5 seconds)
GEngine->AddOnScreenDebugMessage(-1, 5.0f, FColor::Green, TEXT("Hello World"));

// With key (only one message per key at a time)
GEngine->AddOnScreenDebugMessage(1, 0.0f, FColor::Yellow, 
    FString::Printf(TEXT("Health: %.1f"), Health));

// In Tick - use key to avoid spam
void AMyActor::Tick(float DeltaTime)
{
    Super::Tick(DeltaTime);
    
    if (GEngine)
    {
        GEngine->AddOnScreenDebugMessage(
            GetUniqueID(),  // Use actor ID as key
            0.0f,           // Duration (0 = one frame)
            FColor::Cyan,
            FString::Printf(TEXT("Velocity: %s"), *GetVelocity().ToString())
        );
    }
}
```

## Debug Drawing

```cpp
#include "DrawDebugHelpers.h"

void AMyActor::DebugDraw()
{
    // Only in editor or development builds
#if !UE_BUILD_SHIPPING
    
    UWorld* World = GetWorld();
    if (!World)
    {
        return;
    }

    FVector Start = GetActorLocation();

    // Line
    DrawDebugLine(World, Start, Start + FVector(0, 0, 100), FColor::Red, false, -1.0f, 0, 2.0f);

    // Sphere
    DrawDebugSphere(World, Start, 50.0f, 12, FColor::Green, false, -1.0f);

    // Box
    DrawDebugBox(World, Start, FVector(50, 50, 50), FColor::Blue, false, -1.0f);

    // Arrow
    DrawDebugDirectionalArrow(World, Start, Start + GetActorForwardVector() * 100, 
        50.0f, FColor::Yellow, false, -1.0f, 0, 3.0f);

    // String
    DrawDebugString(World, Start + FVector(0, 0, 100), TEXT("Debug Text"), 
        nullptr, FColor::White, -1.0f, true);

    // Capsule
    DrawDebugCapsule(World, Start, 50.0f, 25.0f, GetActorQuat(), FColor::Purple, false, -1.0f);

    // Coordinate system
    DrawDebugCoordinateSystem(World, Start, GetActorRotation(), 100.0f, false, -1.0f);

#endif
}
```

## Console Commands

### Define Custom Command

```cpp
// In actor or component
static FAutoConsoleCommand CmdDebugInventory(
    TEXT("MyGame.DebugInventory"),
    TEXT("Toggle inventory debug mode"),
    FConsoleCommandWithArgsDelegate::CreateLambda([](const TArray<FString>& Args) {
        // Toggle debug flag
        static bool bDebug = false;
        bDebug = !bDebug;
        UE_LOG(LogInventory, Display, TEXT("Inventory debug: %s"), bDebug ? TEXT("ON") : TEXT("OFF"));
    })
);

// Console variable
static TAutoConsoleVariable<int32> CVarDebugLevel(
    TEXT("MyGame.DebugLevel"),
    0,
    TEXT("Debug verbosity level (0-3)"),
    ECVF_Default
);

// Usage in code
int32 DebugLevel = CVarDebugLevel.GetValueOnGameThread();
```

## Assertions

```cpp
// Check (logs error and continues in Development, crashes in Debug)
check(Pointer != nullptr);
checkf(Value > 0, TEXT("Value must be positive, got %d"), Value);

// Verify (always evaluates expression, even in Shipping)
verify(ImportantFunction());

// Ensure (logs error with callstack, continues execution)
if (!ensure(Pointer != nullptr))
{
    return;
}

// ensureMsgf with message
if (!ensureMsgf(Index < Array.Num(), TEXT("Index %d out of bounds (size: %d)"), Index, Array.Num()))
{
    return;
}

// checkCode - only in Debug/Development builds
checkCode(
    if (GEngine)
    {
        GEngine->AddOnScreenDebugMessage(-1, 5.0f, FColor::Red, TEXT("Debug check"));
    }
);
```

## Compile-Time Conditional Logging

```cpp
// Only in non-shipping builds
#if !UE_BUILD_SHIPPING
    UE_LOG(LogMyGame, Verbose, TEXT("Detailed debug info..."));
#endif

// Only with specific define
#if ENABLE_VISUAL_LOG
    UE_VLOG(this, LogAI, Log, TEXT("AI decision: %s"), *Decision);
#endif

// Editor only
#if WITH_EDITOR
    UE_LOG(LogMyGame, Log, TEXT("Editor-only logging"));
#endif
```

## Best Practices

1. **Create project-specific log categories** - don't overuse `LogTemp`
2. **Use appropriate verbosity** - `Verbose` for debug, `Log` for general, `Warning`/`Error` for issues
3. **Include context** - actor names, function names, relevant values
4. **Use `UE_CLOG`** for conditional logging tied to debug flags
5. **Use on-screen messages with keys** in Tick to avoid spam
6. **Wrap debug drawing** in `#if !UE_BUILD_SHIPPING`
7. **Use `GetNameSafe`/`GetPathNameSafe`** to avoid crashes on null pointers
8. **Remove or reduce logging** before shipping - it affects performance
