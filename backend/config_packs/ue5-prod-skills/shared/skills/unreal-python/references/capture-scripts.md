# Capture Scripts CLI Reference

Command-line wrappers for the editor_capture and asset_diagnostic modules.

**Location**: `ue5-dev-tools/skills/ue5-python/scripts/`

**Execution**: All scripts are executed via **ue-mcp** using the `editor.execute` tool:
```python
# General pattern
import orbital_capture
orbital_capture.take_orbital_screenshots_with_preset(...)
```

---

## orbital-capture.py

Multi-angle SceneCapture2D screenshots around a target location.

### Parameters

- **target_x, target_y, target_z** (required) - Target point coordinates
  - Example: `"target_x=0,target_y=0,target_z=100"`
  - Alternative: use `target_location` in `X,Y,Z` format: `"target_location=0,0,100"`

- **preset** (optional) - View preset type (default: `orthographic`)
  - Options: `all`, `perspective`, `orthographic`, `birdseye`, `horizontal`, `technical`

- **distance** (optional) - Camera distance from target in UE units (default: `500`)
  - Example: `"distance=800"`

- **resolution** (optional) - Screenshot resolution in `WxH` format (default: `800x600`)
  - Example: `"resolution=1920x1080"`

- **output_dir** (optional) - Output directory path (default: auto-numbered folder)
  - Example: `"output_dir=C:/Screenshots"`

### View Presets

| Preset | Views Included | Count | Use Case |
|--------|----------------|-------|----------|
| orthographic | Front, Back, Left, Right, Top, Bottom | 6 | Technical documentation |
| perspective | Front, Back, Left, Right (at eye level) | 4 | Natural viewing angles |
| birdseye | 4 elevated 45° angles | 4 | Elevated overview |
| all | All of the above | 14 | Comprehensive coverage |
| horizontal | Perspective + Birdseye | 8 | Horizontal emphasis |
| technical | Same as orthographic | 6 | Technical alias |

### Examples

**Basic orthographic capture**:
```python
import unreal, editor_capture
world = unreal.EditorLevelLibrary.get_editor_world()
editor_capture.take_orbital_screenshots_with_preset(
    loaded_world=world,
    target_location=unreal.Vector(0,0,100)
)
```

**All views with custom resolution**:
```python
import unreal, editor_capture
world = unreal.EditorLevelLibrary.get_editor_world()
editor_capture.take_orbital_screenshots_with_preset(
    loaded_world=world,
    target_location=unreal.Vector(0,0,100),
    preset='all',
    resolution_width=1920,
    resolution_height=1080,
    distance=800
)
```

**Perspective views only**:
```python
import unreal, editor_capture
world = unreal.EditorLevelLibrary.get_editor_world()
editor_capture.take_orbital_screenshots_with_preset(
    loaded_world=world,
    target_location=unreal.Vector(500,500,200),
    preset='perspective',
    distance=1000
)
```

**Using target_location format**:
```python
import unreal, editor_capture
world = unreal.EditorLevelLibrary.get_editor_world()
editor_capture.take_orbital_screenshots_with_preset(
    loaded_world=world,
    target_location=unreal.Vector(0,0,100),
    preset='orthographic'
)
```

### Output

Returns a dictionary with view types as keys and lists of file paths as values. Prints summary of total captures and lists all saved files by view type.

---

## pie-capture.py

PIE (Play-In-Editor) runtime screenshot capture with multi-angle support.

### Commands

- **start** - Start PIE capture session
- **stop** - Stop active capture session
- **status** - Check capture status

### Start Command Parameters

- **command** (required) - Set to `"start"`

- **output_dir** (required for start) - Screenshot output directory
  - Example: `"output_dir=C:/Captures"`

- **interval** (optional) - Screenshot interval in seconds (default: `1.0`)
  - Example: `"interval=2.5"`

- **resolution** (optional) - Screenshot resolution in `WxH` format (default: `1920x1080`)
  - Example: `"resolution=1280x720"`

- **multi_angle** (optional) - Enable multi-angle capture (default: `true`)
  - Options: `true`, `false`

- **camera_distance** (optional) - Camera distance for multi-angle views (default: `300`)
  - Example: `"camera_distance=500"`

- **target_height** (optional) - Target height offset (default: `90`)
  - Example: `"target_height=150"`

- **auto_start_pie** (optional) - Auto-start PIE session (default: `false`)
  - Options: `true`, `false`

### Multi-Angle Views

When `multi_angle=true`, captures 4 views per interval:
- Front view
- Side view
- Top view
- 45° Perspective view

### Examples

**Start capture with auto-start PIE**:
```python
import editor_capture
editor_capture.start_pie_capture(
    output_dir='C:/Captures',
    auto_start_pie=True
)
```

**Start with custom interval and single angle**:
```python
import editor_capture
editor_capture.start_pie_capture(
    output_dir='C:/Captures',
    interval_seconds=2.0,
    multi_angle=False
)
```

**Stop active capture**:
```python
import editor_capture
editor_capture.stop_pie_capture()
```

**Check status**:
```python
import editor_capture
print(f"PIE Running: {editor_capture.is_pie_running()}")
print(f"Capturer: {editor_capture.get_pie_capturer()}")
```

### Output

- **start**: Returns capturer object and status (ACTIVE/INACTIVE, PIE RUNNING/NOT RUNNING)
- **stop**: Confirmation message
- **status**: Displays capturer configuration and PIE session state

---

## window-capture.py

