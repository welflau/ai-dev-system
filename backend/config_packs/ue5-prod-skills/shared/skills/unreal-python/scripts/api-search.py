#!/usr/bin/env python3
"""
UE5 API Search - Query class or function definitions from unreal.py stub files.

Usage:
    python api-search.py actor                         # Fuzzy search (default)
    python api-search.py Actor                         # Fuzzy search (case-insensitive)
    python api-search.py get_actor                     # Fuzzy search for methods
    python api-search.py unreal.Actor                  # Exact class query (with unreal. prefix)
    python api-search.py unreal.Actor.on_destroyed     # Exact member query
    python api-search.py unreal.Actor.*location*       # Wildcard member search
    python api-search.py unreal.log                    # Exact function query
    python api-search.py --input /path/to/unreal.py actor

Query Types:
    - Fuzzy search (DEFAULT): Any string without 'unreal.' prefix
      Examples: 'actor', 'Actor', 'location', 'get_actor', 'spawn'
      Returns all matching classes and members across the entire API

    - Exact class query: 'unreal.ClassName' (requires unreal. prefix)
      Example: 'unreal.Actor'
      Returns class signature summary grouped by Properties/Methods/etc.

    - Exact member query: 'unreal.ClassName.member_name'
      Example: 'unreal.Actor.on_destroyed'
      Returns full definition of the specific member

    - Wildcard member search: 'unreal.ClassName.*pattern*'
      Example: 'unreal.Actor.*location*'
      Returns matching member signatures within that class

    - Exact function query: 'unreal.function_name'
      Example: 'unreal.log'
      Returns full function definition
"""

import argparse
import fnmatch
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Add lib to path (unreal-python/scripts/ -> unreal-python/lib/)
_lib_path = Path(__file__).resolve().parent.parent / "lib"
if str(_lib_path) not in sys.path:
    sys.path.insert(0, str(_lib_path))

from unreal_python_utils import find_ue5_project_root


def find_stub_file(input_path=None):
    """Find the unreal.py stub file.

    Search order:
    1. Explicit --input path if provided
    2. Search upward from current working directory for UE5 project root
    3. Search upward from script's own directory for UE5 project root
    """
    if input_path:
        input_path = input_path.strip()
        if os.path.exists(input_path):
            return input_path
        raise FileNotFoundError(f"Stub file not found: {input_path}")

    # Search upward from current working directory for UE5 project root
    project_root = find_ue5_project_root(Path.cwd())
    if project_root:
        stub_path = project_root / 'Intermediate' / 'PythonStub' / 'unreal.py'
        if stub_path.exists():
            return str(stub_path)

    # Search upward from script's own directory for UE5 project root
    script_dir = Path(__file__).parent.resolve()
    project_root = find_ue5_project_root(script_dir)
    if project_root:
        stub_path = project_root / 'Intermediate' / 'PythonStub' / 'unreal.py'
        if stub_path.exists():
            return str(stub_path)

    raise FileNotFoundError(
        "Cannot find unreal.py stub file. "
        "Use --input to specify path, or run from within a UE5 project directory."
    )


def is_fuzzy_query(query):
    """Check if query is a fuzzy search.

    Default behavior is fuzzy search. Only explicit unreal. prefix triggers exact query.
    Examples of fuzzy: 'actor', 'Actor', 'location', 'get_actor'
    Examples of exact: 'unreal.Actor', 'unreal.Actor.on_destroyed'
    """
    # Only unreal. prefix triggers exact query mode
    if query.startswith('unreal.'):
        return False
    # Everything else is fuzzy search
    return True


def matches_as_word(search_term, name):
    """Check if search_term matches as complete word(s) in name.

    - search_term is treated as complete word(s) that must appear at word boundaries
    - Word boundaries are: start/end of string, underscore, or CamelCase transitions
    - If search_term contains underscore or CamelCase, each part must match as complete word
    - If search_term is all lowercase without separators, greedily match consecutive words

    Examples:
        matches_as_word('actor', 'Actor') -> True
        matches_as_word('actor', 'ActorComponent') -> True
        matches_as_word('actor', 'MyActor') -> True
        matches_as_word('actor', 'factory') -> False (actor is substring, not word)
        matches_as_word('actor', 'FactoryActor') -> True
        matches_as_word('get_actor', 'get_actor_location') -> True
        matches_as_word('get_actor', 'getactor') -> False
        matches_as_word('inputmappingcontext', 'InputMappingContext') -> True
        matches_as_word('inputcontext', 'InputMappingContext') -> True
        matches_as_word('MappingContext', 'InputMappingContext') -> True
    """
    # Split name into words (by underscore and CamelCase)
    normalized_name = re.sub(r'([a-z])([A-Z])', r'\1_\2', name)
    name_words = [w.lower() for w in normalized_name.split('_') if w]

    # Split search term by underscore and CamelCase
    normalized_search = re.sub(r'([a-z])([A-Z])', r'\1_\2', search_term)
    search_words = [w.lower() for w in normalized_search.split('_') if w]

    if not search_words:
        return False

    # Check if search_words appear as consecutive words in name_words
    for i in range(len(name_words) - len(search_words) + 1):
        if name_words[i:i + len(search_words)] == search_words:
            return True

    # If search term has no separators (single word after normalization),
    # try greedy matching: match consecutive name words that together form the search term
    if len(search_words) == 1:
        search_lower = search_words[0]
        # Try to match starting from each position in name_words
        for start in range(len(name_words)):
            combined = ''
            for j in range(start, len(name_words)):
                combined += name_words[j]
                if combined == search_lower:
                    return True
                if len(combined) >= len(search_lower):
                    break

    return False


def matches_in_signature(search_term, signature):
    """Check if search_term matches in a method/property signature.

    This checks for matches in:
    - Method parameters (types and names)
    - Method return types
    - Property types

    Uses the same word-boundary matching as matches_as_word.

    Args:
        search_term: The search term (e.g., 'inputmapping')
        signature: The full signature string (e.g., 'def foo(x: InputMappingContext) -> bool')

    Returns:
        True if search_term matches any identifier in the signature
    """
    # Extract all identifiers from the signature
    # Match: type names, parameter names, etc.
    identifiers = re.findall(r'\b([A-Z][A-Za-z0-9]*|[a-z_][a-z0-9_]*)\b', signature)

    for ident in identifiers:
        if matches_as_word(search_term, ident):
            return True
    return False


def parse_query(query):
    """Parse query string and extract the name to search for.

    Returns tuple of (class_name, member_name, is_wildcard, is_fuzzy) where:
    - For fuzzy search (actor): (search_term, None, False, True)
    - For class query (unreal.Actor): (class_name, None, False, False)
    - For member search (unreal.Actor.*location*): (class_name, pattern, True, False)
    - For exact member query (unreal.Actor.on_destroyed): (class_name, member_name, False, False)
    - For function query (unreal.log): (func_name, None, False, False)
    """
    # Check for fuzzy query first
    if is_fuzzy_query(query):
        return query.lower(), None, False, True

    if query.startswith('unreal.'):
        name = query[7:]  # Remove 'unreal.' prefix
    else:
        name = query

    if not name:
        raise ValueError(f"Invalid query: {query}")

    # Check for member query: ClassName.member_name or ClassName.*pattern*
    if '.' in name:
        parts = name.split('.', 1)
        class_name = parts[0]
        member_name = parts[1]
        if class_name and class_name[0].isupper() and member_name:
            # Check if it's a wildcard pattern or exact member name
            is_wildcard = '*' in member_name or '?' in member_name
            return class_name, member_name, is_wildcard, False

    return name, None, False, False


