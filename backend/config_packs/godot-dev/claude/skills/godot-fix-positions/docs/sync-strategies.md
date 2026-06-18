# Position Sync Strategies

Detailed procedures for synchronizing positions between editor (.tscn) and code (.gd).

---

## Strategy Selection

### Decision Tree

```
Position conflict detected
    ↓
Is it in _process or _physics_process?
    ↓ YES → CRITICAL WARNING (don't sync, warn user)
    ↓ NO
Is it camera/player following?
    ↓ YES → CAMERA_AWARE strategy
    ↓ NO
Is it animation/tween?
    ↓ YES → SKIP (intentional)
    ↓ NO
Is code position the intended final position?
    ↓ YES → CODE_TO_EDITOR strategy
    ↓ NO → EDITOR_TO_CODE strategy
```

---

## Strategy A: Code → Editor Sync

**Purpose**: Move position from code to .tscn, editor becomes source of truth

### When to Use

- Code sets static position once in `_ready()`
- Position never changes after initialization
- Editor should show final runtime position
- WYSIWYG is critical for this node

### Implementation Steps

#### Step 1: Extract Code Position

```python
def extract_code_position(script_path):
    """Find position assignment in _ready() method."""
    with open(script_path) as f:
        lines = f.readlines()

    in_ready = False
    for i, line in enumerate(lines):
        if 'func _ready(' in line:
            in_ready = True
        elif in_ready and line.startswith('func '):
            # Exited _ready function
            break
        elif in_ready and 'position = Vector2(' in line:
            # Extract position
            match = re.search(r'Vector2\s*\(\s*([0-9.+-]+)\s*,\s*([0-9.+-]+)\s*\)', line)
            if match:
                return {
                    'line_number': i + 1,
                    'position': (float(match.group(1)), float(match.group(2))),
                    'original_line': line.strip()
                }

    return None
```

#### Step 2: Update .tscn File

```python
def update_tscn_position(tscn_path, new_position, node_name=None):
    """Update position in .tscn file."""
    with open(tscn_path) as f:
        lines = f.readlines()

    updated_lines = []
    in_target_node = False
    position_updated = False

    for i, line in enumerate(lines):
        # Detect target node
        if node_name:
            if f'[node name="{node_name}"' in line:
                in_target_node = True
        else:
            # Root node
            if line.startswith('[node name="') and not in_target_node:
                in_target_node = True

        # Update position line
        if in_target_node and line.startswith('position ='):
            updated_lines.append(f'position = Vector2({new_position[0]}, {new_position[1]})\n')
            position_updated = True
        # Add position if node doesn't have it
        elif in_target_node and not position_updated and (line.startswith('[node') or line.startswith('[connection')):
            # Insert position before next section
            updated_lines.append(f'position = Vector2({new_position[0]}, {new_position[1]})\n')
            updated_lines.append(line)
            position_updated = True
        else:
            updated_lines.append(line)

        # Stop at next node
        if in_target_node and i > 0 and line.startswith('[node'):
            in_target_node = False

    # Write back
    with open(tscn_path, 'w') as f:
        f.writelines(updated_lines)

    return position_updated
```

#### Step 3: Remove Code Assignment

```python
def remove_code_position(script_path, line_number):
    """Remove position assignment from script, add comment."""
    with open(script_path) as f:
        lines = f.readlines()

    # Get original line for comment
    original_line = lines[line_number - 1].strip()

    # Replace with comment
    indent = len(lines[line_number - 1]) - len(lines[line_number - 1].lstrip())
    comment = ' ' * indent + f'# Position moved to .tscn for editor visibility\n'
    comment += ' ' * indent + f'# Was: {original_line}\n'

    lines[line_number - 1] = comment

    # Write back
    with open(script_path, 'w') as f:
        f.writelines(lines)
```

#### Step 4: Complete Example

**Before:**

enemy.gd:
```gdscript
extends CharacterBody2D

func _ready():
    position = Vector2(100, 150)
    health = 100
```

enemy.tscn:
```ini
[node name="Enemy" type="CharacterBody2D"]
position = Vector2(500, 300)
```

**After:**

enemy.gd:
```gdscript
extends CharacterBody2D

func _ready():
    # Position moved to .tscn for editor visibility
    # Was: position = Vector2(100, 150)
    health = 100
```

enemy.tscn:
```ini
[node name="Enemy" type="CharacterBody2D"]
position = Vector2(100, 150)
```

---

## Strategy B: Editor → Code Sync

**Purpose**: Keep code position, reset editor to default

### When to Use

