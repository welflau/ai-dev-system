#!/usr/bin/env python3
"""
Install ExtraPythonAPIs plugin to a UE5 project.

This script copies the plugin to the project's Plugins directory and
optionally enables it in the .uproject file.

Usage:
    python install_blueprint_utils_plugin.py --project /path/to/project
    python install_blueprint_utils_plugin.py --project /path/to/project --enable
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

# Get the plugin source directory (relative to this script)
SCRIPT_DIR = Path(__file__).parent.resolve()
PLUGIN_SOURCE = SCRIPT_DIR.parent / "plugin" / "ExtraPythonAPIs"
PLUGIN_NAME = "ExtraPythonAPIs"


def find_uproject(project_path: Path) -> Path | None:
    """Find the .uproject file in the given directory."""
    project_path = Path(project_path)

    # If it's a file, check if it's a .uproject
    if project_path.is_file() and project_path.suffix == ".uproject":
        return project_path

    # If it's a directory, look for .uproject files
    if project_path.is_dir():
        uproject_files = list(project_path.glob("*.uproject"))
        if uproject_files:
            return uproject_files[0]

    return None


def install_plugin(project_path: Path, enable: bool = False) -> bool:
    """
    Install the plugin to the target project.

    Args:
        project_path: Path to the UE5 project directory or .uproject file
        enable: If True, also enable the plugin in .uproject

    Returns:
        True if successful, False otherwise
    """
    # Validate plugin source exists
    if not PLUGIN_SOURCE.exists():
        print(f"[ERROR] Plugin source not found: {PLUGIN_SOURCE}")
        return False

    # Find the .uproject file
    uproject = find_uproject(project_path)
    if not uproject:
        print(f"[ERROR] No .uproject file found in: {project_path}")
        return False

    project_dir = uproject.parent
    plugins_dir = project_dir / "Plugins"
    target_plugin_dir = plugins_dir / PLUGIN_NAME

    print(f"[INFO] Project: {uproject}")
    print(f"[INFO] Plugin source: {PLUGIN_SOURCE}")
    print(f"[INFO] Target: {target_plugin_dir}")

    # Create Plugins directory if it doesn't exist
    plugins_dir.mkdir(exist_ok=True)

    # Remove existing plugin if present
    if target_plugin_dir.exists():
        print(f"[INFO] Removing existing plugin at {target_plugin_dir}")
        shutil.rmtree(target_plugin_dir)

    # Copy plugin
    print(f"[INFO] Copying plugin...")
    shutil.copytree(PLUGIN_SOURCE, target_plugin_dir)
    print(f"[OK] Plugin installed to {target_plugin_dir}")

    # Enable plugin in .uproject if requested
    if enable:
        if enable_plugin_in_uproject(uproject):
            print(f"[OK] Plugin enabled in {uproject.name}")
        else:
            print(f"[WARNING] Failed to enable plugin in {uproject.name}")

    return True


def enable_plugin_in_uproject(uproject: Path) -> bool:
    """
    Enable the plugin in the .uproject file.

    Args:
        uproject: Path to the .uproject file

    Returns:
        True if successful, False otherwise
    """
    try:
        with open(uproject, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Ensure Plugins array exists
        if "Plugins" not in data:
            data["Plugins"] = []

        # Check if plugin already exists
        for plugin in data["Plugins"]:
            if plugin.get("Name") == PLUGIN_NAME:
                plugin["Enabled"] = True
                break
        else:
            # Add new plugin entry
            data["Plugins"].append({
                "Name": PLUGIN_NAME,
                "Enabled": True
            })

        # Write back
        with open(uproject, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent='\t')

        return True

    except Exception as e:
        print(f"[ERROR] Failed to update .uproject: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Install ExtraPythonAPIs plugin to a UE5 project"
    )
    parser.add_argument(
        "--project", "-p",
        required=True,
        help="Path to UE5 project directory or .uproject file"
    )
    parser.add_argument(
        "--enable", "-e",
        action="store_true",
        help="Enable the plugin in .uproject after installation"
    )

    args = parser.parse_args()

    # Use CLAUDE_PROJECT_DIR as fallback
    project_path = args.project
    if project_path == "auto":
        project_path = os.environ.get("CLAUDE_PROJECT_DIR", ".")

    success = install_plugin(Path(project_path), args.enable)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