def is_class_name(name):
    """Check if name looks like a class (PascalCase) or function (snake_case/lowercase)."""
    return name[0].isupper()


def extract_parent_class(class_content):
    """Extract parent class name from class definition.

    Returns parent class name or None if no parent or parent is a private base class.
    """
    match = re.match(r'^class\s+\w+\((\w+)\):', class_content)
    if match:
        parent = match.group(1)
        # Skip private base classes like _ObjectBase, _WrapperBase
        if not parent.startswith('_'):
            return parent
    return None


def get_inheritance_chain(content, class_name, class_index=None):
    """Get the inheritance chain for a class.

    Returns list of (class_name, class_content) tuples from the class up to the root.
    """
    chain = []
    current_name = class_name

    while current_name:
        class_def, _, _, _ = find_class_definition(content, current_name, class_index)
        if not class_def:
            break
        chain.append((current_name, class_def))
        current_name = extract_parent_class(class_def)

    return chain


def extract_method_signature(method_text, deprecated_methods):
    """Extract method signature from a method definition.

    Returns tuple of (name, signature, is_deprecated).
    """
    # Match: def method_name(params) -> ReturnType:
    match = re.match(r'def\s+(\w+)\s*(\([^)]*\))\s*(->.*?)?:', method_text, re.DOTALL)
    if match:
        name = match.group(1)
        params = match.group(2)
        return_type = match.group(3).strip() if match.group(3) else ''
        is_deprecated = name in deprecated_methods
        signature = f"def {name}{params}{' ' + return_type if return_type else ''}"
        return name, signature, is_deprecated
    return None, None, False


def extract_property_signature(prop_text, deprecated_props, has_setter=False):
    """Extract property signature from a property definition.

    Returns tuple of (name, signature, is_deprecated).
    """
    # Match @property followed by def name(self) -> Type:
    match = re.search(r'@property\s+def\s+(\w+)\s*\([^)]*\)\s*(->.*?)?:', prop_text, re.DOTALL)
    if match:
        name = match.group(1)
        return_type = match.group(2).strip() if match.group(2) else ''
        is_deprecated = name in deprecated_props
        type_str = return_type[2:].strip() if return_type.startswith('->') else return_type
        access = '[Read-Write]' if has_setter else '[Read-Only]'
        signature = f"{name}: {type_str} {access}" if type_str else f"{name} {access}"
        return name, signature, is_deprecated
    return None, None, False


def extract_enum_value_signature(line, deprecated_enum_values):
    """Extract enum value signature from a line.

    Returns tuple of (name, signature, is_deprecated) or (None, None, False).
    """
    # Match: NAME: Type = value  or  NAME: Type #: comment
    match = re.match(r'^\s+(\w+)\s*:\s*([^=\n#]+)', line)
    if match:
        name = match.group(1)
        type_str = match.group(2).strip()
        is_deprecated = name in deprecated_enum_values or name.endswith('_DEPRECATED')
        signature = f"{name}: {type_str}"
        return name, signature, is_deprecated
    return None, None, False


def extract_class_header(class_content):
    """Extract class declaration line and docstring first line."""
    lines = class_content.split('\n')
    header_line = lines[0] if lines else ''

    # Find docstring (first """ after class declaration)
    docstring_first_line = ''
    in_docstring = False
    for line in lines[1:]:
        stripped = line.strip()
        if not in_docstring:
            if stripped.startswith('"""') or stripped.startswith("r'''") or stripped.startswith("r\"\"\""):
                in_docstring = True
                # Check if single-line docstring
                if stripped.count('"""') >= 2 or stripped.count("'''") >= 2:
                    docstring_first_line = stripped.strip('"\'r ').strip()
                    break
                else:
                    # Multi-line, get content after opening quotes
                    content = stripped.lstrip('r"\'').strip()
                    if content:
                        docstring_first_line = content
                        break
            elif stripped and not stripped.startswith('#'):
                # Non-empty, non-comment line before docstring
                break
        else:
            # Inside multi-line docstring, get first content line
            if stripped and not stripped.startswith('"""'):
                docstring_first_line = stripped
                break

    return header_line, docstring_first_line


def extract_editor_properties(class_content):
    """Extract Editor Properties from class docstring.

    UE5 classes often document properties in docstring format like:
    - ``property_name`` (Type):  [Read-Write] Description

    Returns list of (name, signature, is_deprecated) tuples.
    """
    properties = []

    # Pattern: - ``prop_name`` (Type):  [Access] Description
    # Type can contain nested parentheses like type(Class)
    # Access can be [Read-Write], [Read-Only], or similar
    prop_pattern = r'-\s+``(\w+)``\s*\(([^)]+(?:\([^)]*\)[^)]*)*)\):\s*\[([^\]]+)\]'
    for match in re.finditer(prop_pattern, class_content):
        name = match.group(1)
        type_str = match.group(2).strip()
        access = match.group(3).strip()

        # Normalize access string
        if 'Write' in access:
            access_marker = '[Read-Write]'
        else:
            access_marker = '[Read-Only]'

        # Check for deprecation in the property line
        is_deprecated = 'deprecated' in match.group(0).lower()

        signature = f"{name}: {type_str} {access_marker}"
        properties.append((name, signature, is_deprecated))

    return properties


def find_member_definition(class_content, member_name):
    """Find the full definition of a specific class member.

    Returns tuple of (member_type, definition_text) where member_type is one of:
    'property', 'editor_property', 'method', 'enum_value', or None if not found.
    """
    # 1. Check for @property definition
    prop_pattern = rf'(@property\s+def\s+{re.escape(member_name)}\s*\([^)]*\).*?)(?=\n    @|\n    def |\n\nclass |\Z)'
    match = re.search(prop_pattern, class_content, re.DOTALL)
    if match:
        return 'property', match.group(1).rstrip()

    # 2. Check for method definition
    method_pattern = rf'(def\s+{re.escape(member_name)}\s*\([^)]*\).*?)(?=\n    @|\n    def |\n\nclass |\Z)'
    match = re.search(method_pattern, class_content, re.DOTALL)
    if match:
        return 'method', match.group(1).rstrip()

    # 3. Check for Editor Property in docstring
    # Pattern: - ``member_name`` (Type):  [Access] Description
    # Continuation lines start with 6+ spaces and don't start with "- ``"
    editor_prop_pattern = rf'-\s+``{re.escape(member_name)}``\s*\([^)]+(?:\([^)]*\)[^)]*)*\):\s*\[[^\]]+\][^\n]*(?:\n\s{{6,}}(?!-\s)(?!``)[^\n]*)*'
    match = re.search(editor_prop_pattern, class_content)
    if match:
        return 'editor_property', match.group(0).strip()

    # 4. Check for enum value
    enum_pattern = rf'^(\s+{re.escape(member_name)}\s*:.*?)$'
    match = re.search(enum_pattern, class_content, re.MULTILINE)
    if match:
        return 'enum_value', match.group(1).strip()

    return None, None


