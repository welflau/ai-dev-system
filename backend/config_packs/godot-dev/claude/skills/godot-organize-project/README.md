# Godot Superpowers - Project Structure

Scan and intelligently reorganize Godot project folder structure for optimal organization.

## Quick Start

Navigate to your Godot project directory and use Claude Code:

```bash
cd /path/to/your/godot/project
claude

# Then in Claude Code:
> Use project-structure-organizer to analyze this Godot project
```

## What It Does

1. **Analyzes** current project structure
2. **Proposes** optimal reorganization
3. **Moves** files intelligently by type and category
4. **Updates** all internal references
5. **Validates** all scenes and scripts still work

## Proposed Structure

```
res://
├── scripts/ (ui, gameplay, entities, managers, utils)
├── scenes/ (ui, levels, entities)
├── assets/ (sprites, audio, fonts, shaders)
├── resources/ (configs, data, materials)
└── components/ (from godot-refactoring integration)
```

## Features

- **Automatic analysis** of current structure
- **Smart categorization** by file type and usage
- **Reference auto-updating** in all files
- **Full rollback** support via git
- **Integration** with godot-refactoring skill

## Safety

- Git backup before reorganization
- Reference verification
- Scene integrity checking
- Complete rollback available

## Usage

1. Navigate to Godot project
2. Invoke skill
3. Review proposed structure
4. Approve reorganization
5. Skill executes with git commit

## Requirements

- Claude Code CLI with Superpowers
- Godot 4.x projects
- Git for version control
- Standard Unix tools

## Integration

Works perfectly with **godot-refactoring** skill:

1. Run godot-refactoring → Creates components/
2. Run project-structure-organizer → Organizes rest
3. Result: Fully organized, modular project

## Documentation

See [SKILL.md](./SKILL.md) for complete documentation.

## Installation

See [../INSTALLATION.md](../INSTALLATION.md)

## License

MIT - See [../LICENSE](../LICENSE)
