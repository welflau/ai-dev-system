# Anti-Patterns Detection Guide

Complete reference for detecting all Godot anti-patterns automatically.

---

## Detection Strategy

Run all detection commands in parallel, then aggregate results into a priority-ordered manifest.

---

## 1. Code-Created Objects

**What to detect**: Any node creation via `.new()` in scripts.

### Primary Detection

```bash
# Find all .new() calls
grep -rn "\.new()" --include="*.gd" .

# With context (shows 2 lines before/after)
grep -rn -B2 -A2 "\.new()" --include="*.gd" .
```

### Specific Node Types

```bash
# Scene nodes (should be .tscn files)
grep -rn "Node2D\.new()\|Control\.new()\|Timer\.new()\|Area2D\.new()\|Sprite2D\.new()" --include="*.gd" .

# Collision shapes
grep -rn "CollisionShape2D\.new()\|CollisionPolygon2D\.new()" --include="*.gd" .

# UI elements
grep -rn "Label\.new()\|Button\.new()\|Panel\.new()" --include="*.gd" .
```

### With add_child Pattern

```bash
# Find .new() followed by add_child (common anti-pattern)
grep -rn "add_child.*\.new()" --include="*.gd" .

# Multi-line pattern (object created, then added later)
grep -rn "\.new()" --include="*.gd" . | while read line; do
    file=$(echo "$line" | cut -d: -f1)
    linenum=$(echo "$line" | cut -d: -f2)
    # Check next 10 lines for add_child
    sed -n "${linenum},$((linenum+10))p" "$file" | grep -q "add_child" && echo "$line"
done
```

### Exceptions (Don't Refactor)

These are OKAY to create in code:
```bash
# Resource objects (correct usage)
grep -rn "Resource\.new()\|PackedScene\.new()" --include="*.gd" .

# Data structures (correct usage)
grep -rn "Array\.new()\|Dictionary\.new()" --include="*.gd" .

# Custom classes (correct usage, unless they extend Node)
grep -rn "\.new()" --include="*.gd" . | grep -v "Node\|Timer\|Area\|Sprite\|Control\|Collision"
```

**Output Format:**
```
path/to/file.gd:42:    _damage_timer = Timer.new()
path/to/file.gd:43:    _damage_timer.wait_time = 1.0
path/to/file.gd:44:    add_child(_damage_timer)
```

**Parse this into:**
- File: `path/to/file.gd`
- Line: `42-44`
- Type: `Timer`
- Properties: `wait_time = 1.0`
- Operation: Extract to .tscn

---

## 2. Monolithic Scripts

**What to detect**: Scripts exceeding 150 lines.

### Line Count Detection

```bash
# All scripts over 150 lines
find . -name "*.gd" -exec wc -l {} + | awk '$1 > 150 {print $2 " (" $1 " lines)"}'

# Sorted by size (largest first)
find . -name "*.gd" -exec wc -l {} + | awk '$1 > 150' | sort -rn

# With threshold customization
THRESHOLD=150
find . -name "*.gd" -exec wc -l {} + | awk -v t=$THRESHOLD '$1 > t {print $2 " (" $1 " lines)"}'
```

### Complexity Analysis

```bash
# Count functions in large scripts (indicator of multiple responsibilities)
for file in $(find . -name "*.gd" -exec wc -l {} + | awk '$1 > 150 {print $2}'); do
    echo "$file:"
    grep -c "^func " "$file"
done

# Find scripts with many signal definitions (indicator of coupling)
for file in $(find . -name "*.gd"); do
    count=$(grep -c "^signal " "$file")
    if [ "$count" -gt 5 ]; then
        echo "$file: $count signals"
    fi
done
```

### Responsibility Detection

Look for comment-based sections (indicates multiple responsibilities):
```bash
# Find scripts with multiple "# ====" section headers
for file in $(find . -name "*.gd" -exec wc -l {} + | awk '$1 > 150 {print $2}'); do
    sections=$(grep -c "^# ====" "$file")
    if [ "$sections" -gt 3 ]; then
        echo "$file: $sections sections"
        grep -n "^# ====" "$file"
    fi
done
```

**Output Format:**
```
path/to/player_movement.gd (287 lines)
  12 functions
  6 signals
  5 sections: Input, Physics, Abilities, Health, UI
```

**Parse this into:**
- File: `path/to/player_movement.gd`
- Lines: `287`
- Sections: `Input, Physics, Abilities, Health, UI`
- Operation: Split into components

---

## 3. Tight Coupling

**What to detect**: Direct node access and method checking.

### get_node() Patterns

