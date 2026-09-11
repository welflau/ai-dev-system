# Non-Atomic Batch And Readback

## Pattern

Use `ue_batch` when several typed Actions form one bounded operation and one TCP round-trip is useful.

```json
{
  "actions": [
    {"action_id": "<create-action>", "params": {"name": "<explicit-name>"}},
    {"action_id": "<dependent-action>", "params": {"target": {"$ref": "steps[0].asset_path"}}}
  ],
  "continue_on_error": false,
  "result_verbosity": "compact"
}
```

## Gate

1. Validate both schemas and the expected first-step result field.
2. Use `continue_on_error=false` when the dependent step is invalid or dangerous after failure.
3. Inspect top-level `has_failures`, failed count, `failures[]`, and each required step result.
4. Remember that successful earlier steps are not rolled back.
5. Query the final target through an independent read Action, then compile/validate and save only the explicit package.
