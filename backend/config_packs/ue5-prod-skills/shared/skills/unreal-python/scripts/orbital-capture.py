#!/usr/bin/env python3
"""
Usage:
    orbital-capture.py --target-location X,Y,Z [OPTIONS]

Examples:
    # Capture with default preset (orthographic)
    orbital-capture.py --target-location 0,0,100

    # Capture with perspective preset
    orbital-capture.py --target-location 0,0,100 --preset perspective

    # Custom output directory and distance
    orbital-capture.py --target-location 0,0,100 --distance 800 --output-dir C:/Captures
"""

import sys
import argparse
from pathlib import Path

# Add site-packages to Python path for editor_capture module
# Handle both direct execution and remote execution (where __file__ is not defined)
if '__file__' in globals():
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
        site_packages = Path.cwd()

sys.path.insert(0, str(site_packages))


def parse_vector(vector_str):
    """Parse 'X,Y,Z' string to unreal.Vector."""
    try:
        x, y, z = map(float, vector_str.split(','))
        import unreal
        return unreal.Vector(x, y, z)
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f"Invalid vector format '{vector_str}'. Expected 'X,Y,Z' (e.g., '0,0,100')"
        ) from e


def parse_resolution(res_str):
    """Parse 'WxH' string to (width, height) tuple."""
    try:
        w, h = map(int, res_str.lower().split('x'))
        if w <= 0 or h <= 0:
            raise ValueError("Resolution dimensions must be positive")
        return (w, h)
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f"Invalid resolution format '{res_str}'. Expected 'WxH' (e.g., '1920x1080')"
        ) from e


def main():
    """Main entry point for the wrapper script."""
    parser = argparse.ArgumentParser(
        description="Capture multi-angle screenshots around a target location",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
View Presets:
  all           - All views (perspective + orthographic + birdseye)
  perspective   - 4 perspective horizontal views (front, back, left, right)
  orthographic  - 6 orthographic views (front, back, left, right, top, bottom)
  birdseye      - 4 bird's eye views (elevated 45-degree angles)
  horizontal    - perspective + birdseye views
  technical     - Same as orthographic (for technical documentation)

Examples:
  %(prog)s --target-location 0,0,100
  %(prog)s --target-location 0,0,100 --preset perspective
  %(prog)s --target-location 100,200,150 --distance 800 --output-dir C:/Captures
  %(prog)s --target-location 0,0,100 --resolution 1920x1080
        """
    )

    parser.add_argument(
        "--target-location",
        type=parse_vector,
        required=False,
        dest="target_location",
        help="Camera target point in X,Y,Z format (e.g., '0,0,100'). Alternative: use --target-x/y/z"
    )

    parser.add_argument(
        "--target-x",
        type=float,
        default=None,
        dest="target_x",
        help="Target X coordinate (alternative to --target-location)"
    )

    parser.add_argument(
        "--target-y",
        type=float,
        default=None,
        dest="target_y",
        help="Target Y coordinate (alternative to --target-location)"
    )

    parser.add_argument(
        "--target-z",
        type=float,
        default=None,
        dest="target_z",
        help="Target Z coordinate (alternative to --target-location)"
    )

    parser.add_argument(
        "--distance",
        type=float,
        default=500.0,
        help="Camera distance from target in UE units (default: 500)"
    )

    parser.add_argument(
        "--preset",
        type=str,
        default="orthographic",
        choices=["all", "perspective", "orthographic", "birdseye", "horizontal", "technical"],
        help="View preset to use (default: orthographic)"
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        dest="output_dir",
        help="Output directory for screenshots (default: auto-numbered folder in project)"
    )

    parser.add_argument(
        "--resolution",
        type=parse_resolution,
        default=(800, 600),
        help="Screenshot resolution in WxH format (default: 800x600)"
    )

    args = parser.parse_args()

    # Import modules first (must be done in UE5 Python environment)
    try:
        import unreal
        import editor_capture
    except ImportError as e:
        print("=" * 60, file=sys.stderr)
        print("ERROR: Failed to import required modules", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print(f"Import error: {e}", file=sys.stderr)
        print("", file=sys.stderr)
        print("This script must run in a UE5 Python environment with editor_capture installed.", file=sys.stderr)
        print("", file=sys.stderr)
        print("Troubleshooting:", file=sys.stderr)
        print("1. Ensure the script is executed in a UE5 environment", file=sys.stderr)
        print("2. Check that editor_capture is in site-packages:", file=sys.stderr)
        print(f"   {site_packages}/editor_capture", file=sys.stderr)
        print("3. Verify Python path includes:", file=sys.stderr)
        print(f"   {site_packages}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        sys.exit(1)

    # Validate target location input
    if args.target_location is None:
        # Check if using individual coordinates
        if args.target_x is None or args.target_y is None or args.target_z is None:
            parser.error("Either --target-location or all of --target-x, --target-y, --target-z must be specified")
        # Create Vector from individual coordinates
        args.target_location = unreal.Vector(args.target_x, args.target_y, args.target_z)

    # Get the current world
    try:
        world = unreal.EditorLevelLibrary.get_editor_world()
        if not world:
            print("Error: Could not get editor world", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"Error getting editor world: {e}", file=sys.stderr)
        sys.exit(1)

    # Run orbital capture
    try:
        unreal.log("")
        unreal.log("=" * 60)
        unreal.log("ORBITAL CAPTURE")
        unreal.log("=" * 60)
        unreal.log(f"Target: {args.target_location}")
        unreal.log(f"Distance: {args.distance}")
        unreal.log(f"Preset: {args.preset}")
        unreal.log(f"Resolution: {args.resolution[0]}x{args.resolution[1]}")
        if args.output_dir:
            unreal.log(f"Output: {args.output_dir}")
        unreal.log("")

        results = editor_capture.take_orbital_screenshots_with_preset(
            loaded_world=world,
            preset=args.preset,
            target_location=args.target_location,
            distance=args.distance,
            output_dir=args.output_dir,
            resolution_width=args.resolution[0],
            resolution_height=args.resolution[1],
        )

        # Print summary
        total_captures = sum(len(files) for files in results.values() if files)
        unreal.log("")
        unreal.log("=" * 60)
        unreal.log(f"CAPTURE COMPLETE: {total_captures} screenshots saved")
        unreal.log("=" * 60)

        # Print file paths
        for view_type, file_list in results.items():
            if file_list:
                unreal.log(f"\n{view_type.upper()}:")
                for file_path in file_list:
                    unreal.log(f"  - {file_path}")

        unreal.log("")

    except Exception as e:
        print(f"Error during orbital capture: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
