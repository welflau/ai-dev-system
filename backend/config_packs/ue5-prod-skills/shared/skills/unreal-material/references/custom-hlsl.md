# Material Custom HLSL Reference

Read this only for Material `Custom` node tasks.

## Choose A Pipeline First

| Pipeline | Use when | Requirements |
|---|---|---|
| Math-only | No texture or scene sampling is needed | Inputs are graph values; no sampling calls |
| Surface + TextureObject | Regular texture sampling in a surface material | TextureObject input wired into Custom |
| Surface translucent + scene color | Distortion/frosted glass style effects | Translucent surface material and scene color support |
| Post-process + PostProcessInput0 | Screen-space blur/sharpen/CRT/glow | PostProcess domain and SceneTexture input |
| Post-process + TextureObject | Screen effect plus LUT/noise/mask texture | PostProcess domain plus TextureObject input |

Do not switch pipelines silently when the user explicitly asks for sampling inside Custom HLSL.

## Math-Only Prompt Shape

```text
You are an Unreal Engine material/HLSL engineer.

Goal:
Generate compilable HLSL for an Unreal Material Custom node to implement: [EFFECT].

Hard requirements:
1. Do not sample textures or scene textures inside the Custom node.
2. Use only inputs passed from the material graph.
3. Use a small struct wrapper with Core(...) and Out(...).
4. Keep input names case-sensitive and aligned with Unreal Custom node pins.
5. State the required Custom node Output Type.

Output:
1. Paste-ready HLSL code.
2. Output Type.
3. Inputs table: name, type, purpose, default, graph connection.
```

## Sampling Prompt Shape

```text
You are an Unreal Engine material/HLSL engineer.

Goal:
Generate compilable HLSL for an Unreal Material Custom node to implement: [EFFECT] with sampling.

Hard requirements:
1. Choose exactly one pipeline: Surface+TextureObject, Surface translucent+SceneColor, PostProcess+PostProcessInput0, or PostProcess+TextureObject.
2. Keep sampling statements flattened in main scope; avoid helper/member functions for sampling.
3. Use fixed, countable taps where possible, preferably 16 or fewer.
4. Reuse sampled values and avoid duplicate center sampling.
5. State all graph-side prerequisite nodes and material domain/blend requirements.

Output:
1. Paste-ready HLSL code.
2. Output Type.
3. Inputs table.
4. Sampling budget: center sample, tap count, total samples per pixel.
```

## Stability Rules

- Dependency injection matters: if scene texture helpers are missing, add required graph-side SceneTexture/SceneColor nodes before compiling.
- For post-process scene sampling, validate the current engine's SceneTexture ID / helper usage instead of assuming an old constant.
- Match Custom node input names exactly. HLSL is case-sensitive.
- Compile before delivery and inspect structured material diagnostics.

## Delivery Addendum

For Custom-node tasks, report the chosen pipeline, added prerequisite nodes, Custom output type, input pins, sampling budget, compile result, and any engine-version uncertainty.
