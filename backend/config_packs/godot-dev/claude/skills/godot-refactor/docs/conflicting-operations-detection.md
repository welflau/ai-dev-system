# Conflicting/Ineffective Operations Detection

Detection guide for code that runs without errors but has no effect or conflicts with other code.

---

## Overview

These anti-patterns are harder to spot than syntax errors because they don't crash or throw errors. They're useless operations that waste CPU cycles or overwrite each other.

---

## 1. Duplicate Property Assignments

**What to detect**: Same property assigned multiple times without being read between assignments.

### Detection Patterns

```bash
# Detect consecutive assignments to same variable
grep -rn "^\s*\(\w\+\)\s*=.*$" --include="*.gd" . | \
awk -F: '{file=$1; line=$2; if (prev_file==file && match($0, /([a-z_][a-z0-9_]*)\s*=/, arr) && arr[1]==prev_var) print prev_line"\n"$0; prev_file=file; prev_line=$0; match($0, /([a-z_][a-z0-9_]*)\s*=/, arr); prev_var=arr[1]}'

# Simpler: Find common culprits manually
grep -rn "\.scale\s*=" --include="*.gd" . | head -20
grep -rn "\.position\s*=" --include="*.gd" . | head -20
grep -rn "\.visible\s*=" --include="*.gd" . | head -20
grep -rn "\.modulate\s*=" --include="*.gd" . | head -20
```

### Common Examples

**A. Scale conflicts:**
```gdscript
# BAD: First assignment is useless
sprite.scale = Vector2(2, 2)
# ... no reads of sprite.scale here
sprite.scale = Vector2(1, 1)  # ← Overwrites!

# GOOD: Only set once
sprite.scale = Vector2(1, 1)
```

**B. Visibility conflicts:**
```gdscript
# BAD: Contradictory
visible = true
# ... some code
visible = false  # ← Makes first assignment pointless

# GOOD: Only set to final value
visible = false
```

**C. Position conflicts:**
```gdscript
# BAD: Multiple assignments
position = Vector2(100, 100)
position = Vector2(200, 200)  # ← Overwrites
position = Vector2(300, 300)  # ← Overwrites again!

# GOOD: Just use final position
position = Vector2(300, 300)
```

### Detection Strategy

**Manual inspection approach:**
1. Search for common property patterns in each file
2. Check if property is assigned multiple times in same function
3. Verify no reads occur between assignments
4. If confirmed: keep only the last assignment

**Multi-line context search:**
```bash
# For a specific file, find duplicate assignments with context
file="player.gd"
grep -n "\.scale\s*=" "$file" | while read line; do
    linenum=$(echo "$line" | cut -d: -f1)
    # Show 5 lines of context
    sed -n "$((linenum-2)),$((linenum+2))p" "$file"
    echo "---"
done
```

---

## 2. Self-Assignments

**What to detect**: Variable assigned to itself (no-op).

### Detection Patterns

```bash
# Detect self-assignments
grep -rn "\b\(\w\+\)\s*=\s*\1\b" --include="*.gd" .

# More specific patterns
grep -rn "position\s*=\s*position" --include="*.gd" .
grep -rn "scale\s*=\s*scale" --include="*.gd" .
grep -rn "rotation\s*=\s*rotation" --include="*.gd" .
```

### Examples

```gdscript
# BAD: Assigns to itself
position = position  # ← Does nothing!

# BAD: Self-multiplication by 1
scale *= Vector2(1, 1)  # ← No effect!

# BAD: Self-addition by 0
position += Vector2.ZERO  # ← Useless!

# BAD: Identity rotation
rotation += 0.0  # ← No effect!
```

### Cleanup

Remove the line entirely. It does nothing.

---

## 3. Redundant Default Operations

**What to detect**: Operations that set values to their defaults.

### Detection Patterns

```bash
# Default modulate (white, full alpha)
grep -rn "modulate\s*=\s*Color(1,\s*1,\s*1,\s*1)" --include="*.gd" .
grep -rn "modulate\s*=\s*Color\.WHITE" --include="*.gd" .

# Default scale (1, 1)
grep -rn "scale\s*=\s*Vector2(1,\s*1)" --include="*.gd" .
grep -rn "scale\s*=\s*Vector2\.ONE" --include="*.gd" .

# Default rotation (0)
grep -rn "rotation\s*=\s*0" --include="*.gd" .

# Default position (0, 0) - may be intentional, check context
grep -rn "position\s*=\s*Vector2\.ZERO" --include="*.gd" .

# Default visibility (true for most nodes)
grep -rn "visible\s*=\s*true" --include="*.gd" .
```

