"""
ShellAction — 在项目目录内执行 Shell 命令

安全约束：
- 工作目录只允许是项目 git_repo_path
- 黑名单命令检测
- 超时 30 秒
- 输出截断 5000 字符
- 属于 Tier 1（需用户确认）工具，tool_schema 中标记
"""
import asyncio
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.chat.shell_exec")

TIMEOUT_SECONDS = 30
MAX_OUTPUT_CHARS = 5000

# 危险命令黑名单（检测命令起始词）
_DANGEROUS_PATTERNS = re.compile(
    r'\b(rm\s+-[rRf]|rmdir\s+/[sS]|format\s+[a-zA-Z]:|mkfs|dd\s+if=|'
    r'DROP\s+TABLE|DROP\s+DATABASE|TRUNCATE\s+TABLE|'
    r'shutdown|reboot|halt|poweroff|'
    r'del\s+/[fsFS]|rd\s+/[sS])\b',
    re.IGNORECASE,
)


async def _get_project_base(project_id: str) -> Path | None:
    if not project_id:
        return None
    try:
        from database import db
        row = await db.fetch_one("SELECT git_repo_path FROM projects WHERE id=?", (project_id,))
        if row and row.get("git_repo_path"):
            p = Path(row["git_repo_path"])
            if p.exists():
                return p
    except Exception:
        pass
    return None


class ShellAction(ActionBase):

    @property
    def name(self) -> str:
        return "shell"

    @property
    def description(self) -> str:
        return "在项目目录内执行 Shell 命令"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "在项目根目录内执行 Shell 命令。\n"
                "适合：运行脚本、查看日志、执行测试、检查环境、git 操作等。\n"
                "⚠️ 执行前会显示命令供确认。工作目录固定为项目根目录。\n"
                "超时 30 秒，输出最多 5000 字符。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "要执行的命令，如 'python -m pytest tests/' 或 'git log --oneline -10'",
                    },
                    "working_dir": {
                        "type": "string",
                        "description": "执行目录（相对项目根），默认项目根目录",
                    },
                },
                "required": ["command"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        project_id  = context.get("project_id")
        command     = (context.get("command") or "").strip()
        working_rel = (context.get("working_dir") or "").strip()

        if not command:
            return ActionResult(success=False, error="command 不能为空")

        # 黑名单检测
        if _DANGEROUS_PATTERNS.search(command):
            return ActionResult(
                success=False,
                error=f"命令包含危险操作，已拒绝执行: {command[:100]}",
            )

        base = await _get_project_base(project_id)
        if not base:
            return ActionResult(success=False, error="未找到项目目录，请在项目内使用此工具")

        work_dir = (base / working_rel).resolve() if working_rel else base.resolve()
        try:
            work_dir.relative_to(base.resolve())
        except ValueError:
            return ActionResult(success=False, error="working_dir 超出项目目录范围")

        if not work_dir.exists():
            return ActionResult(success=False, error=f"目录不存在: {working_rel}")

        # Windows / Linux 选择 shell
        if sys.platform == "win32":
            shell_cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
        else:
            shell_cmd = ["/bin/bash", "-c", command]

        logger.info("[shell] %s @ %s", command[:100], work_dir)

        try:
            proc = await asyncio.create_subprocess_exec(
                *shell_cmd,
                cwd=str(work_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                proc.kill()
                return ActionResult(
                    success=False,
                    error=f"命令超时（>{TIMEOUT_SECONDS}s），已终止: {command[:80]}",
                )

            stdout_text = stdout.decode("utf-8", errors="replace").strip()
            stderr_text = stderr.decode("utf-8", errors="replace").strip()
            exit_code   = proc.returncode

            output = ""
            if stdout_text:
                output += stdout_text
            if stderr_text:
                output += ("\n\n[stderr]\n" if output else "") + stderr_text
            if len(output) > MAX_OUTPUT_CHARS:
                output = output[:MAX_OUTPUT_CHARS] + f"\n... (已截断，共 {len(output)} 字符)"

            success = (exit_code == 0)
            return ActionResult(
                success=success,
                data={
                    "type": "shell_result",
                    "command": command,
                    "exit_code": exit_code,
                    "output": output,
                    "working_dir": str(work_dir.relative_to(base)),
                },
                message=f"命令执行{'成功' if success else f'失败（exit={exit_code}）'}: {command[:60]}",
                error=None if success else f"exit code {exit_code}",
            )

        except FileNotFoundError:
            return ActionResult(success=False, error="Shell 不可用，请检查系统环境")
        except Exception as e:
            logger.error("[shell] 执行异常: %s", e)
            return ActionResult(success=False, error=f"执行异常: {e}")
