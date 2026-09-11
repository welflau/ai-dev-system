# Unreal C++ Examples Index

These examples are reusable Unreal C++ task cards. Each card contains:

- when to use it
- a prompt template
- expected files
- minimal C++ skeletons
- build/test gates
- Unreal-specific review checklist

## Core examples

| Example | Main use |
|---|---|
| [actor-component-health.md](./actor-component-health.md) | Actor component lifecycle, delegates, damage state, event-driven gameplay |
| [interactable-interface.md](./interactable-interface.md) | UINTERFACE, interaction component, line trace, Blueprint extension points |
| [dataasset-driven-weapon.md](./dataasset-driven-weapon.md) | DataAsset-driven gameplay config, soft references, weapon component |
| [umg-userwidget.md](./umg-userwidget.md) | C++ UUserWidget, BindWidget, event-driven UI updates |
| [hud-widget-controller.md](./hud-widget-controller.md) | PlayerController-owned HUD creation and gameplay-to-UI bridge |
| [enhanced-input-binding.md](./enhanced-input-binding.md) | Enhanced Input setup from C++ |
| [ai-controller-behavior.md](./ai-controller-behavior.md) | AIController, Blackboard, BehaviorTree bootstrapping |
| [async-timer-lifetime.md](./async-timer-lifetime.md) | Timer/async patterns safe for UObject lifetime |
| [buildcs-dependencies.md](./buildcs-dependencies.md) | Common Build.cs dependency fixes by feature area |
| [automation-test.md](./automation-test.md) | Automation test skeletons and launcher gate |
| [animation-instance-boundary.md](./animation-instance-boundary.md) | AnimInstance ownership and gameplay boundary |
| [commonui-activatable-widget.md](./commonui-activatable-widget.md) | CommonUI activatable widget lifecycle |

## Routing guidance

```text
Gameplay local logic     -> actor component, interface, DataAsset cards
UI / HUD / widgets       -> UMG, HUD controller, CommonUI cards
Input                    -> Enhanced Input card
AI                       -> AIController card
Animation                -> AnimInstance boundary card
Async/timers             -> lifetime card
Build/module failures    -> Build.cs dependency card
Tests                    -> automation test card
```

## Agent usage prompt

```text
Read ../SKILL.md and the matching card.
Adapt the snippet to this project's class names, module names, coding style, and target UE version.
Do not copy blindly. First inspect existing project patterns with rg/git grep.
After edits, use the repository launcher build/test gate and summarize any deviations.
```
