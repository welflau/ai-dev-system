# Position Detection Patterns

Complete reference for detecting position assignments and conflicts in Godot projects.

---

## Detection Patterns

### Static Position Assignments

**Pattern**: `position = Vector2(x, y)` in lifecycle methods

```bash
# Detect in _ready()
grep -rn "func _ready" --include="*.gd" . | while read line; do
    file=$(echo $line | cut -d: -f1)
    grep -A10 "func _ready" "$file" | grep "position\s*=\s*Vector2("
done

# Detect in _init()
grep -rn "func _init" --include="*.gd" . | while read line; do
    file=$(echo $line | cut -d: -f1)
    grep -A10 "func _init" "$file" | grep "position\s*=\s*Vector2("
done
```

**Example matches:**
```gdscript
func _ready():
    position = Vector2(100, 150)  # MATCH
    self.position = Vector2(500, 300)  # MATCH
    global_position = Vector2(0, 0)  # MATCH (different property)
```

---

### Camera-Following Patterns

**Pattern**: `position = camera.position` or similar camera references

```bash
# Detect camera following
grep -rn "position\s*=.*camera" --include="*.gd" .

# Detect get_viewport camera access
grep -rn "position\s*=.*get_viewport.*camera" --include="*.gd" .
```

**Example matches:**
```gdscript
position = camera.position  # MATCH
position = camera.global_position  # MATCH
position = get_viewport().get_camera_2d().position  # MATCH
```

---

### Player-Following Patterns

**Pattern**: `position = player.position` or target references

```bash
# Detect player following
grep -rn "position\s*=.*player" --include="*.gd" .

# Detect target following
grep -rn "position\s*=.*target\.position" --include="*.gd" .
```

**Example matches:**
```gdscript
position = player.position  # MATCH
position = player.global_position + offset  # MATCH
position = target.position  # MATCH
```

---

### Parallax Patterns

**Pattern**: ParallaxBackground/ParallaxLayer nodes with scroll

```bash
# Find parallax nodes
grep -rn "ParallaxBackground\|ParallaxLayer" --include="*.gd" .

# Find scroll offset assignments
grep -rn "scroll_offset\s*=" --include="*.gd" .
```

**Example matches:**
```gdscript
extends ParallaxBackground  # MATCH
scroll_offset = camera.position * 0.5  # MATCH
```

---

### Animation/Tween Patterns (SKIP)

**Pattern**: Tweens or animations affecting position

```bash
# Detect tweens on position
grep -rn "tween_property.*position" --include="*.gd" .

# Detect create_tween with position
grep -rn "create_tween" --include="*.gd" . | while read line; do
    file=$(echo $line | cut -d: -f1)
    grep -A5 "create_tween" "$file" | grep "position"
done
```

**Example matches (SKIP THESE):**
```gdscript
tween.tween_property(self, "position", Vector2(100, 100), 1.0)  # SKIP
var tween = create_tween()
tween.tween_property(sprite, "position", target, 2.0)  # SKIP
```

---

### Process-Based Assignments (CRITICAL)

**Pattern**: Position assignments in `_process()` or `_physics_process()`

```bash
# Detect position in _process
grep -rn "func _process" --include="*.gd" . | while read line; do
    file=$(echo $line | cut -d: -f1)
    grep -A20 "func _process" "$file" | grep "position\s*="
done

# Detect position in _physics_process
grep -rn "func _physics_process" --include="*.gd" . | while read line; do
    file=$(echo $line | cut -d: -f1)
    grep -A20 "func _physics_process" "$file" | grep "position\s*="
done
```

**Example matches (CRITICAL WARNING):**
```gdscript
func _process(delta):
    position = Vector2(100, 100)  # CRITICAL - every frame assignment

func _physics_process(delta):
    position.x = target.position.x  # CRITICAL
```

---

## .tscn Position Parsing

### Extract Position from Scene Files

```bash
# Find all position declarations in .tscn
grep -rn "^position\s*=\s*Vector2(" --include="*.tscn" .

# Extract specific node positions
grep -A5 'node name="Background"' background.tscn | grep "^position"
```

**Example .tscn:**
```ini
[node name="Background" type="Sprite2D"]
position = Vector2(0, 0)  # MATCH

[node name="Enemy" type="CharacterBody2D" parent="."]
position = Vector2(500, 300)  # MATCH
```

---

## Context Extraction

### Get Context Around Position Assignment

**Python helper:**
```python
def extract_context(file_path, line_number, context_lines=30):
    """Extract lines around target line for classification."""
    with open(file_path) as f:
        lines = f.readlines()

    start = max(0, line_number - context_lines)
    end = min(len(lines), line_number + context_lines)

    return ''.join(lines[start:end])
```

**Bash version:**
```bash
# Extract 30 lines before and after
grep -B30 -A30 "position\s*=\s*Vector2(" script.gd
```

---

## Classification Algorithm

### Intelligent Classifier

