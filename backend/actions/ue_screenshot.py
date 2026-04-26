"""
UEScreenshotAction — 启动 UE 游戏截效果图（v0.19.x）

用 UnrealEditor.exe <.uproject> -game 启动游戏，发送 HighResShot 命令截图后退出。
类似 Web 项目的 Playwright 截图，用于 DevAgent 自测 / CI / 交付报告。

命令行：
  UnrealEditor.exe <.uproject>
    -game            # 游戏模式（不开编辑器 UI）
    -windowed        # 窗口模式（不全屏）
    -ResX=1280 -ResY=720
    -ExecCmds="HighResShot 1920x1080 ue_preview.png; Exit"
    -unattended -nopause -nosplash -novsync

注意：
  - 需要 GPU（不支持 -nullrhi，无 GPU 时截图为黑屏）
  - 首次启动需着色器编译（可能 1-3 分钟）
  - 截图保存到 <project>/Saved/Screenshots/WindowsEditor/
  - 需要项目有默认地图（空骨架项目截图全黑，但能验证启动不崩）

输入 context:
    engine_path           引擎根目录（优先）。未给从 uproject 解析
    uproject_path         .uproject 绝对路径
    screenshot_width      默认 1920
    screenshot_height     默认 1080
    timeout_seconds       默认 180（首次启动 + 着色编译可能 2-3 分钟）
    output_dir            截图输出目录（默认 <project_git_root>/screenshots/）
    log_callback          async(str) → None

输出 data:
    {
      "status": "success" | "no_screenshot" | "error",
      "screenshots": [<绝对路径>, ...],
      "screenshot_count": int,
      "duration_ms": int,
      "command": "...",
      "engine_used": {...},
      "message": "...",
    }
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from actions.base import ActionBase, ActionResult
from engines.ue_resolver import resolve_project_engine, verify_engine

logger = logging.getLogger("actions.ue_screenshot")


class UEScreenshotAction(ActionBase):
    """启动 UE 游戏截效果图（类比 Web 的 Playwright 截图）"""

    available_for_traits = {"any_of": ["engine:ue5", "engine:ue4"]}

    @property
    def name(self) -> str:
        return "ue_screenshot"

    @property
    def description(self) -> str:
        return "启动 UE 游戏截效果图，存入项目截图目录"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        import asyncio

        sop_cfg = context.get("sop_config") or {}
        width = int(context.get("screenshot_width") or sop_cfg.get("screenshot_width") or 1920)
        height = int(context.get("screenshot_height") or sop_cfg.get("screenshot_height") or 1080)
        # Editor 全加载约需 300s（含 DDC/plugin 初始化 + 关卡加载）
        # 首次冷启动 5min，后续 ~300s 稳定（已验证 MyFPS UE5.7 实测 304s）
        timeout_seconds = int(context.get("timeout_seconds") or sop_cfg.get("timeout_seconds") or 300)

        log_cb = context.get("log_callback")

        async def _log(msg: str):
            logger.info(msg)
            if log_cb:
                try:
                    await log_cb(msg)
                except Exception:
                    pass

        uproject_path = context.get("uproject_path") or context.get("uproject")
        engine_path = context.get("engine_path") or context.get("ue_engine_path")
        await _log(f"[screenshot] 入参 engine={engine_path or '(无)'}  uproject={uproject_path or '(无)'}")

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
                            await _log(f"[screenshot] 已定位 .uproject: {uproject_path}")
                except Exception as e:
                    await _log(f"[screenshot] 探测 .uproject 异常: {e}")

        # 解析引擎
        engine_info = None
        if engine_path:
            engine_info = verify_engine(engine_path)
        elif uproject_path:
            engine_info = resolve_project_engine(uproject_path)
        else:
            return _err("缺 engine_path 和 uproject_path")

        if not engine_info or not engine_info.path:
            return _err("无法定位 UE 引擎")

        if not uproject_path or not Path(uproject_path).is_file():
            return _err(f".uproject 不存在: {uproject_path}")

        up = Path(uproject_path)

        # UnrealEditor.exe
        editor_exe = Path(engine_info.path) / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
        if not editor_exe.is_file():
            # UE4 fallback
            editor_exe = Path(engine_info.path) / "Engine" / "Binaries" / "Win64" / "UE4Editor.exe"
            if not editor_exe.is_file():
                return _err(f"找不到 UnrealEditor.exe: {editor_exe.parent}")

        await _log(f"[screenshot] 引擎: {engine_info.path} ({engine_info.version})")

        # 截图输出目录
        project_id = context.get("project_id")
        if context.get("output_dir"):
            output_dir = Path(context["output_dir"])
        elif project_id:
            try:
                from git_manager import git_manager
                repo = git_manager._repo_path(project_id)
                output_dir = Path(repo) / "screenshots" if repo else up.parent / "screenshots"
            except Exception:
                output_dir = up.parent / "screenshots"
        else:
            output_dir = up.parent / "screenshots"
        output_dir.mkdir(parents=True, exist_ok=True)

        # UE 原生截图目录
        ue_shot_dir = up.parent / "Saved" / "Screenshots" / "WindowsEditor"
        ue_shot_dir.mkdir(parents=True, exist_ok=True)

        # 组命令
        shot_filename = f"ue_preview_{int(time.time())}.png"
        # Editor 模式截图（不加 -game，直接截 Viewport）
        # 优点：不需要等着色器编译，启动快（30-60s）
        # 截图保存到 Saved/Screenshots/WindowsEditor/
        # Editor Viewport 截图：打开关卡编辑器，截活跃 Viewport 后退出
        # 不需要着色器编译（Editor 模式比 -game 快很多，约 30-90s）
        cmd = [
            str(editor_exe),
            str(up),
            "-nosplash",
            "-nologo",
            f"-ExecCmds=HighResShot {width}x{height} {shot_filename}; Exit",
        ]
        cmd_str = " ".join(str(c) for c in cmd)
        await _log(f"[screenshot] cmd: {cmd_str}")
        await _log(f"[screenshot] 打开 Editor 截关卡视图（30-90s）...")

        # 启动进程（线程模式，与 UBT 同方案）
        t0 = time.time()
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()
        _sentinel = object()

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding="utf-8",
                errors="replace",
            )
        except Exception as e:
            return _err(f"启动 UnrealEditor 异常: {type(e).__name__}: {e!r}")

        await _log(f"[screenshot] subprocess pid={proc.pid}")

        def _reader():
            try:
                for line in proc.stdout:
                    try:
                        loop.call_soon_threadsafe(queue.put_nowait, line.rstrip())
                    except RuntimeError:
                        break  # event loop closed
            finally:
                try:
                    loop.call_soon_threadsafe(queue.put_nowait, _sentinel)
                except RuntimeError:
                    pass  # event loop closed, that's OK

        reader = threading.Thread(target=_reader, daemon=True)
        reader.start()

        deadline = t0 + timeout_seconds
        collected: List[str] = []
        screenshot_detected = False

        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:
                    pass
                break
            try:
                item = await asyncio.wait_for(queue.get(), timeout=min(remaining, 5.0))
            except asyncio.TimeoutError:
                # 超时等待但进程还在 → 继续
                if proc.poll() is not None:
                    break
                continue
            if item is _sentinel:
                break
            line = item
            collected.append(line)
            if log_cb:
                try:
                    await log_cb(line)
                except Exception:
                    pass
            # 检测截图完成信号
            if "highresshot" in line.lower() or shot_filename.lower() in line.lower():
                screenshot_detected = True
                await _log(f"[screenshot] 截图信号: {line[:200]}")

        proc.wait(timeout=10)
        reader.join(timeout=3)
        duration_ms = int((time.time() - t0) * 1000)

        # 查找截图文件——UE 可能把截图存到多个目录之一
        found_shots: List[Path] = []
        search_dirs = [
            ue_shot_dir,                                         # Saved/Screenshots/WindowsEditor
            up.parent / "Saved" / "Screenshots" / "Windows",    # Saved/Screenshots/Windows
            up.parent / "Saved" / "Screenshots",                 # Saved/Screenshots
        ]

        for search_dir in search_dirs:
            if not search_dir.is_dir():
                continue
            # 精确匹配
            for p in search_dir.glob(f"*{shot_filename}"):
                found_shots.append(p)
            # 时间匹配（本次运行后新增的 png）
            if not found_shots:
                for p in sorted(search_dir.glob("*.png"), key=lambda x: x.stat().st_mtime, reverse=True):
                    if p.stat().st_mtime >= t0 - 5:
                        found_shots.append(p)
            if found_shots:
                await _log(f"[screenshot] 在 {search_dir} 找到 {len(found_shots)} 张截图")
                break

        # 拷贝到项目 screenshots 目录
        saved_paths: List[str] = []
        for src in found_shots[:3]:
            dst = output_dir / src.name
            try:
                shutil.copy2(src, dst)
                saved_paths.append(str(dst))
                await _log(f"[screenshot] 已保存: {dst}")
            except Exception as e:
                await _log(f"[screenshot] 拷贝失败: {e}")

        if saved_paths:
            return ActionResult(
                success=True,
                data={
                    "status": "success",
                    "screenshots": saved_paths,
                    "screenshot_count": len(saved_paths),
                    "duration_ms": duration_ms,
                    "command": cmd_str,
                    "engine_used": engine_info.to_dict(),
                    "message": f"截图 {len(saved_paths)} 张（{duration_ms // 1000}s）",
                },
            )
        else:
            await _log("[screenshot] 未找到截图文件（项目可能无默认地图，或 GPU 不可用导致黑屏）")
            return ActionResult(
                success=False,
                data={
                    "status": "no_screenshot",
                    "screenshots": [],
                    "screenshot_count": 0,
                    "duration_ms": duration_ms,
                    "command": cmd_str,
                    "engine_used": engine_info.to_dict(),
                    "message": "未找到截图，项目可能无默认地图或 GPU 不可用",
                    "partial_log": "\n".join(collected[-30:]),
                },
            )


def _err(msg: str) -> ActionResult:
    return ActionResult(
        success=False,
        data={"status": "error", "screenshots": [], "message": msg},
        error=msg,
    )
