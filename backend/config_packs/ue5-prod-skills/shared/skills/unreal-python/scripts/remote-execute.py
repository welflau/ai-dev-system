#!/usr/bin/env python3
"""
UE5 Remote Python Script Executor

This script allows you to execute arbitrary Python scripts in a connected UE5 editor
using the Python plugin's socket-based remote execution capabilities.

The script uses multicast discovery to find running UE5 instances and establishes
a socket connection for direct Python code execution.

Usage:
    # Execute Python code
    python remote-execute.py --code "print('Hello')" --project-path /path/to/project.uproject

    # Execute a Python file
    python remote-execute.py --file /path/to/script.py --project-path /path/to/project.uproject

    # Execute a Python file with arguments (converted to sys.argv for argparse)
    python remote-execute.py --file script.py --args "preset=orthographic,level=/Game/Maps/MyLevel,resolution=1920x1080"

    # Execute with project name filter
    python remote-execute.py --code "print('Hello')" --project-name MyProject

    # Execute file with custom multicast group
    python remote-execute.py --file script.py --project-path project.uproject --multicast-group 239.0.0.1:6766

Requirements:
    - UE5 with Python plugin enabled
    - Python remote execution enabled in project settings
"""

import argparse
import json
import logging
import os
import socket
import sys
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

# Add lib directory to Python path (unreal-python/scripts/ -> unreal-python/lib/)
lib_path = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(lib_path))

from ue5_remote import UE5RemoteExecution
from unreal_python_utils import find_project_name, build_project, needs_rebuild

