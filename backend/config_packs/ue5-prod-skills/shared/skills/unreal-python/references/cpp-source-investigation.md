# C++ Source Investigation

Python APIs are generated from reflected C++ and may hide overloads, factories, or editor-only constraints. Use C++ source investigation when Python stubs, docs, or runtime errors are insufficient.

## When To Investigate

- Python API exists but behaves differently than expected.
- Constructor/factory availability is unclear.
- A property or method is missing from Python.
- You need the real parameter type, metadata, or editor/runtime boundary.
- A small C++ bridge may be safer than forcing Python around an API gap.

## Engine Source Resolution

Resolve engine source from the current project:

1. Read `EngineAssociation` from the workspace `.uproject`.
2. Prefer explicit launcher/editor context or `UE_ENGINE_ROOT` / `UNREAL_ENGINE_ROOT` if `Engine/Source` exists.
3. On Windows, check `HKLM:\SOFTWARE\EpicGames\Unreal Engine\<EngineAssociation>` `InstalledDirectory`.
4. For source/custom builds, check `HKCU:\SOFTWARE\Epic Games\Unreal Engine\Builds` and match either the association key or the path version.
5. Fall back to conventional installs only after the above.
6. If `<EngineRoot>/Engine/Source` is unavailable, say so and avoid guessing implementation details.

Treat engine source as read-only.

## Investigation Workflow

```bash
cd "<EngineRoot>/Engine/Source"
rg -n "class .*GameplayTag" -g "*.h"
rg -n "RequestGameplayTag" -g "*.h" -g "*.cpp"
```

Look for:

- `UFUNCTION` / `UPROPERTY` exposure.
- public vs protected/private constructors.
- static factories such as `Create*`, `Make*`, `Request*`, `Find*`.
- editor-only guards and module ownership.
- required headers and Build.cs modules.

## UFUNCTION Exposure

```cpp
UFUNCTION(BlueprintCallable)
void CallableFromBlueprintAndUsuallyPython();

UFUNCTION(BlueprintPure)
int32 QueryValue() const;

void NativeOnlyHelper();
```

Python usually sees reflected Blueprint-callable/pure APIs, not arbitrary native methods.

## C++ Utility Bridge

If C++ has the right primitive but Python does not expose it cleanly, add a small project/plugin utility rather than fragile Python workarounds.

```cpp
UCLASS()
class UMyPythonUtils : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    UFUNCTION(BlueprintCallable, Category="Python Utilities")
    static FGameplayTag RequestTag(FName TagName);
};
```

After compiling, Python can call the reflected static method.

## Common Searches

```bash
rg -n "Create.*|Request.*|Make.*" -g "*.h"
rg -n "UPROPERTY|UFUNCTION" Path/To/Header.h
rg -n "DECLARE_.*Delegate|FSimpleDelegate|FMulticast" -g "*.h"
```

## Best Practices

- Try Python API search first.
- Prefer exact engine source citations over memory.
- Record why a workaround or C++ helper is necessary.
- Add the smallest module dependency needed for the C++ bridge.
