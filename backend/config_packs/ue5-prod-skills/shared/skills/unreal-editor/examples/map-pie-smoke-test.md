# Map And PIE Smoke Test

## Use When

- Behavior depends on world initialization, actors, components, input, UI, or replication.
- A visual or interactive editor check is part of acceptance.

## Gate

1. Require an interactive launcher-managed editor and confirm bridge readiness.
2. Query current map and `editor.get_pie_state`; do not switch maps during PIE.
3. Open the explicit target map only when needed and read back the current world.
4. Start PIE with `editor.start_pie` using the required mode, net mode, and player count from its current schema.
5. Poll `editor.get_pie_state` until running before runtime assertions.
6. Verify target actor/component/UI state through typed queries and filtered logs. Capture a screenshot only for visual acceptance.
7. Stop PIE cleanly, poll to stopped, and check relevant error/warning categories.
8. Do not save the map unless this task intentionally changed and validated it.

For deterministic Automation suites, use the launcher task flow instead of console-command test execution.
