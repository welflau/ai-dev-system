#!/usr/bin/env python3
"""
Usage:
    asset-diagnostic.py ASSET_PATH [--verbose]

Examples:
    # Diagnose a level
    asset-diagnostic.py /Game/Maps/TestLevel

    # Diagnose with verbose output
    asset-diagnostic.py /Game/Maps/TestLevel --verbose

    # Diagnose a blueprint
    asset-diagnostic.py /Game/Blueprints/BP_MyActor
"""

import sys
import argparse
from pathlib import Path

# Add site-packages to Python path for asset_diagnostic module
# Handle both direct execution and remote execution (where __file__ is not defined)
if '__file__' in globals():
    # Direct execution: use relative path from script location
    site_packages = Path(__file__).parent.parent.parent / "skills" / "ue5-python" / "site-packages"
else:
    # Remote execution: try to find site-packages by searching common locations
    possible_paths = [
        Path("d:/Code/ue5-dev-tools/ue5-dev-tools/skills/ue5-python/site-packages"),
        Path.cwd() / "ue5-dev-tools" / "skills" / "ue5-python" / "site-packages",
    ]
    site_packages = None
    for path in possible_paths:
        if path.exists():
            site_packages = path
            break

    if not site_packages:
        # Last resort: try to import directly (may already be in path)
        site_packages = Path.cwd()

sys.path.insert(0, str(site_packages))


def main():
    """Main entry point for the wrapper script."""
    parser = argparse.ArgumentParser(
        description="Diagnose UE5 assets for common issues",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s /Game/Maps/TestLevel
  %(prog)s /Game/Maps/TestLevel --verbose
  %(prog)s /Game/Blueprints/BP_MyActor

For diagnosing current level or selected assets, use Python API directly:
  import asset_diagnostic
  asset_diagnostic.diagnose_current_level()
  asset_diagnostic.diagnose_selected()
        """
    )

    parser.add_argument(
        "--asset-path",
        required=True,
        dest="asset_path",
        help="Path to the asset to diagnose (e.g., /Game/Maps/TestLevel)"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print comprehensive analysis and metadata (default: issues only)"
    )

    args = parser.parse_args()

    # Import asset_diagnostic module (must be done in UE5 Python environment)
    try:
        import asset_diagnostic
    except ImportError as e:
        print("=" * 60, file=sys.stderr)
        print("ERROR: Failed to import asset_diagnostic module", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print(f"Import error: {e}", file=sys.stderr)
        print("", file=sys.stderr)
        print("This script must run in a UE5 Python environment with asset_diagnostic installed.", file=sys.stderr)
        print("", file=sys.stderr)
        print("Troubleshooting:", file=sys.stderr)
        print("1. Ensure the script is executed in a UE5 environment", file=sys.stderr)
        print("2. Check that asset_diagnostic is in site-packages:", file=sys.stderr)
        print(f"   {site_packages}/asset_diagnostic", file=sys.stderr)
        print("3. Verify Python path includes:", file=sys.stderr)
        print(f"   {site_packages}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        sys.exit(1)

    # Run diagnostic
    try:
        result = asset_diagnostic.diagnose(args.asset_path, verbose=args.verbose)

        # Exit with error code if diagnostic found issues
        if result and result.has_errors:
            sys.exit(1)

    except Exception as e:
        print(f"Error running diagnostic: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
