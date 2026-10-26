"""对 Phaser 仓库做运行时门禁：vite build + 静态服 + 浏览器收错。

对着 git 仓库跑，不另开 DATA_DIR 沙箱，不常驻 Vite。
build 失败或页面 JS 异常 → status=playtest_failed（SOP reject_goto）。
缺 Node / 缺 index.html → status=error。
缺 Playwright / Chromium 时先自动安装，安装失败才 runtime_skipped。
"""
from __future__ import annotations

import asyncio
import http.server
import json
import logging
import os
import shlex
import shutil
import socket
import socketserver
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.h5_playtest")

_CONSOLE_NOISE = (
    "favicon.ico",
    "ResizeObserver loop",
    "Download the React DevTools",
)


def is_runtime_noise(msg: str) -> bool:
    text = msg or ""
    return any(p in text for p in _CONSOLE_NOISE)


_MISSING_BROWSER_NEEDLES = (
    "executable doesn't exist",
    "browsertype.launch",
    "winerror 2",
    "系统找不到指定的文件",
    "playwright was not found",
    "browser has not been found",
)


def is_missing_browser(exc: BaseException) -> bool:
    """Playwright 驱动/Chromium 未装：环境问题，不能当成游戏试玩失败。"""
    if isinstance(exc, FileNotFoundError):
        return True
    err = (str(exc) or "").lower()
    return any(n in err for n in _MISSING_BROWSER_NEEDLES)


def playwright_driver_ok() -> bool:
    try:
        from playwright._impl._driver import compute_driver_executable
        node, cli = compute_driver_executable()
        return Path(node).is_file() and Path(cli).is_file()
    except Exception:
        return False


def _trace_from_context(context: Dict[str, Any]) -> Dict[str, str]:
    return {
        "ticket_id": str(context.get("ticket_id") or ""),
        "project_id": str(context.get("project_id") or ""),
        "requirement_id": str(context.get("requirement_id") or ""),
        "agent_type": str(context.get("agent_type") or "TestAgent"),
    }


def _cmd_line(cmd: List[str]) -> str:
    return " ".join(shlex.quote(str(c)) for c in cmd)


async def _emit_ticket_step(
    trace: Optional[Dict[str, Any]],
    step_name: str,
    phase: str,
    *,
    duration_ms: int = 0,
    reason: str = "",
    task_id: str = "",
) -> str:
    """安装/构建步骤写到工单时间轴（skill_step_*），完成时可挂 task_id。"""
    ticket_id = (trace or {}).get("ticket_id") or ""
    project_id = (trace or {}).get("project_id") or ""
    if not ticket_id:
        return ""
    try:
        from database import db
        from events import event_manager
        from utils import generate_id, now_iso

        action = f"skill_step_{phase}" if phase in ("start", "done", "error") else "skill_step_done"
        log_id = generate_id("LOG")
        created_at = now_iso()
        if phase == "start":
            message = f"{step_name} · 开始"
            level = "info"
        elif phase == "done":
            dur_str = f" ({int(duration_ms)}ms)" if duration_ms else ""
            message = f"{step_name} · 完成{dur_str}"
            level = "info"
        else:
            dur_str = f" ({int(duration_ms)}ms)" if duration_ms else ""
            message = f"{step_name} · 失败{dur_str}"
            if reason:
                message += f" — {reason[:120]}"
            level = "error"

        detail_obj: Dict[str, Any] = {
            "message": message,
            "step_name": step_name,
            "phase": phase,
            "duration_ms": duration_ms,
            "reason": reason,
        }
        if task_id:
            detail_obj["task_id"] = task_id
        detail_json = json.dumps(detail_obj, ensure_ascii=False)

        await db.execute(
            "INSERT INTO ticket_logs "
            "(id, ticket_id, requirement_id, project_id, agent_type, action, detail, level, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (log_id, ticket_id, (trace or {}).get("requirement_id"),
             project_id or "__global__", (trace or {}).get("agent_type") or "TestAgent",
             action, detail_json, level, created_at),
        )
        if project_id:
            await event_manager.publish_to_project(project_id, "log_added", {
                "id": log_id, "ticket_id": ticket_id,
                "agent_type": (trace or {}).get("agent_type") or "TestAgent",
                "action": action, "detail": detail_json, "level": level,
                "created_at": created_at,
                "_task_ref": task_id or "",
            })
        return log_id
    except Exception as e:
        logger.debug("h5 步骤打点失败（非致命）: %s", e)
        return ""


