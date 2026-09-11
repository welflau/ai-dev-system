# Example: Network Replication

This example covers UE's property and RPC replication for multiplayer games.

## Replicated Actor Example

```cpp
// ReplicatedPickup.h
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "ReplicatedPickup.generated.h"

UCLASS()
class MYGAME_API AReplicatedPickup : public AActor
{
    GENERATED_BODY()

public:
    AReplicatedPickup();

    //~ Begin AActor Interface
    virtual void GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const override;
    //~ End AActor Interface

    /** Replicated: current state of the pickup */
    UPROPERTY(ReplicatedUsing = OnRep_PickupState, BlueprintReadOnly, Category = "Pickup")
    bool bIsPickedUp;

    /** Replicated: who picked this up */
    UPROPERTY(Replicated, BlueprintReadOnly, Category = "Pickup")
    TObjectPtr<APawn> PickedUpBy;

    /** Replicated with condition: only replicate to owner */
    UPROPERTY(ReplicatedUsing = OnRep_SecretValue, BlueprintReadOnly, Category = "Pickup")
    int32 SecretValue;

    /** Server RPC: request pickup from client */
    UFUNCTION(Server, Reliable, WithValidation)
    void ServerRequestPickup(APawn* RequestingPawn);

    /** Client RPC: notify specific client */
    UFUNCTION(Client, Reliable)
    void ClientNotifyPickupResult(bool bSuccess, const FString& Message);

    /** Multicast RPC: notify all clients */
    UFUNCTION(NetMulticast, Unreliable)
    void MulticastPlayPickupEffect();

protected:
    /** Called on clients when bIsPickedUp changes */
    UFUNCTION()
    void OnRep_PickupState();

    UFUNCTION()
    void OnRep_SecretValue();

private:
    UPROPERTY(VisibleAnywhere)
    TObjectPtr<UStaticMeshComponent> MeshComponent;
};
```

```cpp
// ReplicatedPickup.cpp
#include "ReplicatedPickup.h"
#include "Net/UnrealNetwork.h"
#include "Components/StaticMeshComponent.h"

AReplicatedPickup::AReplicatedPickup()
{
    // Enable replication
    bReplicates = true;
    
    // Set replication frequency (default is 100)
    NetUpdateFrequency = 10.0f;
    
    // Replicate movement if needed
    SetReplicateMovement(true);

    MeshComponent = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Mesh"));
    RootComponent = MeshComponent;
}

void AReplicatedPickup::GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const
{
    Super::GetLifetimeReplicatedProps(OutLifetimeProps);

    // Always replicate to everyone
    DOREPLIFETIME(AReplicatedPickup, bIsPickedUp);
    DOREPLIFETIME(AReplicatedPickup, PickedUpBy);

    // Conditional replication: only to owner
    DOREPLIFETIME_CONDITION(AReplicatedPickup, SecretValue, COND_OwnerOnly);
}

void AReplicatedPickup::OnRep_PickupState()
{
    // Called on clients when bIsPickedUp changes
    if (bIsPickedUp)
    {
        // Hide mesh on clients
        MeshComponent->SetVisibility(false);
        MeshComponent->SetCollisionEnabled(ECollisionEnabled::NoCollision);
    }
}

void AReplicatedPickup::OnRep_SecretValue()
{
    UE_LOG(LogTemp, Log, TEXT("Secret value updated to: %d"), SecretValue);
}

// Server RPC implementation
void AReplicatedPickup::ServerRequestPickup_Implementation(APawn* RequestingPawn)
{
    if (bIsPickedUp || !RequestingPawn)
    {
        // Notify client of failure
        if (APlayerController* PC = Cast<APlayerController>(RequestingPawn->GetController()))
        {
            ClientNotifyPickupResult(false, TEXT("Pickup failed"));
        }
        return;
    }

    // Server authoritative: set state
    bIsPickedUp = true;
    PickedUpBy = RequestingPawn;

    // Notify all clients with effect
    MulticastPlayPickupEffect();

    // Notify requesting client specifically
    if (APlayerController* PC = Cast<APlayerController>(RequestingPawn->GetController()))
    {
        ClientNotifyPickupResult(true, TEXT("Pickup successful!"));
    }
}

// Server RPC validation (return false to disconnect cheaters)
bool AReplicatedPickup::ServerRequestPickup_Validate(APawn* RequestingPawn)
{
    // Add anti-cheat validation here
    // Return false to disconnect the client
    return RequestingPawn != nullptr;
}

// Client RPC implementation
void AReplicatedPickup::ClientNotifyPickupResult_Implementation(bool bSuccess, const FString& Message)
{
    UE_LOG(LogTemp, Log, TEXT("Pickup result: %s - %s"), 
        bSuccess ? TEXT("Success") : TEXT("Failed"), *Message);
}

// Multicast RPC implementation
void AReplicatedPickup::MulticastPlayPickupEffect_Implementation()
{
    // Play particle effect, sound, etc. on all clients
    UE_LOG(LogTemp, Log, TEXT("Playing pickup effect on all clients"));
}
```