Windows API-based window capturing for UE5 editor windows.

**Platform**: Windows only

**Requirement**: Pillow library (`pip install Pillow`)

### Commands

- **window** - Capture UE5 editor window
- **asset** - Open asset editor and capture
- **batch** - Batch capture multiple assets

### Window Command Parameters

- **command** (required) - Set to `"window"`

- **output_file** (required) - Output file path for screenshot
  - Example: `"output_file=C:/Screenshots/editor.png"`

- **tab** (optional) - Tab number to switch to (1-9)
  - Example: `"tab=1"`

### Asset Command Parameters

- **command** (required) - Set to `"asset"`

- **asset_path** (required) - Asset path to open
  - Example: `"asset_path=/Game/Blueprints/BP_Test"`

- **output_file** (required) - Output file path
  - Example: `"output_file=C:/Screenshots/bp.png"`

- **tab** (optional) - Tab number to switch to
  - Example: `"tab=3"` (Event Graph)

### Batch Command Parameters

- **command** (required) - Set to `"batch"`

- **asset_list** (required) - Comma-separated asset paths
  - Example: `"asset_list=/Game/BP1,/Game/BP2,/Game/BP3"`

- **output_dir** (required) - Output directory
  - Example: `"output_dir=C:/Screenshots"`

### Tab Numbers (Blueprint Editor)

- `1` - Viewport
- `2` - Construction Script
- `3` - Event Graph

### Examples

**Capture current editor window**:
```python
import editor_capture
editor_capture.capture_ue5_window('C:/Screenshots/editor.png')
```

**Capture Blueprint viewport tab**:
```python
import editor_capture
hwnd = editor_capture.find_ue5_window()
editor_capture.switch_to_tab(1, hwnd)
editor_capture.capture_ue5_window('C:/Screenshots/viewport.png')
```

**Open asset and capture**:
```python
import editor_capture
editor_capture.open_asset_and_screenshot(
    asset_path='/Game/BP_Test',
    output_path='C:/Screenshots/bp.png'
)
```

**Batch capture multiple assets**:
```python
import editor_capture
editor_capture.batch_asset_screenshots(
    asset_paths=['/Game/BP1', '/Game/BP2'],
    output_dir='C:/Screenshots'
)
```

### Output

- **window**: Success/failure message with file path
- **asset**: Success/failure with asset open and screenshot status
- **batch**: Summary with success count and detailed results per asset

---

## asset-diagnostic.py

Asset and level diagnostics to detect common issues.

### Parameters

- **asset_path** (optional) - Path to asset to diagnose (default: current level)
  - Example: `"asset_path=/Game/Maps/TestLevel"`

- **asset_type** (optional) - Override asset type detection
  - Options: `Level`, `Blueprint`, `SkeletalMesh`, `StaticMesh`
  - Example: `"asset_type=Blueprint"`

- **verbose** (optional) - Enable detailed diagnostic output (default: `false`)
  - Options: `true`, `false`

### Supported Asset Types

- **Level** - Map/World assets with actor diagnostics
- **Blueprint** - Blueprint class diagnostics
- **SkeletalMesh** - Skeletal mesh bounds and animation diagnostics
- **StaticMesh** - Static mesh diagnostics

### Examples

**Diagnose current level**:
```python
import asset_diagnostic
asset_diagnostic.diagnose_current_level()
```

**Diagnose specific level with verbose output**:
```python
import asset_diagnostic
asset_diagnostic.diagnose('/Game/Maps/TestLevel', verbose=True)
```

**Diagnose Blueprint**:
```python
import asset_diagnostic
asset_diagnostic.diagnose('/Game/Blueprints/BP_MyActor')
```

**Diagnose skeletal mesh**:
```python
import asset_diagnostic
asset_diagnostic.diagnose('/Game/Characters/SK_Character', verbose=True)
```

### Output

Diagnostic results with error and warning counts:
```
Asset Diagnostic Results for /Game/Maps/TestLevel
==================================================
Status: PASS (no issues found)
```

Or with issues:
```
Status: ISSUES FOUND
Errors: 2
Warnings: 3

[Detailed issue information...]
```

Exit code 1 if errors found, 0 if successful.

---

## Common Patterns

### Parameter Syntax

All scripts use key=value pairs separated by commas:
```bash
--args "param1=value1,param2=value2,param3=value3"
```

### Coordinate Format

For target coordinates, use separate X, Y, Z parameters:
```bash
"target_x=100,target_y=200,target_z=300"
```

Or use combined format:
```bash
"target_location=100,200,300"
```

### Boolean Values

Use `true` or `false` (lowercase):
```bash
"verbose=true,auto_start_pie=false"
```

### Resolution Format

Use `WIDTHxHEIGHT` format:
```bash
"resolution=1920x1080"
```

### File Paths

Use absolute paths with forward slashes:
```bash
"output_file=C:/Screenshots/test.png"
```

---

## Troubleshooting

### Script Not Found

Ensure the script or module is available in your workspace.
```python
import editor_capture
# or
import asset_diagnostic
```

### Parameter Parsing Errors

- Check for proper comma separation
- Ensure no spaces around `=` signs
- Use quotes around the entire args string

### PIE Capture Issues

- Ensure PIE is running or use `auto_start_pie=true`
- Check that output directory exists and is writable
- Stop any existing capture before starting a new one

### Window Capture Issues (Windows)

- Ensure Pillow is installed: `pip install Pillow`
- Verify UE5 editor window is open
- Check that window title matches expected pattern
