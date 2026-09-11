# Example: Adding a reflected UObject type

This example demonstrates how to create a simple UObject that can be referenced from Blueprints, following Epic's C++ coding standard and best practices.

## Goal

Add a simple UObject that can be referenced from Blueprints with proper reflection support.

## Checklist

- Header lives in a module under `Source/<ModuleName>/Public/` (for public API) or `Private/` (for internal use)
- Uses `UCLASS()` macro with appropriate specifiers (e.g., `BlueprintType`, `Blueprintable`)
- Includes `GENERATED_BODY()` macro in class declaration
- Generated header (`*.generated.h`) is included last in the header file
- Follows Epic's naming conventions: `U` prefix for UObject-derived classes
- Uses minimal includes in headers; heavy includes move to `.cpp` files
- Adheres to const correctness and modern C++ practices

## Complete Example

### Header File (`MyGameItem.h`)

> **Note**: UE 文件名不带类型前缀（使用 `MyGameItem.h` 而非 `UMyGameItem.h`）

```cpp
// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "UObject/Object.h"
#include "MyGameItem.generated.h"

/**
 * Represents a collectible item in the game with Blueprint support.
 * 
 * This class demonstrates proper UObject reflection with common UPROPERTY patterns.
 */
UCLASS(BlueprintType, Blueprintable, Category="Gameplay|Items")
class MYGAME_API UMyGameItem : public UObject
{
	GENERATED_BODY()

public:
	// Default constructor
	UMyGameItem();

	//~ Begin UObject Interface
	virtual void BeginDestroy() override;
	//~ End UObject Interface

	/** Display name shown to players */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Item Properties", meta=(DisplayName="Item Name"))
	FText DisplayName;

	/** Unique identifier for this item type */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Item Properties", meta=(DisplayName="Item ID"))
	FName ItemId;

	/** Base value of this item in currency */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Item Properties", meta=(ClampMin="0", UIMin="0"))
	int32 BaseValue = 10;

	/** Whether this item can be stacked in inventory */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Item Properties")
	bool bCanStack = true;

	/** Maximum stack size if stackable */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Item Properties", meta=(EditCondition="bCanStack", ClampMin="1"))
	int32 MaxStackSize = 99;

	/** Icon texture for UI display */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Visual")
	TObjectPtr<UTexture2D> IconTexture;

	/** Description shown in tooltips */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Item Properties", meta=(MultiLine="true"))
	FText Description;

	/**
	 * Checks if this item can be used by the specified player.
	 * 
	 * @param PlayerController The player attempting to use the item
	 * @return True if the item can be used, false otherwise
	 */
	UFUNCTION(BlueprintCallable, Category="Item Actions")
	bool CanUseItem(APlayerController* PlayerController) const;

	/**
	 * Uses this item with the specified player.
	 * 
	 * @param PlayerController The player using the item
	 * @return True if the item was successfully used
	 */
	UFUNCTION(BlueprintCallable, Category="Item Actions")
	bool UseItem(APlayerController* PlayerController);

	/**
	 * Gets the current value of this item, potentially modified by game state.
	 * 
	 * @return The current effective value
	 */
	UFUNCTION(BlueprintPure, Category="Item Properties")
	int32 GetCurrentValue() const;

private:
	/** Internal cooldown timer (not exposed to Blueprints) */
	float CooldownRemaining = 0.0f;
};
```

### Source File (`MyGameItem.cpp`)

