# Example: CommonUI Activatable Widget Boundary

Use this when a project uses CommonUI for menus, screens, or gamepad-focused UI.

## Agent checklist

- Confirm CommonUI is enabled and used in existing project UI before adding dependencies.
- UI navigation/screens should not own gameplay authority.
- Prefer project UI manager/router conventions over directly creating widgets in random actors.
- Keep gameplay state in PlayerState, components, ASC, or subsystems; widgets observe and request.

## Build.cs dependency

```csharp
PrivateDependencyModuleNames.AddRange(new string[]
{
    "CommonUI",
    "UMG",
    "Slate",
    "SlateCore"
});
```

## Header pattern

```cpp
#pragma once

#include "CoreMinimal.h"
#include "CommonActivatableWidget.h"
#include "InventoryScreen.generated.h"

class UCommonButtonBase;

UCLASS(Abstract, BlueprintType)
class YOURGAME_API UInventoryScreen : public UCommonActivatableWidget
{
    GENERATED_BODY()

protected:
    virtual void NativeOnActivated() override;
    virtual void NativeOnDeactivated() override;

    UFUNCTION()
    void HandleCloseClicked();

    UPROPERTY(meta=(BindWidgetOptional))
    TObjectPtr<UCommonButtonBase> CloseButton;
};
```

## Implementation notes

```text
- Bind button events in NativeOnActivated and unbind in NativeOnDeactivated or NativeDestruct.
- Use the project's UI layer stack/router if it exists.
- Do not call server RPCs directly from random widget buttons unless that is the established pattern; prefer a PlayerController or view-model boundary.
```

## Validation

```text
- CommonUI module dependency is present.
- Widget blueprint parent class and bind names are valid.
- Keyboard/gamepad focus behavior is smoke-tested.
```