```python
def classify_position_assignment(file_path, line_number, line_content):
    """
    Classify position assignment as:
    - CONFLICT: Static conflict with .tscn
    - INTENTIONAL_DYNAMIC: Camera/player following (skip)
    - INTENTIONAL_ANIMATION: Tweens/animations (skip)
    - PROCESS_ASSIGNMENT: Every-frame assignment (critical)
    - UNKNOWN: Needs manual review
    """

    # Get context
    context = extract_context(file_path, line_number, context_lines=30)
    context_lower = context.lower()

    # SKIP: Animation/tween
    if any(keyword in context_lower for keyword in ['tween', 'create_tween', 'tween_property']):
        return "INTENTIONAL_ANIMATION"

    # SKIP: Camera following
    if any(keyword in context_lower for keyword in ['camera.position', 'get_viewport().get_camera']):
        return "INTENTIONAL_DYNAMIC"

    # SKIP: Player/target following
    if any(keyword in context_lower for keyword in ['player.position', 'target.position']):
        return "INTENTIONAL_DYNAMIC"

    # CRITICAL: Every frame assignment
    if 'func _process(' in context or 'func _physics_process(' in context:
        return "PROCESS_ASSIGNMENT"

    # CONFLICT: Static assignment in _ready
    if 'func _ready(' in context and 'Vector2(' in line_content:
        # Check if .tscn has different position
        tscn_path = find_tscn_for_script(file_path)
        if tscn_path:
            tscn_position = extract_tscn_position(tscn_path)
            code_position = extract_vector2(line_content)

            if tscn_position != code_position:
                return "CONFLICT"

    return "UNKNOWN"
```

---

## Position Extraction Helpers

### Extract Vector2 from Code

```python
import re

def extract_vector2(line):
    """Extract Vector2 coordinates from line."""
    match = re.search(r'Vector2\s*\(\s*([0-9.+-]+)\s*,\s*([0-9.+-]+)\s*\)', line)
    if match:
        return (float(match.group(1)), float(match.group(2)))
    return None
```

**Example:**
```python
extract_vector2("position = Vector2(100, 150)")
# Returns: (100.0, 150.0)
```

---

### Extract Position from .tscn

```python
def extract_tscn_position(tscn_path, node_name=None):
    """Extract position from .tscn file for specific node."""
    with open(tscn_path) as f:
        lines = f.readlines()

    in_target_node = False

    for i, line in enumerate(lines):
        # Find target node
        if node_name:
            if f'[node name="{node_name}"' in line:
                in_target_node = True
        else:
            # Root node (first node section)
            if line.startswith('[node name="'):
                in_target_node = True

        # Extract position if in target node
        if in_target_node and line.startswith('position ='):
            match = re.search(r'Vector2\s*\(\s*([0-9.+-]+)\s*,\s*([0-9.+-]+)\s*\)', line)
            if match:
                return (float(match.group(1)), float(match.group(2)))

        # Stop at next node section
        if in_target_node and i > 0 and line.startswith('[node'):
            break

    return None
```

---

## File Association

### Find .tscn for .gd Script

```python
def find_tscn_for_script(script_path):
    """Find associated .tscn file for a script."""
    import os

    # Same name, different extension
    base = os.path.splitext(script_path)[0]
    tscn_path = base + '.tscn'

    if os.path.exists(tscn_path):
        return tscn_path

    # Search for .tscn files that reference this script
    script_filename = os.path.basename(script_path)

    for root, dirs, files in os.walk('.'):
        for file in files:
            if file.endswith('.tscn'):
                tscn_full = os.path.join(root, file)
                with open(tscn_full) as f:
                    if script_filename in f.read():
                        return tscn_full

    return None
```

---

## Complete Detection Workflow

```bash
#!/bin/bash
# detect_position_conflicts.sh

echo "=== Position Conflict Detection ==="

# 1. Find all .gd files with position assignments
echo "Scanning scripts for position assignments..."
position_files=$(grep -rl "position\s*=\s*Vector2(" --include="*.gd" .)

# 2. For each file, extract and classify
for file in $position_files; do
    echo "Analyzing: $file"

    # Extract line numbers and content
    grep -n "position\s*=\s*Vector2(" "$file" | while IFS=: read line_num line_content; do
        echo "  Line $line_num: $line_content"

        # Get context
        context=$(grep -B30 -A30 "position\s*=\s*Vector2(" "$file" | head -61 | tail -61)

        # Classify (simplified bash version)
        if echo "$context" | grep -q "tween"; then
            echo "    Classification: ANIMATION (skip)"
        elif echo "$context" | grep -q "camera"; then
            echo "    Classification: CAMERA_FOLLOWING (skip)"
        elif echo "$context" | grep -q "func _process"; then
            echo "    Classification: PROCESS_ASSIGNMENT (CRITICAL)"
        elif echo "$context" | grep -q "func _ready"; then
            echo "    Classification: CONFLICT (sync needed)"
        else
            echo "    Classification: UNKNOWN (review)"
        fi
    done
done

echo "=== Detection Complete ==="
```

---

## Detection Report Format

```json
{
  "conflicts": [
    {
      "file": "enemy.gd",
      "line": 45,
      "classification": "CONFLICT",
      "code_position": [100, 150],
      "tscn_file": "enemy.tscn",
      "tscn_position": [500, 300],
      "suggested_strategy": "CODE_TO_EDITOR"
    },
    {
      "file": "background.gd",
      "line": 12,
      "classification": "INTENTIONAL_DYNAMIC",
      "code_position": "camera.position",
      "suggested_strategy": "CAMERA_AWARE"
    }
  ],
  "total_conflicts": 2,
  "critical_warnings": 0,
  "skipped_intentional": 1
}
```

---

## Use This File

When running editor-position-sync skill:

1. Use detection patterns to find position assignments
2. Apply intelligent classifier to each finding
3. Extract context for accurate classification
4. Generate conflict manifest
5. Proceed with synchronization strategies
