# Example: Animation Instance C++ Boundary

Use this when adding C++ animation state exposed to an Animation Blueprint.

## Agent checklist

- Animation instances should read movement/gameplay state; avoid owning gameplay authority.
- Cache pawn/character references safely.
- Keep per-frame animation update lightweight.
- Do not call server RPCs or mutate gameplay state from the AnimInstance update path.

## Header pattern

```cpp
#pragma once

#include "CoreMinimal.h"
#include "Animation/AnimInstance.h"
#include "PlayerAnimInstance.generated.h"

class ACharacter;

UCLASS()
class YOURGAME_API UPlayerAnimInstance : public UAnimInstance
{
    GENERATED_BODY()

protected:
    virtual void NativeInitializeAnimation() override;
    virtual void NativeUpdateAnimation(float DeltaSeconds) override;

    UPROPERTY(BlueprintReadOnly, Category="Movement")
    float GroundSpeed = 0.0f;

    UPROPERTY(BlueprintReadOnly, Category="Movement")
    bool bIsFalling = false;

    UPROPERTY(Transient)
    TWeakObjectPtr<ACharacter> CachedCharacter;
};
```

## Implementation notes

```text
- Use TryGetPawnOwner() and Cast<ACharacter> in initialization/update.
- Read CharacterMovement values for animation state.
- Keep gameplay decisions in character/controller/components, not the animation instance.
```
