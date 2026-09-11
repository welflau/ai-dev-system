# VSCode Debugger Reference

Configure VSCode for F5 debugging of Python scripts running in Unreal Engine 5 editor via debugpy remote debugging.

## Overview

This workflow enables standard VSCode breakpoint debugging for UE5 Python scripts. It uses debugpy for remote attachment on port 19678.

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/setup-vscode.py` | Generates `.vscode/launch.json` and `tasks.json` |
| `scripts/remote-execute.py` | Sends Python code/files to UE5 via remote execution protocol |
| `scripts/start_debug_server.py` | Starts debugpy server inside UE5 editor |

## Quick Setup

```bash
# Auto-detect project root
python scripts/setup-vscode.py

# Specify project path
python scripts/setup-vscode.py --project /path/to/ue5/project

# Force overwrite existing configs
python scripts/setup-vscode.py --force
```

This creates:
- `.vscode/launch.json` — Debug configurations for attaching to UE5
- `.vscode/tasks.json` — Tasks for starting debugpy and executing scripts

## Workflows

### First-Time Setup

1. Run `scripts/setup-vscode.py` to generate VSCode configs
2. Install debugpy in UE5's Python via remote execution:
   ```bash
   python scripts/remote-execute.py \
     --code "import subprocess; subprocess.run(['pip', 'install', 'debugpy'])"
   ```
3. Open a Python file → Set breakpoint → Press F5

### F5 Debug Current File

1. Open a Python file in VSCode
2. Set breakpoints by clicking left of line numbers
3. Press F5 → Select **"UE5 Python: Debug Current File"**
4. Behind the scenes:
   - Task `ue5-start-debug-server` starts debugpy in UE5
   - Task `ue5-execute-python` sends your file to UE5
   - Debugger attaches and pauses at breakpoints

### Attach-Only Mode

For debugging already-running debugpy servers:

1. Manually start debugpy:
   ```bash
   python scripts/remote-execute.py --file scripts/start_debug_server.py
   ```
2. In VSCode, select **"UE5 Python: Attach Only"** → Press F5

## Configuration

### Debug Port

- **Default:** 19678
- **Protocol:** debugpy (Debug Adapter Protocol)
- **Connection:** localhost attachment

To change port:
1. Edit `scripts/start_debug_server.py` (`DEBUG_PORT`)
2. Edit `.vscode/launch.json` (`port` field)

### Path Mappings

Default: local and remote paths are identical:
```json
"pathMappings": [
  {
    "localRoot": "${workspaceFolder}",
    "remoteRoot": "${workspaceFolder}"
  }
]
```

Customize if UE5 Python scripts reside in a different location than the VSCode workspace.

## Generated VSCode Configurations

### launch.json

| Configuration | Description |
|--------------|-------------|
| UE5 Python: Debug Current File | Starts debugpy + executes current file + attaches |
| UE5 Python: Attach Only | Attaches to existing debugpy server |

### tasks.json

| Task | Description |
|------|-------------|
| ue5-start-debug-server | Starts debugpy server in UE5 via remote-execute.py |
| ue5-execute-python | Executes current file in UE5 (detached mode) |
| ue5-start-debug-and-execute | Sequential combo of above two tasks |

## Remote Execution

See `scripts/remote-execute.py --help` for full CLI options. Key usage:

```bash
# Execute a file in UE5
python scripts/remote-execute.py --file myscript.py

# Execute inline code
python scripts/remote-execute.py --code "print('Hello from UE5')"

# Execute with specific project
python scripts/remote-execute.py --file myscript.py --project-name MyProject

# Detached mode (don't wait for output)
python scripts/remote-execute.py --file myscript.py --detached
```