def extract_class_summary(class_content, class_name, deprecated_props, deprecated_methods, deprecated_enum_values):
    """Extract class summary with signatures grouped by type.

    Returns formatted string with:
    - Class declaration and docstring first line
    - Python Properties section (native @property)
    - Editor Properties section (get_editor_property/set_editor_property)
    - Methods section
    - Enum values section (if any)
    """
    header_line, docstring_first_line = extract_class_header(class_content)

    python_properties = []
    editor_properties = []
    methods = []
    enum_values = []

    # Find all property setters to determine read-write access
    setter_pattern = r'@(\w+)\.setter'
    property_setters = set(re.findall(setter_pattern, class_content))

    # Find all @property definitions (Python-style properties)
    prop_pattern = r'(@property\s+def\s+\w+\s*\([^)]*\)\s*(?:->.*?)?:)'
    for match in re.finditer(prop_pattern, class_content, re.DOTALL):
        prop_text = match.group(1)
        # Extract property name to check if it has a setter
        prop_name_match = re.search(r'def\s+(\w+)', prop_text)
        prop_name = prop_name_match.group(1) if prop_name_match else None
        has_setter = prop_name in property_setters if prop_name else False
        name, sig, is_dep = extract_property_signature(prop_text, deprecated_props, has_setter)
        if name:
            python_properties.append((name, sig, is_dep))

    # Extract Editor Properties from docstring (UE5-style properties)
    editor_props = extract_editor_properties(class_content)
    python_prop_names = {p[0] for p in python_properties}
    for name, sig, is_dep in editor_props:
        if name not in python_prop_names:
            editor_properties.append((name, sig, is_dep))

    # Find all method definitions (exclude properties and their setters)
    # Collect all property names (both Python and Editor) to exclude setters
    all_prop_names = {p[0] for p in python_properties} | {p[0] for p in editor_properties}

    # Also get all @property decorated names from the class content
    decorated_prop_names = set(re.findall(r'@property\s+def\s+(\w+)', class_content))

    # Find all def statements
    method_pattern = r'def\s+(\w+)\s*(\([^)]*\))\s*(->.*?)?:'
    for match in re.finditer(method_pattern, class_content, re.DOTALL):
        name = match.group(1)
        # Skip if it's a property getter or setter
        if name in decorated_prop_names:
            continue
        params = match.group(2)
        return_type = match.group(3).strip() if match.group(3) else ''
        is_deprecated = name in deprecated_methods
        signature = f"def {name}{params}{' ' + return_type if return_type else ''}"
        methods.append((name, signature, is_deprecated))

    # Find enum values (class attributes with type annotations)
    # Pattern: NAME: Type = value or NAME: Type
    # These appear at class level, not inside methods
    enum_pattern = r'^    (\w+)\s*:\s*([A-Z]\w*)\s*(?:=|#)'
    for match in re.finditer(enum_pattern, class_content, re.MULTILINE):
        name = match.group(1)
        type_str = match.group(2)
        # Skip if it looks like a method parameter
        if name.startswith('_'):
            continue
        is_deprecated = name in deprecated_enum_values or name.endswith('_DEPRECATED')
        signature = f"{name}: {type_str}"
        enum_values.append((name, signature, is_deprecated))

    # Build output
    output = []
    output.append(header_line)
    if docstring_first_line:
        output.append(f'    """{docstring_first_line}"""')
    output.append('')

    if python_properties:
        output.append('Properties:')
        for name, sig, is_dep in sorted(python_properties, key=lambda x: x[0]):
            dep_marker = ' [DEPRECATED]' if is_dep else ''
            output.append(f'    {sig}{dep_marker}')
        output.append('')

    if editor_properties:
        output.append('Editor Properties (use get_editor_property/set_editor_property):')
        for name, sig, is_dep in sorted(editor_properties, key=lambda x: x[0]):
            dep_marker = ' [DEPRECATED]' if is_dep else ''
            output.append(f'    {sig}{dep_marker}')
        output.append('')

    if methods:
        output.append('Methods:')
        for name, sig, is_dep in sorted(methods, key=lambda x: x[0]):
            dep_marker = ' [DEPRECATED]' if is_dep else ''
            output.append(f'    {sig}{dep_marker}')
        output.append('')

    if enum_values:
        output.append('Enum Values:')
        for name, sig, is_dep in sorted(enum_values, key=lambda x: x[0]):
            dep_marker = ' [DEPRECATED]' if is_dep else ''
            output.append(f'    {sig}{dep_marker}')
        output.append('')

    return '\n'.join(output).rstrip()


def extract_class_summary_with_inheritance(content, class_name, class_index=None):
    """Extract class summary including inherited members.

    Args:
        content: Full unreal.py stub content
        class_name: Name of the class to summarize
        class_index: Optional pre-built class index for fast lookup

    Returns formatted string with all members including inherited ones.
    """
    # Get inheritance chain
    chain = get_inheritance_chain(content, class_name, class_index)
    if not chain:
        return None

    # Get the main class info
    main_class_name, main_class_def = chain[0]
    header_line, docstring_first_line = extract_class_header(main_class_def)

    # Collect all members from class and parents
    all_python_props = {}  # name -> (signature, is_deprecated, source_class)
    all_editor_props = {}
    all_methods = {}
    all_enum_values = {}

    # Process from parent to child so child overrides are preserved
    for cls_name, cls_def in reversed(chain):
        deprecated_props, deprecated_methods, deprecated_enum_values = extract_deprecated_members(cls_def)

        # Find property setters
        setter_pattern = r'@(\w+)\.setter'
        property_setters = set(re.findall(setter_pattern, cls_def))

        # Find Python properties
        prop_pattern = r'(@property\s+def\s+\w+\s*\([^)]*\)\s*(?:->.*?)?:)'
        for match in re.finditer(prop_pattern, cls_def, re.DOTALL):
            prop_text = match.group(1)
            prop_name_match = re.search(r'def\s+(\w+)', prop_text)
            prop_name = prop_name_match.group(1) if prop_name_match else None
            if prop_name:
                has_setter = prop_name in property_setters
                _, sig, is_dep = extract_property_signature(prop_text, deprecated_props, has_setter)
                if sig:
                    all_python_props[prop_name] = (sig, is_dep, cls_name)

        # Find Editor Properties
        editor_props = extract_editor_properties(cls_def)
        for name, sig, is_dep in editor_props:
            if name not in all_python_props:
                all_editor_props[name] = (sig, is_dep, cls_name)

        # Find methods
        decorated_prop_names = set(re.findall(r'@property\s+def\s+(\w+)', cls_def))
        method_pattern = r'def\s+(\w+)\s*(\([^)]*\))\s*(->.*?)?:'
        for match in re.finditer(method_pattern, cls_def, re.DOTALL):
            name = match.group(1)
            if name in decorated_prop_names:
                continue
            params = match.group(2)
            return_type = match.group(3).strip() if match.group(3) else ''
            is_deprecated = name in deprecated_methods
            signature = f"def {name}{params}{' ' + return_type if return_type else ''}"
            all_methods[name] = (signature, is_deprecated, cls_name)

        # Find enum values
        enum_pattern = r'^    (\w+)\s*:\s*([A-Z]\w*)\s*(?:=|#)'
        for match in re.finditer(enum_pattern, cls_def, re.MULTILINE):
            name = match.group(1)
            if name.startswith('_'):
                continue
            type_str = match.group(2)
            is_deprecated = name in deprecated_enum_values or name.endswith('_DEPRECATED')
            signature = f"{name}: {type_str}"
            all_enum_values[name] = (signature, is_deprecated, cls_name)

    # Build output
    output = []
    output.append(header_line)
    if docstring_first_line:
        output.append(f'    """{docstring_first_line}"""')
    output.append('')

    # Show inheritance chain
    if len(chain) > 1:
        parent_names = [c[0] for c in chain[1:]]
        output.append(f'Inherits from: {" -> ".join(parent_names)}')
        output.append('')

    def format_member(name, sig, is_dep, source_class):
        """Format a member with deprecation and inheritance markers."""
        dep_marker = ' [DEPRECATED]' if is_dep else ''
        inherited = ' (inherited)' if source_class != main_class_name else ''
        return f'    {sig}{dep_marker}{inherited}'

    if all_python_props:
        output.append('Properties:')
        for name in sorted(all_python_props.keys()):
            sig, is_dep, source = all_python_props[name]
            output.append(format_member(name, sig, is_dep, source))
        output.append('')

    if all_editor_props:
        output.append('Editor Properties (use get_editor_property/set_editor_property):')
        for name in sorted(all_editor_props.keys()):
            sig, is_dep, source = all_editor_props[name]
            output.append(format_member(name, sig, is_dep, source))
        output.append('')

    if all_methods:
        output.append('Methods:')
        for name in sorted(all_methods.keys()):
            sig, is_dep, source = all_methods[name]
            output.append(format_member(name, sig, is_dep, source))
        output.append('')

    if all_enum_values:
        output.append('Enum Values:')
        for name in sorted(all_enum_values.keys()):
            sig, is_dep, source = all_enum_values[name]
            output.append(format_member(name, sig, is_dep, source))
        output.append('')

    return '\n'.join(output).rstrip()


