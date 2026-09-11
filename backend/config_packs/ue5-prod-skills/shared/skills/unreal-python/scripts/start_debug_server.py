#!/usr/bin/env python3
"""
UE5 Python Debug Server Starter

This script is executed inside UE5 Editor via remote-execute.py to start a debugpy server.
It handles debugpy installation if needed and starts listening for debugger connections.

Usage:
    This script is typically executed by the VSCode task 'ue5-start-debug-server'
    via remote-execute.py, not directly by users.
"""

import sys
import subprocess
import unreal

# Debug configuration
DEBUG_HOST = "127.0.0.1"
DEBUG_PORT = 19678

print("[UE5-DEBUG] Starting debug server setup...")

python_exe = unreal.get_interpreter_executable_path()
if not python_exe:
    print("[UE5-DEBUG] ERROR: Could not determine UE5 Python interpreter path.")
    sys.exit(1)

# Step 1: Check if debugpy is installed, install if needed
try:
    import debugpy
    print(f"[UE5-DEBUG] debugpy is already installed (version: {debugpy.__version__})")
except ImportError:
    print("[UE5-DEBUG] debugpy not found, installing...")
    try:
        subprocess.check_call(
            [sys.executable, '-m', 'pip', 'install', 'debugpy'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        print("[UE5-DEBUG] debugpy installed successfully")

        # Import after installation
        import debugpy
        print(f"[UE5-DEBUG] debugpy version: {debugpy.__version__}")
    except subprocess.CalledProcessError as e:
        print(f"[UE5-DEBUG] ERROR: Failed to install debugpy: {e}")
        sys.exit(1)
    except ImportError as e:
        print(f"[UE5-DEBUG] ERROR: Failed to import debugpy after installation: {e}")
        sys.exit(1)

# Step 2: Start debugpy server
try:
    debugpy.configure(python=python_exe)

    # Check if already listening
    if debugpy.is_client_connected():
        print(f"[UE5-DEBUG] debugpy client already connected on {DEBUG_HOST}:{DEBUG_PORT}")
        print("[UE5-DEBUG] READY")
    else:
        # Start listening
        try:
            debugpy.listen((DEBUG_HOST, DEBUG_PORT))
            print(f"[UE5-DEBUG] debugpy server started on {DEBUG_HOST}:{DEBUG_PORT}")
            print(f"[UE5-DEBUG] Waiting for VSCode to attach to {DEBUG_HOST}:{DEBUG_PORT}...")
            print("[UE5-DEBUG] READY")
        except RuntimeError as e:
            error_msg = str(e).lower()
            if "debugpy.listen() has already been called" in error_msg or "already in use" in error_msg:
                print(f"[UE5-DEBUG] debugpy server already listening on {DEBUG_HOST}:{DEBUG_PORT}")
                print("[UE5-DEBUG] READY")
            else:
                print(f"[UE5-DEBUG] ERROR: Failed to start debugpy server: {e}")
                sys.exit(1)

except Exception as e:
    print(f"[UE5-DEBUG] ERROR: Unexpected error: {e}")
    sys.exit(1)
