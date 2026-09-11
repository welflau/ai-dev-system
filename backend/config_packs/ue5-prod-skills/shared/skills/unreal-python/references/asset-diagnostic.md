# Asset Diagnostic Module API Reference

## Usage via Python API

For asset diagnostics, you can use the `asset_diagnostic` module directly via `editor.execute()`:

```python
import asset_diagnostic
asset_diagnostic.diagnose("/Game/Maps/TestLevel", verbose=True)
```

## Advanced: Module API

UE5 Asset Diagnostic Module - A modular diagnostic tool for analyzing UE5 assets.

> **Important:** This module must be executed in the Unreal Engine Python environment. Use **ue-mcp**'s `editor.execute` tool to send code snippets or scripts to the running UE5 Editor.

This section documents the underlying Python module for custom integration.

## Quick Start

```python
# Script or code to run via editor.execute
import asset_diagnostic

# Diagnose current level (issues only by default)
result = asset_diagnostic.diagnose()

# Diagnose with full analysis output
result = asset_diagnostic.diagnose(verbose=True)

# Diagnose specific asset
result = asset_diagnostic.diagnose("/Game/Maps/MyLevel")

# Diagnose selected assets in Content Browser
results = asset_diagnostic.diagnose_selected()
```



---

## Main Functions

### diagnose()

```python
def diagnose(asset_path: str = None, verbose: bool = False) -> DiagnosticResult
```

Run diagnostics on an asset.

**Parameters:**
- `asset_path`: Path to the asset. If `None`, diagnoses current level.
- `verbose`: If `True`, print comprehensive analysis and metadata. If `False` (default), print only issues.

**Returns:** `DiagnosticResult` or `None` if no diagnostic available.

### diagnose_current_level()

```python
def diagnose_current_level(verbose: bool = False) -> DiagnosticResult
```

Run diagnostics on the currently open level.

**Parameters:**
- `verbose`: If `True`, print comprehensive analysis and metadata. If `False` (default), print only issues.

**Returns:** `DiagnosticResult` or `None` if no level is open.

### diagnose_selected()

```python
def diagnose_selected(verbose: bool = False) -> List[DiagnosticResult]
```

Run diagnostics on assets selected in Content Browser.

**Parameters:**
- `verbose`: If `True`, print comprehensive analysis and metadata. If `False` (default), print only issues.

**Returns:** List of `DiagnosticResult`.

---

## Output Modes

### Default Mode (`verbose=False`)

Prints only issues found - concise output suitable for quick checks:

```
================================================================================
DIAGNOSTIC REPORT: PunchingBagLevel
================================================================================
Asset Path: /Game/Maps/PunchingBagLevel
Asset Type: Level

## ISSUES FOUND
  Errors: 0, Warnings: 2, Total: 2

### WARNINGS (2)
  [1] DemoRobot_JabDemo
      [Physics] Actor may be floating (no support chain to ground)
      Evidence:
        - Position: (70, -150, 90)
        - Class: BP_DemoRobot_C
        ...
      Suggestion: Move actor to contact a supported surface
================================================================================
[WARN] Diagnostic completed with warnings
================================================================================
```

### Verbose Mode (`verbose=True`)

Prints comprehensive level analysis followed by full report with metadata:

```
================================================================================
LEVEL ANALYSIS
================================================================================
## ACTOR SUMMARY
Total actors: 13
Tangible actors: 8

## LEVEL DIMENSIONS
Size: 1200 x 800 x 300 units

## ACTOR REGISTRY (8 tangible)
------------------------------------------------------------
[1] Floor
    Type: StaticMeshActor
    Size: 500 x 500 x 10 (Large)
    Position: (0, 0, 0)
...

## SPATIAL RELATIONSHIPS
FROM: PlayerStart
  -> Floor: 100u South, Same Level
  -> Enemy1: 250u North, Above
...

================================================================================
DIAGNOSTIC REPORT: PunchingBagLevel
================================================================================
## ASSET INFO
  total_actors: 13
  tangible_actors: 8
  player_start_count: 1
  ...

## ISSUES FOUND
  ...
```

---

## Core Types

### AssetType (Enum)

Supported UE5 asset types:

