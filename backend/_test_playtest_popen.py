"""直接测试 subprocess.Popen 启动 UnrealEditor-Cmd.exe"""
import subprocess, sys, os
sys.stdout.reconfigure(encoding='utf-8')

editor_cmd = r"G:\EpicGames\UE_5.7\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
uproject   = r"F:\Projects\TestTPS\MyFPS.uproject"

print("exe exists:", os.path.exists(editor_cmd))
print("uproject exists:", os.path.exists(uproject))

cmd = [
    editor_cmd, uproject,
    "-ExecCmds=Automation RunTests Project.;Quit",
    "-nullrhi", "-unattended", "-nopause", "-nosplash",
    "-buildmachine", "-NoSound",
]
print("cmd:", cmd)

try:
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace",
    )
    print(f"pid={proc.pid}, 等待 5s 输出...")
    import time; start = time.time()
    while time.time() - start < 5:
        line = proc.stdout.readline()
        if not line:
            break
        print("OUT:", line.rstrip())
    proc.terminate()
    print("OK: process started successfully")
except FileNotFoundError as e:
    print(f"FileNotFoundError: {e!r}")
except Exception as e:
    print(f"Exception type={type(e).__name__!r} repr={e!r} str={str(e)!r} args={e.args!r}")
    import traceback; traceback.print_exc()
