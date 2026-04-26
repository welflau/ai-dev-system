"""UEPackageAction — 调 RunUAT BuildCookRun 打包 UE 项目（v0.19.x Phase C）

UE 的「部署」≠ Web 的「起 http.server」，而是把项目 Cook + Pak + Archive 到一个
独立目录（可选平台 Win64 / Linux / Mac / Android / iOS）。

命令：
  <Engine>/Engine/Build/BatchFiles/RunUAT.bat BuildCookRun
    -project=<.uproject>
    -platform=<Win64|Linux|Mac>
    -configuration=<Development|Shipping|Test>
    -cook -stage -pak -archive -archivedirectory=<out>
    -nocompileeditor -utf8output
    -nop4 -unattended
    -build        (可选；没带就用已编译的 editor)

输入 context:
    engine_path        UE 引擎根目录（优先）。未给从 uproject 解析
    uproject_path      .uproject 绝对路径
    platform           Win64 / Linux / Mac / ...  默认 Win64
    configuration      Development / Shipping / Test  默认 Shipping
    archive_dir        产物目录，默认 <uproject_dir>/Packaged/<platform>-<config>
    timeout_seconds    默认 1800（首次 cook + shader 可能 10-30 min）
    include_build      是否先过一次 -build 编译 C++（默认 True）
    log_callback       async(str) → None 每行输出回调
    sop_config         dict 覆盖 timeout / platform / configuration

输出 data:
    {
      "status": "success" | "package_failed" | "error",
      "exit_code": int,
      "duration_ms": int,
      "command": "...",
      "archive_dir": "...",
      "archive_size_bytes": int,
      "errors": [str],      # 结构化错误文本行
      "warnings": [str],
      "raw_head": "...",
      "raw_tail": "...",
      "engine_used": {...},
      "platform": "Win64",
      "configuration": "Shipping",
    }
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from actions.base import ActionBase, ActionResult
from engines.ue_resolver import (
    UEEngineInfo,
    resolve_project_engine,
    verify_engine,
)

logger = logging.getLogger("actions.ue_package")


# RunUAT 的错误/警告识别正则（宽松匹配，AutomationTool 日志不像 UBT 那么规整）
_RE_UAT_ERROR = re.compile(
    r"^(?:ERROR:|Fatal:|\*\*\*\*.*ERROR|BUILD FAILED|AutomationTool.*Exception|Unhandled Exception)",
    re.IGNORECASE,
)
_RE_UAT_WARNING = re.compile(r"^WARNING:", re.IGNORECASE)
_RE_UAT_COMPILE_ERROR = re.compile(
    r"^(?P<file>[A-Za-z]:[\\/][^(]+?)\((?P<line>\d+)\).*error", re.IGNORECASE
)


def _parse_uat_output(text: str) -> Dict[str, List[str]]:
    """解析 RunUAT stdout，抽出 errors + warnings"""
    errors: List[str] = []
    warnings: List[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if _RE_UAT_ERROR.search(line) or _RE_UAT_COMPILE_ERROR.match(line):
            errors.append(line[:400])
        elif _RE_UAT_WARNING.search(line):
            warnings.append(line[:200])
    return {"errors": errors[:50], "warnings": warnings[:20]}


def _dir_size_bytes(path: Path) -> int:
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except Exception:
                    pass
    except Exception:
        pass
    return total


class UEPackageAction(ActionBase):
    """调 RunUAT BuildCookRun 打包 UE 项目"""

    available_for_traits = {"any_of": ["engine:ue5", "engine:ue4"]}

    @property
    def name(self) -> str:
        return "ue_package"

    @property
    def description(self) -> str:
        return "调 RunUAT BuildCookRun 打包 UE 项目，Cook + Pak + Archive"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        sop_cfg = context.get("sop_config") or {}
        timeout_seconds = int(
            context.get("timeout_seconds")
            or sop_cfg.get("timeout_seconds")
            or 1800
        )
        platform = (
            context.get("platform")
            or context.get("target_platform")
            or sop_cfg.get("platform")
            or "Win64"
        )
        configuration = (
            context.get("configuration")
            or context.get("target_config")
            or sop_cfg.get("configuration")
            or "Shipping"
        )
        include_build = bool(
            context.get("include_build", sop_cfg.get("include_build", True))
        )

        log_cb = context.get("log_callback")

        async def _log(msg: str):
            logger.info(msg)
            if log_cb:
                try:
                    await log_cb(msg)
                except Exception:
                    pass

        async def _err_log(msg: str, detail: Optional[Dict] = None):
            await _log(f"[error] {msg}")
            return _err(msg, detail)

        uproject_path = context.get("uproject_path") or context.get("uproject")
        engine_path = context.get("engine_path") or context.get("ue_engine_path")
        await _log(
            f"[package] 入参 engine={engine_path or '(无)'}  uproject={uproject_path or '(无)'}  "
            f"platform={platform} config={configuration}"
        )

        # 探测 .uproject
        if not uproject_path:
            project_id = context.get("project_id")
            if project_id:
                try:
                    from git_manager import git_manager
                    repo_path = git_manager._repo_path(project_id)
                    if repo_path and Path(repo_path).is_dir():
                        found = sorted(Path(repo_path).glob("*.uproject"))
                        if found:
                            uproject_path = str(found[0])
                            await _log(f"[package] 自动定位 .uproject: {uproject_path}")
                except Exception as e:
                    await _log(f"[package] 探测 .uproject 异常: {e}")

        # 解析引擎
        engine_info: Optional[UEEngineInfo] = None
        if engine_path:
            engine_info = verify_engine(engine_path)
        elif uproject_path:
            engine_info = resolve_project_engine(uproject_path)
        else:
            return await _err_log("缺 engine_path 和 uproject_path")

        if not engine_info or not engine_info.path:
            return await _err_log("无法定位 UE 引擎")

        if not uproject_path or not Path(uproject_path).is_file():
            return await _err_log(f".uproject 不存在: {uproject_path}")

        # RunUAT.bat
        run_uat = Path(engine_info.path) / "Engine" / "Build" / "BatchFiles" / "RunUAT.bat"
        if not run_uat.is_file():
            return await _err_log(f"找不到 RunUAT.bat: {run_uat}")

        # 归档目录
        up = Path(uproject_path)
        archive_dir = Path(
            context.get("archive_dir")
            or sop_cfg.get("archive_dir")
            or up.parent / "Packaged" / f"{platform}-{configuration}"
        )
        archive_dir.mkdir(parents=True, exist_ok=True)

        await _log(
            f"[package] 引擎 OK: {engine_info.path} ({engine_info.version} [{engine_info.type}])"
        )
        await _log(f"[package] archive_dir: {archive_dir}")

        # 组命令
        cmd = [
            str(run_uat),
            "BuildCookRun",
            f"-project={uproject_path}",
            f"-platform={platform}",
            f"-clientconfig={configuration}",
            f"-serverconfig={configuration}",
            "-cook",
            "-stage",
            "-pak",
            "-archive",
            f"-archivedirectory={archive_dir}",
            "-nocompileeditor",
            "-utf8output",
            "-nop4",
            "-unattended",
        ]
        if include_build:
            cmd.append("-build")
        cmd_str = " ".join(f'"{c}"' if " " in c else c for c in cmd)
        await _log(f"[package] cmd: {cmd_str}")

        # 执行
        t0 = time.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            await _log(f"[package] subprocess pid={proc.pid}, 开始读 stdout...")
        except FileNotFoundError:
            return await _err_log(f"启动 RunUAT 失败: {run_uat} 不存在或权限不足")
        except Exception as e:
            return await _err_log(f"启动 RunUAT 异常: {e}")

        collected: List[str] = []
        # v0.19.x 工单面板进度区：orchestrator 注入的心跳 callback（可空）
        progress_cb = context.get("_ticket_progress_cb")

        async def _pump():
            assert proc.stdout is not None
            while True:
                raw = await proc.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                collected.append(line)
                if log_cb is not None:
                    try:
                        await log_cb(line)
                    except Exception:
                        pass
                if progress_cb is not None:
                    try:
                        await progress_cb(line)
                    except Exception:
                        pass

        try:
            await asyncio.wait_for(
                asyncio.gather(_pump(), proc.wait()),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            duration_ms = int((time.time() - t0) * 1000)
            return _err(
                f"Package 超时（{timeout_seconds}s）",
                detail={
                    "duration_ms": duration_ms,
                    "command": cmd_str,
                    "engine_used": engine_info.to_dict(),
                    "partial_output": "\n".join(collected[-100:]),
                },
            )

        duration_ms = int((time.time() - t0) * 1000)
        text = "\n".join(collected)
        exit_code = proc.returncode if proc.returncode is not None else -1

        parsed = _parse_uat_output(text)
        errors = parsed["errors"]
        warnings = parsed["warnings"]

        archive_size = _dir_size_bytes(archive_dir)

        if exit_code == 0 and not errors:
            status = "success"
        else:
            status = "package_failed"

        head = text[:8192]
        tail = text[-8192:] if len(text) > 8192 else ""

        data: Dict[str, Any] = {
            "status": status,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "command": cmd_str,
            "archive_dir": str(archive_dir),
            "archive_size_bytes": archive_size,
            "errors": errors,
            "warnings": warnings,
            "raw_head": head,
            "raw_tail": tail,
            "engine_used": engine_info.to_dict(),
            "platform": platform,
            "configuration": configuration,
        }

        size_mb = archive_size / (1024 * 1024)
        msg = (
            f"打包完成 ({size_mb:.1f} MB, {duration_ms // 1000}s)"
            if status == "success"
            else f"打包失败 ({len(errors)} errors)"
        )
        return ActionResult(
            success=(status == "success"),
            data=data,
            message=msg,
        )


def _err(msg: str, detail: Optional[Dict] = None) -> ActionResult:
    data = {"status": "error", "errors": [], "warnings": [], "message": msg}
    if detail:
        data.update(detail)
    return ActionResult(success=False, data=data, message=msg, error=msg)