```bash
# All get_node calls
grep -rn "get_node" --include="*.gd" .

# get_parent (tight coupling to hierarchy)
grep -rn "get_parent" --include="*.gd" .

# get_tree().get_root() (accessing scene tree directly)
grep -rn "get_tree()\.get_root\|get_tree()\.get_first_node_in_group" --include="*.gd" .

# Dollar sign notation (shorthand for get_node)
grep -rn '\$[A-Z]' --include="*.gd" . | grep -v "@onready"
```

### has_method() Pattern

```bash
# Method existence checks (indicates weak typing/coupling)
grep -rn "has_method" --include="*.gd" .

# With context to understand what's being called
grep -rn -A2 "has_method" --include="*.gd" .
```

### Direct Property Access

```bash
# Accessing properties via get_node
grep -rn "get_node.*\." --include="*.gd" . | grep -v "call\|connect"

# Examples: get_node("Player").health, $Enemy.speed
```

### Call Deferred on External Nodes

```bash
# call_deferred on other nodes (coupling indicator)
grep -rn "call_deferred" --include="*.gd" . | grep "get_node\|\$"
```

**Output Format:**
```
base_station.gd:92:    if body.has_method("set_beam_enabled"):
base_station.gd:93:        body.set_beam_enabled(false)

player_movement.gd:45:    var ui = get_node("../UI/HealthBar")
player_movement.gd:46:    ui.value = health
```

**Parse this into:**
- File: `base_station.gd`
- Lines: `92-93`
- Coupling: `has_method check → direct call`
- Target: Unknown type with `set_beam_enabled` method
- Operation: Create signal in Events.gd

---

## 4. Inline Data

**What to detect**: Constants containing game data.

### Const Array Detection

```bash
# Constants with array literals
grep -rn "^[[:space:]]*const.*\[" --include="*.gd" .

# Constants with dictionary literals
grep -rn "^[[:space:]]*const.*{" --include="*.gd" .

# Large const declarations (multi-line)
grep -rn -A10 "^const.*\[" --include="*.gd" . | grep -B1 "\]"
```

### Data Type Identification

```bash
# Numeric data (likely configuration)
grep -rn "^const.*\[.*[0-9]" --include="*.gd" .

# String data (likely content/names)
grep -rn "^const.*\[.*\"" --include="*.gd" .

# Mixed dictionary data (likely structured game data)
grep -rn "^const.*\[.*{" --include="*.gd" .
```

### Exclude Valid Constants

```bash
# Filter out simple enums (these are okay)
grep -rn "^const.*\[" --include="*.gd" . | grep -v "enum"

# Filter out single-value constants (these are okay)
grep -rn "^const.*\[" --include="*.gd" . | grep -v "\[[^,]*\]"
```

**Output Format:**
```
enemy_spawner.gd:12:const ENEMY_TYPES = [
enemy_spawner.gd:13:    {"type": "basic", "health": 100, "speed": 200},
enemy_spawner.gd:14:    {"type": "fast", "health": 50, "speed": 400},
enemy_spawner.gd:15:]

weapon_data.gd:8:const WEAPONS = [
weapon_data.gd:9:    {"name": "Laser", "damage": 10, "cooldown": 0.5},
weapon_data.gd:10:]
```

**Parse this into:**
- File: `enemy_spawner.gd`
- Lines: `12-15`
- Data type: Array of dictionaries
- Fields: `type (String), health (int), speed (float)`
- Operation: Create Resource class + .tres files

---

## 5. Deep Inheritance

**What to detect**: Scripts with >2 inheritance levels.

### Extends Chain Detection

```bash
# Find all extends declarations
grep -rn "^extends " --include="*.gd" .

# Build inheritance tree (requires parsing)
# This is complex - typically done in code
```

### Manual Script
```python
#!/usr/bin/env python3
# inheritance_depth.py
import os
import re

def get_parent(filepath):
    """Extract parent class from 'extends' statement."""
    with open(filepath) as f:
        for line in f:
            if line.startswith('extends '):
                return line.split()[1].strip()
    return None

def find_depth(script, scripts_map, visited=None):
    """Recursively find inheritance depth."""
    if visited is None:
        visited = set()
    if script in visited:
        return 0  # Circular reference
    visited.add(script)

    parent = get_parent(script)
    if not parent or parent in ['Node', 'Node2D', 'Control', 'Resource']:
        return 1

    # Find parent script
    parent_script = scripts_map.get(parent)
    if parent_script:
        return 1 + find_depth(parent_script, scripts_map, visited)
    return 1

# Usage
scripts = {}
for root, dirs, files in os.walk('.'):
    for f in files:
        if f.endswith('.gd'):
            path = os.path.join(root, f)
            # Extract class_name if present
            with open(path) as file:
                for line in file:
                    if line.startswith('class_name '):
                        class_name = line.split()[1].strip()
                        scripts[class_name] = path
                        break

for path in scripts.values():
    depth = find_depth(path, scripts)
    if depth > 2:
        print(f"{path}: depth {depth}")
```