async def run_and_trace(
    cmd: List[str],
    cwd: Path,
    timeout: int,
    *,
    tool: str,
    trace: Optional[Dict[str, Any]] = None,
) -> Tuple[int, str, str]:
    """跑命令，有工单时写入时间轴 + ticket_command_log（可点「📟 后台记录」）。"""
    t0 = time.monotonic()
    code, raw = await run_cmd(cmd, cwd, timeout)
    record_id = ""
    ticket_id = (trace or {}).get("ticket_id") or ""
    if ticket_id:
        status = "timeout" if code == 124 else ("error" if code != 0 else "success")
        try:
            from command_log import record_traced_command
            record_id = await record_traced_command(
                source="h5_playtest",
                tool=tool,
                command=_cmd_line(cmd),
                cwd=str(cwd),
                exit_code=code,
                status=status,
                duration_ms=_ms(t0),
                output=raw,
                ticket_id=ticket_id,
                project_id=(trace or {}).get("project_id") or "",
                requirement_id=(trace or {}).get("requirement_id") or "",
                agent_type=(trace or {}).get("agent_type") or "TestAgent",
            )
        except Exception as e:
            logger.debug("h5 命令记录失败（非致命）: %s", e)
    return code, raw, record_id


async def ensure_playwright_chromium(
    timeout: int = 300,
    trace: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """缺包或缺 Chromium 时当场装。成功返回 (True, 备注)。

    真要装的时候打 skill_step，每条 pip / playwright 命令进时间轴和任务 Log。
    """
    py = sys.executable
    cwd = Path.cwd()
    steps: List[str] = []
    needed = False
    last_rid = ""
    t0 = time.monotonic()

    try:
        import playwright  # noqa: F401
    except ImportError:
        needed = True
        steps.append("pip install playwright")
        await _emit_ticket_step(trace, "自动安装 Playwright Chromium", "start")
        code, raw, last_rid = await run_and_trace(
            [py, "-m", "pip", "install", "playwright"], cwd, timeout,
            tool="pip:playwright", trace=trace,
        )
        if code != 0:
            await _emit_ticket_step(
                trace, "自动安装 Playwright Chromium", "error",
                duration_ms=_ms(t0), reason=raw[-160:], task_id=last_rid,
            )
            return False, f"pip install playwright 失败: {raw[-300:]}"

    if not playwright_driver_ok():
        if not needed:
            await _emit_ticket_step(trace, "自动安装 Playwright Chromium", "start")
        needed = True
        steps.append("pip install --force-reinstall playwright")
        code, raw, last_rid = await run_and_trace(
            [py, "-m", "pip", "install", "--force-reinstall", "playwright"],
            cwd, timeout, tool="pip:playwright-reinstall", trace=trace,
        )
        if code != 0 or not playwright_driver_ok():
            await _emit_ticket_step(
                trace, "自动安装 Playwright Chromium", "error",
                duration_ms=_ms(t0), reason=raw[-160:], task_id=last_rid,
            )
            return False, f"playwright driver 缺失: {raw[-300:]}"

    steps.append("playwright install chromium")
    logger.info("h5_playtest 自动安装 Chromium…")
    chrom_cmd = [py, "-m", "playwright", "install", "chromium"]
    code, raw, last_rid = await run_and_trace(
        chrom_cmd, cwd, timeout, tool="playwright:install-chromium", trace=trace,
    )
    if code != 0:
        if needed:
            await _emit_ticket_step(
                trace, "自动安装 Playwright Chromium", "error",
                duration_ms=_ms(t0), reason=raw[-160:], task_id=last_rid,
            )
        return False, f"playwright install chromium 失败: {raw[-400:]}"
    if needed:
        await _emit_ticket_step(
            trace, "自动安装 Playwright Chromium", "done",
            duration_ms=_ms(t0), task_id=last_rid,
        )
    return True, "；".join(steps)


def resolve_bin(repo: Path, name: str) -> Optional[List[str]]:
    exe = f"{name}.cmd" if os.name == "nt" else name
    local = repo / "node_modules" / ".bin" / exe
    if local.is_file():
        return [str(local)]
    found = shutil.which(name) or shutil.which(f"{name}.cmd")
    if found:
        return [found]
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if npx:
        return [npx, "--yes", name]
    return None


def pick_free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


async def run_cmd(
    cmd: List[str], cwd: Path, timeout: int,
) -> Tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        raw_b, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, f"命令超时（{timeout}s）: {' '.join(cmd)}"
    raw = (raw_b or b"").decode("utf-8", errors="replace")
    return int(proc.returncode or 0), raw


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args: Any) -> None:
        return


def start_static_server(root: Path, port: int) -> socketserver.TCPServer:
    handler = lambda *a, **k: _QuietHandler(*a, directory=str(root), **k)
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", port), handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