### Examples

```gdscript
# BAD: Setting to default white
sprite.modulate = Color(1, 1, 1, 1)  # ← Already the default!

# BAD: Setting to default scale
sprite.scale = Vector2.ONE  # ← Already 1,1 by default!

# BAD: Setting to default rotation
rotation = 0.0  # ← Already 0 by default!

# CONDITIONAL: May be intentional reset
position = Vector2.ZERO  # ← Could be resetting, check context
```

### When to Keep

**Keep if:**
- Resetting after previous modification
- Explicitly clarifying state for readability
- Required for animation/tween reset

**Remove if:**
- In `_ready()` with no prior changes
- No previous assignment to this property
- Clearly redundant

---

## 4. Conflicting Tweens/Animations

**What to detect**: Multiple tweens targeting the same property on the same node.

### Detection Patterns

```bash
# Find tween property calls
grep -rn "tween_property" --include="*.gd" . > tweens.txt

# Find multiple tweens in same function
for file in $(find . -name "*.gd"); do
    # Count tween_property calls per function
    awk '/^func / {fname=$2} /tween_property/ {print FILENAME":"fname":"$0}' "$file"
done

# Specific: Find conflicting scale tweens
grep -B5 -A2 "tween_property.*\"scale\"" --include="*.gd" .

# Specific: Find conflicting position tweens
grep -B5 -A2 "tween_property.*\"position\"" --include="*.gd" .
```

### Examples

**A. Simultaneous conflicting tweens:**
```gdscript
# BAD: Both tweens run at same time on same property
func _start_animation():
    var tween1 = create_tween()
    tween1.tween_property(self, "scale", Vector2(2, 2), 1.0)

    var tween2 = create_tween()
    tween2.tween_property(self, "scale", Vector2(0.5, 0.5), 1.0)  # ← Conflicts!

# GOOD: Choose one or sequence them
func _start_animation():
    var tween = create_tween()
    tween.tween_property(self, "scale", Vector2(2, 2), 1.0)
    # OR use chain:
    # tween.tween_property(self, "scale", Vector2(0.5, 0.5), 1.0)
```

**B. Tween on property that's set elsewhere:**
```gdscript
# BAD: _process sets position every frame, tween has no effect
func _ready():
    var tween = create_tween()
    tween.tween_property(self, "position", Vector2(100, 100), 2.0)

func _process(delta):
    position = target_position  # ← Overwrites tween every frame!

# GOOD: Disable _process during tween or tween the target instead
func _ready():
    set_process(false)  # Disable override
    var tween = create_tween()
    tween.tween_property(self, "position", Vector2(100, 100), 2.0)
    tween.finished.connect(func(): set_process(true))
```

**C. AnimationPlayer conflicts:**
```gdscript
# BAD: Animation and script fight over same property
# Animation modifies sprite.scale
# Script also modifies sprite.scale in _process
# Result: Jittery, broken animation

# GOOD: Let animation own the property, or use different properties
```

### Detection Strategy

1. Find all `create_tween()` calls
2. Extract `tween_property()` targets in surrounding lines
3. Group by function
4. Check for duplicates targeting same property
5. Flag for manual review

### Resolution Options

**Ask user:**
```
⚠️  Conflicting tweens detected:

File: player.gd
Function: _start_animation()
Line 45: tween_property(self, "scale", Vector2(2,2), 1.0)
Line 48: tween_property(self, "scale", Vector2(0.5,0.5), 1.0)

Both tweens run simultaneously on the same property.

Options:
1. Keep first tween (scale to 2,2)
2. Keep second tween (scale to 0.5,0.5)
3. Chain them (first→second sequence)
4. Skip this fix (I'll fix manually)

Choice [1-4]: _
```

---

## 5. Overridden Function Calls

**What to detect**: Function called multiple times where later call negates the first.

### Detection Patterns

```bash
# set_process called multiple times
grep -rn "set_process" --include="*.gd" . | \
awk -F: '{if ($1==prev_file) print prev_line"\n"$0; prev_file=$1; prev_line=$0}'

# set_physics_process patterns
grep -rn "set_physics_process" --include="*.gd" . | \
awk -F: '{if ($1==prev_file) print prev_line"\n"$0; prev_file=$1; prev_line=$0}'

# queue_free patterns (nothing should come after this!)
grep -A5 "queue_free()" --include="*.gd" . | grep -v "^--$"
```