**Output Format:**
```
entities/enemies/boss_enemy.gd: depth 3
  BaseEntity → Enemy → BossEnemy
```

**Parse this into:**
- File: `entities/enemies/boss_enemy.gd`
- Depth: `3`
- Chain: `BaseEntity → Enemy → BossEnemy`
- Operation: Flatten to composition

---

## 6. Missing Scene Files

**What to detect**: Scripts without corresponding .tscn files.

### Orphan Script Detection

```bash
# Find .gd files without matching .tscn
for gd in $(find . -name "*.gd"); do
    tscn="${gd%.gd}.tscn"
    if [ ! -f "$tscn" ]; then
        # Check if script extends Node (should have scene)
        if grep -q "^extends.*Node" "$gd"; then
            echo "Missing scene: $gd"
        fi
    fi
done
```

### Scene-Less Nodes

```bash
# Find nodes created in code that should be scenes
# (Combines with code-created objects detection)
```

---

## Detection Output Format

Generate a unified manifest:

```json
{
  "project_path": "/path/to/godot/project",
  "scanned_at": "2026-02-02T03:23:00Z",
  "anti_patterns": [
    {
      "type": "code_created_object",
      "file": "laser_beam.gd",
      "lines": "38-45",
      "node_type": "Timer",
      "priority": 2,
      "operation": "extract_to_tscn"
    },
    {
      "type": "monolithic_script",
      "file": "player_movement.gd",
      "lines": "1-287",
      "line_count": 287,
      "sections": ["Input", "Physics", "Abilities", "Health", "UI"],
      "priority": 4,
      "operation": "split_script"
    },
    {
      "type": "tight_coupling",
      "file": "base_station.gd",
      "lines": "92-93",
      "coupling_type": "has_method_check",
      "priority": 3,
      "operation": "signal_decoupling"
    },
    {
      "type": "inline_data",
      "file": "enemy_spawner.gd",
      "lines": "12-15",
      "data_type": "array_of_dicts",
      "priority": 1,
      "operation": "extract_to_tres"
    }
  ],
  "summary": {
    "code_created_objects": 3,
    "monolithic_scripts": 2,
    "tight_couplings": 5,
    "inline_data": 2,
    "deep_inheritance": 1,
    "total": 13
  }
}
```

---

## Priority Calculation

**Priority order** (lower number = do first):

1. **Inline data** (foundational - other code depends on this)
2. **Code-created objects** (structural - affects scene hierarchy)
3. **Tight coupling** (architectural - affects communication)
4. **Monolithic scripts** (refinement - final cleanup)
5. **Deep inheritance** (advanced - requires careful planning)

**Within each category**, prioritize by:
- Frequency: More occurrences = higher priority
- Impact: Code referenced by many files = higher priority
- Simplicity: Easier refactorings first (build confidence)

---

## False Positives to Ignore

**Legitimate .new() usage:**
```gdscript
# Creating resources (not scene nodes)
var texture = ImageTexture.new()
var material = ShaderMaterial.new()

# Creating data structures
var data = Dictionary.new()

# Custom non-Node classes
var helper = MathHelper.new()
```

**Legitimate get_node() usage:**
```gdscript
# @onready references (already correct pattern)
@onready var timer = $Timer

# One-time setup in _ready() (acceptable if minimal)
func _ready():
    var child = $ChildNode  # Okay if just accessing direct child
```

**Legitimate constants:**
```gdscript
# Enums (should stay as const)
const States = ["IDLE", "RUNNING", "JUMPING"]

# Single values (not data collections)
const MAX_SPEED = 400.0
const GRAVITY = 980.0
```

---

## Testing Detection Accuracy

After running detection, manually verify a sample:

```bash
# Take 10% of detected anti-patterns randomly
# Manually inspect to ensure true positives
# Adjust regex patterns if false positive rate >5%
```

**Accuracy goals:**
- True positive rate: >95%
- False positive rate: <5%
- False negative rate: <10% (some edge cases acceptable)

---

## Shell Script: Complete Detection

