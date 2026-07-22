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


@router.get("/ticket/{ticket_id}/specs")
async def get_ticket_openspec(project_id: str, ticket_id: str):
    """读取工单的 OpenSpec 内容：proposal/specs/design/tasks + verify 结果。

    返回 openspec/changes/{ticket_id}/ 目录下所有 .md 文件内容，
    以及 openspec_stage（来自 tickets 表）供前端判断验证状态。
    """
    repo_path = await _get_project_repo_path(project_id)
    if not repo_path:
        raise HTTPException(404, "项目无本地路径")

    spec_dir = Path(repo_path) / "openspec" / "changes" / ticket_id
    if not spec_dir.exists():
        return {
            "initialized": False,
            "ticket_id": ticket_id,
            "files": {},
            "openspec_stage": None,
        }

    # 读取 .md 文件
    files: dict = {}
    for md_file in sorted(spec_dir.rglob("*.md")):
        try:
            rel = md_file.relative_to(spec_dir).as_posix()
            content = md_file.read_text(encoding="utf-8", errors="replace")
            # 按文件名简化 key（proposal/specs/design/tasks/changelog）
            key = md_file.stem.lower()
            if "/" in rel:
                key = rel.replace("/", "_").replace(".md", "")
            files[key] = {"path": rel, "content": content}
        except Exception:
            pass

    # 也读 openspec_stage
    ticket_row = await db.fetch_one(
        "SELECT openspec_stage FROM tickets WHERE id = ? AND project_id = ?",
        (ticket_id, project_id),
    )
    openspec_stage = (ticket_row or {}).get("openspec_stage")

    return {
        "initialized": True,
        "ticket_id": ticket_id,
        "files": files,
        "openspec_stage": openspec_stage,
    }


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


@router.get("/ticket/{ticket_id}/spec-versions")
async def get_ticket_spec_versions(project_id: str, ticket_id: str):
    """返回工单的 specs 版本历史（ticket_spec_versions 表 + 文件系统备份）。"""
    repo_path = await _get_project_repo_path(project_id)

    # 从 DB 读版本记录
    rows = await db.fetch_all(
        """SELECT id, version, change_summary, triggered_by, created_at
           FROM ticket_spec_versions WHERE ticket_id = ?
           ORDER BY version ASC""",
        (ticket_id,),
    )

    # 从文件系统读备份文件内容
    file_versions: dict = {}
    if repo_path:
        changes_dir = Path(repo_path) / "openspec" / "changes" / ticket_id
        if changes_dir.exists():
            for vf in sorted(changes_dir.glob("specs.v*.md")):
                try:
                    num = int(vf.stem.replace("specs.v", ""))
                    file_versions[num] = vf.read_text(encoding="utf-8", errors="replace")
                except (ValueError, Exception):
                    pass

    versions = []
    for row in rows:
        ver = row["version"]
        versions.append({
            "version": ver,
            "change_summary": row["change_summary"] or "",
            "created_at": row["created_at"],
            "content": row.get("content") or file_versions.get(ver, ""),
        })

    # 补充文件系统里有但 DB 无记录的版本（兼容旧数据）
    db_vers = {r["version"] for r in rows}
    for ver, content in file_versions.items():
        if ver not in db_vers:
            versions.append({
                "version": ver,
                "change_summary": f"v{ver}（文件备份）",
                "created_at": "",
                "content": content,
            })
    versions.sort(key=lambda x: x["version"])

    return {"ticket_id": ticket_id, "versions": versions}


@router.get("/project-stats")
async def get_project_openspec_stats(project_id: str):
    """返回项目三层覆盖率统计，供仪表盘展示。"""
    # 工单总数
    total_row = await db.fetch_one(
        "SELECT COUNT(*) as cnt FROM tickets WHERE project_id=? AND status NOT IN ('cancelled')",
        (project_id,),
    )
    total = (total_row or {}).get("cnt", 0)
    if total == 0:
        return {"total": 0, "openspec": {}, "superpowers": {}, "harness": {}}

    # OpenSpec 各阶段覆盖数
    os_rows = await db.fetch_all(
        """SELECT openspec_stage, COUNT(*) as cnt FROM tickets
           WHERE project_id=? AND openspec_stage IS NOT NULL AND status NOT IN ('cancelled')
           GROUP BY openspec_stage""",
        (project_id,),
    )
    os_counts = {r["openspec_stage"]: r["cnt"] for r in os_rows}

    # Superpowers 激活过的工单数（ticket_logs 有 superpowers_skill action）
    sp_row = await db.fetch_one(
        """SELECT COUNT(DISTINCT ticket_id) as cnt FROM ticket_logs
           WHERE project_id=? AND action='superpowers_skill'""",
        (project_id,),
    )
    sp_count = (sp_row or {}).get("cnt", 0)

    # 已完成工单数
    done_row = await db.fetch_one(
        "SELECT COUNT(*) as cnt FROM tickets WHERE project_id=? AND status='done'",
        (project_id,),
    )
    done_count = (done_row or {}).get("cnt", 0)

    # 有变更记录的工单数
    changed_row = await db.fetch_one(
        "SELECT COUNT(*) as cnt FROM tickets WHERE project_id=? AND change_count > 0",
        (project_id,),
    )
    changed_count = (changed_row or {}).get("cnt", 0)

    def pct(n): return round(n / total * 100) if total else 0

    return {
        "total": total,
        "openspec": {
            "proposed": os_counts.get("proposed", 0),
            "verified": os_counts.get("verified", 0),
            "archived": os_counts.get("archived", 0),
            "coverage_pct": pct(sum(os_counts.values())),
        },
        "superpowers": {
            "activated": sp_count,
            "coverage_pct": pct(sp_count),
        },
        "harness": {
            "done": done_count,
            "changed": changed_count,
            "done_pct": pct(done_count),
        },
    }
