# API Search Reference

Query UE5 Python API definitions from `unreal.py` stub files using fuzzy or exact search.

## Script Location

`scripts/api-search.py`

## Requirements

- **ripgrep (rg)**: Required for fuzzy search. Install via `scoop install ripgrep` (Windows) or `brew install ripgrep` (macOS).

## Usage

```bash
# Fuzzy search (default) - searches names AND signatures
python scripts/api-search.py actor
python scripts/api-search.py inputmapping

# Chained fuzzy search - all terms must match
python scripts/api-search.py actor render
python scripts/api-search.py inputmapping context

# Query a class definition
python scripts/api-search.py unreal.InputMappingContext

# Query a specific member
python scripts/api-search.py unreal.Actor.on_destroyed
python scripts/api-search.py unreal.GameplayTag.import_text

# Wildcard member search
python scripts/api-search.py unreal.Actor.*location*

# Query a module-level function
python scripts/api-search.py unreal.log

# Multiple queries with pipe
python scripts/api-search.py unreal.Actor|Pawn|log

# Fuzzy search with filters
python scripts/api-search.py -c actor          # classes only
python scripts/api-search.py -m location       # methods only
python scripts/api-search.py -e collision      # enum values only

# Specify stub file explicitly
python scripts/api-search.py --input /path/to/unreal.py unreal.Actor
```

## Arguments

| Argument | Short | Required | Description |
|----------|-------|----------|-------------|
| `query` | | Yes | Search term(s); multiple terms filter progressively |
| `--input` | `-i` | No | Path to unreal.py stub. Auto-detects from `Intermediate/PythonStub/unreal.py` |
| `--class-only` | `-c` | No | Fuzzy search: only show matching classes |
| `--method-only` | `-m` | No | Fuzzy search: only show matching methods/functions |
| `--enum-only` | `-e` | No | Fuzzy search: only show matching enum values |

## Output Formats

- **Fuzzy search**: Results grouped by type (Classes, Methods, Properties, Enum Values) with class inheritance
- **Exact class query**: Class signature summary with all members
- **Exact member query**: Full definition of the specific member
- **Wildcard member search**: Matching member signatures within that class
- **No match**: Exits with code 1 and prints error to stderr

## Features

- **Signature matching**: Search terms match method parameters, return types, and property types
  - Example: `inputmapping` finds methods with `InputMappingContext` parameters
- **Word-boundary matching**: `actor` matches `Actor`, `ActorComponent`, `MyActor` but not `factory`
- **Greedy matching**: `inputmappingcontext` matches `InputMappingContext`
- **Class inheritance**: Results show `class Actor(Object):` instead of just `class Actor:`

## Example Output

### Fuzzy Search

```
$ python scripts/api-search.py actor

=== Matching Classes (15) ===

class Actor(Object):
    """Actor is the base class for all objects..."""

class ActorComponent(Object):
    """ActorComponent is the base class..."""

=== Matching Methods (42 in 8 classes) ===

class Actor(Object):
    def get_actor_location(self) -> Vector
    def set_actor_location(self, new_location: Vector, ...) -> bool
...
```

### Chained Fuzzy Search with Signature Matching

```
$ python scripts/api-search.py inputmapping register

=== Matching Methods (5 in 1 classes) ===

class EnhancedInputUserSettings(SaveGame):
    def register_input_mapping_context(self, imc: InputMappingContext) -> bool
    def register_input_mapping_contexts(self, mapping_contexts: Set[InputMappingContext]) -> bool
...
```