- Position is calculated/dynamic
- Code is source of truth
- Editor position is arbitrary/wrong
- Runtime position determined by logic

### Implementation Steps

#### Step 1: Reset .tscn to Default

```python
def reset_tscn_position(tscn_path, node_name=None):
    """Remove or reset position in .tscn to Vector2(0, 0)."""
    with open(tscn_path) as f:
        lines = f.readlines()

    updated_lines = []
    in_target_node = False

    for line in lines:
        # Detect target node
        if node_name:
            if f'[node name="{node_name}"' in line:
                in_target_node = True
        else:
            if line.startswith('[node name="') and not in_target_node:
                in_target_node = True

        # Skip position line
        if in_target_node and line.startswith('position ='):
            continue  # Remove position line
        else:
            updated_lines.append(line)

        # Stop at next node
        if in_target_node and line.startswith('[node') and len(updated_lines) > 1:
            in_target_node = False

    # Write back
    with open(tscn_path, 'w') as f:
        f.writelines(updated_lines)
```

#### Step 2: Document Code Position

```python
def document_code_position(script_path, line_number):
    """Add documentation comment above position assignment."""
    with open(script_path) as f:
        lines = f.readlines()

    # Add comment above assignment
    indent = len(lines[line_number - 1]) - len(lines[line_number - 1].lstrip())
    comment = ' ' * indent + '# Position set in code (not in .tscn)\n'
    comment += ' ' * indent + '# Editor shows default (0,0), runtime shows calculated position\n'

    lines.insert(line_number - 1, comment)

    # Write back
    with open(script_path, 'w') as f:
        f.writelines(lines)
```

#### Step 3: Complete Example

**Before:**

spawner.gd:
```gdscript
func _ready():
    position = calculate_spawn_position()
```

spawner.tscn:
```ini
[node name="Spawner" type="Node2D"]
position = Vector2(123, 456)
```

**After:**

spawner.gd:
```gdscript
func _ready():
    # Position set in code (not in .tscn)
    # Editor shows default (0,0), runtime shows calculated position
    position = calculate_spawn_position()
```

spawner.tscn:
```ini
[node name="Spawner" type="Node2D"]
```

---

## Strategy C: Camera-Aware Positioning

**Purpose**: Handle camera-following backgrounds and parallax layers

### When to Use

- Background follows camera
- Parallax layers with camera sync
- Player-relative UI elements
- Dynamic camera positioning

### Implementation Steps

#### Step 1: Detect Camera Start Position

```python
def find_camera_start_position(project_root):
    """Find initial camera position from main scene."""

    # Search for main scene
    project_godot = os.path.join(project_root, 'project.godot')
    main_scene = None

    with open(project_godot) as f:
        for line in f:
            if 'config/main_scene' in line:
                match = re.search(r'"([^"]+)"', line)
                if match:
                    main_scene = match.group(1).replace('res://', '')

    if not main_scene:
        return None

    # Parse main scene for camera
    main_scene_path = os.path.join(project_root, main_scene)

    with open(main_scene_path) as f:
        lines = f.readlines()

    in_camera_node = False
    for line in lines:
        if 'type="Camera2D"' in line:
            in_camera_node = True
        elif in_camera_node and line.startswith('position ='):
            match = re.search(r'Vector2\s*\(\s*([0-9.+-]+)\s*,\s*([0-9.+-]+)\s*\)', line)
            if match:
                return (float(match.group(1)), float(match.group(2)))
        elif in_camera_node and line.startswith('[node'):
            break

    # Default camera position (typically viewport center)
    return (512, 300)  # 1024x600 / 2
```

#### Step 2: Update Background .tscn

```python
def update_camera_aware_position(tscn_path, camera_position, node_name=None):
    """Update background position to camera start position."""
    return update_tscn_position(tscn_path, camera_position, node_name)
```

#### Step 3: Document Camera-Relative Behavior

```python
def document_camera_behavior(script_path):
    """Add editor preview documentation to camera-following script."""
    with open(script_path) as f:
        content = f.read()

    # Find _process or _physics_process function
    if 'func _process(' in content:
        func_name = '_process'
    elif 'func _physics_process(' in content:
        func_name = '_physics_process'
    else:
        return

    # Add comment before function
    comment = '''# EDITOR PREVIEW: Position in .tscn set to camera start position
# for accurate level design preview. At runtime, follows camera dynamically.
'''

    # Insert comment
    content = content.replace(
        f'func {func_name}(',
        f'{comment}func {func_name}('
    )

    with open(script_path, 'w') as f:
        f.write(content)
```

