# Example: Module Build.cs Dependencies by Feature Area

## Use when

- Build errors mention missing headers, unresolved externals, or module visibility.
- Adding UMG, Enhanced Input, AI, GAS, Networking, Slate, Editor tools, or AssetRegistry usage.
- Agent needs to fix dependencies without hacking include paths.

## Agent prompt template

```text
Fix Unreal module dependencies correctly.
Do not add arbitrary include paths as a first resort.
Inspect which module owns the type/header and add the minimal Public/Private dependency.
Run the Editor target build through the repository launcher and explain why each dependency is needed.
```

## Common dependency map

```csharp
// Core gameplay module baseline
PublicDependencyModuleNames.AddRange(new[] {
    "Core", "CoreUObject", "Engine", "InputCore"
});

// UMG / widgets
PrivateDependencyModuleNames.AddRange(new[] {
    "UMG", "Slate", "SlateCore"
});

// Enhanced Input
PrivateDependencyModuleNames.AddRange(new[] {
    "EnhancedInput"
});

// AI / Behavior Tree / EQS / GameplayTasks
PrivateDependencyModuleNames.AddRange(new[] {
    "AIModule", "GameplayTasks", "NavigationSystem"
});

// Gameplay Ability System
PublicDependencyModuleNames.AddRange(new[] {
    "GameplayAbilities", "GameplayTags", "GameplayTasks"
});

// Networking helpers are usually in Engine/NetCore depending on feature
PrivateDependencyModuleNames.AddRange(new[] {
    "NetCore"
});

// Editor-only module example
PrivateDependencyModuleNames.AddRange(new[] {
    "UnrealEd", "Blutility", "EditorSubsystem", "AssetRegistry"
});
```

## Public vs Private rule of thumb

```text
Public dependency:
  A type from that module appears in this module's public headers.

Private dependency:
  A type from that module is used only in .cpp files or private headers.
```

## Review checklist

- No dependency was added “just in case.”
- Public dependencies are used only when public headers require them.
- Editor-only dependencies are not added to runtime modules.
- `*.Build.cs` changes are explained in the final response.
- Include path hacks are avoided unless the project already requires them.