def search_class_members(class_content, pattern, deprecated_props, deprecated_methods, deprecated_enum_values):
    """Search class members matching a wildcard pattern.

    Args:
        class_content: Full class definition text
        pattern: Wildcard pattern like '*location*'
        deprecated_*: Dicts of deprecated member names

    Returns formatted string with matching member signatures.
    """
    matching_python_props = []
    matching_editor_props = []
    matching_methods = []
    matching_enum_values = []

    # Find all property setters to determine read-write access
    setter_pattern = r'@(\w+)\.setter'
    property_setters = set(re.findall(setter_pattern, class_content))

    # Find Python-style properties
    prop_pattern = r'(@property\s+def\s+(\w+)\s*\([^)]*\)\s*(?:->.*?)?:)'
    for match in re.finditer(prop_pattern, class_content, re.DOTALL):
        name = match.group(2)
        if fnmatch.fnmatch(name.lower(), pattern.lower()):
            prop_text = match.group(1)
            has_setter = name in property_setters
            _, sig, is_dep = extract_property_signature(prop_text, deprecated_props, has_setter)
            if sig:
                matching_python_props.append((name, sig, is_dep))

    # Search Editor Properties from docstring
    editor_props = extract_editor_properties(class_content)
    matched_python_prop_names = {p[0] for p in matching_python_props}
    for name, sig, is_dep in editor_props:
        if name not in matched_python_prop_names and fnmatch.fnmatch(name.lower(), pattern.lower()):
            matching_editor_props.append((name, sig, is_dep))

    # Find methods
    # Get all @property decorated names to exclude setters
    all_prop_names = set(re.findall(r'@property\s+def\s+(\w+)', class_content))

    method_pattern = r'def\s+(\w+)\s*(\([^)]*\))\s*(->.*?)?:'
    for match in re.finditer(method_pattern, class_content, re.DOTALL):
        name = match.group(1)
        if name in all_prop_names:  # Skip property methods and setters
            continue
        if fnmatch.fnmatch(name.lower(), pattern.lower()):
            params = match.group(2)
            return_type = match.group(3).strip() if match.group(3) else ''
            is_deprecated = name in deprecated_methods
            signature = f"def {name}{params}{' ' + return_type if return_type else ''}"
            matching_methods.append((name, signature, is_deprecated))

    # Find enum values
    enum_pattern = r'^    (\w+)\s*:\s*([A-Z]\w*)\s*(?:=|#)'
    for match in re.finditer(enum_pattern, class_content, re.MULTILINE):
        name = match.group(1)
        if fnmatch.fnmatch(name.lower(), pattern.lower()):
            type_str = match.group(2)
            is_deprecated = name in deprecated_enum_values or name.endswith('_DEPRECATED')
            signature = f"{name}: {type_str}"
            matching_enum_values.append((name, signature, is_deprecated))

    total_matches = len(matching_python_props) + len(matching_editor_props) + len(matching_methods) + len(matching_enum_values)

    if total_matches == 0:
        return None

    # Build output
    output = []

    if matching_python_props:
        output.append('Properties:')
        for name, sig, is_dep in sorted(matching_python_props, key=lambda x: x[0]):
            dep_marker = ' [DEPRECATED]' if is_dep else ''
            output.append(f'    {sig}{dep_marker}')
        output.append('')

    if matching_editor_props:
        output.append('Editor Properties (use get_editor_property/set_editor_property):')
        for name, sig, is_dep in sorted(matching_editor_props, key=lambda x: x[0]):
            dep_marker = ' [DEPRECATED]' if is_dep else ''
            output.append(f'    {sig}{dep_marker}')
        output.append('')

    if matching_methods:
        output.append('Methods:')
        for name, sig, is_dep in sorted(matching_methods, key=lambda x: x[0]):
            dep_marker = ' [DEPRECATED]' if is_dep else ''
            output.append(f'    {sig}{dep_marker}')
        output.append('')

    if matching_enum_values:
        output.append('Enum Values:')
        for name, sig, is_dep in sorted(matching_enum_values, key=lambda x: x[0]):
            dep_marker = ' [DEPRECATED]' if is_dep else ''
            output.append(f'    {sig}{dep_marker}')
        output.append('')

    return '\n'.join(output).rstrip(), total_matches


def extract_deprecated_members(class_content):
    """Extract deprecated properties, methods, and enum values from a class definition.

    Returns a tuple of (deprecated_properties, deprecated_methods, deprecated_enum_values).
    Each is a dict mapping name to deprecation message.
    """
    deprecated_props = {}
    deprecated_methods = {}
    deprecated_enum_values = {}

    # Pattern A: Find @property with deprecated docstring
    prop_pattern = r'@property\s+def\s+(\w+)\s*\([^)]*\)[^:]*:\s*r?"""[^"]*?(deprecated:[^\n"]+)'
    for match in re.finditer(prop_pattern, class_content, re.IGNORECASE | re.DOTALL):
        name = match.group(1)
        message = match.group(2).strip()
        deprecated_props[name] = message

    # Pattern B: Find "deprecated: Property 'name'" in docstrings
    prop_explicit_pattern = r"(deprecated:\s*Property\s*'(\w+)'[^\n]*)"
    for match in re.finditer(prop_explicit_pattern, class_content, re.IGNORECASE):
        message = match.group(1).strip()
        prop_name = match.group(2)
        snake_name = re.sub(r'(?<!^)(?=[A-Z])', '_', prop_name).lower()
        snake_name = snake_name.lstrip('b_')
        if snake_name.startswith('_'):
            snake_name = snake_name[1:]
        deprecated_props[snake_name] = message

    # Pattern C: Find enum values with _DEPRECATED suffix
    enum_deprecated_pattern = r'^\s+(\w+_DEPRECATED)\s*:[^#\n]*#:\s*\d+(?::\s*(.+))?$'
    for match in re.finditer(enum_deprecated_pattern, class_content, re.MULTILINE):
        name = match.group(1)
        comment = match.group(2).strip() if match.group(2) else ""
        deprecated_enum_values[name] = comment if comment else "Deprecated"

    # Pattern D: Find "Will be deprecated" in enum value comments
    will_deprecate_pattern = r'^\s+(\w+)\s*:[^#\n]*#:\s*\d+:?\s*(.*Will be deprecated[^\n]*)'
    for match in re.finditer(will_deprecate_pattern, class_content, re.MULTILINE | re.IGNORECASE):
        name = match.group(1)
        message = match.group(2).strip()
        deprecated_enum_values[name] = message

    # Pattern E: Find methods with deprecated docstring
    method_pattern = r'(?<!@property\s)def\s+(\w+)\s*\([^)]*\)[^:]*:\s*r?"""[^"]*?(deprecated:[^\n"]+)'
    for match in re.finditer(method_pattern, class_content, re.IGNORECASE | re.DOTALL):
        name = match.group(1)
        message = match.group(2).strip()
        if name not in deprecated_props:
            deprecated_methods[name] = message

    return (
        dict(sorted(deprecated_props.items())),
        dict(sorted(deprecated_methods.items())),
        dict(sorted(deprecated_enum_values.items()))
    )


