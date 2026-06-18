# Godot Refactoring Skill - File Index

Quick navigation guide for the godot-refactoring skill.

---

## Start Here

**New to the skill?** Read these in order:
1. **README.md** - Overview and quick start (5 min read)
2. **EXAMPLES.md** - Real-world examples (10 min read)
3. **SKILL.md** - Main workflow (20 min read)

**Ready to use?** Jump to:
- **SKILL.md** - Start refactoring workflow

**Need reference?** See below for specific topics.

---

## Core Files

### SKILL.md (725 lines)
**Purpose**: Main skill file with complete workflow

**Contents**:
- Core principles & Iron Law
- When to use this skill (decision flowchart)
- 4 phases: Analysis, Refactoring, Commits, Verification
- 4 operations: Scenes, Scripts, Signals, Data
- Red flags & rationalization warnings
- Quick reference tables

**Use when**: Starting a refactoring session

**Read time**: 20 minutes

---

## Core Reference Files (NEW)

### godot-node-reference.md (4200+ lines)
**Purpose**: Comprehensive Godot 4.x node catalog for intelligent selection

**Contents**:
- 80+ essential Godot 4.x nodes organized by category
- 15 categories: Core Base, 2D Visual, Physics, Lighting, Particles, Navigation, 3D, Audio, UI, Containers, Utilities, Viewports
- For each node: Purpose, properties, use cases, patterns, tscn template, related nodes
- Quick node selection reference
- Complete API information

**Categories**:
- Core Base Nodes (Node, Node2D, Node3D, CanvasItem)
- 2D Visual (Sprite2D, AnimatedSprite2D, Line2D, Polygon2D, etc.)
- 2D Physics (RigidBody2D, CharacterBody2D, StaticBody2D, Area2D, etc.)
- 2D Lighting & Particles (PointLight2D, DirectionalLight2D, GPUParticles2D, CPUParticles2D)
- 2D Navigation (NavigationRegion2D, NavigationAgent2D, NavigationLink2D)
- 3D Nodes (MeshInstance3D, Camera3D, RigidBody3D, Light3D, etc.)
- Audio (AudioStreamPlayer, AudioStreamPlayer2D, AudioStreamPlayer3D)
- UI/Control (Button, Label, LineEdit, TextEdit, ProgressBar, etc.)
- Containers (HBoxContainer, VBoxContainer, GridContainer, TabContainer, ScrollContainer)

**Use when**: Operation A - Intelligent node selection during refactoring

**Read time**: 30 minutes (reference specific nodes as needed)

---

### node-selection-guide.md (1100+ lines)
**Purpose**: Intelligent node selection system with confidence scoring

**Contents**:
- 9 comprehensive decision trees (Timing, 2D Visual, Physics, Detection, Audio, UI, Lighting, Particles, Navigation)
- Variable name pattern matching heuristics
- Property assignment analysis patterns
- Method call analysis patterns
- Parent node context analysis
- **Confidence scoring system** (50-99%) with automatic decision thresholds
- Safe fallback strategies for uncertain cases
- 4 detailed heuristic examples with full scoring
- Algorithm for automated intelligent selection

**Decision Trees**:
- Timing/Delay Operations (Timer, Tween, await, deferred)
- Visual 2D Nodes (Static vs Animated)
- Physics Bodies (CharacterBody2D, RigidBody2D, StaticBody2D, Area2D)
- Detection/Trigger Areas
- Audio Playback (non-spatial, 2D spatial, 3D spatial)
- UI Elements (text, input, buttons, layouts)
- Lighting (PointLight2D, DirectionalLight2D)
- Particles (GPUParticles2D vs CPUParticles2D)
- Navigation/AI (NavigationRegion, NavigationAgent)

**Use when**: Operation A - Analyzing code-created nodes for type selection

**Read time**: 25 minutes (reference trees as needed)

---

### scene-reusability-patterns.md (900+ lines)
**Purpose**: Modular component library patterns for zero duplication

**Contents**:
- Component library directory structure conventions
- Step-by-step pattern implementation (7 steps)
- Resource config class generation
- Configurable component script pattern
- Base scene creation templates
- Preset resource generation
- **Automatic library building workflow**:
  - First detection → full component base + preset
  - Second detection → reuse base + new preset
  - Third detection → new category + base + preset