async def browse_and_collect(
    url: str,
    *,
    observe_ms: int = 3000,
    screenshot: Optional[Path] = None,
    auto_install: bool = True,
    trace: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """打开页面，收集 pageerror / console.error。缺浏览器时先自动安装再试一次。"""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        if auto_install:
            ok, msg = await ensure_playwright_chromium(trace=trace)
            if ok:
                return await browse_and_collect(
                    url, observe_ms=observe_ms, screenshot=screenshot,
                    auto_install=False, trace=trace,
                )
            return {"skipped": True, "reason": f"自动安装 Playwright 失败: {msg}"}
        return {"skipped": True, "reason": "playwright 未安装"}

    errors: List[Dict[str, str]] = []
    warnings: List[str] = []
    has_canvas = False
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 402, "height": 874})
            page.on("pageerror", lambda exc: errors.append({
                "source": "pageerror", "msg": str(exc),
            }))

            def _on_console(msg: Any) -> None:
                raw_t = getattr(msg, "text", "")
                text = raw_t() if callable(raw_t) else str(raw_t or "")
                raw_tp = getattr(msg, "type", "")
                mtype = raw_tp() if callable(raw_tp) else str(raw_tp or "")
                if mtype == "error" and not is_runtime_noise(text):
                    errors.append({"source": "console.error", "msg": text})
                elif mtype == "warning" and not is_runtime_noise(text):
                    warnings.append(text)

            page.on("console", _on_console)
            await page.goto(url, wait_until="load", timeout=20000)
            await page.wait_for_timeout(observe_ms)
            has_canvas = bool(await page.evaluate(
                "() => !!document.querySelector('#game-container canvas, canvas')"
            ))
            if screenshot is not None:
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(screenshot), full_page=False)
            await browser.close()
    except Exception as e:
        err = str(e)
        if is_missing_browser(e) and auto_install:
            ok, msg = await ensure_playwright_chromium(trace=trace)
            if ok:
                return await browse_and_collect(
                    url, observe_ms=observe_ms, screenshot=screenshot,
                    auto_install=False, trace=trace,
                )
            return {"skipped": True, "reason": f"自动安装 Playwright 失败: {msg}；原错误: {err[:160]}"}
        if is_missing_browser(e):
            return {"skipped": True, "reason": f"Playwright 浏览器未安装: {err[:200]}"}
        return {
            "skipped": False,
            "errors": [{"source": "browser", "msg": err[:400]}],
            "warnings": warnings,
            "has_canvas": False,
        }
    return {
        "skipped": False,
        "errors": errors,
        "warnings": warnings,
        "has_canvas": has_canvas,
    }


