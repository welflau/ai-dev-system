#!/usr/bin/env python3
"""
Usage:
    pie-capture.py start --output-dir PATH [OPTIONS]
    pie-capture.py stop
    pie-capture.py status

Examples:
    # Start PIE capture with auto-start
    pie-capture.py start --output-dir C:/Captures --auto-start-pie

    # Start with custom interval and resolution
    pie-capture.py start --output-dir C:/Captures --interval 2.0 --resolution 1920x1080

    # Stop active capture
    pie-capture.py stop

    # Check capture status
    pie-capture.py status
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


def cmd_start(args):
    """Handle the 'start' command."""
    import unreal
    import editor_capture

    unreal.log("")
    unreal.log("=" * 60)
    unreal.log("PIE CAPTURE START")
    unreal.log("=" * 60)
    unreal.log(f"Output directory: {args.output_dir}")
    unreal.log(f"Interval: {args.interval} seconds")
    unreal.log(f"Resolution: {args.resolution[0]}x{args.resolution[1]}")
    unreal.log(f"Multi-angle: {args.multi_angle}")
    unreal.log(f"Camera distance: {args.camera_distance}")
    unreal.log(f"Target height: {args.target_height}")
    unreal.log(f"Auto-start PIE: {args.auto_start_pie}")
    unreal.log("")

    try:
        capturer = editor_capture.start_pie_capture(
            output_dir=args.output_dir,
            interval_seconds=args.interval,
            resolution=args.resolution,
            auto_start_pie=args.auto_start_pie,
            multi_angle=args.multi_angle,
            camera_distance=args.camera_distance,
            target_height=args.target_height,
        )

        unreal.log("[SUCCESS] PIE capture started successfully")
        if args.auto_start_pie:
            unreal.log("[INFO] PIE session auto-started")
        else:
            unreal.log("[INFO] Start PIE manually to begin capturing")
        unreal.log("")

    except Exception as e:
        print(f"Error starting PIE capture: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


def cmd_stop(args):
    """Handle the 'stop' command."""
    import unreal
    import editor_capture

    unreal.log("")
    unreal.log("=" * 60)
    unreal.log("PIE CAPTURE STOP")
    unreal.log("=" * 60)

    try:
        editor_capture.stop_pie_capture()
        unreal.log("[SUCCESS] PIE capture stopped")
        unreal.log("")

    except Exception as e:
        print(f"Error stopping PIE capture: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_status(args):
    """Handle the 'status' command."""
    import unreal
    import editor_capture

    unreal.log("")
    unreal.log("=" * 60)
    unreal.log("PIE CAPTURE STATUS")
    unreal.log("=" * 60)

    try:
        is_running = editor_capture.is_pie_running()
        capturer = editor_capture.get_pie_capturer()

        if capturer:
            unreal.log("[STATUS] Capturer: ACTIVE")
            unreal.log(f"[INFO] Output directory: {capturer.output_dir}")
            unreal.log(f"[INFO] Interval: {capturer.interval_seconds} seconds")
            unreal.log(f"[INFO] Multi-angle: {capturer.multi_angle}")
        else:
            unreal.log("[STATUS] Capturer: INACTIVE")

        if is_running:
            unreal.log("[STATUS] PIE Session: RUNNING")
        else:
            unreal.log("[STATUS] PIE Session: NOT RUNNING")

        unreal.log("")

    except Exception as e:
        print(f"Error checking status: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    """Main entry point for the wrapper script."""
    parser = argparse.ArgumentParser(
        description="Control Play-In-Editor (PIE) screenshot capture",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  start     Start PIE capture with specified settings
  stop      Stop active PIE capture
  status    Check PIE capture and session status
        """
    )

    parser.add_argument(
        "--command",
        type=str,
        required=True,
        choices=["start", "stop", "status"],
        help="Command to execute: start, stop, or status"
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        dest="output_dir",
        help="Output directory for screenshots (required for 'start' command)"
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Screenshot interval in seconds (default: 1.0)"
    )

    parser.add_argument(
        "--resolution",
        type=str,
        default="1920x1080",
        help="Screenshot resolution in WxH format (default: 1920x1080)"
    )

    parser.add_argument(
        "--multi-angle",
        type=lambda x: x.lower() in ("true", "1", "yes"),
        default=True,
        dest="multi_angle",
        help="Enable multi-angle capture (default: true)"
    )

    parser.add_argument(
        "--camera-distance",
        type=float,
        default=300,
        dest="camera_distance",
        help="Camera distance from target (default: 300)"
    )

    parser.add_argument(
        "--target-height",
        type=float,
        default=90,
        dest="target_height",
        help="Target height offset (default: 90)"
    )

    parser.add_argument(
        "--auto-start-pie",
        type=lambda x: x.lower() in ("true", "1", "yes"),
        default=False,
        dest="auto_start_pie",
        help="Auto-start PIE session"
    )

    args = parser.parse_args()

    # Parse resolution
    args.resolution = parse_resolution(args.resolution)

    # Import modules (must be done in UE5 Python environment)
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

    # Execute command
    if args.command == "start":
        if not args.output_dir:
            parser.error("--output-dir is required for 'start' command")
        cmd_start(args)
    elif args.command == "stop":
        cmd_stop(args)
    elif args.command == "status":
        cmd_status(args)


if __name__ == "__main__":
    main()