## Replication Conditions

| Condition | Description |
|-----------|-------------|
| `COND_None` | Always replicate (default) |
| `COND_InitialOnly` | Only on initial replication |
| `COND_OwnerOnly` | Only to owning connection |
| `COND_SkipOwner` | Everyone except owner |
| `COND_SimulatedOnly` | Only to simulated proxies |
| `COND_AutonomousOnly` | Only to autonomous proxy (controlled pawn) |
| `COND_SimulatedOrPhysics` | Simulated or physics-enabled |
| `COND_InitialOrOwner` | Initial or to owner |
| `COND_Custom` | Custom condition via virtual function |
| `COND_ReplayOrOwner` | Replay recording or owner |
| `COND_ReplayOnly` | Only during replay |
| `COND_SkipReplay` | Skip during replay |
| `COND_ServerOnly` | Only on server (not replicated, but organized) |

## RPC Types

| Specifier | Direction | Reliability | Use Case |
|-----------|-----------|-------------|----------|
| `Server` | Client → Server | User choice | Gameplay requests |
| `Client` | Server → Owning Client | User choice | Owner-specific feedback |
| `NetMulticast` | Server → All Clients | User choice | Effects, announcements |

| Reliability | Description |
|-------------|-------------|
| `Reliable` | Guaranteed delivery, ordered |
| `Unreliable` | May be dropped, for frequent updates |

## Common Patterns

### Check Authority

```cpp
void AMyActor::DoSomething()
{
    if (HasAuthority())
    {
        // We are the server, make authoritative changes
        Health = 100;
    }
    else
    {
        // We are a client, request server to do it
        ServerDoSomething();
    }
}
```

### Check Local Control

```cpp
void AMyPawn::HandleInput()
{
    if (IsLocallyControlled())
    {
        // This pawn is controlled by local player
        // Send input to server
        ServerProcessInput(InputVector);
    }
}
```

### Role Checking

```cpp
void AMyActor::Tick(float DeltaTime)
{
    Super::Tick(DeltaTime);

    switch (GetLocalRole())
    {
    case ROLE_Authority:
        // Server or standalone
        TickServer(DeltaTime);
        break;
    case ROLE_AutonomousProxy:
        // Locally controlled on client
        TickLocalClient(DeltaTime);
        break;
    case ROLE_SimulatedProxy:
        // Not locally controlled on client
        TickRemoteClient(DeltaTime);
        break;
    default:
        break;
    }
}
```

## Module Dependencies

Add to your `Build.cs`:

```csharp
PublicDependencyModuleNames.AddRange(new string[] { 
    "Core", 
    "CoreUObject", 
    "Engine",
    "NetCore"  // For advanced networking features
});
```

## Best Practices

1. **Minimize replicated properties** - bandwidth is precious
2. **Use appropriate conditions** - don't replicate to clients that don't need it
3. **Validate Server RPCs** - always implement `_Validate` for security
4. **Use Unreliable for frequent updates** - like movement smoothing
5. **Use Reliable for important events** - like damage, death, pickups
6. **Set `NetUpdateFrequency`** appropriately for each actor type
7. **Use `OnRep_` functions** for client-side reactions to state changes
8. **Don't trust client data** - server should validate everything
