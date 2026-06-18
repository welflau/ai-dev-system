# Editor Position Sync

**Fix position conflicts between Godot editor (.tscn) and code (.gd)**

## Problem

Your background appears at (0, 0) in the editor, but follows the camera at runtime → level design is confusing!

Your enemy spawns at (500, 300) in the editor, but `_ready()` sets `position = Vector2(100, 150)` → which is correct?

**Editor Position Sync** detects and fixes these conflicts automatically.

---

## What It Does

### ✓ Detects Position Conflicts

- Static position assignments in `_ready()` that conflict with .tscn
- Camera-following backgrounds that don't preview correctly
- Parallax layers with mismatched positions
- Every-frame position assignments (critical warnings)

### ✓ Intelligent Classification

- **CONFLICT**: Static position differs between editor and code → sync needed
- **INTENTIONAL_DYNAMIC**: Camera/player following → document, don't break
- **INTENTIONAL_ANIMATION**: Tweens/animations → skip
- **PROCESS_ASSIGNMENT**: Every-frame assignment → critical warning

### ✓ Three Sync Strategies

1. **Code → Editor**: Move position from code to .tscn (WYSIWYG)
2. **Editor → Code**: Keep code position, reset editor to default
3. **Camera-Aware**: Set editor position to camera start for accurate preview

---

## Quick Start

### Installation

```bash
# Clone repository
git clone https://github.com/Asreonn/godot-superpowers.git

# Navigate to your Godot project
cd /path/to/your/godot/project

# Run the skill (via Claude Code)
/editor-position-sync
```

### Usage in Claude Code

```
You: My background follows the camera but appears at (0,0) in the editor

Claude: [Automatically invokes editor-position-sync skill]

=== Editor Position Sync Analysis ===

Project: MyGame

Conflicts detected:
- Camera-following elements: 1
- Static position assignments: 0

Would you like me to:
1. Proceed with automatic sync (recommended)
2. Show detailed breakdown first
3. Cancel

You: 1

[Skill automatically syncs background to camera start position]

✓ Position Sync Complete
✓ Editor now shows background at camera start
✓ Level design preview accurate
```

---

## Examples

### Example 1: Static Position Conflict

**Before:**

enemy.gd:
```gdscript
func _ready():
    position = Vector2(100, 150)
```

enemy.tscn:
```ini
position = Vector2(500, 300)
```

**Problem**: Editor shows (500, 300), runtime shows (100, 150) → confusing!

**After (CODE_TO_EDITOR sync):**

enemy.gd:
```gdscript
func _ready():
    # Position moved to .tscn for editor visibility
    # Was: position = Vector2(100, 150)
```

enemy.tscn:
```ini
position = Vector2(100, 150)
```

**Result**: Editor matches runtime ✓

---

### Example 2: Camera-Following Background

**Before:**

background.gd:
```gdscript
func _process(delta):
    position = camera.position
```

background.tscn:
```ini
position = Vector2(0, 0)
```

**Problem**: Editor shows background at origin, but runtime follows camera → level design is inaccurate!

**After (CAMERA_AWARE sync):**

background.gd:
```gdscript
# EDITOR PREVIEW: Position in .tscn set to camera start position
# for accurate level design preview. At runtime, follows camera dynamically.
func _process(delta):
    position = camera.position
```

background.tscn:
```ini
position = Vector2(512, 300)  # Camera start position
```

**Result**: Editor shows realistic camera view, level design is accurate ✓

---

## Features

### Automatic Detection

- Scans all `.gd` files for position assignments
- Parses all `.tscn` files for position properties
- Extracts context (30 lines) for intelligent classification
- Detects camera-following, player-relative, parallax patterns

### Intelligent Classification

```python
# Detects this as INTENTIONAL_DYNAMIC (skip):
func _process(delta):
    position = camera.position

# Detects this as CONFLICT (sync):
func _ready():
    position = Vector2(100, 150)

# Detects this as INTENTIONAL_ANIMATION (skip):
tween.tween_property(self, "position", target, 1.0)
```

### Camera Start Detection

Automatically finds camera start position from:
- Main scene `Camera2D` node position
- Player spawn position (if camera follows player)
- Default viewport center (fallback)

### Safe Execution

- Git commit after each sync operation
- Automatic validation test after each commit
- Auto-rollback on test failure
- Descriptive commit messages

