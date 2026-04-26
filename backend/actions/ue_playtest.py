"""
UEPlaytestAction — 跑 UE Automation Framework 冒烟测试（v0.19 Phase ②A）

借道 UnrealEditor.exe 的命令行模式 + Automation 命令：
  UnrealEditor-Cmd.exe <.uproject>
    -ExecCmds="Automation RunTests <FilterOrList>;Quit"
    -nullrhi            # 无 GPU 渲染（CI 友好）
    -unattended         # 关闭交互式弹窗
    -nopause -nosplash  # 静默启动
    -buildmachine       # 减少启动日志 + disable 崩溃弹窗
    -log=<path>         # 日志写到指定路径（同时也流式推回）
    -AutomationScreenshotsDir=<dir>  # 失败时截图位置（用于排查）

输入 context:
    engine_path         引擎根目录，优先。未给则从 uproject 解析
    uproject_path       .uproject 绝对路径。未给则从 project_id 的 git 仓库探测
    test_filter         Automation filter，默认 "Project."（只跑项目自身的测试，不跑 Engine 级）
    test_names          List[str]，直接列测试名代替 filter（互斥，填了就覆盖 filter）
    timeout_seconds     默认 600（首次可能 3-5 分钟因着色编译）
    sop_config          {timeout_seconds, test_filter, ...} 覆盖默认
    project_id          用于探测 .uproject（可选）
    log_callback        async (str) → None，每行 stdout 回调一次

输出 data:
    {
      "status": "success" | "playtest_failed" | "error",
      "exit_code": int,
      "duration_ms": int,
      "command": "...",
      "tests": [
        {"name": "...", "result": "passed"|"failed"|"skipped", "duration_ms": int|None, "errors": [str]}
      ],
      "summary": {"total": N, "passed": N, "failed": N, "skipped": N},
      "screenshots": [<path>, ...],
      "raw_head": "开头 ~8KB",
      "raw_tail": "末尾 ~8KB",
      "engine_used": {path, version, type}
    }

语义：
  - exit=0 且无失败测试           → success
  - exit!=0 或有任何 failed 测试  → playtest_failed（→ orchestrator reject_goto fix_issues）
  - 引擎/uproject 找不到等环境问题 → error（→ orchestrator BLOCKED）
"""
from __future__ import annotations

import asyncio
import json
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

logger = logging.getLogger("actions.ue_playtest")


# ==================== Automation 日志解析 ====================
#
# UE 5.x Automation 典型输出（LogAutomationController 通道）：
#
#   LogAutomationController: BeginEvents: Project.Functional.Smoke
#   LogAutomationController: Test Completed. Result={Passed}  Name={Project.Functional.Smoke}
#
# 失败：
#   LogAutomationController: Error: Screenshot comparison failed for ...
#   LogAutomationController: Test Completed. Result={Failed}  Name={...}
#
# 总结：
#   LogAutomationController: Results for test Group: Project
#   LogAutomationController:  * 12 tests ran
#   LogAutomationController:  * 10 passed
#   LogAutomationController:  * 2 failed
#

# 单测完成行：Test Completed. Result={XXX}  Name={YYY}
_RE_TEST_RESULT = re.compile(
    r"LogAutomationController.*Test Completed\.\s*Result=\{(?P<result>\w+)\}.*Name=\{(?P<name>[^}]+)\}"
)

# 测试中的 error 行（归到最近一次测试）
_RE_AUTO_ERROR = re.compile(
    r"LogAutomationController:?\s*(?:Error|Warning):\s*(?P<msg>.+)$"
)

# 总结行
_RE_SUMMARY_TOTAL = re.compile(r"\*\s*(?P<n>\d+)\s+tests?\s+ran", re.IGNORECASE)
_RE_SUMMARY_PASS = re.compile(r"\*\s*(?P<n>\d+)\s+passed", re.IGNORECASE)
_RE_SUMMARY_FAIL = re.compile(r"\*\s*(?P<n>\d+)\s+failed", re.IGNORECASE)

# 测试开始（用于关联 error 到测试）
_RE_TEST_BEGIN = re.compile(
    r"LogAutomationController.*(?:BeginEvents|Test Started).*?[:=]\s*\{?(?P<name>[^}\s]+)"
)


