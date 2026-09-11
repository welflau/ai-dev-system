# Example: USTRUCT and UENUM

This example demonstrates how to create reflected structs and enums for Blueprint and serialization support.

## UENUM Example

### Basic Enum (`EItemRarity.h` or in a shared header)

```cpp
#pragma once

#include "CoreMinimal.h"
#include "EItemRarity.generated.h"

/**
 * Defines the rarity tiers for game items.
 * BlueprintType allows use in Blueprints.
 */
UENUM(BlueprintType)
enum class EItemRarity : uint8
{
	Common      UMETA(DisplayName = "Common"),
	Uncommon    UMETA(DisplayName = "Uncommon"),
	Rare        UMETA(DisplayName = "Rare"),
	Epic        UMETA(DisplayName = "Epic"),
	Legendary   UMETA(DisplayName = "Legendary")
};
```

### Enum as Flags

```cpp
/**
 * Bitflags for item categories.
 * Use ENUM_CLASS_FLAGS to enable bitwise operations.
 */
UENUM(BlueprintType, meta=(Bitflags, UseEnumValuesAsMaskValuesInEditor="true"))
enum class EItemCategory : uint8
{
	None        = 0         UMETA(Hidden),
	Weapon      = 1 << 0    UMETA(DisplayName = "Weapon"),
	Armor       = 1 << 1    UMETA(DisplayName = "Armor"),
	Consumable  = 1 << 2    UMETA(DisplayName = "Consumable"),
	Quest       = 1 << 3    UMETA(DisplayName = "Quest Item"),
	Crafting    = 1 << 4    UMETA(DisplayName = "Crafting Material")
};
ENUM_CLASS_FLAGS(EItemCategory)

// Usage:
// EItemCategory Categories = EItemCategory::Weapon | EItemCategory::Crafting;
// bool bIsWeapon = EnumHasAnyFlags(Categories, EItemCategory::Weapon);
```

## USTRUCT Example

### Simple Data Struct (`FItemData.h`)

```cpp
#pragma once

#include "CoreMinimal.h"
#include "EItemRarity.h"
#include "FItemData.generated.h"

/**
 * Represents static data for an item type.
 * BlueprintType allows passing as function parameters in Blueprints.
 */
USTRUCT(BlueprintType)
struct MYGAME_API FItemData
{
	GENERATED_BODY()

	/** Default constructor */
	FItemData()
		: ItemId(NAME_None)
		, DisplayName(FText::GetEmpty())
		, Rarity(EItemRarity::Common)
		, BaseValue(0)
		, MaxStackSize(1)
		, bIsQuestItem(false)
	{
	}

	/** Unique identifier */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Item")
	FName ItemId;

	/** Localized display name */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Item")
	FText DisplayName;

	/** Item description for UI */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Item", meta = (MultiLine = true))
	FText Description;

	/** Rarity tier */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Item")
	EItemRarity Rarity;

	/** Base currency value */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Item", meta = (ClampMin = "0"))
	int32 BaseValue;

	/** Maximum items per stack (1 = non-stackable) */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Item", meta = (ClampMin = "1"))
	int32 MaxStackSize;

	/** Quest items cannot be sold or dropped */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Item")
	bool bIsQuestItem;

	/** Icon for UI display */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Visual")
	TSoftObjectPtr<UTexture2D> Icon;

	/** Mesh for world representation */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Visual")
	TSoftObjectPtr<UStaticMesh> WorldMesh;

	/** Equality operator for comparisons */
	bool operator==(const FItemData& Other) const
	{
		return ItemId == Other.ItemId;
	}

	/** Hash function for TMap/TSet support */
	friend uint32 GetTypeHash(const FItemData& ItemData)
	{
		return GetTypeHash(ItemData.ItemId);
	}

	/** Check if this struct has valid data */
	bool IsValid() const
	{
		return !ItemId.IsNone();
	}
};
```

### Runtime Instance Struct

```cpp
/**
 * Represents a runtime instance of an item (e.g., in inventory).
 * Tracks quantity and instance-specific state.
 */
USTRUCT(BlueprintType)
struct MYGAME_API FItemInstance
{
	GENERATED_BODY()

	FItemInstance()
		: ItemId(NAME_None)
		, Quantity(0)
		, UniqueId(FGuid())
	{
	}

	FItemInstance(FName InItemId, int32 InQuantity = 1)
		: ItemId(InItemId)
		, Quantity(InQuantity)
		, UniqueId(FGuid::NewGuid())
	{
	}

	/** Reference to item definition */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Instance")
	FName ItemId;

	/** Current stack quantity */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Instance", meta = (ClampMin = "0"))
	int32 Quantity;

	/** Unique instance identifier (for networking/saving) */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Instance")
	FGuid UniqueId;

	bool IsValid() const
	{
		return !ItemId.IsNone() && Quantity > 0;
	}
};
```

## Key USTRUCT Specifiers

| Specifier | Purpose |
|-----------|---------|
| `BlueprintType` | Usable as Blueprint variable/parameter |
| `Atomic` | Always serialized as a single unit |
| `NoExport` | Not exported to generated header |
| `Immutable` | Cannot be modified after construction |

## Key UENUM Specifiers

| Specifier | Purpose |
|-----------|---------|
| `BlueprintType` | Usable in Blueprints |
| `meta=(Bitflags)` | Treat as bitmask flags |
| `meta=(ScriptName="...")` | Custom name in scripts |

## Key UMETA Specifiers

| Specifier | Purpose |
|-----------|---------|
| `DisplayName = "..."` | Custom display name in editor |
| `Hidden` | Hide from editor dropdowns |
| `ToolTip = "..."` | Tooltip in editor |

## Best Practices

1. **Always initialize members** in the default constructor
2. **Use `TSoftObjectPtr`** for asset references to avoid loading at startup
3. **Implement `operator==`** and `GetTypeHash` for container support
4. **Keep structs small** - large structs are expensive to copy
5. **Use `UPROPERTY()`** on all members that need serialization or reflection
6. **Consider `USTRUCT(Atomic)`** for structs that should always serialize completely
