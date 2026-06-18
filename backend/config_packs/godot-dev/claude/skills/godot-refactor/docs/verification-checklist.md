# Verification Checklist

Complete guide for validating refactoring results and ensuring no regressions.

---

## Overview

The Iron Law: **NO functional or visual changes during refactoring.**

This checklist ensures every refactoring operation preserves exact behavior while improving code quality.

---

## Pre-Refactoring Baseline

### Establish Baseline BEFORE Any Changes

**1. Git State:**
```bash
# Create baseline tag
git tag baseline-$(date +%Y%m%d-%H%M%S)

# Ensure clean working tree
git status
# Should show: "nothing to commit, working tree clean"
```

**2. Screenshot Baseline:**
```bash
# Open main scenes in Godot
godot --editor -e project.godot

# For each major scene:
# - Run the scene (F6)
# - Take screenshot of initial state
# - Save as baseline_scene_name.png
```

**3. Console Baseline:**
```bash
# Run game, capture console output
godot --headless --verbose project.godot 2>&1 | tee baseline_console.log

# Note any existing warnings/errors (will filter these later)
```

**4. Performance Baseline:**
```bash
# Run game, note FPS in various scenarios
# Record in baseline_performance.txt:

Main menu: 60 FPS
Level 1 start: 58 FPS
10 enemies active: 52 FPS
Boss fight: 48 FPS
```

**5. Behavior Baseline:**

Create a test script for critical paths:
```
baseline_behavior.txt:

✓ Player spawns at correct position
✓ Movement responds to WASD
✓ Jump triggers on Space
✓ Laser fires on Left Click
✓ Enemies spawn every 2 seconds
✓ Health bar updates on damage
✓ Score increases when enemy killed
✓ Game over screen shows on death
```

---

## Per-Operation Verification

After EACH refactoring operation (A, B, C, or D):

### Quick Syntax Check

**1. Godot Editor Load:**
```bash
# Open project (will show parse errors immediately)
godot --editor -e project.godot

# Check Output panel for:
# - Red errors (critical - must fix)
# - Yellow warnings (investigate)
# - Parse errors (script won't run)
```

**2. Scene Load Test:**
```bash
# For each modified scene, right-click → "Open Scene"
# Should load without "Failed to load resource" errors
```

**3. Script Validation:**
```bash
# Check modified scripts in editor
# Look for red underlines (syntax errors)
# Look for null reference warnings
```

### Reference Integrity Check

**1. @onready Variables:**

For each added @onready:
```gdscript
@onready var _timer: Timer = $Timer
```

Verify:
- [ ] Node path exists in scene (`$Timer` node present)
- [ ] Type hint matches node type (Timer)
- [ ] Variable name is descriptive
- [ ] Private vars prefixed with `_`

**2. Signal Connections:**

For each signal connection:
```gdscript
_timer.timeout.connect(_on_timer_timeout)
```

Verify:
- [ ] Signal name is valid (exists on node)
- [ ] Callback function exists
- [ ] Parameters match signal signature
- [ ] No "Signal 'X' not found" errors in console

**3. Resource References:**

For each resource usage:
```gdscript
@export var data: EnemyTypeData
```

Verify:
- [ ] .tres file exists at expected path
- [ ] Resource loads without errors
- [ ] Properties accessible in code

### Behavioral Verification

**Run the affected feature:**

1. **Play the scene** (F6 or F5)
2. **Trigger the refactored code path**
3. **Observe behavior matches baseline**

Example for Timer extraction:
```
Before: Timer fires every 1.0 seconds
After: Timer fires every 1.0 seconds ✓

Before: _on_damage_tick called on timeout
After: _on_damage_tick called on timeout ✓

Before: Damage applies to enemies in range
After: Damage applies to enemies in range ✓
```

**4. Console Check:**
```bash
# Run scene, check Output panel
# New errors? → Must fix before committing
# Same warnings as baseline? → Okay to proceed
```

### Git Commit

Only commit if all checks pass:
```bash
git add <modified files>
git commit -m "Refactor: <operation> in <file>

- <specific change 1>
- <specific change 2>
- Preserves existing behavior"
```

---

## Post-Refactoring Complete Verification

After ALL operations complete:

### Full Suite Visual Verification

**1. Screenshot Comparison:**

For each baseline screenshot:
```bash
# Run same scene
# Take new screenshot
# Compare side-by-side

diff baseline_main_menu.png current_main_menu.png
# Should be identical (or pixel-perfect match)
```

