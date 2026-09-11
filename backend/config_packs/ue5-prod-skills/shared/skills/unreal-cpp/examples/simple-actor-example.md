# Example: Simple AActor-derived class

This example shows a minimal AActor-derived class with common patterns.

## Header File (`SimpleCollectible.h`)

> **Note**: UE 文件名不带类型前缀（使用 `SimpleCollectible.h` 而非 `ASimpleCollectible.h`）

```cpp
// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "SimpleCollectible.generated.h"

/**
 * A simple collectible actor that can be picked up by players.
 */
UCLASS(Blueprintable)
class MYGAME_API ASimpleCollectible : public AActor
{
	GENERATED_BODY()
	
public:	
	// Sets default values for this actor's properties
	ASimpleCollectible();

protected:
	// Called when the game starts or when spawned
	virtual void BeginPlay() override;

public:	
	// Called every frame
	virtual void Tick(float DeltaTime) override;

	/** Static mesh component for visual representation */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Components")
	TObjectPtr<UStaticMeshComponent> MeshComponent;

	/** Whether this collectible has been picked up */
	UPROPERTY(VisibleInstanceOnly, BlueprintReadOnly, Category="Collectible")
	bool bIsCollected = false;

	/** Score value when collected */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Collectible", meta=(ClampMin="0"))
	int32 ScoreValue = 100;

	/** Rotation speed in degrees per second */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Collectible")
	float RotationSpeed = 45.0f;

	/** Called when a player collects this item */
	UFUNCTION(BlueprintCallable, Category="Collectible")
	void Collect();

	/** Checks if this collectible can be collected */
	UFUNCTION(BlueprintPure, Category="Collectible")
	bool CanBeCollected() const { return !bIsCollected; }

private:
	/** Current rotation angle */
	float CurrentRotation = 0.0f;
};
```

## Source File (`SimpleCollectible.cpp`)

```cpp
// Copyright Epic Games, Inc. All Rights Reserved.

#include "SimpleCollectible.h"
#include "Components/StaticMeshComponent.h"

ASimpleCollectible::ASimpleCollectible()
{
	// Set this actor to call Tick() every frame
	PrimaryActorTick.bCanEverTick = true;

	// Create and setup mesh component
	MeshComponent = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("MeshComponent"));
	RootComponent = MeshComponent;

	// Set default mesh (would typically be set in Blueprint)
	static ConstructorHelpers::FObjectFinder<UStaticMesh> MeshFinder(TEXT("/Engine/BasicShapes/Sphere"));
	if (MeshFinder.Succeeded())
	{
		MeshComponent->SetStaticMesh(MeshFinder.Object);
	}
}

void ASimpleCollectible::BeginPlay()
{
	Super::BeginPlay();
	
	UE_LOG(LogTemp, Log, TEXT("Collectible spawned at location: %s"), 
		*GetActorLocation().ToString());
}

void ASimpleCollectible::Tick(float DeltaTime)
{
	Super::Tick(DeltaTime);

	// Rotate the collectible
	if (!bIsCollected)
	{
		CurrentRotation += RotationSpeed * DeltaTime;
		FRotator NewRotation = GetActorRotation();
		NewRotation.Yaw = CurrentRotation;
		SetActorRotation(NewRotation);
	}
}

void ASimpleCollectible::Collect()
{
	if (bIsCollected)
	{
		return;
	}

	bIsCollected = true;
	
	// Disable collision and hide mesh
	if (MeshComponent)
	{
		MeshComponent->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		MeshComponent->SetVisibility(false);
	}

	UE_LOG(LogTemp, Log, TEXT("Collectible collected! Score: %d"), ScoreValue);
	
	// Schedule destruction after a delay
	SetLifeSpan(2.0f);
}
```

## Key Learning Points

1. **AActor vs UObject**: 
   - AActor classes have `A` prefix and can be placed in levels
   - UObject classes have `U` prefix and are typically data containers

2. **Component Setup**:
   - Use `CreateDefaultSubobject` in constructor for components
   - Set `RootComponent` for the primary component

3. **ConstructorHelpers**:
   - Use `ConstructorHelpers::FObjectFinder` to load default assets
   - Only works in constructors

4. **Lifecycle Methods**:
   - `BeginPlay()`: Called when actor enters gameplay
   - `Tick()`: Called every frame (enable with `PrimaryActorTick.bCanEverTick = true`)
   - `SetLifeSpan()`: Automatically destroys actor after specified time

5. **Common UPROPERTY Specifiers**:
   - `VisibleAnywhere`: Visible in details panel but not editable
   - `VisibleInstanceOnly`: Only visible for placed instances, not defaults
   - `EditAnywhere`: Editable everywhere