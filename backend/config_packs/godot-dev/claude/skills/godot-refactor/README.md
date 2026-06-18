# Godot Superpowers - Refactoring

Automatically refactor Godot projects to clean, modular architecture with zero functional changes.

## Quick Start

Navigate to your Godot project directory and use Claude Code:

```bash
cd /path/to/your/godot/project
claude

# Then in Claude Code:
> Use godot-refactoring to analyze this Godot project
```

## What It Does

Detects and fixes 5 types of anti-patterns:

1. **Code-created objects** → Modular component scenes
2. **Monolithic scripts** → Focused components
3. **Tight coupling** → Signal-based communication
4. **Inline data** → Resource files
5. **Conflicting operations** → Clean code

## Features

### Intelligent Node Selection
- 9 decision trees for automatic detection
- 90%+ confidence scoring
- Pattern matching on variables, properties, methods
- 80+ Godot node catalog

### Modular Components
- Zero duplication architecture
- Automatic component library building
- Inspector-configurable presets
- Progressive library growth

### Safety
- Git baseline before changes
- Per-operation validation
- Automatic rollback on failure
- Iron Law: NO functional changes

## Documentation

- [INDEX.md](./INDEX.md) - Navigation guide
- [EXAMPLES.md](./EXAMPLES.md) - Real-world examples
- [SKILL.md](./SKILL.md) - Main workflow
- [docs/](./docs/) - Comprehensive guides

### Key Guides

- [godot-node-reference.md](./docs/godot-node-reference.md) - 80+ nodes
- [node-selection-guide.md](./docs/node-selection-guide.md) - Decision trees
- [scene-reusability-patterns.md](./docs/scene-reusability-patterns.md) - Modular patterns
- [refactoring-operations.md](./docs/refactoring-operations.md) - Step-by-step procedures

## Installation

See [../INSTALLATION.md](../INSTALLATION.md)

## Requirements

- Claude Code CLI with Superpowers
- Godot 4.x projects
- Git for version control
- Standard Unix tools

## Usage

1. Navigate to Godot project
2. Invoke skill in Claude Code
3. Review detected anti-patterns
4. Approve refactoring
5. Skill executes automatically with commits

## Example Transformation

**Before:**
```gdscript
func _ready():
    _damage_timer = Timer.new()
    _damage_timer.wait_time = 0.5
    add_child(_damage_timer)
```

**After:**
```
Components created:
- components/timers/configurable_timer.tscn (reusable)
- components/timers/presets/damage_timer.tres (config)

Code:
@onready var _damage_timer: ConfigurableTimer = $DamageTimer
```

Result: Modular, reusable, zero duplication!

## Statistics

- **12,220+ lines** documentation
- **150+ Godot nodes** documented
- **5 operations** automated
- **Production ready** ✓

## License

MIT - See [../LICENSE](../LICENSE)