```bash
#!/bin/bash
# detect_anti_patterns.sh

PROJECT_DIR="${1:-.}"
OUTPUT_FILE="refactoring_manifest.json"

echo "Scanning Godot project: $PROJECT_DIR"

# Code-created objects
echo "Detecting code-created objects..."
CODE_CREATED=$(grep -rn "\.new()" --include="*.gd" "$PROJECT_DIR" | \
    grep -E "(Node|Timer|Area|Sprite|Control|Collision)" | wc -l)

# Monolithic scripts
echo "Detecting monolithic scripts..."
MONOLITHIC=$(find "$PROJECT_DIR" -name "*.gd" -exec wc -l {} + | \
    awk '$1 > 150' | wc -l)

# Tight coupling
echo "Detecting tight coupling..."
COUPLING=$(grep -rn "get_node\|has_method" --include="*.gd" "$PROJECT_DIR" | wc -l)

# Inline data
echo "Detecting inline data..."
INLINE_DATA=$(grep -rn "^[[:space:]]*const.*\[" --include="*.gd" "$PROJECT_DIR" | wc -l)

# Summary
echo ""
echo "=== Detection Summary ==="
echo "Code-created objects: $CODE_CREATED"
echo "Monolithic scripts: $MONOLITHIC"
echo "Tight coupling: $COUPLING"
echo "Inline data: $INLINE_DATA"
echo "Total anti-patterns: $((CODE_CREATED + MONOLITHIC + COUPLING + INLINE_DATA))"
```

---

## 6. Conflicting/Ineffective Operations

**What to detect**: Code that runs without errors but has no effect or conflicts with other code.

### Overview

Unlike other anti-patterns, these don't cause crashes or errors. They're subtle: duplicate assignments, self-assignments, redundant operations, and conflicting tweens.

See `conflicting-operations-detection.md` for comprehensive detection patterns.

### Quick Detection

```bash
# Duplicate property assignments (common properties)
grep -rn "\.scale\s*=" --include="*.gd" . | awk -F: '{if ($1==prev && $2-prev_line<20) print prev_entry"\n"$0; prev=$1; prev_line=$2; prev_entry=$0}'

# Self-assignments
grep -rn "position\s*=\s*position" --include="*.gd" .
grep -rn "scale\s*=\s*scale" --include="*.gd" .

# Redundant defaults
grep -rn "modulate\s*=\s*Color(1,\s*1,\s*1,\s*1)" --include="*.gd" .
grep -rn "scale\s*=\s*Vector2(1,\s*1)" --include="*.gd" .

# Conflicting tweens
grep -B3 -A2 "tween_property.*\"scale\"" --include="*.gd" . | grep -B5 "tween_property.*\"scale\""

# Overridden function calls
grep -rn "set_process" --include="*.gd" . | awk -F: '{if ($1==prev_file && $2-prev_line<30) print prev_line_content"\n"$0; prev_file=$1; prev_line=$2; prev_line_content=$0}'

# Code after queue_free (always wrong!)
grep -A5 "queue_free()" --include="*.gd" . | grep -v "^--$" | grep -A1 "queue_free"
```

### Common Examples

**Duplicate assignments:**
```gdscript
sprite.scale = Vector2(2, 2)  # Line 45
sprite.scale = Vector2(1, 1)  # Line 52 ← Overwrites, line 45 is useless
```

**Self-assignments:**
```gdscript
position = position  # ← Does nothing!
```

**Redundant defaults:**
```gdscript
modulate = Color.WHITE  # ← Already the default
scale = Vector2.ONE     # ← Already 1,1
```

**Conflicting tweens:**
```gdscript
var tween1 = create_tween()
tween1.tween_property(self, "scale", Vector2(2,2), 1.0)

var tween2 = create_tween()
tween2.tween_property(self, "scale", Vector2(0.5,0.5), 1.0)  # ← Conflicts!
```

**Overridden calls:**
```gdscript
set_process(true)   # Line 12
set_process(false)  # Line 18 ← Makes line 12 useless
```

### Priority

Run this detection **last** (after Operations A-D) because refactoring may introduce or remove these issues.

### Output Format

```
player_movement.gd:45:    sprite.scale = Vector2(2, 2)
player_movement.gd:52:    sprite.scale = Vector2(1, 1)
  → Duplicate assignment detected (keep line 52, remove line 45)

player_movement.gd:78:    position = position
  → Self-assignment (no effect, remove line)

player_movement.gd:92:    var tween1 = create_tween()
player_movement.gd:93:    tween1.tween_property(self, "scale", Vector2(2,2), 1.0)
player_movement.gd:95:    var tween2 = create_tween()
player_movement.gd:96:    tween2.tween_property(self, "scale", Vector2(0.5,0.5), 1.0)
  → Conflicting tweens (ask user which to keep)
```

### Cleanup Strategy

**Auto-fix:**
- Self-assignments (always remove)
- Code after `queue_free()` (report as error)
- Obvious redundant defaults in `_ready()`

**Ask user:**
- Duplicate assignments (which value to keep?)
- Conflicting tweens (which one or chain?)
- Process state changes (what's the intent?)

**Report only:**
- AnimationPlayer conflicts (complex)
- Conditional logic that might be intentional

---

**Use this guide** in Phase 1 of the refactoring skill to automatically detect all anti-patterns with high accuracy.
