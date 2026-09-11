# Example: C++ Automation Test Skeleton

## Use when

- Adding deterministic tests for pure gameplay logic.
- Creating a gate for the agent repair loop.
- Testing small systems without opening the full editor UI.

## Agent prompt template

```text
Add an Unreal automation test for the changed gameplay behavior.
Keep the test deterministic and narrow.
Place it in the project's existing Tests folder or module convention.
Run the discovered suite through `launcher_run_automation` and report the terminal result.
```

## Simple automation test skeleton

```cpp
#if WITH_DEV_AUTOMATION_TESTS

#include "Misc/AutomationTest.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(
    FHealthClampAutomationTest,
    "Project.Gameplay.Health.ClampsToRange",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FHealthClampAutomationTest::RunTest(const FString& Parameters)
{
    const float MaxHealth = 100.0f;
    const float Damage = 250.0f;
    const float Result = FMath::Clamp(MaxHealth - Damage, 0.0f, MaxHealth);

    TestEqual(TEXT("Health clamps to zero"), Result, 0.0f);
    return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
```

## Launcher gate

```text
launcher_run_automation(
  project_root_hint=<discovered project root>,
  suite=<discovered exact test filter>,
  build=true)
-> poll launcher_task_status(task_id) to a terminal state
```

Do not run a raw commandlet or read Automation Reports directly. Use the launcher result and MCP log service required by `AGENTS.md`.

## Review checklist

- Test name is stable and namespaced.
- Test does not require nondeterministic editor state.
- Test does not mutate production content unless isolated.
- For UObject tests, create objects with valid outer/world context if required.
- For network tests, prefer dedicated functional tests or project-specific harness.