def build_class_index(content):
    """Build an index of all class definitions for fast lookup.

    Scans the file line by line to find class boundaries, which is much faster
    than using regex with re.DOTALL on large files.

    Returns a dict mapping class_name -> (start_offset, end_offset) in the content string.
    """
    index = {}
    lines = content.split('\n')
    current_class = None
    current_start = 0
    offset = 0

    class_pattern = re.compile(r'^class (\w+)(?:\([^)]*\))?:')
    func_pattern = re.compile(r'^def ([a-z_]\w*)\(')

    for line in lines:
        match = class_pattern.match(line)
        if match:
            if current_class:
                index[current_class] = (current_start, offset)
            current_class = match.group(1)
            current_start = offset
        elif func_pattern.match(line):
            if current_class:
                index[current_class] = (current_start, offset)
                current_class = None

        offset += len(line) + 1

    if current_class:
        index[current_class] = (current_start, len(content))

    return index


def get_class_content(content, class_index, class_name):
    """Get class content using pre-built index."""
    if class_name not in class_index:
        return None
    start, end = class_index[class_name]
    return content[start:end].rstrip()


def find_class_definition(content, class_name, class_index=None):
    """Find a class definition and return its full text along with deprecated members.

    Returns a tuple of (class_definition, deprecated_properties, deprecated_methods, deprecated_enum_values).

    If class_index is provided, uses it for O(1) lookup instead of regex search.
    """
    if class_index is not None:
        class_def = get_class_content(content, class_index, class_name)
        if class_def:
            deprecated_props, deprecated_methods, deprecated_enum_values = extract_deprecated_members(class_def)
            return class_def, deprecated_props, deprecated_methods, deprecated_enum_values
        return None, {}, {}, {}

    pattern = rf'^class {re.escape(class_name)}(?:\([^)]*\))?:.*?(?=\nclass |\ndef [a-z_]+\(|\Z)'
    match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
    if match:
        class_def = match.group(0).rstrip()
        deprecated_props, deprecated_methods, deprecated_enum_values = extract_deprecated_members(class_def)
        return class_def, deprecated_props, deprecated_methods, deprecated_enum_values
    return None, {}, {}, {}


def find_function_definition(content, func_name):
    """Find a module-level function definition and return its full text."""
    pattern = rf'^def {re.escape(func_name)}\([^)]*\).*?(?=\ndef |\nclass |\Z)'
    match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
    if match:
        return match.group(0).rstrip()
    return None


def find_ripgrep():
    """Find ripgrep executable (rg)."""
    for name in ['rg', 'rg.exe']:
        path = shutil.which(name)
        if path:
            return path
    return None


def ripgrep_fuzzy_search(stub_file, search_term):
    """Use ripgrep to quickly find matching lines in the stub file.

    Returns a dict with:
    - 'classes': set of class names containing the search term
    - 'class_lines': dict of class_name -> list of line numbers with matches
    - 'member_lines': list of (line_number, line_content) for member matches
    """
    rg_path = find_ripgrep()
    if not rg_path:
        return None

    try:
        result = subprocess.run(
            [rg_path, '-i', '-n', '--no-heading', search_term, stub_file],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=30
        )
    except (subprocess.TimeoutExpired, OSError):
        return None

    if result.returncode not in (0, 1):
        return None

    matches = {
        'class_names': set(),
        'member_lines': [],
        'function_lines': [],
    }

    class_pattern = re.compile(rf'^class\s+(\w*{re.escape(search_term)}\w*)', re.IGNORECASE)
    member_pattern = re.compile(r'^\s+')
    func_pattern = re.compile(rf'^def\s+([a-z_]\w*{re.escape(search_term)}\w*)', re.IGNORECASE)

    for line in result.stdout.splitlines():
        if ':' not in line:
            continue
        parts = line.split(':', 1)
        if len(parts) != 2:
            continue
        try:
            line_num = int(parts[0])
        except ValueError:
            continue
        content = parts[1]

        class_match = class_pattern.match(content)
        if class_match:
            matches['class_names'].add(class_match.group(1))
            continue

        func_match = func_pattern.match(content)
        if func_match:
            matches['function_lines'].append((line_num, content))
            continue

        if member_pattern.search(content):
            matches['member_lines'].append((line_num, content))

    return matches