**Use image diff tool:**
```bash
# Install: apt-get install imagemagick
compare baseline_scene.png current_scene.png diff_scene.png

# If diff_scene.png is all black → identical ✓
# If diff_scene.png shows colors → visual regression ✗
```

**2. Manual Visual Check:**

Open each major scene and verify:
- [ ] UI elements in same positions
- [ ] Sprites render identically
- [ ] Animations play the same
- [ ] Colors unchanged
- [ ] Effects appear correct

### Full Suite Functional Verification

**Use the behavior baseline checklist:**

```
baseline_behavior.txt vs current_behavior.txt

✓ Player spawns at correct position
✓ Movement responds to WASD
✓ Jump triggers on Space
✓ Laser fires on Left Click
✓ Enemies spawn every 2 seconds
✓ Health bar updates on damage
✓ Score increases when enemy killed
✓ Game over screen shows on death
```

**For EACH item:**
1. Execute the action
2. Observe the result
3. Confirm matches baseline
4. Check box if passing

**If ANY checkbox fails → Regression found**

### Performance Verification

**1. FPS Comparison:**

Run same scenarios as baseline:
```
                 Baseline  Current  Δ
Main menu:       60 FPS    60 FPS   0
Level 1 start:   58 FPS    59 FPS   +1  ✓
10 enemies:      52 FPS    51 FPS   -1  ✓
Boss fight:      48 FPS    47 FPS   -1  ✓

Acceptable delta: ±2 FPS
```

**2. Load Time Check:**
```bash
# Time scene loading
time godot --headless --quit-after 10 project.godot

# Compare to baseline
# Should be within ±10% load time
```

**3. Memory Usage** (optional):
```bash
# Run with profiler
godot --profile project.godot

# Compare memory footprint
# Should be similar (refactoring doesn't change memory much)
```

### Console Error Audit

**1. Capture current console output:**
```bash
godot --headless --verbose project.godot 2>&1 | tee current_console.log
```

**2. Compare to baseline:**
```bash
# Filter out timestamps/addresses
diff <(grep "ERROR\|WARNING" baseline_console.log | sort) \
     <(grep "ERROR\|WARNING" current_console.log | sort)

# Should show NO new errors/warnings
```

**3. Acceptable differences:**
- ✓ No differences (perfect)
- ✓ Fewer warnings (improvement)
- ✗ New errors (must fix)
- ✗ New warnings (investigate)

### Code Quality Verification

**1. Script Size Check:**
```bash
# Before refactoring
find . -name "*.gd" -exec wc -l {} + | awk '{total += $1} END {print total " total lines"}'
# e.g., 1850 total lines

# After refactoring
find . -name "*.gd" -exec wc -l {} + | awk '{total += $1} END {print total " total lines"}'
# e.g., 1420 total lines

# Reduction: 430 lines (23%) ✓
```

**2. Anti-Pattern Elimination:**

Re-run detection from Phase 1:
```bash
# Code-created objects
grep -rn "\.new()" --include="*.gd" . | grep -E "(Node|Timer|Area)" | wc -l
# Should be 0 ✓

# Monolithic scripts
find . -name "*.gd" -exec wc -l {} + | awk '$1 > 150' | wc -l
# Should be 0 ✓

# Tight coupling
grep -rn "has_method" --include="*.gd" . | wc -l
# Should be 0 or near 0 ✓

# Inline data
grep -rn "^[[:space:]]*const.*\[" --include="*.gd" . | wc -l
# Should be 0 or only valid enums ✓
```

**3. Architecture Validation:**

Check for clean patterns:
```bash
# Signal usage (should increase)
grep -rn "\.connect\|\.emit" --include="*.gd" . | wc -l

# @onready usage (should increase)
grep -rn "@onready" --include="*.gd" . | wc -l

# Resource usage (should increase)
grep -rn "@export.*Resource\|@export.*Array\[.*Data\]" --include="*.gd" . | wc -l
```

---

## Regression Handling

### If Verification Fails

**Step 1: Identify the regression**
```
Symptom: Player jump not working after refactoring

When: After Operation B (split player_movement.gd)
What changed: Movement code split into components
```

**Step 2: Isolate the operation**
```bash
# Check git log
git log --oneline

# Find the commit that introduced regression
# Use git bisect if unclear
git bisect start
git bisect bad HEAD
git bisect good baseline-20260202
```

