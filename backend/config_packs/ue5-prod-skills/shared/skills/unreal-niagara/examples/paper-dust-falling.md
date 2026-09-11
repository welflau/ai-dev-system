# Example: Paper Dust / Falling Debris Tuning

Load this example only when the user asks for paper scraps, falling debris, floating dust, broad area emission, or collision/settling behavior.

## Goal

Create a scene-wide paper-dust feel: many small scraps drift through the scene like airborne dust, slowly fall, collide with the ground, and settle without obvious popping.

## Recommended source template

Start from a working multi-stage system instead of building from zero. Prefer a local template that already contains a balanced multi-stage update stack and a working `Collision -> SolveForcesAndVelocity` relationship.

## Safe creation pattern

```json
{"action_id":"niagara.create_system","params":{"name":"NS_OfficePaperDebris_Physics","path":"/Game/FX","template_system_path":"/Game/FX/Templates/NS_WorkingFallingDebrisTemplate.NS_WorkingFallingDebrisTemplate","if_exists":"overwrite"}}
```

Then tune existing modules only. Do not add a second `Collision` module.

## Starting values

| Area | Module / input | Value |
|------|----------------|-------|
| Renderer | Mesh scale | `0.5` |
| Spawn area | `ShapeLocation.Box Size` | `(200, 200, 5)` |
| Extra spawn shape | `ShapeLocation001` | Disable if it creates unwanted spherical emission |
| Initial motion | `AddVelocity.Velocity` | `(0, 0, -3)` |
| Gravity | `GravityForce.Gravity` | `(0, 0, -15)` |
| Gravity | `GravityForce001.Gravity` | `(0, 0, -15)` |
| Wind | `WindForce.Wind Speed` | `(20, 20, 10)` |
| Wind | `WindForce001.Wind Speed` | `(-15, 10, 5)` |
| Wind | `WindForce002.Wind Speed` | `(8, -12, 3)` |
| Noise | `CurlNoiseForce` / `CurlNoiseForce001` | Keep template defaults enabled |
| Lifetime | `ParticleState.Lifetime` | `15.0` |
| Collision | `Collision.Enable Rest State` | `true` |
| Collision | `Collision.Restitution` | `0.02` |
| Collision | `Collision.Friction` | `0.8` |
| Collision | `Collision.Particle Radius Scale` | `3.0` |

## Important lessons

- Prefer tuning Wind/Gravity/Drag values over disabling force modules. Disabling modules in multi-stage systems can cause flicker, popping, or unbalanced solver behavior.
- If particles appear from a single point, inspect all `ShapeLocation` modules. Set the box shape size and disable redundant shape modules only after confirming their role.
- If collision does not work, verify `SimTarget`, collision type/channel, duplicate Collision modules, and `Collision -> SolveForcesAndVelocity` ordering.
- For GPU collision, use `niagara.set_module_static_int` on `GPU Collision Type`. Use `depth_buffer` unless distance fields are enabled.

## Minimal batch shape-area edit

```json
{
  "actions": [
    {"action_id":"niagara.set_module_input","params":{"system_path":"/Game/FX/NS_OfficePaperDebris_Physics.NS_OfficePaperDebris_Physics","emitter_name":"HangingParticulates","stage":"particle_spawn","module_name":"ShapeLocation","input_name":"Box Size","value_type":"vec3","value":[200,200,5]}},
    {"action_id":"niagara.set_module_enabled","params":{"system_path":"/Game/FX/NS_OfficePaperDebris_Physics.NS_OfficePaperDebris_Physics","emitter_name":"HangingParticulates","stage":"particle_spawn","module_name":"ShapeLocation001","enabled":false}},
    {"action_id":"niagara.get_compile_diagnostics","params":{"asset_path":"/Game/FX/NS_OfficePaperDebris_Physics.NS_OfficePaperDebris_Physics","refresh_compile":true,"wait":true,"min_severity":"warning"}},
    {"action_id":"editor.save_all","params":{}}
  ],
  "result_verbosity":"compact"
}
```