```cpp
// Copyright Epic Games, Inc. All Rights Reserved.

#include "MyGameItem.h"
#include "GameFramework/PlayerController.h"
#include "Engine/Texture2D.h"
#include "TimerManager.h"

UMyGameItem::UMyGameItem()
{
	// Initialize default values
	DisplayName = FText::FromString(TEXT("New Item"));
	ItemId = FName(TEXT("DefaultItem"));
	Description = FText::FromString(TEXT("A collectible game item."));
}

void UMyGameItem::BeginDestroy()
{
	// Clean up any resources
	IconTexture = nullptr;
	
	Super::BeginDestroy();
}

bool UMyGameItem::CanUseItem(APlayerController* PlayerController) const
{
	if (!PlayerController)
	{
		return false;
	}

	// Check cooldown
	if (CooldownRemaining > 0.0f)
	{
		return false;
	}

	// Add additional checks as needed
	return true;
}

bool UMyGameItem::UseItem(APlayerController* PlayerController)
{
	if (!CanUseItem(PlayerController))
	{
		return false;
	}

	// Implement item usage logic here
	UE_LOG(LogTemp, Log, TEXT("Using item: %s"), *DisplayName.ToString());
	
	// Set cooldown (example: 5 seconds)
	CooldownRemaining = 5.0f;
	
	// In a real implementation, you'd set up a timer to decrement cooldown
	// For this example, we'll just mark it as used
	
	return true;
}

int32 UMyGameItem::GetCurrentValue() const
{
	// Example: modify base value based on some condition
	return BaseValue;
}
```

## Key Points from CoreMinimal.h Usage

When including `CoreMinimal.h`, you get access to these commonly used UE types (non-exhaustive):

- **Containers**: `TArray`, `TMap`, `TSet`, `FString`, `FText`, `FName`
- **Math**: `FVector`, `FRotator`, `FTransform`, `FMatrix`, `FQuat`
- **Templates**: `TSharedPtr`, `TUniquePtr`, `TWeakObjectPtr`, `TObjectPtr`
- **Logging**: `UE_LOG`, `LOG_CATEGORY`
- **Delegates**: `DECLARE_DELEGATE`, `DECLARE_MULTICAST_DELEGATE`
- **Type Traits**: `TIsArithmetic`, `TIsPointer`, `TIsEnumClass`

## Module Configuration (`MyGame.Build.cs`)

Ensure your module's Build.cs includes necessary dependencies:

```csharp
PublicDependencyModuleNames.AddRange(new string[] { 
    "Core", 
    "CoreUObject", 
    "Engine", 
    "InputCore" 
    // Add other dependencies as needed
});
```

## Common UPROPERTY Specifiers

- `EditAnywhere`: Editable in both archetypes and instances
- `BlueprintReadOnly`: Readable in Blueprints but not writable
- `BlueprintReadWrite`: Readable and writable in Blueprints
- `Category`: Organizes properties in editor details panel
- `meta=(DisplayName="...")`: Custom display name
- `meta=(ClampMin="0", ClampMax="100")`: Value range constraints
- `meta=(EditCondition="bSomeBool")`: Conditional property editing

## Common UFUNCTION Specifiers

- `BlueprintCallable`: Can be called from Blueprints
- `BlueprintPure`: Pure function (no side effects, const)
- `Category`: Organizes functions in Blueprint context menu

## If it fails to compile

### Missing `*.generated.h`
- Ensure the header includes `MyType.generated.h` and that it is the last include in that header
- Ensure the file is located in a module that is part of the build target
- Ensure the type is declared with the right `UCLASS/USTRUCT` macros and includes required UE headers

### UHT parsing errors
- Check for missing `UCLASS()` / `GENERATED_BODY()`
- Check for includes/forward declarations for reflected types
- Avoid templates/complex macros in UPROPERTY/UFUNCTION signatures unless you know they are supported
- Ensure proper forward declarations for custom types

### Linker errors / unresolved externals
- Usually a missing module dependency or missing implementation file
- Confirm the symbol lives in the linked module and the `.Build.cs` dependencies include it
- Check that all virtual functions have implementations if not pure virtual

### Build configuration issues
- Ensure you're building the correct target (Editor for development, Game for shipping)
- Clean intermediate files (`Intermediate/` folder) if UHT seems stuck
- Check module dependencies in `.Build.cs` files