def fuzzy_search(content, search_term, stub_file=None, filter_type=None):
    """Search across all classes and members for matching names.

    Args:
        content: Full unreal.py stub content
        search_term: Lowercase search string (e.g., 'actor', 'location')
        stub_file: Path to stub file (optional, enables ripgrep optimization)
        filter_type: Optional filter - 'class', 'method', 'enum', or None for all

    Returns formatted string with:
    - Matching class names (with their summary)
    - Matching members from any class (grouped by class)
    """
    include_classes = filter_type in (None, 'class')
    include_methods = filter_type in (None, 'method')
    include_enums = filter_type in (None, 'enum')
    include_properties = filter_type is None
    include_functions = filter_type in (None, 'method')

    class_index = build_class_index(content)

    rg_results = None
    if stub_file:
        rg_results = ripgrep_fuzzy_search(stub_file, search_term)

    matching_classes = []
    members_by_class = {}
    matching_functions = []

    if rg_results:
        matching_classes = [c for c in rg_results['class_names'] if matches_as_word(search_term, c)]

        lines = content.split('\n')

        line_to_class = {}
        current_class = None
        for i, line in enumerate(lines, 1):
            class_match = re.match(r'^class (\w+)', line)
            if class_match:
                current_class = class_match.group(1)
            elif re.match(r'^def [a-z_]', line):
                current_class = None
            if current_class:
                line_to_class[i] = current_class

        for line_num, line_content in rg_results['member_lines']:
            class_name = line_to_class.get(line_num)
            if class_name and class_name not in matching_classes:
                if class_name not in members_by_class:
                    members_by_class[class_name] = []

        for line_num, line_content in rg_results['function_lines']:
            func_match = re.match(r'^def\s+([a-z_]\w*)\s*(\([^)]*\))\s*(->.*?)?:', line_content)
            if func_match:
                name = func_match.group(1)
                if matches_as_word(search_term, name):
                    params = func_match.group(2)
                    return_type = func_match.group(3).strip() if func_match.group(3) else ''
                    signature = f"def {name}{params}{' ' + return_type if return_type else ''}"
                    matching_functions.append((name, signature))

        for class_name in list(members_by_class.keys()):
            class_def, deprecated_props, deprecated_methods, deprecated_enum_values = find_class_definition(content, class_name, class_index)
            if not class_def:
                del members_by_class[class_name]
                continue

            members = []
            setter_pattern = r'@(\w+)\.setter'
            property_setters = set(re.findall(setter_pattern, class_def))

            prop_pattern = r'(@property\s+def\s+(\w+)\s*\([^)]*\)\s*(?:->.*?)?:)'
            for match in re.finditer(prop_pattern, class_def, re.DOTALL):
                name = match.group(2)
                prop_text = match.group(1)
                has_setter = name in property_setters
                _, sig, is_dep = extract_property_signature(prop_text, deprecated_props, has_setter)
                if sig and (matches_as_word(search_term, name) or matches_in_signature(search_term, sig)):
                    members.append(('property', name, sig, is_dep))

            editor_props = extract_editor_properties(class_def)
            python_prop_names = {m[1] for m in members if m[0] == 'property'}
            for name, sig, is_dep in editor_props:
                if name not in python_prop_names:
                    if matches_as_word(search_term, name) or matches_in_signature(search_term, sig):
                        members.append(('editor_property', name, sig, is_dep))

            decorated_prop_names = set(re.findall(r'@property\s+def\s+(\w+)', class_def))
            method_pattern = r'def\s+(\w+)\s*(\([^)]*\))\s*(->.*?)?:'
            for match in re.finditer(method_pattern, class_def, re.DOTALL):
                name = match.group(1)
                if name in decorated_prop_names:
                    continue
                params = match.group(2)
                return_type = match.group(3).strip() if match.group(3) else ''
                is_deprecated = name in deprecated_methods
                signature = f"def {name}{params}{' ' + return_type if return_type else ''}"
                if matches_as_word(search_term, name) or matches_in_signature(search_term, signature):
                    members.append(('method', name, signature, is_deprecated))

            enum_pattern = r'^    (\w+)\s*:\s*([A-Z]\w*)\s*(?:=|#)'
            for match in re.finditer(enum_pattern, class_def, re.MULTILINE):
                name = match.group(1)
                if matches_as_word(search_term, name):
                    type_str = match.group(2)
                    is_deprecated = name in deprecated_enum_values or name.endswith('_DEPRECATED')
                    signature = f"{name}: {type_str}"
                    members.append(('enum_value', name, signature, is_deprecated))

            if members:
                members_by_class[class_name] = members
            else:
                del members_by_class[class_name]

    else:
        for class_name in class_index:
            class_def, deprecated_props, deprecated_methods, deprecated_enum_values = find_class_definition(content, class_name, class_index)
            if not class_def:
                continue

            if matches_as_word(search_term, class_name):
                matching_classes.append(class_name)

            pattern = f'*{search_term}*'
            result = search_class_members(
                class_def, pattern,
                deprecated_props, deprecated_methods, deprecated_enum_values
            )

            if result:
                _, count = result
                if count > 0 and class_name not in matching_classes:
                    members = []
                    setter_pattern = r'@(\w+)\.setter'
                    property_setters = set(re.findall(setter_pattern, class_def))

                    prop_pattern = r'(@property\s+def\s+(\w+)\s*\([^)]*\)\s*(?:->.*?)?:)'
                    for match in re.finditer(prop_pattern, class_def, re.DOTALL):
                        name = match.group(2)
                        if matches_as_word(search_term, name):
                            prop_text = match.group(1)
                            has_setter = name in property_setters
                            _, sig, is_dep = extract_property_signature(prop_text, deprecated_props, has_setter)
                            if sig:
                                members.append(('property', name, sig, is_dep))

                    editor_props = extract_editor_properties(class_def)
                    python_prop_names = {m[1] for m in members if m[0] == 'property'}
                    for name, sig, is_dep in editor_props:
                        if name not in python_prop_names and matches_as_word(search_term, name):
                            members.append(('editor_property', name, sig, is_dep))

                    decorated_prop_names = set(re.findall(r'@property\s+def\s+(\w+)', class_def))
                    method_pattern = r'def\s+(\w+)\s*(\([^)]*\))\s*(->.*?)?:'
                    for match in re.finditer(method_pattern, class_def, re.DOTALL):
                        name = match.group(1)
                        if name in decorated_prop_names:
                            continue
                        if matches_as_word(search_term, name):
                            params = match.group(2)
                            return_type = match.group(3).strip() if match.group(3) else ''
                            is_deprecated = name in deprecated_methods
                            signature = f"def {name}{params}{' ' + return_type if return_type else ''}"
                            members.append(('method', name, signature, is_deprecated))

                    enum_pattern = r'^    (\w+)\s*:\s*([A-Z]\w*)\s*(?:=|#)'
                    for match in re.finditer(enum_pattern, class_def, re.MULTILINE):
                        name = match.group(1)
                        if matches_as_word(search_term, name):
                            type_str = match.group(2)
                            is_deprecated = name in deprecated_enum_values or name.endswith('_DEPRECATED')
                            signature = f"{name}: {type_str}"
                            members.append(('enum_value', name, signature, is_deprecated))

                    if members:
                        members_by_class[class_name] = members

        func_pattern = r'^def ([a-z_]\w*)\s*(\([^)]*\))\s*(->.*?)?:'
        for match in re.finditer(func_pattern, content, re.MULTILINE):
            name = match.group(1)
            if matches_as_word(search_term, name):
                params = match.group(2)
                return_type = match.group(3).strip() if match.group(3) else ''
                signature = f"def {name}{params}{' ' + return_type if return_type else ''}"
                matching_functions.append((name, signature))

    output = []
    total_count = 0

    if include_classes and matching_classes:
        output.append(f"=== Matching Classes ({len(matching_classes)}) ===")
        output.append('')
        for class_name in sorted(matching_classes):
            class_def, _, _, _ = find_class_definition(content, class_name, class_index)
            if class_def:
                header_line, docstring_first_line = extract_class_header(class_def)
                output.append(header_line)
                if docstring_first_line:
                    output.append(f'    """{docstring_first_line}"""')
                output.append('')
        total_count += len(matching_classes)

    if include_functions and matching_functions:
        output.append(f"=== Matching Module Functions ({len(matching_functions)}) ===")
        output.append('')
        for name, sig in sorted(matching_functions, key=lambda x: x[0]):
            output.append(f"    {sig}")
        output.append('')
        total_count += len(matching_functions)

    classes_with_members = [c for c in members_by_class if c not in matching_classes]

    methods_by_class = {}
    props_by_class = {}
    enums_by_class = {}

    for class_name in classes_with_members:
        members = members_by_class[class_name]
        if include_methods:
            methods = [(n, s, d) for t, n, s, d in members if t == 'method']
            if methods:
                methods_by_class[class_name] = methods
        if include_properties:
            props = [(n, s, d) for t, n, s, d in members if t in ('property', 'editor_property')]
            if props:
                props_by_class[class_name] = props
        if include_enums:
            enums = [(n, s, d) for t, n, s, d in members if t == 'enum_value']
            if enums:
                enums_by_class[class_name] = enums

    def get_class_header(cls_name):
        cls_def, _, _, _ = find_class_definition(content, cls_name, class_index)
        if cls_def:
            header, _ = extract_class_header(cls_def)
            return header
        return f"class {cls_name}:"

    if methods_by_class:
        method_count = sum(len(methods_by_class[c]) for c in methods_by_class)
        output.append(f"=== Matching Methods ({method_count} in {len(methods_by_class)} classes) ===")
        output.append('')
        for class_name in sorted(methods_by_class.keys()):
            output.append(get_class_header(class_name))
            for name, sig, is_dep in sorted(methods_by_class[class_name], key=lambda x: x[0]):
                dep_marker = ' [DEPRECATED]' if is_dep else ''
                output.append(f'    {sig}{dep_marker}')
            output.append('')
        total_count += method_count

    if props_by_class:
        prop_count = sum(len(props_by_class[c]) for c in props_by_class)
        output.append(f"=== Matching Properties ({prop_count} in {len(props_by_class)} classes) ===")
        output.append('')
        for class_name in sorted(props_by_class.keys()):
            output.append(get_class_header(class_name))
            for name, sig, is_dep in sorted(props_by_class[class_name], key=lambda x: x[0]):
                dep_marker = ' [DEPRECATED]' if is_dep else ''
                output.append(f'    {sig}{dep_marker}')
            output.append('')
        total_count += prop_count

    if enums_by_class:
        enum_count = sum(len(enums_by_class[c]) for c in enums_by_class)
        output.append(f"=== Matching Enum Values ({enum_count} in {len(enums_by_class)} classes) ===")
        output.append('')
        for class_name in sorted(enums_by_class.keys()):
            output.append(get_class_header(class_name))
            for name, sig, is_dep in sorted(enums_by_class[class_name], key=lambda x: x[0]):
                dep_marker = ' [DEPRECATED]' if is_dep else ''
                output.append(f'    {sig}{dep_marker}')
            output.append('')
        total_count += enum_count

    if total_count == 0:
        return None, 0

    return '\n'.join(output).rstrip(), total_count