### Examples

**A. Process state toggling:**
```gdscript
# BAD: First call is useless
func _ready():
    set_process(true)
    # ... setup code
    set_process(false)  # ← Makes first call pointless

# GOOD: Just use the final state
func _ready():
    # ... setup code
    set_process(false)
```

**B. Code after queue_free:**
```gdscript
# BAD: Code after queue_free won't run
func _die():
    queue_free()
    print("I'm dead")  # ← Never prints! Node is queued for deletion

# GOOD: Do work before queue_free
func _die():
    print("I'm dead")
    queue_free()  # Always last
```

**C. Multiple visibility toggles:**
```gdscript
# BAD: Toggling unnecessarily
func _update_ui():
    health_bar.visible = true
    # ... some checks
    health_bar.visible = false
    # ... more code
    health_bar.visible = true  # ← What's the intent?

# GOOD: Determine visibility once
func _update_ui():
    var should_show = health > 0
    health_bar.visible = should_show
```

### Detection Strategy

1. Find functions that affect node state
2. Check for multiple calls in same scope
3. Verify no branching logic between calls
4. If sequential: keep only last call

---

## 6. No-Op Conditional Branches

**What to detect**: If/else branches that do nothing differently.

### Detection Patterns

```bash
# Simple: Find empty if bodies
grep -A2 "^[[:space:]]*if " --include="*.gd" . | grep -B1 "^[[:space:]]*$"

# Find if/else with identical bodies (requires manual inspection)
```

### Examples

```gdscript
# BAD: Both branches do the same thing
if enemy_type == "fast":
    speed = 200
else:
    speed = 200  # ← Same result!

# GOOD: Just set the value
speed = 200

# BAD: Empty branch
if health > 0:
    pass  # ← Does nothing
else:
    _die()

# GOOD: Invert condition
if health <= 0:
    _die()
```

---

## Detection Output Format

```json
{
  "type": "conflicting_operation",
  "file": "player.gd",
  "subtype": "duplicate_assignment",
  "lines": [45, 52],
  "property": "scale",
  "values": ["Vector2(2, 2)", "Vector2(1, 1)"],
  "recommendation": "Remove line 45 (first assignment is unused)",
  "auto_fixable": true
}
```

---

## Cleanup Priorities

**Priority 1 (Auto-fix):**
- Self-assignments (`position = position`)
- Redundant defaults (`modulate = Color.WHITE` in `_ready()`)
- Code after `queue_free()`

**Priority 2 (Ask user):**
- Duplicate assignments (which to keep?)
- Conflicting tweens (which one?)
- Multiple process state changes (final state?)

**Priority 3 (Report only):**
- AnimationPlayer conflicts (complex fix)
- No-op conditionals (logic may be intentional)

---

## Integration with Main Skill

Run this detection **after** Operations A-D, because:
- Operations A-D may introduce or remove conflicts
- Refactoring may create temporary duplicates
- Check at the end ensures final cleanliness

---

## Testing Conflicts

Create test file with intentional conflicts:

```gdscript
# test_conflicts.gd
extends Node2D

func _ready():
    # Duplicate assignments
    scale = Vector2(2, 2)
    scale = Vector2(1, 1)

    # Self-assignment
    position = position

    # Redundant default
    modulate = Color.WHITE

    # Conflicting tweens
    var t1 = create_tween()
    t1.tween_property(self, "rotation", PI, 1.0)
    var t2 = create_tween()
    t2.tween_property(self, "rotation", -PI, 1.0)

    # Overridden call
    set_process(true)
    set_process(false)

    # Code after queue_free
    queue_free()
    print("This never prints")
```

Run detection, verify all 6 issues found.

---

## Manual Review Checklist

For each detected conflict:
- [ ] Verified both assignments exist
- [ ] Confirmed no reads between assignments
- [ ] Checked for control flow (if/loops) that might affect execution
- [ ] Determined which value to keep (usually last one)
- [ ] Applied fix
- [ ] Tested behavior unchanged

---

**Use this guide** for Operation E in the main refactoring skill to detect and clean all conflicting/ineffective operations.
