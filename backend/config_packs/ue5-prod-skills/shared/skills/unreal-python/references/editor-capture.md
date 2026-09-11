# Editor Capture Module API Reference

## Usage via Python API

You can use the `editor_capture` submodules directly via **ue-mcp**'s `editor.execute()` tool:

```python
import editor_capture
# Use submodules: editor_capture.orbital, editor_capture.asset_editor, etc.
```

## Advanced: Module API

Screenshot capture and editor automation toolkit for UE5.

**Location:** `site-packages/editor_capture/`

This section documents the underlying Python modules for users who need to integrate capture functionality into custom scripts.

## Overview

The `editor_capture` module provides three submodules for different capture and automation scenarios:

| Module | Purpose | Platform |
|--------|---------|----------|
| `orbital` | Multi-angle SceneCapture2D screenshots | Cross-platform |
| `asset_editor` | Asset editor operations | Cross-platform |
| `window_capture` | Window capture via Windows API | Windows only |

## Quick Start

### Orbital Screenshots

Capture multi-angle screenshots around a target location using SceneCapture2D:

```python
import unreal
from editor_capture import orbital

world = unreal.EditorLevelLibrary.get_editor_world()
results = orbital.take_orbital_screenshots(
    world,
    target_location=unreal.Vector(0, 0, 100),
    distance=500.0
)
print(f'Captured {sum(len(v) for v in results.values())} screenshots')
```

Temporary actors (grid, gizmo, capture actors) are automatically cleaned up via transaction undo. Set `auto_cleanup=False` to keep them.

### Asset Editor Operations

Open/close asset editors programmatically:

```python
from editor_capture import asset_editor

# Open a Blueprint editor
asset_editor.open_asset_editor('/Game/Blueprints/BP_MyActor')

# Close a specific editor
asset_editor.close_asset_editor('/Game/Blueprints/BP_MyActor')

# Close all open editors
asset_editor.close_all_asset_editors()
```

### Window Capture (Windows only)

Capture UE5 editor window screenshots:

```python
from editor_capture import window_capture

# Capture the UE5 editor window
window_capture.capture_ue5_window('C:/Screenshots/editor.png')
```

## API Reference

### orbital Module

#### View Configurations

```python
PERSPECTIVE_VIEWS  # 4 horizontal views: front, left, right, back
ORTHOGRAPHIC_VIEWS # 6 orthographic views: front, back, left, right, top, bottom
BIRDSEYE_VIEWS     # 4 elevated views at 45-degree angle
VIEW_PRESETS       # Preset configurations: all, perspective, orthographic, birdseye, horizontal, technical
```

#### Main Functions

```python
take_orbital_screenshots(
    loaded_world,
    target_location=None,        # unreal.Vector, default: origin
    distance=500.0,              # Distance from target
    output_dir=None,             # Default: Saved/Screenshots/Orbital
    folder_prefix="capture",
    resolution_width=800,
    resolution_height=600,
    enable_perspective_views=True,
    enable_orthographic_views=True,
    enable_birdseye_views=True,
    ortho_width=600.0,
    enable_grid=True,            # Spawn reference grid
    grid_size=500.0,
    grid_divisions=10,
    enable_gizmo=True,           # Spawn axis indicator
    gizmo_size=80.0,
    organize_by_type=True,       # Create subfolders by view type
    auto_cleanup=True            # Auto-remove temporary actors after capture
)
# Returns: dict with keys "perspective", "orthographic", "birdseye" containing file paths

take_orbital_screenshots_with_preset(
    loaded_world,
    preset="orthographic",       # "all", "perspective", "orthographic", "birdseye", "horizontal", "technical"
    auto_cleanup=True,           # Auto-remove temporary actors after capture
    # ... same parameters as above
)
```

#### Utility Functions

```python
calculate_camera_transform(target, yaw_deg, pitch_deg, distance)
# Returns: (camera_location, camera_rotation)

spawn_reference_grid(actor_subsystem, target_location, grid_size=500.0, divisions=10)
# Returns: list of grid actors for cleanup

spawn_axis_gizmo(actor_subsystem, target_location, arrow_length=80.0)
# Returns: list of gizmo actors for cleanup

capture_single_view(actor_subsystem, loaded_world, camera_location, camera_rotation, ...)
# Returns: str (saved file path) or None

get_next_capture_folder(base_dir, folder_prefix)
# Returns: str (path to new numbered folder)
```

### asset_editor Module

```python
open_asset_editor(asset_path)
# Opens editor for any asset type
# Returns: bool

open_blueprint_editor(blueprint_path)
# Opens Blueprint editor (validates asset is Blueprint)
# Returns: bool

open_multiple_asset_editors(asset_paths)
# Opens multiple asset editors at once
# Returns: {"success": [paths], "failed": [paths]}

close_asset_editor(asset_path)
# Closes editor for specific asset
# Returns: bool

close_all_asset_editors()
# Closes all open asset editors
# Returns: bool

load_asset(asset_path, expected_type=None)
# Load and optionally validate asset type
# Returns: asset or None

asset_exists(asset_path)
# Check if asset exists
# Returns: bool
```

