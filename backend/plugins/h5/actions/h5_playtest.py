"""对 Phaser 仓库做运行时门禁：vite build + 静态服 + 浏览器收错。

对着 git 仓库跑，不另开 DATA_DIR 沙箱，不常驻 Vite。
build 失败或页面 JS 异常 → status=playtest_failed（SOP reject_goto）。
缺 Node / 缺 index.html → status=error。
未装 Playwright 时 build 通过也算过，带 runtime_skipped 警告。
"""
from __future__ import annotations

import asyncio
import http.server
import logging
import os
import shutil
import socket
import socketserver
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
) -> Dict[str, Any]:
    """打开页面，收集 pageerror / console.error。未装 Playwright 返回 skipped。"""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
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
                text = msg.text()
                if msg.type == "error" and not is_runtime_noise(text):
                    errors.append({"source": "console.error", "msg": text})
                elif msg.type == "warning" and not is_runtime_noise(text):
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
        if "Executable doesn't exist" in err or "browserType.launch" in err:
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

        npm = resolve_bin(root, "npm")
        if not (root / "node_modules").is_dir():
            if not npm:
                return _env("找不到 npm，请安装 Node.js")
            notes.append("node_modules 缺失，执行 npm install")
            code, raw = await run_cmd(npm + ["install"], root, min(timeout, 180))
            if code != 0:
                return _fail(
                    "npm install 失败",
                    errors=[{"source": "npm", "msg": raw[-500:]}],
                    command=npm + ["install"],
                    raw_tail=raw[-4000:],
                    duration_ms=_ms(t0),
                    notes=notes,
                )

        vite = resolve_bin(root, "vite")
        if not vite:
            return _env("找不到 vite，请在仓库执行 npm install")
        build_cmd = vite + ["build"]
        code, raw = await run_cmd(build_cmd, root, min(timeout, 120))
        if code != 0:
            return _fail(
                "vite build 失败",
                errors=[{"source": "vite", "msg": raw[-500:]}],
                command=build_cmd,
                raw_tail=raw[-4000:],
                duration_ms=_ms(t0),
                notes=notes,
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
            runtime = await browse_and_collect(url, observe_ms=observe_ms, screenshot=shot)
        finally:
            httpd.shutdown()
            httpd.server_close()

        if shot and shot.is_file():
            screenshots.append(shot.as_posix())

        data: Dict[str, Any] = {
            "command": build_cmd,
            "duration_ms": _ms(t0),
            "url": url,
            "notes": notes,
            "screenshots": screenshots,
            "raw_tail": raw[-2000:],
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
    command: List[str],
    raw_tail: str,
    duration_ms: int,
    notes: List[str],
) -> ActionResult:
    return ActionResult(
        success=False,
        data={
            "status": "playtest_failed",
            "errors": errors,
            "command": command,
            "raw_tail": raw_tail,
            "duration_ms": duration_ms,
            "notes": notes,
        },
        message=msg,
        error=msg,
    )