def _parse_automation_output(text: str) -> Dict[str, Any]:
    """解析 UE Automation 日志，抽出每个测试结果 + 总体 summary"""
    tests: List[Dict[str, Any]] = []
    test_errors: Dict[str, List[str]] = {}
    current_test: Optional[str] = None

    total = None
    passed_n = None
    failed_n = None

    for raw in text.splitlines():
        line = raw.rstrip()

        mb = _RE_TEST_BEGIN.search(line)
        if mb:
            current_test = mb.group("name").strip().strip("{}").strip(",")
            continue

        mr = _RE_TEST_RESULT.search(line)
        if mr:
            result = mr.group("result").strip().lower()
            name = mr.group("name").strip()
            # 规整 result：passed/failed/skipped
            result_map = {
                "passed": "passed", "success": "passed", "pass": "passed",
                "failed": "failed", "fail": "failed", "error": "failed",
                "skipped": "skipped", "notrun": "skipped",
            }
            norm = result_map.get(result, result)
            tests.append({
                "name": name,
                "result": norm,
                "duration_ms": None,
                "errors": test_errors.pop(name, []),
            })
            current_test = None
            continue

        me = _RE_AUTO_ERROR.match(line)
        if me and current_test:
            test_errors.setdefault(current_test, []).append(me.group("msg").strip())

        # summary 抽取
        ms = _RE_SUMMARY_TOTAL.search(line)
        if ms:
            try: total = int(ms.group("n"))
            except ValueError: pass
        mp = _RE_SUMMARY_PASS.search(line)
        if mp:
            try: passed_n = int(mp.group("n"))
            except ValueError: pass
        mf = _RE_SUMMARY_FAIL.search(line)
        if mf:
            try: failed_n = int(mf.group("n"))
            except ValueError: pass

    # 补齐：有 errors 残留未关联到 Test Completed，挂到同名测试（若已存在）
    if test_errors:
        for name, errs in test_errors.items():
            matched = next((t for t in tests if t["name"] == name), None)
            if matched:
                matched["errors"].extend(errs)
            else:
                # 完全没 Test Completed：视为 failed
                tests.append({
                    "name": name, "result": "failed",
                    "duration_ms": None, "errors": errs,
                })

    # summary fallback：直接从 tests 推
    if total is None:
        total = len(tests)
    if passed_n is None:
        passed_n = sum(1 for t in tests if t["result"] == "passed")
    if failed_n is None:
        failed_n = sum(1 for t in tests if t["result"] == "failed")
    skipped_n = sum(1 for t in tests if t["result"] == "skipped")

    return {
        "tests": tests,
        "summary": {
            "total": total,
            "passed": passed_n,
            "failed": failed_n,
            "skipped": skipped_n,
        },
    }


def _find_screenshots(screenshot_dir: Path) -> List[str]:
    if not screenshot_dir.is_dir():
        return []
    # 最多列 20 张
    out = []
    for p in screenshot_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg"):
            out.append(str(p))
            if len(out) >= 20:
                break
    return out


# ==================== Action ====================