### window_capture Module (Windows only)

Requires: `pip install Pillow`

#### Window Management

```python
find_ue5_window()
# Find UE5 editor window by process ID
# Returns: hwnd (int) or None

set_foreground_window(hwnd)
# Bring window to foreground
# Returns: bool

get_foreground_window()
# Get current foreground window
# Returns: hwnd (int)
```

#### Input Simulation

```python
switch_to_tab(tab_number=1, hwnd=None)
# Switch Blueprint editor tab using Ctrl+Shift+Alt+<number>
# tab_number: 1-9 (1=Viewport, 2=Construction Script, 3=Event Graph, etc.)
# Returns: bool

switch_to_viewport_tab(hwnd=None)
# Convenience wrapper for switch_to_tab(1)
# Returns: bool

click_window_center(hwnd=None)
# Click center of window to ensure focus
# Returns: bool
```

#### Screenshot Functions

```python
capture_window(hwnd, crop_titlebar=True)
# Capture window using PrintWindow API (works for background windows)
# Returns: PIL Image or None

capture_ue5_window(output_path, crop_titlebar=True)
# Capture UE5 editor window to file
# Returns: bool
```

#### Combined Functions

```python
open_asset_and_screenshot(asset_path, output_path, delay=3.0, tab_number=None, crop_titlebar=True)
# Open asset editor, wait, optionally switch tab, capture screenshot
# Returns: {"opened": bool, "screenshot": bool, "screenshot_path": str}

batch_asset_screenshots(asset_paths, output_dir, delay=3.0, tab_number=None, close_after=True)
# Screenshot multiple assets in sequence
# Returns: {"success": [(path, screenshot_path)], "failed": [path]}
```

## Common Use Cases

### Capture orthographic views for model QA

```python
import unreal
from editor_capture import orbital

world = unreal.EditorLevelLibrary.get_editor_world()

# Find actor to capture
actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.StaticMeshActor)
target_actor = next((a for a in actors if 'MyModel' in a.get_actor_label()), None)

if target_actor:
    results = orbital.take_orbital_screenshots_with_preset(
        world,
        preset='orthographic',  # Only orthographic views
        target_location=target_actor.get_actor_location(),
        distance=300.0,
        enable_grid=False,
        enable_gizmo=True
    )
    print(f'Saved to: {results}')
```

### Screenshot multiple Blueprint viewports

```python
from editor_capture import window_capture
import os

blueprints = [
    '/Game/Blueprints/BP_Character',
    '/Game/Blueprints/BP_Weapon',
    '/Game/Blueprints/BP_Vehicle',
]

output_dir = 'C:/Screenshots/Blueprints'
results = window_capture.batch_asset_screenshots(
    blueprints,
    output_dir,
    delay=2.0,
    tab_number=1,  # Viewport tab
    close_after=True
)

print(f'Success: {len(results["success"])}, Failed: {len(results["failed"])}')
```

### Capture Event Graph of a Blueprint

```python
from editor_capture import window_capture, asset_editor
import time

blueprint_path = '/Game/Blueprints/BP_MyActor'
output_path = 'C:/Screenshots/event_graph.png'

# Open the Blueprint
asset_editor.open_asset_editor(blueprint_path)
time.sleep(2.0)

# Switch to Event Graph tab (typically tab 3)
window_capture.switch_to_tab(3)
time.sleep(0.5)

# Capture screenshot
window_capture.capture_ue5_window(output_path)

# Close editor
asset_editor.close_asset_editor(blueprint_path)
```

## Output Structure

Orbital screenshots are organized by default into subfolders:

```
Saved/Screenshots/Orbital/capture_1/
    perspective/
        front.png
        left.png
        right.png
        back.png
    orthographic/
        ortho_front.png
        ortho_back.png
        ortho_left.png
        ortho_right.png
        ortho_top.png
        ortho_bottom.png
    birdseye/
        birdseye_front.png
        birdseye_left.png
        birdseye_right.png
        birdseye_back.png
```

## Notes

- **Auto cleanup**: Orbital capture spawns temporary actors (grid, gizmo, capture actors) and automatically removes them via transaction undo when `auto_cleanup=True` (default). Set `auto_cleanup=False` to keep temporary actors for debugging.
- **Windows-only**: The `window_capture` module uses Windows API and only works on Windows.
- **Pillow dependency**: `window_capture` requires Pillow (`pip install Pillow`).
- **Tab numbers**: Blueprint editor tabs are numbered 1-9. Common mappings: 1=Viewport, 2=Construction Script, 3=Event Graph (may vary by asset type).