**Step 3: Analyze the diff**
```bash
git show <commit-hash>

# Look for:
# - Signal connections that broke
# - Missing @onready references
# - Incorrect component communication
```

**Step 4: Fix the regression**

**Option A: Fix in place**
```gdscript
# Found issue: Jump signal not connected
func _ready():
    # Add missing connection:
    abilities.jump_requested.connect(_on_jump)
```

**Option B: Revert and redo**
```bash
# If fix is complex, revert the operation
git revert <commit-hash>

# Redo the operation correctly
# Commit again with proper implementation
```

**Step 5: Re-verify**
- Run full verification checklist again
- Ensure regression is fixed
- Ensure no new regressions introduced

### Common Regressions and Fixes

| Regression | Cause | Fix |
|-----------|-------|-----|
| "Invalid get index" error | @onready path incorrect | Fix node path in $Reference |
| Signal not firing | Connection missing | Add .connect() in _ready() |
| Null reference | Node doesn't exist | Create node in .tscn file |
| Wrong behavior | Logic moved incorrectly | Review component split, restore logic |
| Performance drop | Accidental duplication | Check for duplicate processing |
| Visual glitch | Scene hierarchy changed | Restore correct parent-child relationships |

---

## Rollback Procedure

### When to Rollback

Rollback if:
- ✗ Multiple regressions found
- ✗ Core functionality broken
- ✗ Fix attempt creates more issues
- ✗ Verification fails after 3 fix attempts

### How to Rollback

**Full rollback to baseline:**
```bash
# Reset to baseline tag
git reset --hard baseline-20260202-HHMMSS

# Tag the failed attempt for analysis
git tag refactor-failed-$(date +%Y%m%d-%H%M%S) HEAD@{1}

# Clean working directory
git clean -fd
```

**Partial rollback (keep some operations):**
```bash
# Revert specific operations in reverse order
git revert <commit-hash-operation-D>
git revert <commit-hash-operation-C>
# Keep operations A and B
```

**After rollback:**
1. Analyze what went wrong
2. Plan corrected approach
3. Re-attempt refactoring with lessons learned

---

## Success Criteria Checklist

Refactoring is successful when ALL criteria met:

### Code Quality
- [ ] No `.new()` calls for scene nodes
- [ ] All scripts <150 lines
- [ ] Signal-based architecture used
- [ ] No `get_node()` for behavior coupling
- [ ] No `has_method()` checks
- [ ] Data in .tres resources, not const
- [ ] Clean git history with descriptive commits

### Functional Preservation
- [ ] All baseline behaviors working
- [ ] No new errors in console
- [ ] No new warnings (or fewer than baseline)
- [ ] All UI interactions identical
- [ ] All game mechanics unchanged
- [ ] All animations/effects identical

### Visual Preservation
- [ ] Screenshots match pixel-perfect (or nearly so)
- [ ] No UI element position changes
- [ ] No color/sprite changes
- [ ] No unintended visibility changes

### Performance Preservation
- [ ] FPS within ±2 of baseline
- [ ] Load times within ±10%
- [ ] Memory usage similar
- [ ] No new performance bottlenecks

### Maintainability Improvements
- [ ] Code more modular
- [ ] Components reusable
- [ ] Dependencies reduced
- [ ] Easier to test
- [ ] Easier to extend

---

## Post-Success Steps

After verification passes:

**1. Final commit:**
```bash
git add .
git commit -m "Refactor: Complete Godot refactoring

Summary:
- Extracted 8 .tscn scenes from code
- Split 3 monolithic scripts into components
- Implemented signal-based architecture
- Extracted 5 .tres resource files
- Reduced codebase by 430 lines (23%)
- Zero functional regressions
- All tests passing"
```

**2. Create completion tag:**
```bash
git tag refactor-complete-$(date +%Y%m%d)
```

**3. Generate refactoring report:**

