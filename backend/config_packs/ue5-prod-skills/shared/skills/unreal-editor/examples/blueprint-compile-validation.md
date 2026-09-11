# Blueprint Compile Validation

## Use When

- C++ reflection or Blueprint-visible APIs changed.
- A Blueprint, Widget Blueprint, or graph was edited.
- A stale generated class or binding is suspected.

## Gate

1. Confirm the exact Blueprint path and call `blueprint.describe_full` before mutation.
2. Record parent/generated class, relevant components, variables, graphs, nodes/pins, and current compile state.
3. Apply one scoped change through the matching typed Action.
4. Compile with `blueprint.compile` and inspect the structured result.
5. On failure, query filtered Blueprint/Class/Linker logs; do not continue graph mutation against stale IDs.
6. On success, describe the touched graph or Blueprint again and compare the requested state.
7. Save only that package with `editor.save_loaded_asset`.

Success requires compile success plus structural readback. A successful mutation response alone is insufficient.