# Configure logging
logging.basicConfig(format="[%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


def launch_editor(
    executor: UE5RemoteExecution,
    launch_project_path: Path,
    project_root: Path,
) -> bool:
    """
    Launch UE5 Editor and wait for it to become available.

    Args:
        executor: UE5RemoteExecution instance to use for discovering running instance
        launch_project_path: Path to .uproject file
        project_root: Root directory of the project

    Returns:
        True if editor launched and became available, False otherwise
    """
    # Check and Fix Configuration
    logger.info(f"Checking project configuration in: {project_root}")
    from ue5_remote.config import run_config_check

    config_result = run_config_check(project_root, auto_fix=True)

    if config_result["status"] == "error":
        logger.error(f"Configuration check failed: {config_result['summary']}")
        return False

    if config_result["python_plugin"]["modified"]:
        logger.info(f"Fixed Python Plugin: {config_result['python_plugin']['message']}")

    if config_result["remote_execution"]["modified"]:
        logger.info(
            f"Fixed Remote Execution: {config_result['remote_execution']['message']}"
        )

    if config_result["status"] == "fixed":
        logger.info("Configuration fixed. Proceeding...")
    elif config_result["status"] == "ok":
        logger.info("Configuration is correct.")

    # Check if build is needed
    rebuild_needed, rebuild_reason = needs_rebuild(launch_project_path)

    if rebuild_needed:
        logger.info(f"Build required: {rebuild_reason}")
        logger.info("Building project before launching Editor...")
        build_success, build_msg = build_project(launch_project_path)
        if build_success:
            logger.info(build_msg)
        else:
            logger.error(f"Build failed: {build_msg}")
            return False
    else:
        logger.info(f"Skipping build: {rebuild_reason}")

    # Find Editor
    from unreal_python_utils import find_ue5_editor

    editor_path = find_ue5_editor()

    if not editor_path:
        logger.error(
            "Could not find Unreal Editor executable. Please launch it manually."
        )
        return False

    logger.info(f"Launching UE5 Editor: {editor_path}")
    logger.info(f"Project: {launch_project_path}")

    # Launch Editor
    subprocess.Popen(
        [str(editor_path), str(launch_project_path)], start_new_session=True
    )

    # Wait for editor to start (poll for instance)
    max_attempts = 60  # 60 * 2s = 120s timeout
    logger.info(
        "Waiting for UE5 to start and enable remote execution (timeout: 120s)..."
    )

    found = False
    for i in range(max_attempts):
        if executor.find_unreal_instance():
            found = True
            break
        time.sleep(2.0)

    if not found:
        logger.error("Timeout waiting for Editor to start and enable remote execution.")
        return False

    return True


def find_correct_instance(
    executor: UE5RemoteExecution,
    expected_project_path: Optional[Path],
) -> bool:
    """
    Find UE5 instance matching the expected project path.

    Args:
        executor: UE5RemoteExecution instance
        expected_project_path: Expected .uproject file path

    Returns:
        True if matching instance found and selected, False otherwise
    """
    instances = executor.find_all_matching_instances()

    if not instances:
        return False

    if not expected_project_path:
        # No path specified, use first instance
        executor.unreal_node_id = instances[0].get("source")
        return True

    # Check each instance for matching project path
    expected_resolved = expected_project_path.resolve()

    for instance in instances:
        executor.unreal_node_id = instance.get("source")

        if not executor.open_connection():
            continue

        actual_path = None
        try:
            actual_path = executor.get_project_path()
            if actual_path:
                actual_resolved = Path(actual_path).resolve()
                if actual_resolved == expected_resolved:
                    logger.info(f"Found matching instance: {actual_path}")
                    return True
                else:
                    logger.debug(f"Instance project mismatch: {actual_path}")
        except Exception as e:
            logger.debug(f"Error checking instance: {e}")

        if not (actual_path and Path(actual_path).resolve() == expected_resolved):
            executor.close_connection()

    logger.info(f"No instance found for project: {expected_project_path}")
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Execute arbitrary Python scripts in UE5 editor via socket-based remote execution",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Execute Python code
  python remote-execute.py --code "print('Hello')" --project-path /path/to/project.uproject

  # Execute a Python file
  python remote-execute.py --file script.py --project-path /path/to/project.uproject

  # Execute a Python file with arguments (converted to --key value for argparse)
  python remote-execute.py --file script.py --args "preset=orthographic,no-grid=true"

  # Custom multicast group
  python remote-execute.py --file script.py --project-path project.uproject --multicast-group 239.0.0.1:6766

  # Enable verbose logging
  python remote-execute.py --code "..." --project-path project.uproject -v
        """,
    )

    parser.add_argument("--code", help="Python code to execute")

    parser.add_argument("--file", type=Path, help="Python file to execute")

    parser.add_argument(
        "--project-path",
        type=Path,
        help="Path to .uproject file (optional if --project-name is specified)",
    )

    parser.add_argument(
        "--project-name",
        default=None,
        help="Project name to filter UE5 instances (default: auto-detect)",
    )

    parser.add_argument(
        "--multicast-group",
        default="239.0.0.1:6766",
        help="Multicast group IP:port (default: 239.0.0.1:6766)",
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Command execution timeout in seconds (default: 5.0)",
    )

    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )

    parser.add_argument(
        "--detached",
        action="store_true",
        help="Run in detached mode (spawn subprocess and exit)",
    )

    parser.add_argument(
        "--wait",
        type=float,
        default=0.0,
        help="Wait time in seconds before execution (useful for detached mode)",
    )

    parser.add_argument(
        "--no-restart-on-crash",
        action="store_true",
        help="Disable automatic editor restart if connection is lost (likely crash)",
    )

    parser.add_argument(
        "--args",
        type=str,
        default="",
        help="Arguments as key=value pairs, comma-separated. Converted to sys.argv for argparse. "
        "Boolean flags: key=true adds --key, key=false skips. "
        "(e.g., 'preset=orthographic,no-grid=true,resolution=1920x1080')",
    )

    args = parser.parse_args()

    # Handle detached mode
    if args.detached:
        # Filter out --detached from arguments
        new_args = [sys.executable] + [arg for arg in sys.argv if arg != "--detached"]

        # Spawn detached subprocess
        subprocess.Popen(
            new_args,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        sys.exit(0)

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # Wait if requested
    if args.wait > 0:
        logger.info(f"Waiting {args.wait} seconds before execution...")
        time.sleep(args.wait)

    # Validate arguments
    if not args.code and not args.file:
        parser.error("Either --code or --file must be specified")

    # Determine project name (Priority: CLI args > Auto-detect from filesystem)
    project_name = args.project_name if args.project_name else find_project_name()

    if not args.project_path and not project_name:
        parser.error(
            "Could not determine project name.\n"
            "Please specify either:\n"
            "  --project-name <name>   (to filter by project)\n"
            "  --project-path <path>   (to enable auto-launch)\n"
            "Or run from a directory containing a .uproject file"
        )

    # Prepare command
    if args.code:
        command = args.code
        exec_type = UE5RemoteExecution.ExecTypes.EXECUTE_FILE
    else:
        file_path = args.file.absolute()

        # Check if script arguments are provided
        if args.args:
            # Parse key=value pairs (comma-separated, no spaces after commas)
            script_args = {}
            for pair in args.args.split(","):
                if "=" in pair:
                    key, value = pair.split("=", 1)
                    script_args[key.strip()] = value
                elif pair.strip():
                    logger.warning(f"Ignoring invalid argument (no '='): {pair}")

            # Read script content
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    script_content = f.read()
            except Exception as e:
                logger.error(f"Failed to read script file: {e}")
                sys.exit(1)

            # Build sys.argv list for argparse compatibility
            argv_list = [str(file_path)]  # argv[0] is script name
            for key, value in script_args.items():
                # Convert underscores to hyphens for argparse compatibility
                arg_name = key.replace("_", "-")
                # Handle boolean flags (true = add flag, false = skip)
                if value.lower() in ("true", "false"):
                    if value.lower() == "true":
                        argv_list.append(f"--{arg_name}")
                else:
                    argv_list.append(f"--{arg_name}")
                    # Normalize UE paths: //Game/... -> /Game/... (MSYS escape workaround)
                    if value.startswith("//") and not value.startswith("///"):
                        value = value[1:]  # Remove one leading slash
                    argv_list.append(value)

            # Inject sys.argv override at the beginning of the script
            argv_repr = repr(argv_list)
            command = f"import sys\nsys.argv = {argv_repr}\n{script_content}"
            exec_type = UE5RemoteExecution.ExecTypes.EXECUTE_FILE

            if args.verbose:
                logger.debug(f"Script arguments: {script_args}")
                logger.debug(f"Injected sys.argv: {argv_list}")
        else:
            command = str(file_path)
            exec_type = UE5RemoteExecution.ExecTypes.EXECUTE_FILE

    # Parse multicast group
    try:
        ip, port = args.multicast_group.split(":")
        multicast_group = (ip, int(port))
    except ValueError:
        parser.error("Invalid multicast group format. Use IP:port")

    # Create executor
    executor = UE5RemoteExecution(
        multicast_group=multicast_group, project_name=project_name or ""
    )

    # Find and connect to UE5
    if not find_correct_instance(executor, args.project_path):
        logger.info("No running UE5 instance found. Preparing to auto-launch...")

        # Determine project info for launch AND config check
        launch_project_path = args.project_path
        project_root = None

        if launch_project_path:
            # If user provided .uproject path
            if launch_project_path.is_file():
                project_root = launch_project_path.parent
            else:
                if launch_project_path.is_dir():
                    project_root = launch_project_path
                    candidates = list(project_root.glob("*.uproject"))
                    if candidates:
                        launch_project_path = candidates[0]
        elif project_name:
            # Try to find project root from filesystem
            from unreal_python_utils import find_ue5_project_root

            project_root = find_ue5_project_root()
            if project_root:
                candidates = list(project_root.glob("*.uproject"))
                if candidates:
                    launch_project_path = candidates[0]

        if not launch_project_path or not project_root:
            logger.error(
                "Cannot auto-launch: Project path/root not specified and could not be inferred."
            )
            sys.exit(1)

        # Launch editor and wait for it to be ready
        if not launch_editor(executor, launch_project_path, project_root):
            sys.exit(1)

    # Execute command with crash detection and retry
    max_crash_retries = 0 if args.no_restart_on_crash else 1
    result = None

    for attempt in range(max_crash_retries + 1):
        if not executor.open_connection():
            sys.exit(1)

        try:
            result = executor.execute_command(
                command, exec_type=exec_type, timeout=args.timeout
            )
        finally:
            executor.close_connection()

        # Check for crash
        if result.get("crashed", False) and attempt < max_crash_retries:
            logger.warning("Editor appears to have crashed. Restarting...")

            # Need to determine project info for restart
            launch_project_path = None
            project_root = None

            if args.project_path:
                if args.project_path.is_file():
                    project_root = args.project_path.parent
                    launch_project_path = args.project_path
                elif args.project_path.is_dir():
                    project_root = args.project_path
                    candidates = list(project_root.glob("*.uproject"))
                    if candidates:
                        launch_project_path = candidates[0]
            elif project_name:
                from unreal_python_utils import find_ue5_project_root

                project_root = find_ue5_project_root()
                if project_root:
                    candidates = list(project_root.glob("*.uproject"))
                    if candidates:
                        launch_project_path = candidates[0]

            if not launch_project_path or not project_root:
                logger.error("Cannot restart editor: Project path/root not available.")
                sys.exit(1)

            if not launch_editor(executor, launch_project_path, project_root):
                logger.error("Failed to restart editor")
                sys.exit(1)

            continue  # Retry command execution

        break  # Success or non-crash error

    # Print results
    if "error" in result and result.get("error"):
        logger.error(f"Execution failed: {result['error']}")
        sys.exit(1)

    if "success" in result and result["success"]:
        if "result" in result:
            print(f"Result: {result['result']}")
        if "output" in result and result["output"]:
            print("Output:")
            for line in result["output"]:
                if isinstance(line, dict):
                    print(f"  {line.get('type', 'log')}: {line.get('output', '')}")
                else:
                    print(f"  {line}")
        sys.exit(0)
    else:
        logger.error("Command execution failed")
        if "raw" in result:
            print(json.dumps(result["raw"], indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