#### Step 4: Complete Example

**Before:**

background.gd:
```gdscript
extends Sprite2D

@onready var camera = get_viewport().get_camera_2d()

func _process(delta):
    position = camera.position
```

background.tscn:
```ini
[node name="Background" type="Sprite2D"]
position = Vector2(0, 0)
texture = ExtResource("1")
```

**After:**

background.gd:
```gdscript
extends Sprite2D

@onready var camera = get_viewport().get_camera_2d()

# EDITOR PREVIEW: Position in .tscn set to camera start position
# for accurate level design preview. At runtime, follows camera dynamically.
func _process(delta):
    position = camera.position
```

background.tscn:
```ini
[node name="Background" type="Sprite2D"]
position = Vector2(512, 300)
texture = ExtResource("1")
```

**Result**: Editor now shows background at camera start, making level design accurate!

---

## Parallax Specific Handling

### ParallaxBackground/ParallaxLayer

```python
def handle_parallax_layer(script_path, tscn_path, camera_start):
    """Special handling for parallax layers."""

    # Extract parallax scroll multiplier from script
    with open(script_path) as f:
        content = f.read()

    # Look for scroll multiplier patterns
    match = re.search(r'motion_scale\s*=\s*Vector2\s*\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*\)', content)

    if match:
        scale_x = float(match.group(1))
        scale_y = float(match.group(2))

        # Calculate parallax-adjusted position
        parallax_position = (
            camera_start[0] * scale_x,
            camera_start[1] * scale_y
        )

        # Update .tscn with parallax-adjusted position
        update_tscn_position(tscn_path, parallax_position)

        # Add parallax documentation
        with open(script_path, 'a') as f:
            f.write(f'\n# Parallax layer: motion_scale affects editor position\n')
            f.write(f'# Camera start: {camera_start}, Parallax pos: {parallax_position}\n')
```

---

## Batch Sync Workflow

```python
def sync_all_conflicts(conflicts):
    """Sync all detected conflicts in priority order."""

    for conflict in conflicts:
        classification = conflict['classification']

        if classification == 'CONFLICT':
            # Determine strategy
            if conflict['code_position'] and conflict['tscn_position']:
                # Default to CODE_TO_EDITOR for static conflicts
                strategy = 'CODE_TO_EDITOR'
            else:
                strategy = 'EDITOR_TO_CODE'
        elif classification == 'INTENTIONAL_DYNAMIC':
            # Camera/player following
            if 'camera' in conflict['context']:
                strategy = 'CAMERA_AWARE'
            else:
                continue  # Skip
        elif classification == 'PROCESS_ASSIGNMENT':
            # Critical warning
            print(f"⚠️  CRITICAL: Every-frame position assignment in {conflict['file']}:{conflict['line']}")
            continue
        else:
            continue  # Skip unknown

        # Execute strategy
        if strategy == 'CODE_TO_EDITOR':
            execute_code_to_editor(conflict)
        elif strategy == 'EDITOR_TO_CODE':
            execute_editor_to_code(conflict)
        elif strategy == 'CAMERA_AWARE':
            execute_camera_aware(conflict)

        # Git commit after each
        git_commit_sync(conflict, strategy)
```

---

## Git Commit Templates

```python
def git_commit_sync(conflict, strategy):
    """Create descriptive git commit for sync operation."""

    if strategy == 'CODE_TO_EDITOR':
        message = f"""Sync: Move {conflict['node_name']} position from code to editor

- Updated {conflict['tscn_file']} position to {conflict['code_position']}
- Removed static position assignment from {conflict['file']}
- Editor now matches runtime position"""

    elif strategy == 'EDITOR_TO_CODE':
        message = f"""Sync: Keep {conflict['node_name']} position in code

- Reset {conflict['tscn_file']} to default position
- Kept position assignment in {conflict['file']}
- Runtime position calculated dynamically"""

    elif strategy == 'CAMERA_AWARE':
        message = f"""Sync: Camera-aware positioning for {conflict['node_name']}

- Updated {conflict['tscn_file']} to camera start position
- Added documentation for camera-following behavior
- Editor now shows accurate runtime preview"""

    subprocess.run(['git', 'add', conflict['file'], conflict['tscn_file']])
    subprocess.run(['git', 'commit', '-m', message])
```

---

## Use These Strategies

When running editor-position-sync skill:

1. Classify each conflict
2. Select appropriate strategy
3. Execute strategy steps
4. Git commit with descriptive message
5. Run validation test
6. Continue to next conflict