def chained_fuzzy_search(content, search_terms, stub_file=None, filter_type=None):
    """Perform chained fuzzy search with multiple terms filtering progressively.

    Args:
        content: Full unreal.py stub content
        search_terms: List of search terms (e.g., ['actor', 'render'])
        stub_file: Path to stub file (optional, enables ripgrep optimization)
        filter_type: Optional filter - 'class', 'method', 'enum', or None for all

    Returns formatted string with results matching ALL terms.
    """
    if not search_terms:
        return None, 0

    class_index = build_class_index(content)

    include_classes = filter_type in (None, 'class')
    include_methods = filter_type in (None, 'method')
    include_enums = filter_type in (None, 'enum')
    include_properties = filter_type is None
    include_functions = filter_type in (None, 'method')

    matching_classes = []
    matching_functions = []
    members_by_class = {}

    rg_results = None
    if stub_file:
        rg_results = ripgrep_fuzzy_search(stub_file, search_terms[0])

    if rg_results:
        lines = content.split('\n')
        line_to_class = {}
        current_class = None
        for i, line in enumerate(lines, 1):
            class_match = re.match(r'^class (\w+)', line)
            if class_match:
                current_class = class_match.group(1)
            elif re.match(r'^def [a-z_]', line):
                current_class = None
            if current_class:
                line_to_class[i] = current_class

        if include_classes:
            for class_name in rg_results['class_names']:
                if all(matches_as_word(term, class_name) for term in search_terms):
                    matching_classes.append(class_name)

        if include_functions:
            for line_num, line_content in rg_results['function_lines']:
                func_match = re.match(r'^def\s+([a-z_]\w*)\s*(\([^)]*\))\s*(->.*?)?:', line_content)
                if func_match:
                    name = func_match.group(1)
                    if all(matches_as_word(term, name) for term in search_terms):
                        params = func_match.group(2)
                        return_type = func_match.group(3).strip() if func_match.group(3) else ''
                        signature = f"def {name}{params}{' ' + return_type if return_type else ''}"
                        matching_functions.append((name, signature))

        candidate_classes = set()
        for line_num, line_content in rg_results['member_lines']:
            class_name = line_to_class.get(line_num)
            if class_name:
                candidate_classes.add(class_name)

        for class_name in candidate_classes:
            if class_name in matching_classes:
                continue

            class_def, deprecated_props, deprecated_methods, deprecated_enum_values = find_class_definition(content, class_name, class_index)
            if not class_def:
                continue

            members = []
            setter_pattern = r'@(\w+)\.setter'
            property_setters = set(re.findall(setter_pattern, class_def))

            if include_properties:
                prop_pattern = r'(@property\s+def\s+(\w+)\s*\([^)]*\)\s*(?:->.*?)?:)'
                for match in re.finditer(prop_pattern, class_def, re.DOTALL):
                    name = match.group(2)
                    prop_text = match.group(1)
                    has_setter = name in property_setters
                    _, sig, is_dep = extract_property_signature(prop_text, deprecated_props, has_setter)
                    if sig and all(matches_as_word(term, name) or matches_in_signature(term, sig) for term in search_terms):
                        members.append(('property', name, sig, is_dep))

                editor_props = extract_editor_properties(class_def)
                python_prop_names = {m[1] for m in members if m[0] == 'property'}
                for name, sig, is_dep in editor_props:
                    if name not in python_prop_names:
                        if all(matches_as_word(term, name) or matches_in_signature(term, sig) for term in search_terms):
                            members.append(('editor_property', name, sig, is_dep))

            if include_methods:
                decorated_prop_names = set(re.findall(r'@property\s+def\s+(\w+)', class_def))
                method_pattern = r'def\s+(\w+)\s*(\([^)]*\))\s*(->.*?)?:'
                for match in re.finditer(method_pattern, class_def, re.DOTALL):
                    name = match.group(1)
                    if name in decorated_prop_names:
                        continue
                    params = match.group(2)
                    return_type = match.group(3).strip() if match.group(3) else ''
                    is_deprecated = name in deprecated_methods
                    signature = f"def {name}{params}{' ' + return_type if return_type else ''}"
                    if all(matches_as_word(term, name) or matches_in_signature(term, signature) for term in search_terms):
                        members.append(('method', name, signature, is_deprecated))

            if include_enums:
                enum_pattern = r'^    (\w+)\s*:\s*([A-Z]\w*)\s*(?:=|#)'
                for match in re.finditer(enum_pattern, class_def, re.MULTILINE):
                    name = match.group(1)
                    if all(matches_as_word(term, name) for term in search_terms):
                        type_str = match.group(2)
                        is_deprecated = name in deprecated_enum_values or name.endswith('_DEPRECATED')
                        signature = f"{name}: {type_str}"
                        members.append(('enum_value', name, signature, is_deprecated))

            if members:
                members_by_class[class_name] = members

    else:
        raise RuntimeError("ripgrep (rg) is required for chained fuzzy search but was not found. Please install ripgrep.")

    output = []
    total_count = 0

    if matching_classes:
        output.append(f"=== Matching Classes ({len(matching_classes)}) ===")
        output.append('')
        for class_name in sorted(matching_classes):
            class_def, _, _, _ = find_class_definition(content, class_name, class_index)
            if class_def:
                header_line, docstring_first_line = extract_class_header(class_def)
                output.append(header_line)
                if docstring_first_line:
                    output.append(f'    """{docstring_first_line}"""')
                output.append('')
        total_count += len(matching_classes)

    if matching_functions:
        output.append(f"=== Matching Module Functions ({len(matching_functions)}) ===")
        output.append('')
        for name, sig in sorted(matching_functions, key=lambda x: x[0]):
            output.append(f"    {sig}")
        output.append('')
        total_count += len(matching_functions)

    classes_with_members = [c for c in members_by_class if c not in matching_classes]

    methods_by_class_out = {}
    props_by_class_out = {}
    enums_by_class_out = {}

    for class_name in classes_with_members:
        members = members_by_class[class_name]
        methods = [(n, s, d) for t, n, s, d in members if t == 'method']
        props = [(n, s, d) for t, n, s, d in members if t in ('property', 'editor_property')]
        enums = [(n, s, d) for t, n, s, d in members if t == 'enum_value']

        if methods:
            methods_by_class_out[class_name] = methods
        if props:
            props_by_class_out[class_name] = props
        if enums:
            enums_by_class_out[class_name] = enums

    def get_class_header(cls_name):
        cls_def, _, _, _ = find_class_definition(content, cls_name, class_index)
        if cls_def:
            header, _ = extract_class_header(cls_def)
            return header
        return f"class {cls_name}:"

    if methods_by_class_out:
        method_count = sum(len(methods_by_class_out[c]) for c in methods_by_class_out)
        output.append(f"=== Matching Methods ({method_count} in {len(methods_by_class_out)} classes) ===")
        output.append('')
        for class_name in sorted(methods_by_class_out.keys()):
            output.append(get_class_header(class_name))
            for name, sig, is_dep in sorted(methods_by_class_out[class_name], key=lambda x: x[0]):
                dep_marker = ' [DEPRECATED]' if is_dep else ''
                output.append(f'    {sig}{dep_marker}')
            output.append('')
        total_count += method_count

    if props_by_class_out:
        prop_count = sum(len(props_by_class_out[c]) for c in props_by_class_out)
        output.append(f"=== Matching Properties ({prop_count} in {len(props_by_class_out)} classes) ===")
        output.append('')
        for class_name in sorted(props_by_class_out.keys()):
            output.append(get_class_header(class_name))
            for name, sig, is_dep in sorted(props_by_class_out[class_name], key=lambda x: x[0]):
                dep_marker = ' [DEPRECATED]' if is_dep else ''
                output.append(f'    {sig}{dep_marker}')
            output.append('')
        total_count += prop_count

    if enums_by_class_out:
        enum_count = sum(len(enums_by_class_out[c]) for c in enums_by_class_out)
        output.append(f"=== Matching Enum Values ({enum_count} in {len(enums_by_class_out)} classes) ===")
        output.append('')
        for class_name in sorted(enums_by_class_out.keys()):
            output.append(get_class_header(class_name))
            for name, sig, is_dep in sorted(enums_by_class_out[class_name], key=lambda x: x[0]):
                dep_marker = ' [DEPRECATED]' if is_dep else ''
                output.append(f'    {sig}{dep_marker}')
            output.append('')
        total_count += enum_count

    if total_count == 0:
        return None, 0

    return '\n'.join(output).rstrip(), total_count


