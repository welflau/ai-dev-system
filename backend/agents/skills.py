"""
AI 自动开发系统 - Agent 技能库
定义 Agent 可调用的工具（skills/tools）以及执行逻辑
"""
import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("skills")


# ==================== 技能 Schema 定义 ====================

SKILL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "read_file",
        "description": "读取项目文件内容。用于了解现有代码结构、查看已有实现等。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径，相对于项目根目录，如 index.html 或 src/app.js",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_files",
        "description": "列出项目目录下的文件列表，了解项目结构。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "目录路径，相对于项目根目录。默认为根目录（.）",
                    "default": ".",
                }
            },
            "required": [],
        },
    },
    {
        "name": "write_file",
        "description": "写入或创建文件。用于输出实现代码、配置文件等。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径，相对于项目根目录",
                },
                "content": {
                    "type": "string",
                    "description": "文件完整内容",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "run_command",
        "description": "在项目目录运行命令（如 python -m pytest、node --check 等）。仅用于验证/测试，不要用来安装包。",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的 shell 命令，如 'python -m py_compile main.py'",
                },
                "timeout": {
                    "type": "integer",
                    "description": "超时秒数，默认 30",
                    "default": 30,
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "finish",
        "description": "完成任务并输出最终结果。当所有文件都已写入完毕时调用此工具。",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "实现摘要，描述完成了哪些工作",
                },
                "notes": {
                    "type": "string",
                    "description": "补充说明、关键决策或注意事项",
                },
            },
            "required": ["summary"],
        },
    },
]


# ==================== 技能执行器 ====================

class SkillExecutor:
    """技能执行器：负责实际调用工具并返回结果"""

    def __init__(self, project_root: Optional[Path] = None):
        self.project_root = project_root
        self._written_files: Dict[str, str] = {}   # path -> content（本次会话写入的文件）

    @property
    def written_files(self) -> Dict[str, str]:
        return self._written_files

    async def execute(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        """执行工具，返回结果字符串（会被 LLM 看到）"""
        try:
            if tool_name == "read_file":
                return await self._read_file(tool_input.get("path", ""))
            elif tool_name == "list_files":
                return await self._list_files(tool_input.get("path", "."))
            elif tool_name == "write_file":
                return await self._write_file(
                    tool_input.get("path", ""),
                    tool_input.get("content", ""),
                )
            elif tool_name == "run_command":
                return await self._run_command(
                    tool_input.get("command", ""),
                    tool_input.get("timeout", 30),
                )
            elif tool_name == "finish":
                # finish 工具只记录，不返回操作结果
                return f"[任务完成] {tool_input.get('summary', '')}"
            else:
                return f"[错误] 未知工具: {tool_name}"
        except Exception as e:
            logger.exception("技能 %s 执行异常: %s", tool_name, e)
            return f"[执行错误] {tool_name}: {e}"

    async def _read_file(self, rel_path: str) -> str:
        if not rel_path:
            return "[错误] 未提供路径"

        # 先从本次写入缓存中找
        if rel_path in self._written_files:
            content = self._written_files[rel_path]
            return f"[内存中 - 本次写入]\n{content[:5000]}"

        if self.project_root is None:
            return "[错误] 无法访问文件：未设置项目根目录"

        path = self.project_root / rel_path
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            if len(text) > 8000:
                text = text[:8000] + f"\n... (截断，共 {len(text)} 字符)"
            return text
        except FileNotFoundError:
            return f"[文件不存在] {rel_path}"
        except Exception as e:
            return f"[读取错误] {rel_path}: {e}"

    async def _list_files(self, rel_path: str = ".") -> str:
        lines = []

        # 已写入的内存文件
        if self._written_files:
            lines.append("[本次已写入文件]")
            for p in sorted(self._written_files.keys()):
                lines.append(f"  {p}")

        if self.project_root is None:
            if not lines:
                return "[错误] 未设置项目根目录"
            return "\n".join(lines)

        target = self.project_root / rel_path
        if not target.exists():
            return f"[目录不存在] {rel_path}"

        try:
            entries = []
            for item in sorted(target.iterdir()):
                if item.name.startswith("."):
                    continue
                if item.is_dir():
                    entries.append(f"  {item.name}/")
                else:
                    size = item.stat().st_size
                    entries.append(f"  {item.name}  ({size} bytes)")
            if entries:
                lines.append(f"[仓库文件 - {rel_path}]")
                lines.extend(entries[:50])
            else:
                lines.append(f"[空目录] {rel_path}")
        except Exception as e:
            lines.append(f"[列目录错误] {rel_path}: {e}")

        return "\n".join(lines) if lines else "(空)"

    async def _write_file(self, rel_path: str, content: str) -> str:
        if not rel_path:
            return "[错误] 未提供路径"
        if not content:
            return "[错误] 文件内容为空"

        # 存入内存（orchestrator 后续持久化到仓库）
        self._written_files[rel_path] = content
        logger.info("📝 SkillExecutor 写入: %s (%d chars)", rel_path, len(content))
        return f"[已写入] {rel_path}（{len(content)} 字符）"

    async def _run_command(self, command: str, timeout: int = 30) -> str:
        if not command:
            return "[错误] 命令为空"

        # 安全白名单（只允许验证类命令）
        allowed_prefixes = (
            "python -m py_compile",
            "python -c",
            "python3 -m py_compile",
            "python3 -c",
            "node --check",
            "node -e",
            "echo ",
            "cat ",
        )
        cmd_lower = command.strip().lower()
        if not any(cmd_lower.startswith(p.lower()) for p in allowed_prefixes):
            return f"[拒绝] 仅允许验证类命令（如 python -m py_compile）。收到: {command}"

        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.project_root) if self.project_root else None,
            )
            out = (proc.stdout or "").strip()
            err = (proc.stderr or "").strip()
            rc = proc.returncode
            result_parts = [f"[退出码: {rc}]"]
            if out:
                result_parts.append(f"[stdout]\n{out[:2000]}")
            if err:
                result_parts.append(f"[stderr]\n{err[:2000]}")
            return "\n".join(result_parts) if len(result_parts) > 1 else f"[退出码: {rc}] (无输出)"
        except subprocess.TimeoutExpired:
            return f"[超时] 命令超时 ({timeout}s): {command}"
        except Exception as e:
            return f"[执行错误] {command}: {e}"


# ==================== OpenAI format 转换工具 ====================

def schemas_to_openai_tools(schemas: List[Dict]) -> List[Dict]:
    """将 Anthropic tool schema 格式转换为 OpenAI function calling 格式"""
    tools = []
    for s in schemas:
        tools.append({
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s["description"],
                "parameters": s["input_schema"],
            },
        })
    return tools
