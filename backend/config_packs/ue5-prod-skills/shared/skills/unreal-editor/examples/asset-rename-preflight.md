# Asset Rename And Redirector Preflight

## Use When

- One or more assets must move or rename.
- Redirectors and dependent Blueprint references matter.

## Gate

1. Treat the operation as high risk and confirm exact source/destination package paths.
2. Query source existence, asset class, referencers, source-control state, and destination conflicts.
3. Call `editor.plan_asset_renames` or the maintenance-manifest plan mode.
4. Stop on protected paths, missing sources, duplicate destinations, external referencers, or conflicts.
5. Present the normalized plan and rollback scope before destructive apply when user approval is required.
6. Apply only the confirmed plan. If a plan hash is returned, pass the exact hash required by the apply schema.
7. Read back destination assets, source absence/redirectors, references, and dependent Blueprint compile state.
8. Save only validated intended packages. Never run broad redirector fixup or delete candidates implicitly.