class UEPlaytestAction(ActionBase):
    """v0.19：跑 UE Automation Framework 冒烟测试"""

    available_for_traits = {"any_of": ["engine:ue5", "engine:ue4"]}

    @property
    def name(self) -> str:
        return "ue_playtest"

    @property
    def description(self) -> str:
        return "调 UnrealEditor-Cmd.exe 跑 Automation Framework 测试，产出结构化测试结果"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        sop_cfg = context.get("sop_config") or {}
        timeout_seconds = int(
            context.get("timeout_seconds")
            or sop_cfg.get("timeout_seconds")
            or 600
        )
        test_filter = (
            context.get("test_filter")
            or sop_cfg.get("test_filter")
            or "Project."
        )
        test_names = context.get("test_names") or sop_cfg.get("test_names")

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
            f"[playtest] 入参 engine_path={engine_path or '(无)'}  uproject={uproject_path or '(无)'}"
        )

        # 自动探测 .uproject
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
                            await _log(f"[playtest] 已定位 .uproject: {uproject_path}")
                except Exception as e:
                    await _log(f"[playtest] 自动探测 .uproject 异常: {e}")

        # 解析引擎
        engine_info: Optional[UEEngineInfo] = None
        if engine_path:
            engine_info = verify_engine(engine_path)
        elif uproject_path:
            engine_info = resolve_project_engine(uproject_path)
        else:
            return await _err_log("缺 engine_path 和 uproject_path，无法定位 UE 引擎")

        if not engine_info or not engine_info.path:
            return await _err_log("无法定位 UE 引擎，请在项目设置里配置 ue_engine_path")

        if not uproject_path or not Path(uproject_path).is_file():
            return await _err_log(f".uproject 不存在: {uproject_path}")

        await _log(
            f"[playtest] 引擎 OK: {engine_info.path} "
            f"(UE {engine_info.version} [{engine_info.type}])"
        )

        # UnrealEditor-Cmd.exe 路径
        editor_cmd = Path(engine_info.path) / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"
        if not editor_cmd.is_file():
            # UE4 fallback
            editor_cmd = Path(engine_info.path) / "Engine" / "Binaries" / "Win64" / "UE4Editor-Cmd.exe"
            if not editor_cmd.is_file():
                return await _err_log(
                    f"找不到 UnrealEditor-Cmd.exe（{engine_info.path}/Engine/Binaries/Win64/）"
                )

        # 截图目录（方便 failed 测试排查）
        up = Path(uproject_path)
        screenshot_dir = up.parent / "Saved" / "Automation" / "Screenshots"
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        # 组命令
        if test_names:
            # 用 RunTests Name1+Name2+... 语法
            exec_cmds = f"Automation RunTests {'+'.join(test_names)};Quit"
        else:
            exec_cmds = f"Automation RunTests {test_filter};Quit"

        cmd = [
            str(editor_cmd),
            str(up),
            f'-ExecCmds={exec_cmds}',
            "-nullrhi",
            "-unattended",
            "-nopause",
            "-nosplash",
            "-buildmachine",
            "-NoSound",
            f"-AutomationScreenshotsDir={screenshot_dir}",
        ]
        cmd_str = " ".join(f'"{c}"' if " " in c else c for c in cmd)
        await _log(f"[playtest] cmd: {cmd_str}")

        # 执行（流式）
        t0 = time.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            await _log(f"[playtest] subprocess pid={proc.pid}, 开始读 stdout...")
        except FileNotFoundError:
            return await _err_log(f"启动 Editor-Cmd 失败: {editor_cmd} 不存在或权限不足")
        except Exception as e:
            return await _err_log(f"启动 Editor-Cmd 异常: {e}")

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
                f"Playtest 超时（{timeout_seconds}s）",
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

        # 解析
        parsed = _parse_automation_output(text)
        tests = parsed["tests"]
        summary = parsed["summary"]

        # 截图
        shots = _find_screenshots(screenshot_dir)

        if exit_code == 0 and summary["failed"] == 0:
            status = "success"
        else:
            status = "playtest_failed"

        head = text[:8192]
        tail = text[-8192:] if len(text) > 8192 else ""

        data: Dict[str, Any] = {
            "status": status,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "command": cmd_str,
            "tests": tests,
            "summary": summary,
            "screenshots": shots,
            "raw_head": head,
            "raw_tail": tail,
            "engine_used": engine_info.to_dict(),
            "test_filter": test_filter,
            "test_names": test_names,
        }

        msg = (
            f"Playtest 通过 ({summary['passed']}/{summary['total']}，耗时 {duration_ms // 1000}s)"
            if status == "success"
            else f"Playtest 失败 ({summary['failed']}/{summary['total']} failed)"
        )
        logger.info(msg)
        return ActionResult(
            success=(status == "success"),
            data=data,
            message=msg,
        )


def _err(msg: str, detail: Optional[Dict] = None) -> ActionResult:
    data = {"status": "error", "tests": [],
            "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
            "message": msg}
    if detail:
        data.update(detail)
    return ActionResult(success=False, data=data, message=msg, error=msg)
