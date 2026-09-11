# Cursor-Based Log Diagnosis

## Pattern

1. Query `unreal.logs.get(mode="auto", tailLines=<bounded>, filter={category/contains/minVerbosity})`.
2. Retain the returned cursor before reproducing the behavior.
3. Reproduce once through the smallest editor/PIE/automation path.
4. Query again with the cursor and the same narrow filter to receive only new evidence.
5. Widen category, verbosity, lines, or bytes only when the first query cannot discriminate the cause.

Use `ue_logs_tail` when connected live ring-buffer or Python bridge logs are specifically required; its schema uses `n`, `source`, `category`, and `min_verbosity`. Never mix these parameter names or raw-read `Saved/Logs`.