class H5PlaytestAction(ActionBase):
    available_for_traits = {"any_of": ["framework:phaser"]}

    @property
    def name(self) -> str:
        return "h5_playtest"

    @property
    def description(self) -> str:
        return "vite build 后用无头浏览器打开产物，收集 Phaser 运行时错误"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        repo = context.get("repo_path") or context.get("target_dir")
        if not repo:
            return _env("缺 repo_path")
        root = Path(repo)
        if not (root / "package.json").is_file():
            return _env("仓库没有 package.json，先跑 instantiate_h5_template")
        if not (root / "index.html").is_file():
            return _env("仓库没有 index.html")

        sop = context.get("sop_config") or {}
        timeout = int(sop.get("timeout_seconds") or context.get("timeout_seconds") or 180)
        observe_ms = int(sop.get("observe_ms") or context.get("observe_ms") or 3000)
        t0 = time.monotonic()
        notes: List[str] = []
        trace = _trace_from_context(context)

        npm = resolve_bin(root, "npm")
        if not (root / "node_modules").is_dir():
            if not npm:
                return _env("找不到 npm，请安装 Node.js")
            notes.append("node_modules 缺失，执行 npm install")
            inst_t0 = time.monotonic()
            await _emit_ticket_step(trace, "安装 npm 依赖", "start")
            code, raw, rid = await run_and_trace(
                npm + ["install"], root, min(timeout, 180),
                tool="npm:install", trace=trace,
            )
            if code != 0:
                await _emit_ticket_step(
                    trace, "安装 npm 依赖", "error",
                    duration_ms=_ms(inst_t0), reason=raw[-160:], task_id=rid,
                )
                return _fail(
                    "npm install 失败",
                    errors=[{"source": "npm", "msg": raw[-500:]}],
                    command=npm + ["install"],
                    raw_tail=raw[-4000:],
                    duration_ms=_ms(t0),
                    notes=notes,
                    task_id=rid,
                )
            await _emit_ticket_step(
                trace, "安装 npm 依赖", "done",
                duration_ms=_ms(inst_t0), task_id=rid,
            )

        vite = resolve_bin(root, "vite")
        if not vite:
            return _env("找不到 vite，请在仓库执行 npm install")
        build_cmd = vite + ["build"]
        code, raw, _rid = await run_and_trace(
            build_cmd, root, min(timeout, 120),
            tool="vite:build", trace=trace,
        )
        if code != 0:
            return _fail(
                "vite build 失败",
                errors=[{"source": "vite", "msg": raw[-500:]}],
                command=build_cmd,
                raw_tail=raw[-4000:],
                duration_ms=_ms(t0),
                notes=notes,
                task_id=_rid,
            )
        notes.append("vite build 通过")

        dist = root / "dist"
        if not (dist / "index.html").is_file():
            return _fail(
                "vite build 没有产出 dist/index.html",
                errors=[{"source": "vite", "msg": "dist/index.html missing"}],
                command=build_cmd,
                raw_tail=raw[-2000:],
                duration_ms=_ms(t0),
                notes=notes,
                task_id=_rid,
            )

        port = pick_free_port()
        httpd = start_static_server(dist, port)
        url = f"http://127.0.0.1:{port}/"
        shot: Optional[Path] = None
        docs_prefix = str(context.get("docs_prefix") or "")
        if docs_prefix:
            shot = root / docs_prefix / "screenshots" / "h5_playtest.png"
        screenshots: List[str] = []
        try:
            runtime = await browse_and_collect(
                url, observe_ms=observe_ms, screenshot=shot, trace=trace,
            )
        finally:
            httpd.shutdown()
            httpd.server_close()

        if shot and shot.is_file():
            try:
                screenshots.append(shot.relative_to(root).as_posix())
            except Exception:
                screenshots.append(shot.as_posix())

        # 若上下文含 project_id，顺手刷新常驻 dev 预览服务（指向 dist/），让时间轴上的「🎮 在线试玩」链接随时可点开
        preview_url = ""
        project_id = str(context.get("project_id") or "")
        if project_id:
            try:
                from agents.deploy import DeployAgent
                preview_url = await DeployAgent.deploy_env(project_id, "dev") or ""
            except Exception:
                pass

        data: Dict[str, Any] = {
            "command": _cmd_line(build_cmd),
            "duration_ms": _ms(t0),
            "url": preview_url or url,
            "preview_url": preview_url,
            "notes": notes,
            "screenshots": screenshots,
            "raw_tail": raw[-2000:],
            "task_id": _rid,
        }

        if runtime.get("skipped"):
            reason = str(runtime.get("reason") or "runtime skipped")
            data["status"] = "success"
            data["runtime_skipped"] = True
            data["warnings"] = [reason]
            data["errors"] = []
            notes.append(reason)
            return ActionResult(
                success=True,
                data=data,
                message=f"vite build 通过，运行时检查跳过（{reason}）",
            )

        errors = list(runtime.get("errors") or [])
        warnings = list(runtime.get("warnings") or [])
        if not runtime.get("has_canvas"):
            warnings.append("页面加载后未发现 canvas（Phaser 可能没启动）")
        data["errors"] = errors[:40]
        data["warnings"] = warnings[:20]
        data["has_canvas"] = bool(runtime.get("has_canvas"))

        if errors:
            data["status"] = "playtest_failed"
            brief = "; ".join(f"{e.get('source')}: {(e.get('msg') or '')[:80]}" for e in errors[:3])
            return ActionResult(
                success=False,
                data=data,
                message=f"H5 试玩失败 · {len(errors)} errors · {brief}",
                error=brief,
            )

        data["status"] = "success"
        extra = "" if runtime.get("has_canvas") else "（无 canvas 警告）"
        return ActionResult(
            success=True,
            data=data,
            message=f"H5 试玩通过{extra}",
        )


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def _env(msg: str) -> ActionResult:
    return ActionResult(
        success=False,
        data={"status": "error"},
        message=msg,
        error=msg,
    )


def _fail(
    msg: str,
    *,
    errors: List[Dict[str, Any]],
    command: Any,
    raw_tail: str,
    duration_ms: int,
    notes: List[str],
    task_id: str = "",
) -> ActionResult:
    cmd_str = _cmd_line(command) if isinstance(command, list) else str(command or "")
    return ActionResult(
        success=False,
        data={
            "status": "playtest_failed",
            "errors": errors,
            "command": cmd_str,
            "raw_tail": raw_tail,
            "duration_ms": duration_ms,
            "notes": notes,
            "task_id": task_id,
        },
        message=msg,
        error=msg,
    )