- Advanced patterns (hierarchical configs, component factory, validation)
- Anti-patterns to avoid
- Integration with Operation A workflow
- Configuration best practices
- Testing examples

**Workflow**:
1. **First Timer Detection**: Create base + preset → components/timers/
2. **Second Timer Detection**: Reuse base, create new preset
3. **First Area Detection**: Create base + preset → components/areas/
4. Result: Modular, organized, zero duplication

**Example Result**:
```
components/
├─ timers/
│  ├─ configurable_timer.tscn (1 reusable base)
│  ├─ configurable_timer.gd
│  ├─ timer_config.gd
│  └─ presets/ (damage_timer.tres, cooldown_timer.tres, etc.)
├─ areas/
│  ├─ configurable_area.tscn (1 reusable base)
│  └─ presets/ (detection_zone.tres, damage_zone.tres, etc.)
```

**Use when**: Operation A - Component organization and automatic library building

**Read time**: 20 minutes (reference patterns as needed)

---

## Supporting Documentation

### anti-patterns-detection.md (553 lines)
**Purpose**: Detection patterns and analysis tools

**Contents**:
- Code-created objects detection (grep patterns)
- Monolithic scripts detection (line counting)
- Tight coupling detection (get_node, has_method)
- Inline data detection (const arrays)
- Deep inheritance analysis
- False positive filtering
- Detection output format
- Shell script: complete detection

**Use when**: Phase 1 - Analysis & Baseline

**Key sections**:
- Lines 1-100: Code-created objects
- Lines 101-150: Monolithic scripts
- Lines 151-250: Tight coupling
- Lines 251-350: Inline data
- Lines 450-553: Detection script

**Read time**: 15 minutes (reference as needed)

---

### tscn-generation-guide.md (742 lines)
**Purpose**: Complete .tscn file format reference

**Contents**:
- .tscn file format basics (INI-like syntax)
- Header section (gd_scene, load_steps, uid)
- Node section (types, properties, hierarchy)
- Property types (strings, numbers, vectors, etc.)
- Sub-resources (shapes, materials)
- Complete templates by node type (Timer, Area2D, Sprite2D, etc.)
- Signal connections
- Scene instancing
- Common mistakes
- Validation checklist
- Code generation helper (Python)
- Real-world examples

**Use when**: Operation A - Extract Code-Created Objects

**Key sections**:
- Lines 1-100: Format basics
- Lines 101-200: Node and property types
- Lines 201-500: Templates (Timer, Area2D, Sprite2D, etc.)
- Lines 501-650: Advanced (sub-resources, instancing)
- Lines 651-742: Validation & examples

**Read time**: 20 minutes (reference as needed)

---

### godot-best-practices.md (792 lines)
**Purpose**: Clean architecture patterns reference

**Contents**:
- Core principles (scene-first, signals, composition)
- Scene-first design pattern
- Signal-based communication (Events.gd)
- Component composition pattern
- Resource-based data pattern
- Single responsibility principle
- Naming conventions (files, classes, variables, signals)
- @onready best practices
- Script size guidelines (80-120 lines optimal)
- Architecture patterns (game manager, state machine, object pool)
- Testing and validation
- Common patterns summary table

**Use when**: Throughout refactoring for reference

**Key sections**:
- Lines 1-100: Scene-first design
- Lines 101-200: Signal-based communication
- Lines 201-300: Component composition
- Lines 301-400: Resource-based data
- Lines 401-500: Naming conventions
- Lines 501-600: @onready practices
- Lines 601-700: Architecture patterns
- Lines 701-792: Common patterns table

**Read time**: 25 minutes (reference as needed)

---

### refactoring-operations.md (978 lines)
**Purpose**: Detailed step-by-step procedures

**Contents**:
- **Operation A**: Extract Code-Created Objects to .tscn (250 lines)
  - Detection, analysis, generation, code update, scene integration
  - Special cases (complex setup, conditional creation, multiple instances)

- **Operation B**: Split Monolithic Scripts (200 lines)
  - Detection, analysis, planning, extraction, signal migration
  - Component creation and interface design

- **Operation C**: Implement Signal-Based Decoupling (180 lines)
  - Events.gd setup, signal definition, emitter/receiver updates
  - Common coupling patterns

- **Operation D**: Extract Data to .tres Resources (150 lines)
  - Resource class creation, .tres file generation, code updates
  - Inspector configuration, advanced resource inheritance