---

## When to Use

### ✓ Use This Skill When:

- "My nodes are in the wrong place at runtime"
- "Editor shows one position, game shows another"
- "My background jumps when the game starts"
- "Camera-following elements don't preview correctly"
- "I can't trust the editor preview for positioning"

### ✗ Don't Use When:

- Positions are already synchronized
- You want to add new positioning features (use different skill)
- Issue is not related to position conflicts

---

## Workflow

### Phase 1: Detection (Automatic)

1. Scan project for position assignments
2. Parse .tscn files for positions
3. Classify each conflict intelligently
4. Generate conflict manifest
5. Present findings to user

### Phase 2: Synchronization (Semi-Automatic)

1. User approves sync
2. For each conflict:
   - Select strategy (CODE_TO_EDITOR, EDITOR_TO_CODE, CAMERA_AWARE)
   - Execute sync operation
   - Git commit
   - Run validation test
   - Continue to next conflict

### Phase 3: Verification (Automatic)

1. Open project in Godot
2. Visual verification of synced positions
3. Runtime verification (quick play test)
4. Generate completion report

---

## Configuration

### Detection Sensitivity

Default: Detect all position assignments in `_ready()`, `_init()`, `_process()`

Custom:
```bash
# Only detect static conflicts (skip dynamic)
SYNC_MODE=static ./sync.sh

# Include global_position
SYNC_PROPERTIES="position,global_position" ./sync.sh
```

### Strategy Selection

Default: Auto-select strategy based on classification

Manual:
```bash
# Force CODE_TO_EDITOR for all conflicts
SYNC_STRATEGY=code_to_editor ./sync.sh
```

---

## Integration

### With godot-refactoring

Best practice workflow:

1. Run `godot-refactoring` first (extract code-created objects to scenes)
2. Run `editor-position-sync` (sync positions)
3. Result: Clean, modular, WYSIWYG project

### With scene-hierarchy-cleaner (future skill)

1. Organize scene hierarchy
2. Sync positions
3. Result: Organized + accurate

---

## Troubleshooting

### "No conflicts detected" but positions are wrong

- Check if positions are in `_process()` (intentional dynamic, not conflict)
- Verify .tscn file exists for script
- Check if position property is named differently (`global_position`)

### "Sync broke my camera following"

- Re-run with `--dry-run` to see what would be synced
- Manually classify as INTENTIONAL_DYNAMIC
- Report issue (skill should auto-detect camera following)

### "Git commit failed"

- Ensure you have a git repository initialized
- Check for uncommitted changes (skill creates baseline)
- Verify write permissions

---

## Technical Details

### .tscn Position Format

```ini
[node name="NodeName" type="Node2D"]
position = Vector2(100.0, 150.0)
```

### Position Assignment Detection

```python
# Regex pattern
r'position\s*=\s*Vector2\s*\(\s*[0-9.+-]+\s*,\s*[0-9.+-]+\s*\)'

# Context extraction (30 lines before/after)
grep -B30 -A30 "position\s*=" script.gd
```

### Classification Algorithm

```python
if "tween" in context:
    return INTENTIONAL_ANIMATION
elif "camera" in context:
    return INTENTIONAL_DYNAMIC
elif "_process" in context:
    return PROCESS_ASSIGNMENT
elif "_ready" in context and tscn_position != code_position:
    return CONFLICT
```

---

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md) in repository root.

### Adding New Sync Strategies

1. Create strategy function in `sync-strategies.md`
2. Add classification logic in `position-detection-patterns.md`
3. Update `SKILL.md` with strategy documentation
4. Add tests and examples

---

## License

MIT License - see [LICENSE](../LICENSE)

---

## Acknowledgments

Created as part of **Godot Superpowers** skill collection.

Inspired by user feedback: "My backgrounds follow the camera but appear at (0,0) in the editor - I can't design levels accurately!"

---

## Links

- Repository: https://github.com/Asreonn/godot-superpowers
- Issues: https://github.com/Asreonn/godot-superpowers/issues
- Documentation: [docs/](docs/)
- Related Skills:
  - [godot-refactoring](../godot-refactoring/)
  - [project-structure-organizer](../project-structure-organizer/)

---

**Fix position conflicts. Trust your editor preview. Build with confidence.**
