---
name: unreal-python
description: "Unified guide for Unreal Editor Python scripting, API search from unreal.py stubs, visual verification, remote execution, diagnostics, and VS Code debugpy setup. Use when writing UE Python scripts, querying Python API availability, or validating editor automation."
---

# Unreal Python Skill

## Context

- Repository rules: [`AGENTS.md`](../../../AGENTS.md)
- Related skills: [Editor workflows](../unreal-editor/SKILL.md), [UEEditorMCP](../unreal-mcp/SKILL.md), [C++](../unreal-cpp/SKILL.md), [Blueprint/Widget](../unreal-blueprint/SKILL.md), [Material](../unreal-material/SKILL.md), [Niagara](../unreal-niagara/SKILL.md)

Use this skill for Unreal Editor Python scripts, automation probes, API discovery, asset diagnostics, screenshots, PIE capture, or VS Code debugging.

## Local Structure

```text
unreal-python/
  scripts/       CLI tools: api-search, remote-execute, setup-vscode, capture, diagnostics
  lib/           reusable Python libraries
  references/    detailed docs loaded on demand
  examples/      small task examples
  assets/        VS Code launch/task templates
  plugin/        optional ExtraPythonAPIs plugin
```

## Workflow

1. Clarify only blocking requirements; otherwise infer a minimal script and validate it.
2. Search existing project scripts and examples before writing new helpers.
3. Verify API availability with `scripts/api-search.py` against `Intermediate/PythonStub/unreal.py`.
4. For API gaps or ambiguous behavior, read [references/cpp-source-investigation.md](./references/cpp-source-investigation.md).
5. Prefer an existing typed Action or official Toolset over Python. Use Python only when discovery proves a capability gap or the task is explicitly Python authoring.
6. Implement one focused script or probe at a time.
7. Execute through a currently discovered Python-capable Action/Toolset, or use `scripts/remote-execute.py` when its bridge prerequisites are verified. Do not assume an `editor.execute` Action exists.
8. Validate with diagnostics and screenshots/PIE capture when the change has visual or runtime impact.

## Transactions And Asset Safety

Any script that mutates assets should use an editor transaction and explicit dirty/save behavior:

```python
with unreal.ScopedEditorTransaction("Describe the edit"):
    asset.modify()
    asset.set_editor_property("PropertyName", value)
```

Validate asset paths, world context, selected objects, and package writability before mutation. Do not save levels or assets unless the task calls for it or validation requires it.

## API Search

Use [references/api-search.md](./references/api-search.md) for full usage.

```bash
python scripts/api-search.py actor
python scripts/api-search.py unreal.Actor.on_destroyed
python scripts/api-search.py unreal.Actor.*location*
python scripts/api-search.py -c widget
python scripts/api-search.py -m collision
```

The tool auto-detects `Intermediate/PythonStub/unreal.py`; pass `--input` only when needed.

## Visual Verification

Use the capture tools only when the task needs visual proof:

| Scenario | Tool |
|---|---|
| Static scene or level setup | `scripts/orbital-capture.py` |
| Blueprint/asset editor view | `scripts/window-capture.py` |
| Runtime/PIE behavior | `scripts/pie-capture.py` |
| Asset health check | `scripts/asset-diagnostic.py` |

Read [references/capture-scripts.md](./references/capture-scripts.md) and [references/editor-capture.md](./references/editor-capture.md) only when using those tools.

## VS Code Debugging

Use [references/vscode-debugger.md](./references/vscode-debugger.md) when setting up or using F5 debugging.

```bash
python scripts/setup-vscode.py
python scripts/remote-execute.py --file scripts/start_debug_server.py
```

Then attach with the generated debug configuration.

## References

- [Best Practices](./references/best-practices.md)
- [Common Pitfalls](./references/common-pitfals/)
- [Capture Scripts](./references/capture-scripts.md)
- [Editor Capture API](./references/editor-capture.md)
- [Asset Diagnostic](./references/asset-diagnostic.md)
- [ExtraPythonAPIs Plugin](./references/extra-python-apis.md)
- [C++ Source Investigation](./references/cpp-source-investigation.md)
- [API Search](./references/api-search.md)
- [VS Code Debugger](./references/vscode-debugger.md)

## Delivery

Report script path, execution method, validation artifacts, assets touched/saved, and any API limitation or manual editor step left.