- **Common Challenges** (150 lines)
  - Circular dependencies, nested nodes, dynamic creation, order issues

**Use when**: Phase 2 - Automatic Refactoring

**Key sections**:
- Lines 1-250: Operation A (extract scenes)
- Lines 251-450: Operation B (split scripts)
- Lines 451-630: Operation C (signal decoupling)
- Lines 631-780: Operation D (extract data)
- Lines 781-978: Common challenges

**Read time**: 30 minutes (reference specific operations as needed)

---

### verification-checklist.md (747 lines)
**Purpose**: Testing, validation, and rollback

**Contents**:
- Pre-refactoring baseline (git, screenshots, console, performance, behavior)
- Per-operation verification (syntax, references, behavior)
- Post-refactoring complete verification (visual, functional, performance)
- Regression handling (identify, isolate, analyze, fix)
- Rollback procedure (when and how)
- Success criteria checklist
- Post-success steps (final commit, completion tag, report)
- Continuous verification (pre-commit hooks, CI/CD)
- Troubleshooting (scene loading, signals, null references)

**Use when**:
- Before Phase 1 - Establish baseline
- After each operation - Verify
- Phase 4 - Final verification

**Key sections**:
- Lines 1-100: Pre-refactoring baseline
- Lines 101-200: Per-operation verification
- Lines 201-400: Complete verification
- Lines 401-500: Regression handling
- Lines 501-600: Rollback procedure
- Lines 601-747: Success criteria & troubleshooting

**Read time**: 20 minutes (reference specific sections as needed)

---

## Additional Resources

### README.md (82 lines)
**Quick overview and getting started guide**

