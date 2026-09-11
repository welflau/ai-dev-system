# Example: Preset + CVar + Bounded BFS

Use this pattern when a runtime constant needs both:

- semantic presets per object/category/tag, editable through Project Settings; and
- a global debug override through a console variable.

It also fits any bounded propagation problem such as structural support, connectivity, buff spread, power/water networks, or fire spread.

## 1. Preset In `UDeveloperSettings`

```cpp
USTRUCT(BlueprintType)
struct FSupportPreset
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Support")
    FGameplayTag CategoryTag;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Support", meta = (ClampMin = "0", ClampMax = "16"))
    int32 MaxReach = 2;
};

UCLASS(Config = Game, DefaultConfig, meta = (DisplayName = "Runtime Support Settings"))
class UMyRuntimeSettings : public UDeveloperSettings
{
    GENERATED_BODY()

public:
    UPROPERTY(EditAnywhere, Config, Category = "Support")
    TArray<FSupportPreset> SupportPresets;

    static const FSupportPreset* FindPresetByTag(const FGameplayTag& Tag);
};
```

Guidelines:

- Keep preset lookup behind one helper such as `FindPresetByTag`.
- Store user-tunable defaults in config-backed settings, not scattered constants.
- Full editor restart is required after reflected field/type changes.

## 2. Global CVar Override

Define file-scope CVar objects before any helper that references them.

```cpp
namespace
{
    static TAutoConsoleVariable<int32> CVarSupportMaxReachOverride(
        TEXT("MyProject.Support.MaxReachOverride"),
        -1,
        TEXT("-1=use preset; >=0=global override for debugging"),
        ECVF_Default);

    static int32 ResolveMaxReach(const FGameplayTag& CategoryTag)
    {
        const int32 OverrideValue = CVarSupportMaxReachOverride.GetValueOnAnyThread();
        if (OverrideValue >= 0)
        {
            return OverrideValue;
        }

        if (const FSupportPreset* Preset = UMyRuntimeSettings::FindPresetByTag(CategoryTag))
        {
            return Preset->MaxReach;
        }

        return 2;
    }
}
```

Use a project/system/field naming pattern such as `<Project>.<System>.<Field>Override`.

## 3. Bounded BFS Invariants

Any propagation or support decision should satisfy:

1. Bounded search: always cap depth/radius with `MaxReach`.
2. Non-recursive termination: a soft rule may terminate only on hard/direct anchors, not on another node that is true only by the same soft rule.
3. Self-exclusion: seed `Visited` with the current group/cluster so it cannot prove itself.

```cpp
static bool IsHardAnchor(const FNode& Node)
{
    return Node.bGrounded || Node.bStatic || Node.bExternallyPinned;
}

static bool HasBoundedAnchorPath(
    const FNode& Start,
    TConstArrayView<FGuid> CurrentGroupIds,
    const INodeView& View,
    int32 MaxReach)
{
    if (MaxReach <= 0)
    {
        return false;
    }

    TArray<TPair<FIntVector, int32>, TInlineAllocator<32>> Queue;
    TSet<FIntVector, DefaultKeyFuncs<FIntVector>, TInlineSetAllocator<32>> Visited;
    TSet<FGuid> CurrentGroup(CurrentGroupIds);

    Queue.Emplace(Start.Coord, 0);
    Visited.Add(Start.Coord);

    while (!Queue.IsEmpty())
    {
        const TPair<FIntVector, int32> Cur = Queue.Pop(EAllowShrinking::No);
        if (Cur.Value >= MaxReach)
        {
            continue;
        }

        for (const FIntVector& Offset : View.GetNeighborOffsets())
        {
            const FIntVector NextCoord = Cur.Key + Offset;
            if (Visited.Contains(NextCoord))
            {
                continue;
            }
            Visited.Add(NextCoord);

            const FNode* Neighbor = View.FindNode(NextCoord);
            if (!Neighbor || CurrentGroup.Contains(Neighbor->Id))
            {
                continue;
            }

            if (IsHardAnchor(*Neighbor))
            {
                return true;
            }

            Queue.Emplace(NextCoord, Cur.Value + 1);
        }
    }

    return false;
}
```

## Validation

- Test `MaxReach=0`, direct hard anchor, one-hop anchor, max-depth boundary, and cycles with only soft anchors.
- Add temporary `[DIAG-<Tag>]` logs only while proving runtime behavior, then remove them.
- Run the smallest Automation suite that covers the changed subsystem; if the project has no suite, document the manual validation gap.

## Engine Source Anchors

Resolve `<EngineRoot>` from `.uproject` before citing:

- `TAutoConsoleVariable<T>` in `Runtime/Core/Public/HAL/IConsoleManager.h`
- `UDeveloperSettings` in `Developer/DeveloperSettings`
- `FGameplayTag::RequestGameplayTag` in the GameplayTags plugin headers
- `TInlineAllocator` in `Runtime/Core/Public/Containers/ContainerAllocationPolicies.h`
