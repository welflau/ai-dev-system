"""
GenericCLIAction — 把一条"声明过的 CLI 命令"安全地暴露成 LLM 工具。

与 ShellAction（让 LLM 传任意 command 字符串，Tier 1 需确认）不同：
GenericCLIAction 的命令主干写死在 skill 的 command_template 里，LLM 只能填模板
预留的、白名单化的参数槽。这是"接新工具只加 skill 定义、不再硬编码"的安全前提。

安全四重（复用 ShellAction 的执行内核）：
  1. 命令主干 skill 白名单（LLM 选不了模板外的命令）
  2. LLM 只能填模板预留的自由槽（context 已预填的槽 LLM 填了也忽略）
  3. LLM 填入值一律 shlex.quote 防注入
  4. 渲染后整串过 _DANGEROUS_PATTERNS 黑名单复查 + cwd 锁 repo_path
超时 = spec.timeout；输出 MAX_OUTPUT_CHARS 截断。
"""
from __future__ import annotations

import asyncio
import logging
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, List

from actions.base import ActionBase, ActionResult
from actions.chat.shell_exec import _DANGEROUS_PATTERNS, MAX_OUTPUT_CHARS, _get_project_base

logger = logging.getLogger("actions.generic_cli")

# context 预填的、LLM 不应自己填的通用槽（命令主干参数）
_PREFILLED_SLOTS = {"cli", "change_id", "goal", "desc", "repo_path", "project_id", "ticket_id"}


class GenericCLIAction(ActionBase):
    """一条 skill 声明的 CLI 命令 → 一个 LLM 工具。"""

    def __init__(self, spec, timeout: int = 60):
        # spec: skills.executable_loader.CliToolSpec
        self._spec = spec
        self._timeout = int(getattr(spec, "timeout", timeout) or timeout)

    @property
    def name(self) -> str:
        return self._spec.name

    @property
    def description(self) -> str:
        return self._spec.description or f"执行 CLI: {self._spec.name}"

    def _free_slots(self) -> List[str]:
        """LLM 可填的槽 = 模板槽 - 预填槽（或 skill 显式声明的 free_slots）。"""
        if self._spec.free_slots is not None:
            return list(self._spec.free_slots)
        return [s for s in self._spec.template_slots() if s not in _PREFILLED_SLOTS]

    def tool_schema(self) -> Dict[str, Any]:
        free = self._free_slots()
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {s: {"type": "string"} for s in free},
                "required": free,
            },
        }

    def _render(self, context: Dict[str, Any]) -> str:
        """用 context（预填）+ LLM 填的自由槽渲染 command_template。
        LLM 填入值 shlex.quote；缺槽报错；模板未声明的槽被忽略。"""
        slots = self._spec.template_slots()
        free = set(self._free_slots())
        values: Dict[str, str] = {}
        missing: List[str] = []
        for slot in slots:
            raw = context.get(slot)
            if raw is None or raw == "":
                missing.append(slot)
                continue
            val = str(raw)
            # LLM 填的自由槽做 shell 转义；预填的主干参数也转义（值可能含空格）
            values[slot] = shlex.quote(val) if (slot in free or " " in val) else val
        if missing:
            raise ValueError(f"命令模板缺少参数: {missing}（工具 {self.name}）")
        # str.format 只替换 {slot}，模板里其余照原样
        return self._spec.command_template.format(**values)

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        try:
            rendered = self._render(context)
        except ValueError as e:
            return ActionResult(success=False, error=str(e))

        # 黑名单复查（渲染后整串）
        if _DANGEROUS_PATTERNS.search(rendered):
            return ActionResult(success=False, error=f"命令包含危险操作，已拒绝: {rendered[:120]}")

        # cwd 锁 repo_path（优先 context.repo_path，兜底查 DB）
        repo_path = context.get("repo_path")
        base = Path(repo_path) if repo_path and Path(repo_path).is_dir() else None
        if not base:
            base = await _get_project_base(context.get("project_id"))
        if not base:
            return ActionResult(success=False, error="未找到项目目录（repo_path/project_id）")

        logger.info("[cli:%s] %s @ %s", self.name, rendered[:120], base)

        try:
            if sys.platform == "win32":
                proc = await asyncio.create_subprocess_shell(
                    rendered, cwd=str(base),
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                    stdin=asyncio.subprocess.DEVNULL,
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    "/bin/bash", "-c", rendered, cwd=str(base),
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                    stdin=asyncio.subprocess.DEVNULL,
                )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=self._timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return ActionResult(success=False,
                                    error=f"CLI 超时（>{self._timeout}s）: {self.name}")

            output = (stdout.decode("utf-8", errors="replace").strip() if stdout else "")
            if len(output) > MAX_OUTPUT_CHARS:
                output = output[:MAX_OUTPUT_CHARS] + f"\n... (已截断，共 {len(output)} 字符)"
            exit_code = proc.returncode if proc.returncode is not None else -1
            success = (exit_code == 0)
            return ActionResult(
                success=success,
                data={"type": "cli_result", "tool": self.name, "command": rendered,
                      "exit_code": exit_code, "output": output},
                message=(f"[{self.name}] exit={exit_code}\n{output}" if output
                         else f"[{self.name}] exit={exit_code}（无输出）"),
                error=None if success else f"exit code {exit_code}",
            )
        except FileNotFoundError:
            return ActionResult(success=False, error=f"CLI 不可用: {rendered[:80]}")
        except Exception as e:
            logger.error("[cli:%s] 执行异常: %s", self.name, e)
            return ActionResult(success=False, error=f"执行异常: {e}")