Sections:
- Overview (what the skill does)
- Quick start (how to invoke)
- Files (what's included)
- Usage (4 phases summary)
- Integration (with other skills)
- Success criteria

Read time: 5 minutes

---

### EXAMPLES.md (393 lines)
**Real-world refactoring examples**

Examples:
1. Simple Timer Refactoring (before/after code)
2. Signal Decoupling (base_station → player)
3. Monolithic Script Split (287 → 98 lines)
4. Data Extraction to Resources
5. Full Project Refactoring (space shooter game)

Each example shows:
- Before code (anti-pattern)
- Detection phase
- Refactoring steps
- After code (clean pattern)
- Git commits
- Outcomes

Read time: 15 minutes

---

### IMPLEMENTATION_SUMMARY.md
**This implementation report**

Sections:
- Overview of implementation
- Files created (descriptions)
- Skill capabilities (4 operations)
- Four phase workflow
- Key features (safety, automation, quality)
- Technical implementation details
- Testing strategy
- Integration with Superpowers
- Expected outcomes
- File statistics
- Success metrics
- Next steps

Read time: 10 minutes

---

### validate-skill.sh
**Automated validation script**

Purpose: Verify all skill files are present and valid

Usage:
```bash
bash ~/.config/opencode/skills/godot-refactoring/validate-skill.sh
```

Output:
- File presence checks (✓/✗)
- YAML frontmatter validation
- Line counts
- File sizes
- Overall PASS/FAIL

Run time: <1 second

---

## Reading Order Recommendations

### For Quick Start (30 minutes)
1. README.md (5 min)
2. EXAMPLES.md - Example 1 & 6 (10 min) ← See modular patterns
3. SKILL.md - Overview + Phase 1 (15 min)

### For Complete Understanding (2.5 hours)
1. README.md (5 min)
2. EXAMPLES.md (20 min) ← Includes new modular examples
3. SKILL.md (20 min)
4. godot-node-reference.md - quick scan by category (20 min) ← NEW
5. node-selection-guide.md - decision trees section (15 min) ← NEW
6. scene-reusability-patterns.md - overview + examples (15 min) ← NEW
7. anti-patterns-detection.md - scan sections (15 min)
8. tscn-generation-guide.md - basic templates (20 min)
9. godot-best-practices.md - core principles (20 min)
10. refactoring-operations.md - Operation A in detail (15 min) ← Uses all 3 new guides
11. verification-checklist.md - success criteria (10 min)

### For Reference During Refactoring
Keep these open in tabs:
- SKILL.md (main workflow)
- anti-patterns-detection.md (grep patterns)
- tscn-generation-guide.md (templates)
- verification-checklist.md (testing)

Jump to operations in refactoring-operations.md as needed.

---

## Topic Index

**Need to...** → **See file** → **Section/Lines**

### Intelligent Node Selection (NEW)
- Understand decision trees → node-selection-guide.md → Lines 1-300
- Apply confidence scoring → node-selection-guide.md → Lines 400-700
- See heuristic examples → node-selection-guide.md → Lines 750-900
- Reference node types → godot-node-reference.md → All sections

### Component Library Patterns (NEW)
- Learn modular patterns → scene-reusability-patterns.md → Lines 1-200
- See pattern implementation → scene-reusability-patterns.md → Lines 200-600
- Understand auto-building → scene-reusability-patterns.md → Lines 100-150
- See real examples → EXAMPLES.md → Example 6

### Detection & Analysis
- Detect code-created objects → anti-patterns-detection.md → Lines 1-100
- Detect monolithic scripts → anti-patterns-detection.md → Lines 101-150
- Detect tight coupling → anti-patterns-detection.md → Lines 151-250
- Detect inline data → anti-patterns-detection.md → Lines 251-350

### File Generation
- Generate .tscn files → tscn-generation-guide.md → Lines 201-500
- Generate .tres files → refactoring-operations.md → Lines 631-780
- Validate file format → tscn-generation-guide.md → Lines 651-700

### Refactoring Operations
- Extract scenes → refactoring-operations.md → Lines 1-250
- Split scripts → refactoring-operations.md → Lines 251-450
- Decouple via signals → refactoring-operations.md → Lines 451-630
- Extract data → refactoring-operations.md → Lines 631-780

### Best Practices
- Scene-first design → godot-best-practices.md → Lines 1-100
- Signal architecture → godot-best-practices.md → Lines 101-200
- Component composition → godot-best-practices.md → Lines 201-300
- Resource data → godot-best-practices.md → Lines 301-400
- Naming conventions → godot-best-practices.md → Lines 401-500

### Verification
- Pre-refactoring baseline → verification-checklist.md → Lines 1-100
- Per-operation checks → verification-checklist.md → Lines 101-200
- Final verification → verification-checklist.md → Lines 201-400
- Rollback procedure → verification-checklist.md → Lines 501-600

### Troubleshooting
- Scene won't load → verification-checklist.md → Lines 701+
- Signal not connecting → verification-checklist.md → Lines 701+
- Null references → verification-checklist.md → Lines 701+
- Common mistakes → tscn-generation-guide.md → Lines 701-730

### Examples
- Timer extraction → EXAMPLES.md → Example 1
- Signal decoupling → EXAMPLES.md → Example 2
- Script splitting → EXAMPLES.md → Example 3
- Data extraction → EXAMPLES.md → Example 4
- Full project → EXAMPLES.md → Example 5

---

## File Statistics Summary

```
File                              Lines  Purpose
────────────────────────────────────────────────────────────────
SKILL.md                          725    Main workflow & phases
anti-patterns-detection.md        553    Detection patterns
tscn-generation-guide.md          800    File format + components
godot-best-practices.md           792    Clean patterns
refactoring-operations.md         1100   Enhanced operations (A-D)
verification-checklist.md         747    Testing & validation
godot-node-reference.md           4200+  Node catalog (80+ nodes)
node-selection-guide.md           1100+  Intelligent selection system
scene-reusability-patterns.md     900+   Modular component patterns
README.md                         82     Quick start
EXAMPLES.md                       600+   Real-world + modular examples
IMPLEMENTATION_SUMMARY.md         200+   Implementation report
INDEX.md                          -      This file
validate-skill.sh                 -      Validation script
────────────────────────────────────────────────────────────────
Total                             11,799+
```

---

## Quick Command Reference

```bash
# Validate skill installation
bash ~/.config/opencode/skills/godot-refactoring/validate-skill.sh

# View skill files
ls -lh ~/.config/opencode/skills/godot-refactoring/

# Read a specific file
cat ~/.config/opencode/skills/godot-refactoring/README.md

# Search across all files
grep -rn "pattern" ~/.config/opencode/skills/godot-refactoring/

# Line count
wc -l ~/.config/opencode/skills/godot-refactoring/*.md
```

---

**Last Updated**: 2026-02-02
**Skill Version**: 1.0
**Status**: Production Ready
