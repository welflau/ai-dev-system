# UE5 Python Best Practices

Essential patterns and guidelines for writing reliable UE5 Editor Python scripts.

## Debug Visualization

**[Critical]** When writing scripts that create or modify visual elements, include debug visualization to enable precise visual verification.

### What to Visualize

- Object/character world coordinates (X, Y, Z)
- Mesh bounding box dimensions (width, height, depth)
- Distances between key objects
- Facing directions and orientations
- Attachment points and socket locations

### Implementation

```python
import unreal

# Draw debug text at actor location
unreal.SystemLibrary.draw_debug_string(
    world,
    actor.get_actor_location(),
    f"Pos: {actor.get_actor_location()}",
    text_color=unreal.LinearColor(1, 1, 0, 1),  # Yellow
    duration=0.0  # Persistent
)

# Draw debug box showing mesh bounds
bounds_origin, bounds_extent = mesh_component.get_local_bounds()
unreal.SystemLibrary.draw_debug_box(
    world,
    bounds_origin,
    bounds_extent,
    unreal.LinearColor(0, 1, 0, 1),  # Green
    duration=0.0
)

# Draw debug line showing distance between objects
unreal.SystemLibrary.draw_debug_line(
    world,
    actor_a.get_actor_location(),
    actor_b.get_actor_location(),
    unreal.LinearColor(1, 0, 0, 1),  # Red
    duration=0.0
)
```

**Why?** Screenshots with debug overlays make visual verification precise - you can confirm exact positions, sizes, and relationships rather than eyeballing.

---

## Core Interaction Patterns

### 1. Use Subsystems Instead of Static Libraries

In UE4, we frequently used static function libraries such as `EditorAssetLibrary`. In UE5, Epic recommends using **Subsystems** - their lifecycle management is clearer and more aligned with object-oriented design.

- **Recommended:** `unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)`
- **Example:** Use `EditorActorSubsystem` instead of legacy LevelLibrary

```python
import unreal

# Recommended: Get subsystem instance
actor_subsystem = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
selected_actors = actor_subsystem.get_selected_level_actors()
```

### 2. Must Handle Undo/Redo (Transaction Management)

If your script modifies the scene or assets without creating a Transaction, the user's `Ctrl+Z` will be ineffective. Always use `unreal.ScopedEditorTransaction`:

```python
# Wrap all modification operations in a with statement
with unreal.ScopedEditorTransaction("My Python Batch Rename"):
    for actor in selected_actors:
        actor.set_actor_label(f"Prefix_{actor.get_actor_label()}")
    # Users can now undo the entire loop's modifications with Ctrl+Z
```

### 3. Use Asset Registry for Efficient Queries

Do not iterate through the Content directory and `load_asset` to find files - this is extremely slow. The **Asset Registry** is an in-memory database that stores metadata without loading files.

```python
asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()

# Set up filter to find specific assets
filter = unreal.ARFilter(
    class_names=["MaterialInstanceConstant"],
    recursive_paths=True,
    package_paths=["/Game/Characters"]
)

# Get only metadata (AssetData) without loading actual assets
asset_data_list = asset_registry.get_assets(filter)

for data in asset_data_list:
    print(data.package_name)  # Extremely fast
    # Only load the asset when modification is necessary
    # asset = data.get_asset()
```

### 4. Asset Loading vs Finding

Choose the right method for your use case:

| Method | Purpose | Performance |
|--------|---------|-------------|
| `load_asset(path)` | Load asset into memory for processing | Slow |
| `find_asset(path)` | Quick check if asset exists | Fast |
| `list_assets(directory)` | List asset paths without loading | Fast |

**Recommended workflow:**

1. Use `list_assets()` to get paths
2. Use `find_asset()` to verify existence if needed
3. Only `load_asset()` when you need to modify the asset

---

## Additional Guidelines

| Guideline | Description |
|-----------|-------------|
| **Don't over-handle errors** | Let exceptions propagate; fail loudly not silently |
| **Report results clearly** | Track success/failure counts; log meaningful progress |
| **Verify visual results** | Use screenshot verification for visual/gameplay changes |
| **Use ASCII-only output** | For cross-platform compatibility, use `[OK]`, `[ERROR]` instead of emojis |