```markdown
# Refactoring Report

## Summary
- Duration: 2 hours
- Operations: 13 total (4 types)
- Files modified: 18
- Files created: 13 (.tscn + .tres + components)
- Lines reduced: 430 (23%)

## Operations Performed

### Code-Created Objects → Scenes (8)
1. laser_beam.gd: Timer → laser_beam_damage_timer.tscn
2. enemy.gd: Area2D → enemy_detection_area.tscn
...

### Monolithic Scripts → Components (3)
1. player_movement.gd (287 lines) → 4 components (avg 95 lines)
...

### Direct Coupling → Signals (5)
1. base_station → player: has_method → signal
...

### Inline Data → Resources (2)
1. enemy_spawner ENEMY_TYPES → EnemyTypeData .tres
...

## Metrics

### Before
- Total scripts: 24
- Average script size: 156 lines
- Code-created nodes: 8
- Tight couplings: 12
- Inline data blocks: 4

### After
- Total scripts: 31 (+7 components)
- Average script size: 94 lines
- Code-created nodes: 0 ✓
- Tight couplings: 0 ✓
- Inline data blocks: 0 ✓

## Verification Results
- ✓ All visual checks passed
- ✓ All functional tests passed
- ✓ Performance within ±1 FPS
- ✓ Zero new errors/warnings
- ✓ All anti-patterns eliminated

## Recommendations
1. Apply these patterns to new code
2. Add unit tests for components
3. Document signal architecture
4. Create component library for reuse
```

**4. Push and continue:**
```bash
# Push to remote if not already done
git push origin $(git branch --show-current)

# Continue developing on current branch
# Changes are already on your working branch
# Build new features on clean foundation
```

---

## Continuous Verification

### Prevent Regression in Future Development

**1. Pre-commit hook:**
```bash
# .git/hooks/pre-commit

#!/bin/bash
# Detect anti-pattern reintroduction

new_calls=$(git diff --cached --name-only | grep "\.gd$" | \
  xargs git diff --cached | grep "^\+.*\.new()" | \
  grep -E "(Node|Timer|Area)" | wc -l)

if [ $new_calls -gt 0 ]; then
  echo "ERROR: Code-created nodes detected in commit"
  echo "Please use scenes instead of .new()"
  exit 1
fi
```

**2. CI/CD checks** (if applicable):
```yaml
# .github/workflows/godot-quality.yml
name: Code Quality

on: [push, pull_request]

jobs:
  check-anti-patterns:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Check for code-created nodes
        run: |
          count=$(grep -rn "\.new()" --include="*.gd" . | grep -E "(Node|Timer)" | wc -l)
          if [ $count -gt 0 ]; then exit 1; fi
      - name: Check script sizes
        run: |
          large=$(find . -name "*.gd" -exec wc -l {} + | awk '$1 > 150' | wc -l)
          if [ $large -gt 0 ]; then exit 1; fi
```

**3. Documentation:**

Create `ARCHITECTURE.md` to guide future development:
```markdown
# Architecture Guidelines

## Patterns to Follow
- Scene-first design (create .tscn, then add scripts)
- Signal-based communication (use Events.gd)
- Component composition (focused scripts <150 lines)
- Resource-based data (.tres for config/data)

## Patterns to Avoid
- ✗ Node.new() for scene nodes
- ✗ get_node() for cross-tree behavior access
- ✗ has_method() type checking
- ✗ const arrays with game data
- ✗ Scripts >150 lines

## Examples
See `examples/` directory for clean pattern implementations.
```

---

## Troubleshooting

### Issue: Scene Won't Load

**Symptoms:**
- "Failed to load resource" error
- Scene file shows as broken in FileSystem

**Diagnosis:**
```bash
# Validate .tscn syntax
godot --check-only scene.tscn

# Check for common issues:
# - Missing load_steps count
# - Invalid node type
# - Broken ext_resource path
```

**Fix:**
- Re-generate .tscn using templates
- Verify all referenced files exist
- Check format=3 in header

### Issue: Signal Not Connecting

**Symptoms:**
- No error, but callback never fires
- "Signal 'X' not found" warning

**Diagnosis:**
```gdscript
# Add debug logging
func _ready():
    if not _timer.timeout.is_connected(_on_timeout):
        print("ERROR: Signal not connected")
    _timer.timeout.connect(_on_timeout)
    print("Connected successfully")
```

**Fix:**
- Verify signal name spelling
- Check node reference is valid (@onready loaded)
- Ensure callback function exists and has correct signature

### Issue: Null Reference

**Symptoms:**
- "Invalid get index" error
- "Attempt to call function on null instance"

**Diagnosis:**
```gdscript
@onready var _timer: Timer = $Timer

func _ready():
    if not _timer:
        print("ERROR: _timer is null")
        print("Available children:", get_children())
```

**Fix:**
- Verify node path in .tscn file
- Check $NodeName matches actual node name
- Use get_node_or_null() for optional nodes

---

**Use this checklist** in Phase 4 of the refactoring skill to ensure zero regressions and successful completion.
