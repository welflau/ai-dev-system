"""
OpenSpec API — 检测安装状态 + 运行 openspec 命令并流式输出
"""
import asyncio
import json
import logging
import os
import shutil
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from database import db

logger = logging.getLogger("api.openspec")

router = APIRouter(prefix="/api/projects/{project_id}/openspec", tags=["openspec"])


class RunCommandRequest(BaseModel):
    command: str   # "install_en" | "install_cn" | "init_en" | "init_cn"
    lang: str = "en"  # "en" | "cn"


# ── 检测工具 ──────────────────────────────────────────────────────────────────

def _check_npm_installed() -> bool:
    return shutil.which("npm") is not None


def _check_openspec_installed(lang: str) -> bool:
    """检测 openspec / openspec-cn 全局命令是否存在。"""
    cmd = "openspec-cn" if lang == "cn" else "openspec"
    return shutil.which(cmd) is not None


def _check_openspec_initialized(repo_path: str) -> bool:
    """检测项目目录是否含有 openspec/ 目录及至少一个文件。"""
    if not repo_path:
        return False
    spec_dir = Path(repo_path) / "openspec"
    if not spec_dir.is_dir():
        return False
    return any(spec_dir.iterdir())


async def _get_project_repo_path(project_id: str) -> str:
    row = await db.fetch_one(
        "SELECT git_repo_path FROM projects WHERE id = ?", (project_id,)
    )
    if not row:
        raise HTTPException(404, "项目不存在")
    return row.get("git_repo_path") or ""


# ── 接口 ──────────────────────────────────────────────────────────────────────

@router.get("/status")
async def get_openspec_status(project_id: str):
    """返回 openspec 安装状态与初始化状态。"""
    repo_path = await _get_project_repo_path(project_id)

    npm_ok = _check_npm_installed()
    installed_en = _check_openspec_installed("en")
    installed_cn = _check_openspec_installed("cn")
    initialized = _check_openspec_initialized(repo_path)

    return {
        "npm_available": npm_ok,
        "installed_en": installed_en,
        "installed_cn": installed_cn,
        "initialized": initialized,
        "repo_path": repo_path,
        "openspec_dir": str(Path(repo_path) / "openspec") if repo_path else "",
    }


@router.post("/run")
async def run_openspec_command(project_id: str, req: RunCommandRequest):
    """
    运行 openspec 命令，流式返回 stdout/stderr。
    command: "install_en" | "install_cn" | "init_en" | "init_cn"
    """
    repo_path = await _get_project_repo_path(project_id)

    COMMANDS = {
        "install_en": (["npm", "install", "-g", "@fission-ai/openspec@latest"], None),
        "install_cn": (["npm", "install", "-g", "@studyzy/openspec-cn@latest"], None),
        "init_en": (["openspec", "init"], repo_path or None),
        "init_cn": (["openspec-cn", "init"], repo_path or None),
    }

    if req.command not in COMMANDS:
        raise HTTPException(400, f"未知命令: {req.command}")

    cmd_args, cwd = COMMANDS[req.command]

    if req.command.startswith("init") and not repo_path:
        raise HTTPException(400, "项目无本地路径，无法执行初始化")

    # init 命令有交互式 harness 选择器，自动注入 Enter 键序列确认默认选择
    # 默认已选 Claude Code + CodeBuddy，多个 \n 覆盖所有可能的交互提示
    stdin_input = None
    if req.command.startswith("init"):
        stdin_input = b"\n\n\n\n\n"  # 多次 Enter，确认所有交互提示

    return StreamingResponse(
        _stream_command(cmd_args, cwd, stdin_input=stdin_input),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _stream_command(cmd_args: list, cwd: str | None, stdin_input: bytes = None):
    """运行子进程，逐行 yield SSE 事件。

    stdin_input: 可选的 stdin 字节流，用于自动回答交互提示（如 openspec init 的 harness 选择）。
    """

    def _sse(event: str, data: dict) -> bytes:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()

    yield _sse("start", {"cmd": " ".join(cmd_args)})

    try:
        # Windows 需要 shell=True 才能找到 npm/openspec（PATH 扩展）
        use_shell = sys.platform == "win32"
        stdin_mode = asyncio.subprocess.PIPE if stdin_input else asyncio.subprocess.DEVNULL

        if use_shell:
            import subprocess
            cmd_str = " ".join(cmd_args)
            proc = await asyncio.create_subprocess_shell(
                cmd_str,
                stdin=stdin_mode,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd,
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdin=stdin_mode,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd,
            )

        # 有 stdin_input 时写入并关闭（模拟 Enter 确认交互提示）
        if stdin_input and proc.stdin:
            try:
                proc.stdin.write(stdin_input)
                await proc.stdin.drain()
                proc.stdin.close()
            except Exception:
                pass

        async for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            if line:
                yield _sse("line", {"text": line})

        rc = await proc.wait()
        yield _sse("done", {"exit_code": rc, "success": rc == 0})

    except FileNotFoundError as e:
        yield _sse("error", {"message": f"命令未找到: {e}"})
    except Exception as e:
        logger.exception("openspec run error: %s", e)
        yield _sse("error", {"message": str(e)})