```python
class AssetType(Enum):
    LEVEL = "Level"
    BLUEPRINT = "Blueprint"
    MATERIAL = "Material"
    MATERIAL_INSTANCE = "MaterialInstance"
    STATIC_MESH = "StaticMesh"
    SKELETAL_MESH = "SkeletalMesh"
    TEXTURE = "Texture"
    ANIMATION = "Animation"
    SOUND = "Sound"
    PARTICLE_SYSTEM = "ParticleSystem"
    WIDGET_BLUEPRINT = "WidgetBlueprint"
    DATA_ASSET = "DataAsset"
    UNKNOWN = "Unknown"
```

### IssueSeverity (Enum)

```python
class IssueSeverity(Enum):
    ERROR = "ERROR"      # Critical issue that will cause problems
    WARNING = "WARNING"  # Potential issue that should be addressed
    INFO = "INFO"        # Informational note
    SUGGESTION = "SUGGESTION"  # Optimization or best practice
```

### DiagnosticIssue (Dataclass)

```python
@dataclass
class DiagnosticIssue:
    severity: IssueSeverity
    category: str              # e.g., "Physics", "Gameplay", "Position"
    message: str
    actor: Optional[str]       # Actor name/label
    evidence: Optional[List[str]]  # Supporting evidence lines
    suggestion: Optional[str]  # How to fix or improve
```

### DiagnosticResult (Dataclass)

```python
@dataclass
class DiagnosticResult:
    asset_path: str
    asset_type: AssetType
    asset_name: str
    issues: List[DiagnosticIssue]
    metadata: Dict[str, Any]
    summary: Optional[str]

    # Properties
    error_count: int
    warning_count: int
    has_errors: bool
    has_warnings: bool

    # Methods
    def add_issue(severity, category, message, actor=None, evidence=None, suggestion=None)
    def print_report(verbose: bool = False)
```

---

## Level Diagnostic Checks

The `LevelDiagnostic` performs the following checks:

| Check | Severity | Description |
|-------|----------|-------------|
| PlayerStart Missing | WARNING | No PlayerStart actor found |
| PlayerStart Low Z | WARNING | PlayerStart below -1000 units |
| Multiple PlayerStarts | INFO | More than one PlayerStart |
| Actor at Origin | INFO | Actor at (0, 0, 0) |
| Actor Extreme Position | WARNING | Position exceeds 1,000,000 units |
| Overlapping Actors | INFO | Same-class actors overlapping |
| Floating Objects | WARNING | Actor not connected to ground |
| Character Orientation | WARNING | Pitch/roll exceeds +/-5 degrees |

---

## Utility Functions

```python
def detect_asset_type(asset_path: str) -> AssetType
def get_current_level_path() -> Optional[str]
def get_selected_assets() -> List[str]
def load_asset(asset_path: str) -> Optional[object]
def get_asset_references(asset_path: str) -> Dict[str, List[str]]
```

---

## Creating Custom Diagnostics

```python
from asset_diagnostic import BaseDiagnostic, AssetType, DiagnosticResult, IssueSeverity, register_diagnostic

class MyCustomDiagnostic(BaseDiagnostic):
    @property
    def supported_types(self):
        return [AssetType.BLUEPRINT]

    def diagnose(self, asset_path: str, verbose: bool = False) -> DiagnosticResult:
        result = self._create_result(asset_path, AssetType.BLUEPRINT)

        # Perform checks...
        result.add_issue(
            IssueSeverity.WARNING,
            "MyCategory",
            "Issue description",
            evidence=["Evidence line 1"],
            suggestion="How to fix"
        )

        return result

# Register
register_diagnostic(MyCustomDiagnostic())
```

---

## Metadata Keys (Level Diagnostic)

| Key | Type | Description |
|-----|------|-------------|
| `total_actors` | int | Total actors in level |
| `tangible_actors` | int | Actors with physical presence |
| `player_start_count` | int | PlayerStart actors |
| `ground_actors_count` | int | Detected ground surfaces |
| `support_chain_max_depth` | int | Max support chain depth |
| `floating_actors_count` | int | Unsupported actors |
| `level_bounds` | dict | Min/max coordinates |
| `level_dimensions` | dict | Width/length/height |
| `level_center` | tuple | Center point |
