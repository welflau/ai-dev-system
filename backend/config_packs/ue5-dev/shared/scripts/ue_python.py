#!/usr/bin/env python3
"""
ue_python.py — Send Python code to a running UE Editor.

Wraps UE's built-in remote_execution.py (shipped with Python Editor Script Plugin).
Engine path is read from .claude/ue-config.json, or detected from registry.

Requires: Edit > Project Settings > Plugins > Python > Enable Remote Execution Server

Usage:
    python ue_python.py "import unreal; print(unreal.SystemLibrary.get_engine_version())"
    python ue_python.py --file script.py
    echo "import unreal; print('ok')" | python ue_python.py

Exit codes:
    0 = success
    1 = execution error (Python raised an exception inside UE)
    2 = connection failed (UE Editor not found or Remote Execution not enabled)
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


# ── 引擎路径检测 ──────────────────────────────────────────────────────────────

_RE_RELATIVE = 'Engine/Plugins/Experimental/PythonScriptPlugin/Content/Python'

def _find_re_dir():
    """返回含 remote_execution.py 的目录路径，找不到返回 None。"""

    def _check(engine_root):
        p = Path(engine_root) / _RE_RELATIVE / 'remote_execution.py'
        if p.exists():
            return str(p.parent)
        return None

    # 1. .claude/ue-config.json（在当前目录或脚本父目录）
    for base in [Path.cwd(), Path(__file__).parent.parent]:
        cfg = base / '.claude' / 'ue-config.json'
        if cfg.exists():
            try:
                data = json.loads(cfg.read_text(encoding='utf-8'))
                ep = data.get('engine_path', '')
                if ep:
                    result = _check(ep)
                    if result:
                        return result
            except Exception:
                pass

    # 2. 环境变量 UE_ENGINE_PATH（优先于注册表）
    env_path = os.environ.get('UE_ENGINE_PATH', '')
    if env_path:
        r = _check(env_path)
        if r:
            return r

    # 3. Windows 注册表（按版本号降序，优先最新版本）
    if sys.platform == 'win32':
        try:
            import winreg
            candidates = []
            for hive in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
                try:
                    key = winreg.OpenKey(hive, r'SOFTWARE\EpicGames\Unreal Engine')
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        sub = winreg.EnumKey(key, i)
                        try:
                            sk = winreg.OpenKey(key, sub)
                            ep, _ = winreg.QueryValueEx(sk, 'InstalledDirectory')
                            candidates.append((sub, ep))
                        except Exception:
                            pass
                except Exception:
                    pass
            # 按版本号降序排序，优先使用最新版本
            candidates.sort(key=lambda x: [int(n) for n in x[0].split('.') if n.isdigit()], reverse=True)
            for _, ep in candidates:
                r = _check(ep)
                if r:
                    return r
        except ImportError:
            pass

    # 3. 常见路径
    for drv in 'CDEFGH':
        for base in ['Epic Games', 'EpicGames']:
            for ver in ['5.7', '5.6', '5.5', '5.4', '5.3', '5.2']:
                r = _check(f'{drv}:/{base}/UE_{ver}')
                if r:
                    return r

    return None


# ── 核心执行 ──────────────────────────────────────────────────────────────────

_RUNNER_TEMPLATE = '''\
import sys, json, time, os
sys.path.insert(0, {re_dir!r})
import remote_execution as ue_re

config = ue_re.RemoteExecutionConfig()
re = ue_re.RemoteExecution(config)
re.start()

# 等待足够时间让所有 Editor 都响应
deadline = time.time() + {discover_timeout}
while time.time() < deadline:
    time.sleep(0.2)

nodes = re.remote_nodes
if not nodes:
    re.stop()
    sys.stdout.write(json.dumps({{"success":False,"error":"no_node","output":[],"result":""}}))
    sys.exit(2)

# 优先匹配 project_root 或 project_name
target_project = {project_hint!r}
chosen = None
if target_project:
    th = target_project.replace('\\\\', '/').lower().rstrip('/')
    for n in nodes:
        pr = n.get('project_root', '').replace('\\\\', '/').lower().rstrip('/')
        pn = n.get('project_name', '').lower()
        if th in pr or th == pn:
            chosen = n
            break

if not chosen:
    # 多个节点时打印警告，取第一个
    if len(nodes) > 1:
        names = [n.get('project_name','?') for n in nodes]
        sys.stderr.write('Warning: multiple UE Editors found ' + str(names) + ', using first: ' + names[0] + '\\n')
        sys.stderr.write('Tip: run /ue-init in the UE project directory to set project hint.\\n')
    chosen = nodes[0]

re.open_command_connection(chosen['node_id'])
try:
    result = re.run_command({code!r}, unattended=True, exec_mode='ExecuteFile')
finally:
    re.close_command_connection()
    re.stop()

sys.stdout.write(json.dumps({{
    "success": result.get("success", False),
    "output":  result.get("output", []),
    "result":  str(result.get("result", "")),
}}))
'''


def _read_project_hint():
    """从 .claude/ue-config.json 读取项目路径提示，用于多 Editor 时精准匹配。"""
    for base in [Path.cwd(), Path(__file__).parent.parent]:
        cfg = base / '.claude' / 'ue-config.json'
        if cfg.exists():
            try:
                data = json.loads(cfg.read_text(encoding='utf-8'))
                return data.get('project_root') or data.get('project_name') or ''
            except Exception:
                pass
    return ''


def run_command(code, timeout=30.0):
    """Execute Python code in UE Editor. Returns (success, output_lines, result)."""
    re_dir = _find_re_dir()
    if not re_dir:
        raise ConnectionError(
            "找不到 UE remote_execution.py。\n"
            "确认 UE 已安装，并运行 /ue-init 生成 .claude/ue-config.json"
        )

    project_hint = _read_project_hint()

    script = _RUNNER_TEMPLATE.format(
        re_dir=re_dir,
        discover_timeout=min(timeout, 3.0),  # 等待所有节点响应
        code=code,
        project_hint=project_hint,
    )

    # 写临时文件避免引号转义问题
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py',
                                    delete=False, encoding='utf-8') as tf:
        tf.write(script)
        tmp_path = tf.name

    try:
        proc = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True, text=True,
            timeout=timeout + 15,
            encoding='utf-8', errors='replace',
        )
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    stdout = proc.stdout.strip()
    last_line = stdout.split('\n')[-1] if stdout else ''

    try:
        data = json.loads(last_line)
    except json.JSONDecodeError:
        err = (proc.stderr or stdout or '').strip()[:500]
        raise RuntimeError(f'Subprocess error: {err}')

    if data.get('error') == 'no_node':
        raise ConnectionError(
            "UE Editor not found on the network.\n"
            "Check:\n"
            "  1. UE Editor is running and project is loaded\n"
            "  2. Edit > Project Settings > Plugins > Python >\n"
            "     'Enable Remote Execution Server' is checked"
        )

    success = data.get('success', False)
    output_lines = []
    for item in data.get('output', []):
        line = (item.get('output', '') if isinstance(item, dict) else str(item)).rstrip()
        if line:
            output_lines.append(line)
    result = data.get('result', '').strip()
    return success, output_lines, result


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Send Python code to a running UE Editor',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument('code', nargs='?', help='Inline Python code')
    grp.add_argument('--file', '-f', metavar='PATH', help='Python script file')
    parser.add_argument('--timeout', '-t', type=float, default=30.0)
    parser.add_argument('--quiet',   '-q', action='store_true')
    args = parser.parse_args()

    if args.file:
        try:
            code = Path(args.file).read_text(encoding='utf-8')
        except OSError as e:
            print(f'Cannot read file: {e}', file=sys.stderr)
            sys.exit(2)
    elif args.code:
        code = args.code
    else:
        code = sys.stdin.read()

    if not code.strip():
        print('Error: no code provided', file=sys.stderr)
        sys.exit(2)

    try:
        success, lines, result = run_command(code, args.timeout)
    except ConnectionError as e:
        print(f'[ue_python] Connection failed: {e}', file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f'[ue_python] Error: {e}', file=sys.stderr)
        sys.exit(2)

    if not args.quiet:
        for ln in lines:
            print(ln)
        if result:
            print(result)

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