def execute_single_query(query, content, stub_file, filter_type=None):
    """Execute a single query and return (success, output) tuple."""
    name, member_name, is_wildcard, is_fuzzy = parse_query(query)

    if is_fuzzy:
        result = fuzzy_search(content, name, stub_file, filter_type)
        if result:
            output, count = result
            return True, f"Fuzzy search for '{query}':\n\n{output}"
        else:
            return False, f"No matches found for '{query}'"

    elif member_name is not None and is_wildcard:
        class_def, deprecated_props, deprecated_methods, deprecated_enum_values = find_class_definition(content, name)
        if not class_def:
            return False, f"Error: Class '{name}' is not defined in unreal module"

        result = search_class_members(
            class_def, member_name,
            deprecated_props, deprecated_methods, deprecated_enum_values
        )
        if result:
            output, count = result
            return True, f"Found {count} member(s) matching '{member_name}' in {name}:\n\n{output}"
        else:
            return False, f"No members matching '{member_name}' found in {name}"

    elif member_name is not None and not is_wildcard:
        chain = get_inheritance_chain(content, name)
        if not chain:
            return False, f"Error: Class '{name}' is not defined in unreal module"

        member_type = None
        definition = None
        source_class = None

        for cls_name, cls_def in chain:
            member_type, definition = find_member_definition(cls_def, member_name)
            if definition:
                source_class = cls_name
                break

        if definition:
            type_label = {
                'property': 'Property',
                'editor_property': 'Editor Property (use get_editor_property/set_editor_property)',
                'method': 'Method',
                'enum_value': 'Enum Value'
            }.get(member_type, 'Member')
            inherited_note = f' (inherited from {source_class})' if source_class != name else ''
            return True, f"{name}.{member_name} [{type_label}]{inherited_note}:\n\n{definition}"
        else:
            return False, f"Error: Member '{member_name}' not found in class '{name}' or its parents"

    elif is_class_name(name):
        summary = extract_class_summary_with_inheritance(content, name)
        if summary:
            return True, summary
        else:
            return False, f"Error: '{query}' is not defined in unreal module"

    else:
        result = find_function_definition(content, name)
        if result:
            return True, result
        else:
            return False, f"Error: '{query}' is not defined in unreal module"


def main():
    parser = argparse.ArgumentParser(
        description='Search UE5 Python API definitions in unreal.py stub file',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Query Types:
  Fuzzy search (default):  actor, Actor, location, get_actor
    - Any query without 'unreal.' prefix
    - Case-insensitive word-boundary search across all classes, methods, properties
    - Matches method/property names AND parameter types, return types
    - Results grouped by type: Classes, Methods, Properties, Enum Values

  Exact class query:       unreal.Actor
    - Returns class signature summary with all members

  Exact member query:      unreal.Actor.on_destroyed
    - Returns full definition of the specific member

  Wildcard member search:  unreal.Actor.*location*
    - Returns matching member signatures within that class

  Exact function query:    unreal.log
    - Returns full module-level function definition

Multiple queries:          unreal.Actor|Pawn|log
    - Use | to combine multiple queries in one call
    - If first query has 'unreal.' prefix, it applies to all queries

Chained fuzzy search:      actor render
    - Multiple terms filter results progressively
    - Each term must match name OR signature (params/return type)
    - Example: "inputmapping context" finds methods with InputMappingContext params

Fuzzy search filters (mutually exclusive):
    -c, --class-only       Only show matching classes
    -m, --method-only      Only show matching methods/functions
    -e, --enum-only        Only show matching enum values
'''
    )
    parser.add_argument(
        'query',
        nargs='+',
        help='Search term(s); multiple terms filter progressively'
    )
    parser.add_argument(
        '--input', '-i',
        metavar='FILE',
        help='Path to unreal.py stub file (auto-detects if not provided)'
    )

    filter_group = parser.add_mutually_exclusive_group()
    filter_group.add_argument(
        '--class-only', '-c',
        action='store_true',
        help='Fuzzy search: only show matching classes'
    )
    filter_group.add_argument(
        '--method-only', '-m',
        action='store_true',
        help='Fuzzy search: only show matching methods/functions'
    )
    filter_group.add_argument(
        '--enum-only', '-e',
        action='store_true',
        help='Fuzzy search: only show matching enum values'
    )

    args = parser.parse_args()

    filter_type = None
    if args.class_only:
        filter_type = 'class'
    elif args.method_only:
        filter_type = 'method'
    elif args.enum_only:
        filter_type = 'enum'

    try:
        stub_file = find_stub_file(args.input)

        with open(stub_file, 'r', encoding='utf-8') as f:
            content = f.read()

        first_query = args.query[0]
        if '|' in first_query and len(args.query) == 1:
            raw_queries = [q.strip() for q in first_query.split('|') if q.strip()]

            if not raw_queries:
                print("Error: No valid query provided", file=sys.stderr)
                sys.exit(1)

            queries = []
            if raw_queries[0].startswith('unreal.'):
                for q in raw_queries:
                    if q.startswith('unreal.'):
                        queries.append(q)
                    else:
                        queries.append(f'unreal.{q}')
            else:
                queries = raw_queries

            all_outputs = []
            any_success = False

            for query in queries:
                success, output = execute_single_query(query, content, stub_file, filter_type)
                if success:
                    any_success = True
                    all_outputs.append(output)
                else:
                    all_outputs.append(output)

            if len(queries) > 1:
                print('\n\n' + '=' * 60 + '\n\n'.join([''] + all_outputs))
            else:
                if any_success:
                    print(all_outputs[0])
                else:
                    print(all_outputs[0], file=sys.stderr)
                    sys.exit(1)

            if not any_success:
                sys.exit(1)

        else:
            search_terms = args.query

            if search_terms[0].startswith('unreal.'):
                success, output = execute_single_query(search_terms[0], content, stub_file, filter_type)
                if success:
                    print(output)
                else:
                    print(output, file=sys.stderr)
                    sys.exit(1)
            else:
                result = chained_fuzzy_search(content, search_terms, stub_file, filter_type)
                if result:
                    output, count = result
                    terms_str = ' '.join(search_terms)
                    print(f"Chained fuzzy search for '{terms_str}':\n")
                    print(output)
                else:
                    terms_str = ' '.join(search_terms)
                    print(f"No matches found for '{terms_str}'", file=sys.stderr)
                    sys.exit(1)

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
