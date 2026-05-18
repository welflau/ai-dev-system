"""
ue_python_bridge.py — 向運行中的 UE Editor 發送 Python 代碼執行

移植自 ECC/scripts/ue_python.py（已驗證），適配 ADS 的異步環境。
通信協議：UE 官方 remote_execution.py（UDP 多播發現 + TCP 執行）

前置條件：
  1. UE Editor 已運行並載入項目
  2. Edit > Project Settings > Plugins > Python > Enable Remote Execution Server 已勾選

用法：
    from engines.ue_python_bridge import run_python
    result = await run_python("import unreal; print(unreal.SystemLibrary.get_engine_version())", project_id)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger("engines.ue_python_bridge")

# remote_execution.py 在引擎中的相對路徑
_RE_RELATIVE = "Engine/Plugins/Experimental/PythonScriptPlugin/Content/Python"

# 用於生成在子進程中執行的 runner 腳本模板
_RUNNER_TEMPLATE = '''\
import sys, json, time
sys.path.insert(0, {re_dir!r})
import remote_execution as ue_re

config = ue_re.RemoteExecutionConfig()
re = ue_re.RemoteExecution(config)
re.start()

# 等待 Editor 響應（discover_timeout 秒）
deadline = time.time() + {discover_timeout}
while time.time() < deadline:
    time.sleep(0.2)

nodes = re.remote_nodes
if not nodes:
    re.stop()
    sys.stdout.write(json.dumps({{"success":False,"error":"no_node","output":[],"result":""}}))
    sys.exit(2)

# 按 project_hint 匹配目標 Editor（多個 Editor 同時運行時精準選擇）
target = {project_hint!r}
chosen = None
if target:
    th = target.replace('\\\\', '/').lower().rstrip('/')
    for n in nodes:
        pr = n.get('project_root', '').replace('\\\\', '/').lower().rstrip('/')
        pn = n.get('project_name', '').lower()
        if th in pr or th == pn:
            chosen = n
            break

if not chosen:
    if len(nodes) > 1:
        names = [n.get('project_name','?') for n in nodes]
        sys.stderr.write('Warning: multiple UE Editors: ' + str(names) + ', using: ' + names[0] + '\\n')
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


def _find_re_dir(engine_path: Optional[str] = None) -> Optional[str]:
    """尋找 remote_execution.py 所在目錄。
    優先順序：
    1. 傳入的 engine_path
    2. 環境變量 UE_ENGINE_PATH
    3. Windows 註冊表（通過 ue_resolver 掃描）
    4. 常見路徑枚舉
    """
    def _check(root: str) -> Optional[str]:
        p = Path(root) / _RE_RELATIVE / "remote_execution.py"
        return str(p.parent) if p.exists() else None

    # 1. 指定引擎路徑
    if engine_path:
        r = _check(engine_path)
        if r:
            return r

    # 2. 環境變量
    env_path = os.environ.get("UE_ENGINE_PATH", "")
    if env_path:
        r = _check(env_path)
        if r:
            return r

    # 3. Windows 註冊表（復用 ue_resolver）
    try:
        from engines.ue_resolver import detect_installed_engines
        engines = detect_installed_engines()
        # 按版本倒序，優先最新
        for eng in sorted(engines, key=lambda e: e.version or "", reverse=True):
            r = _check(str(eng.install_dir))
            if r:
                return r
    except Exception as e:
        logger.debug("ue_resolver 掃描失敗: %s", e)

    # 4. 常見路徑枚舉
    for drv in "CDEFGHI":
        for base in ["Epic Games", "EpicGames"]:
            for ver in ["5.7", "5.6", "5.5", "5.4", "5.3", "5.2", "5.1"]:
                r = _check(f"{drv}:/{base}/UE_{ver}")
                if r:
                    return r

    return None


async def _get_project_hint(project_id: Optional[str]) -> str:
    """取項目根路徑作為 Editor 匹配提示（多 Editor 同時運行時使用）"""
    if not project_id:
        return ""
    try:
        from database import db
        row = await db.fetch_one(
            "SELECT local_repo_path FROM projects WHERE id = ?", (project_id,)
        )
        if row and row.get("local_repo_path"):
            return str(row["local_repo_path"])
    except Exception as e:
        logger.debug("取 project hint 失敗: %s", e)
    return ""


async def run_python(
    code: str,
    project_id: Optional[str] = None,
    engine_path: Optional[str] = None,
    timeout: float = 60.0,
    discover_timeout: float = 3.0,
) -> Dict:
    """向運行中的 UE Editor 發送 Python 代碼執行。

    Returns:
        {
            "success": bool,
            "stdout": str,          # 合併的輸出行
            "result": str,          # 最後一行 result
            "error": str | None,    # 錯誤信息（success=False 時）
            "exit_code": int,
        }
    """
    # 1. 找 remote_execution.py
    re_dir = _find_re_dir(engine_path)
    if not re_dir:
        return {
            "success": False,
            "stdout": "",
            "result": "",
            "error": (
                "找不到 UE remote_execution.py。\n"
                "請確認：\n"
                "  1. UE 已安裝\n"
                "  2. Edit > Project Settings > Plugins > Python > Enable Remote Execution Server 已勾選\n"
                "  3. 設置環境變量 UE_ENGINE_PATH 指向引擎根目錄"
            ),
            "exit_code": 2,
        }

    # 2. 取項目提示
    project_hint = await _get_project_hint(project_id)

    # 3. 生成 runner 腳本
    script = _RUNNER_TEMPLATE.format(
        re_dir=re_dir,
        discover_timeout=min(discover_timeout, timeout * 0.3),
        code=code,
        project_hint=project_hint,
    )

    # 4. 寫臨時文件（避免命令行引號轉義問題）
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as tf:
            tf.write(script)
            tmp_path = tf.name

        # 5. 異步子進程執行
        logger.info("UE Python 橋接：執行 %d 字符代碼（project=%s）", len(code), project_id)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, tmp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout + 15
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return {
                "success": False, "stdout": "", "result": "",
                "error": f"執行超時（{timeout}s）", "exit_code": -1,
            }

        exit_code = proc.returncode or 0
        stdout = stdout_b.decode("utf-8", errors="replace").strip()
        stderr = stderr_b.decode("utf-8", errors="replace").strip()

        # 6. 解析 JSON 輸出
        last_line = stdout.split("\n")[-1] if stdout else ""
        try:
            data = json.loads(last_line)
        except json.JSONDecodeError:
            err = (stderr or stdout or "Unknown error")[:500]
            return {
                "success": False, "stdout": stdout, "result": "",
                "error": f"子進程輸出解析失敗: {err}", "exit_code": exit_code,
            }

        if data.get("error") == "no_node":
            return {
                "success": False, "stdout": "", "result": "",
                "error": (
                    "未找到 UE Editor。\n請確認：\n"
                    "  1. UE Editor 已運行\n"
                    "  2. Remote Execution Server 已啟用"
                ),
                "exit_code": 2,
            }

        # 整理輸出行
        output_lines = []
        for item in data.get("output", []):
            line = (item.get("output", "") if isinstance(item, dict) else str(item)).rstrip()
            if line:
                output_lines.append(line)

        combined_stdout = "\n".join(output_lines)
        if stderr:
            logger.debug("UE Python stderr: %s", stderr[:200])

        result = {
            "success": data.get("success", False),
            "stdout": combined_stdout,
            "result": data.get("result", "").strip(),
            "error": None if data.get("success") else (combined_stdout or stderr or "執行失敗"),
            "exit_code": exit_code,
        }
        logger.info(
            "UE Python 橋接完成：success=%s, stdout=%d chars",
            result["success"], len(combined_stdout),
        )
        return result

    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
