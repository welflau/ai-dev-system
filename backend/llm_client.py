"""
AI 自动开发系统 - LLM 客户端
支持 Anthropic Messages API（原生）和 OpenAI 兼容 API
通过 LLM_API_FORMAT 环境变量切换：anthropic / openai（默认 anthropic）
"""
import json
import logging
import time
import httpx
from typing import Any, AsyncGenerator, Dict, List, Optional
from config import settings

logger = logging.getLogger("llm")

# J-3: 支持 Extended Thinking 的模型（需 Anthropic API 兼容）
_THINKING_CAPABLE_MODELS = {
    "claude-3-7-sonnet",
    "claude-opus-4",
    "claude-sonnet-4",   # claude-sonnet-4-5 / 4-6 及后续版本
}

def _model_supports_thinking(model_id: str) -> bool:
    """判断模型是否支持 Extended Thinking（前缀匹配）"""
    mid = (model_id or "").lower()
    return any(mid.startswith(m) or m in mid for m in _THINKING_CAPABLE_MODELS)


# ==================== LLM 会话记录上下文 ====================
import contextvars

class _LLMContext:
    """协程安全的 LLM 调用上下文（使用 contextvars）"""
    _ticket_id: contextvars.ContextVar = contextvars.ContextVar('llm_ticket_id', default=None)
    _requirement_id: contextvars.ContextVar = contextvars.ContextVar('llm_requirement_id', default=None)
    _project_id: contextvars.ContextVar = contextvars.ContextVar('llm_project_id', default=None)
    _agent_type: contextvars.ContextVar = contextvars.ContextVar('llm_agent_type', default=None)
    _action: contextvars.ContextVar = contextvars.ContextVar('llm_action', default=None)

    @property
    def ticket_id(self): return self._ticket_id.get()
    @ticket_id.setter
    def ticket_id(self, v): self._ticket_id.set(v)

    @property
    def requirement_id(self): return self._requirement_id.get()
    @requirement_id.setter
    def requirement_id(self, v): self._requirement_id.set(v)

    @property
    def project_id(self): return self._project_id.get()
    @project_id.setter
    def project_id(self, v): self._project_id.set(v)

    @property
    def agent_type(self): return self._agent_type.get()
    @agent_type.setter
    def agent_type(self, v): self._agent_type.set(v)

    @property
    def action(self): return self._action.get()
    @action.setter
    def action(self, v): self._action.set(v)

_llm_ctx = _LLMContext()


def set_llm_context(
    ticket_id: str = None,
    requirement_id: str = None,
    project_id: str = None,
    agent_type: str = None,
    action: str = None,
):
    """设置 LLM 调用上下文（在 Agent 执行前调用，协程安全）"""
    _llm_ctx.ticket_id = ticket_id
    _llm_ctx.requirement_id = requirement_id
    _llm_ctx.project_id = project_id
    _llm_ctx.agent_type = agent_type
    _llm_ctx.action = action


def clear_llm_context():
    """清除 LLM 调用上下文"""
    _llm_ctx.ticket_id = None
    _llm_ctx.requirement_id = None
    _llm_ctx.project_id = None
    _llm_ctx.agent_type = None
    _llm_ctx.action = None


def _truncate(text: str, max_len: int = 200) -> str:
    """截断文本用于日志显示"""
    if not text:
        return "(empty)"
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"... ({len(text)} chars total)"


# ── Anthropic 定价表（$/1M tokens，2025-05 版）──────────────────────────────
# 格式：model_prefix → (input_per_1m, output_per_1m)
_MODEL_PRICING: dict = {
    "claude-opus-4":         (15.0,  75.0),
    "claude-opus":           (15.0,  75.0),
    "claude-sonnet-4":       (3.0,   15.0),
    "claude-sonnet-3-7":     (3.0,   15.0),
    "claude-sonnet-3-5":     (3.0,   15.0),
    "claude-sonnet":         (3.0,   15.0),
    "claude-haiku-4":        (0.8,   4.0),
    "claude-haiku-3-5":      (0.8,   4.0),
    "claude-haiku":          (0.25,  1.25),
}

def _calc_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """根据模型和 token 数计算 USD 费用（粗估，仅供参考）"""
    if not model or not input_tokens:
        return 0.0
    model_lower = model.lower()
    price_in, price_out = 3.0, 15.0  # 默认 sonnet 价格
    for prefix, prices in _MODEL_PRICING.items():
        if prefix in model_lower:
            price_in, price_out = prices
            break
    cost = (input_tokens * price_in + (output_tokens or 0) * price_out) / 1_000_000
    return round(cost, 6)


def _ctx_label() -> str:
    """返回当前上下文标签，用于日志前缀"""
    parts = []
    if _llm_ctx.agent_type:
        parts.append(_llm_ctx.agent_type)
    if _llm_ctx.action:
        parts.append(_llm_ctx.action)
    if _llm_ctx.ticket_id:
        parts.append(_llm_ctx.ticket_id[:12])
    return " | ".join(parts) if parts else "no-context"


# ==================== CLI 适配表 ====================
# 每个 cli_type 描述如何把 (cli_cmd, model, prompt) 组装成子进程调用
# build_cmd(cli, model, prompt) -> list[str]
# stdin=True 表示 prompt 通过 stdin 传入（custom 模式），否则作为命令行参数
#
# 各工具默认可执行文件名（在 PATH 中直接可用时）：
#   claude           → claude
#   claude-internal  → claude  （腾讯内网版 Claude Code，同二进制，通过模型名区分）
#   gemini-internal  → gemini  （腾讯内网版 Gemini CLI）
#   codebuddy        → codebuddy
#   custom           → 用户自定义
#
# 各工具支持的模型列表（前端下拉联动，后端仅做透传，无需枚举校验）：
CLI_MODEL_OPTIONS: Dict[str, list] = {
    "claude": [
        # Claude 官方 CLI 支持的模型（来源：claude --model 选择界面）
        "claude-sonnet-4-6",
        "claude-sonnet-4-6-1m",
        "claude-opus-4-8",
        "claude-opus-4-8-1m",
        "claude-opus-4-7",
        "claude-opus-4-7-1m",
        "claude-opus-4-6",
        "claude-opus-4-6-1m",
        "claude-haiku-4-5",
    ],
    "claude-internal": [
        # 腾讯内网 Claude Code 可用模型（同 claude 二进制，模型名区分）
        "claude-sonnet-4-6",
        "claude-sonnet-4-6-1m",
        "claude-opus-4-8",
        "claude-opus-4-8-1m",
        "claude-haiku-4-5",
    ],
    "gemini-internal": [
        # 腾讯内网 Gemini CLI 可用模型
        "gemini-3.1-pro",
        "gemini-3.5-flash",
        "gemini-2.5-pro",
    ],
    "codebuddy": [
        # CodeBuddy CLI 可用模型（来源：codebuddy 模型选择界面）
        "claude-sonnet-4-6",
        "claude-sonnet-4-6-1m",
        "claude-opus-4-8",
        "claude-opus-4-8-1m",
        "claude-opus-4-7",
        "claude-opus-4-7-1m",
        "claude-opus-4-6",
        "claude-opus-4-6-1m",
        "claude-haiku-4-5",
        "gemini-3.1-pro",
        "gemini-3.5-flash",
        "gemini-2.5-pro",
        "gpt-5.5",
        "gpt-5.4",
        "gpt-5.3-codex",
        "gpt-5.1-codex",
        "gpt-5.1-codex-mini",
        "glm-5.1-ioa",
        "glm-5v-turbo-ioa",
        "glm-5.0-ioa",
        "glm-4.7-ioa",
        "minimax-m2.7-ioa",
        "minimax-m2.5-ioa",
        "kimi-k2.6-ioa",
        "hy3-preview-ioa",
        "deepseek-v4-pro-ioa",
        "deepseek-v4-flash-ioa",
        "deepseek-v3-2-volc-ioa",
    ],
    "custom": [],   # 自定义工具不预设模型列表
}

_CLI_ADAPTERS: Dict[str, Dict] = {
    "claude": {
        "build_cmd": lambda cli, model, prompt: (
            [cli, "--print", "--output-format", "stream-json",
             "--include-partial-messages", "--model", model]
            if model else
            [cli, "--print", "--output-format", "stream-json", "--include-partial-messages"]
        ),
        "stdin": True,
        "streaming": True,
        "default_cmd": "claude",
    },
    "claude-internal": {
        "build_cmd": lambda cli, model, prompt: (
            [cli, "--print", "--output-format", "stream-json",
             "--include-partial-messages", "--model", model]
            if model else
            [cli, "--print", "--output-format", "stream-json", "--include-partial-messages"]
        ),
        "stdin": True,
        "streaming": True,
        "default_cmd": "claude",
    },
    "gemini-internal": {
        "build_cmd": lambda cli, model, prompt: (
            [cli, "--model", model]
            if model else [cli]
        ),
        "stdin": True,
        "streaming": False,
        "default_cmd": "gemini",
    },
    "codebuddy": {
        "build_cmd": lambda cli, model, prompt: (
            [cli, "--print", "--output-format", "stream-json",
             "--include-partial-messages", "--model", model]
            if model else
            [cli, "--print", "--output-format", "stream-json", "--include-partial-messages"]
        ),
        "stdin": True,
        "streaming": True,
        "default_cmd": "codebuddy",
    },
    "custom": {
        "build_cmd": lambda cli, model, prompt: [cli],
        "stdin": True,
        "streaming": False,
        "default_cmd": "",
    },
}


class LLMClient:
    """LLM 客户端 — 支持 Anthropic Messages API、OpenAI 兼容 API 和本地 CLI"""

    def __init__(self):
        self.base_url = settings.LLM_BASE_URL.rstrip("/")
        self.api_key = settings.LLM_API_KEY
        self.model = settings.LLM_MODEL
        self.timeout = settings.LLM_TIMEOUT
        self.max_retries = settings.LLM_MAX_RETRIES
        self.api_format = settings.LLM_API_FORMAT  # "anthropic" / "openai" / "cli"
        self._pending_requests: int = 0   # 当前在途 LLM 请求数（供 /api/metrics 读取）

        # CLI 模式专属
        self.cli_type    = settings.LLM_CLI_TYPE
        self.cli_cmd     = settings.LLM_CLI_CMD
        self.cli_model   = settings.LLM_CLI_MODEL or settings.LLM_MODEL
        self.cli_timeout = settings.LLM_CLI_TIMEOUT

    @property
    def is_configured(self) -> bool:
        """是否已配置 LLM"""
        if self.api_format == "cli":
            return bool(self.cli_cmd)   # CLI 模式只需要可执行文件路径非空
        return bool(self.base_url and self.api_key)

    # ---- Anthropic Messages API ----

    def _anthropic_headers(self) -> Dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    def _to_anthropic_payload(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> Dict[str, Any]:
        """将通用 messages 转换为 Anthropic Messages API payload"""
        system_text = ""
        user_messages = []
        for msg in messages:
            if msg["role"] == "system":
                # system content 只支持字符串
                content = msg["content"]
                system_text += (content if isinstance(content, str) else str(content)) + "\n"
            else:
                # content 可能是字符串（普通消息）或 list（vision blocks）—— 直接透传
                user_messages.append(msg)
        # Anthropic 要求至少有一条 user 消息
        if not user_messages:
            user_messages = [{"role": "user", "content": "Hello"}]
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": user_messages,
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if system_text.strip():
            payload["system"] = system_text.strip()
        return payload

    async def _call_anthropic(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> tuple:
        """调用 Anthropic Messages API，返回 (response_text, usage_dict)"""
        url = f"{self.base_url}/v1/messages"
        payload = self._to_anthropic_payload(messages, temperature, max_tokens)

        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        url, headers=self._anthropic_headers(), json=payload
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    # Anthropic 格式：content[0].text
                    content_blocks = data.get("content", [])
                    texts = [
                        b["text"] for b in content_blocks if b.get("type") == "text"
                    ]
                    text = "".join(texts) if texts else ""
                    usage = data.get("usage", {})
                    return text, {
                        "input_tokens": usage.get("input_tokens"),
                        "output_tokens": usage.get("output_tokens"),
                    }
            except Exception as e:
                if attempt == self.max_retries - 1:
                    logger.error("Anthropic 调用失败 (attempt %d/%d): %s", attempt + 1, self.max_retries, e)
                    return self._fallback_response(messages), None
                logger.warning("Anthropic 调用重试 %d/%d: %s", attempt + 1, self.max_retries, e)

        return self._fallback_response(messages), None

    # ---- OpenAI 兼容 API ----

    def _openai_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def _call_openai(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> tuple:
        """调用 OpenAI 兼容 API，返回 (response_text, usage_dict)"""
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        url, headers=self._openai_headers(), json=payload
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    text = data["choices"][0]["message"]["content"]
                    usage = data.get("usage", {})
                    return text, {
                        "input_tokens": usage.get("prompt_tokens"),
                        "output_tokens": usage.get("completion_tokens"),
                    }
            except Exception as e:
                if attempt == self.max_retries - 1:
                    logger.error("OpenAI 调用失败 (attempt %d/%d): %s", attempt + 1, self.max_retries, e)
                    return self._fallback_response(messages), None
                logger.warning("OpenAI 调用重试 %d/%d: %s", attempt + 1, self.max_retries, e)

        return self._fallback_response(messages), None

    # ---- CLI 子进程调用 ----

    def _messages_to_prompt(self, messages: List[Dict]) -> str:
        """
        将 messages 转为 CLI stdin 的用户消息文本（不含 system）。

        策略：
        - 只取最后一条 user 消息（system 已通过 --system-prompt 参数单独传递）
        - 保持简单可靠
        """
        last_user_text = ""

        for m in messages:
            role    = m.get("role", "")
            content = m.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            if not isinstance(content, str):
                content = str(content)
            content = content.strip()

            if role == "user":
                last_user_text = content  # 每次覆盖，只保留最后一条

        return last_user_text

    def _extract_system_prompt(self, messages: List[Dict]) -> str:
        """从 messages 中提取 system 消息文本（供 --system-prompt 参数使用）。"""
        for m in messages:
            if m.get("role") == "system":
                content = m.get("content", "")
                if isinstance(content, list):
                    content = " ".join(
                        b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                return str(content).strip() if content else ""
        return ""

    def _messages_to_stdin(self, messages: List[Dict]) -> bytes:
        """
        将 messages 转为 CLI stdin bytes。
        - 无图片：纯文本（兼容旧行为）
        - 有图片：JSON 格式（claude/codebuddy 支持 JSON stdin 含 image blocks）

        JSON 格式：单条 user 消息，content 为 blocks 数组。
        system prompt 拼入最前面的 text block，图片 blocks 跟在文本后。
        """
        import json as _json

        # 检查是否有图片 block
        has_image = False
        for m in messages:
            content = m.get("content", "")
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "image":
                        has_image = True
                        break
            if has_image:
                break

        if not has_image:
            return self._messages_to_prompt(messages).encode("utf-8")

        # 有图片：构建 JSON stdin
        last_user_text = ""
        last_user_images = []

        for m in messages:
            role = m.get("role", "")
            content = m.get("content", "")
            if role == "user":
                if isinstance(content, list):
                    last_user_text = " ".join(
                        b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                    last_user_images = [
                        b for b in content
                        if isinstance(b, dict) and b.get("type") == "image"
                    ]
                else:
                    last_user_text = content or ""
                    last_user_images = []

        # 构建 blocks：text + 图片（system 已通过 --system-prompt 参数单独传递）
        user_blocks = []
        if last_user_text:
            user_blocks.append({"type": "text", "text": last_user_text})
        user_blocks.extend(last_user_images)

        payload = {"role": "user", "content": user_blocks}
        return _json.dumps(payload, ensure_ascii=False).encode("utf-8")

    @staticmethod
    def _build_settings_args(cli_type: str, cwd: Optional[str]) -> tuple:
        """
        为 claude/codebuddy CLI 构建 --settings 参数。

        读取 <cwd>/.ads/mcp_servers.json，将其中 enabled=true 的 server 转换为
        Claude/CodeBuddy settings.json 格式，写入临时文件并返回 (extra_args, tmp_path)。
        extra_args 可直接追加到 cmd 中；tmp_path 用完后由调用方删除。

        不支持 --settings 的 cli_type 或无 .ads 配置时返回 ([], None)。
        """
        if cli_type not in ("claude", "claude-internal", "codebuddy"):
            logger.debug("🖥️  CLI MCP 注入跳过：cli_type=%s 不支持 --settings", cli_type)
            return [], None
        if not cwd:
            logger.debug("🖥️  CLI MCP 注入跳过：cwd 为空")
            return [], None

        import json as _json
        import os as _os
        import tempfile
        from pathlib import Path as _Path

        ads_mcp = _Path(cwd) / ".ads" / "mcp_servers.json"
        if not ads_mcp.exists():
            logger.debug("🖥️  CLI MCP 注入跳过：%s 不存在", ads_mcp)
            return [], None

        try:
            servers_cfg = _json.loads(ads_mcp.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("🖥️  CLI MCP 注入：读取 %s 失败: %s", ads_mcp, e)
            return [], None

        # .ads/mcp_servers.json 格式：list of {name, command, args, env, enabled}
        # 转为 Claude/CodeBuddy settings.json 的 mcpServers dict
        mcp_servers = {}
        entries = servers_cfg if isinstance(servers_cfg, list) else servers_cfg.get("servers", [])
        skipped = []
        for s in entries:
            if not s.get("enabled", True):
                skipped.append(s.get("name") or s.get("id") or "?")
                continue
            name = s.get("name") or s.get("id") or ""
            if not name:
                continue
            entry: dict = {}
            if s.get("command"):
                entry["command"] = s["command"]
            if s.get("args"):
                entry["args"] = s["args"]
            if s.get("env"):
                entry["env"] = s["env"]
            if entry.get("command"):
                mcp_servers[name] = entry

        if skipped:
            logger.debug("🖥️  CLI MCP 注入：跳过已禁用 server: %s", skipped)

        if not mcp_servers:
            logger.info("🖥️  CLI MCP 注入：%s 中无可用 server（全部禁用或格式不符）", ads_mcp)
            return [], None

        # 构造 settings.json，allowedTools 放行所有 MCP 工具
        settings_obj = {
            "mcpServers": mcp_servers,
        }

        try:
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, encoding="utf-8"
            )
            _json.dump(settings_obj, tmp, ensure_ascii=False, indent=2)
            tmp.close()
            server_names = list(mcp_servers.keys())
            logger.info(
                "🖥️  CLI MCP 注入成功: %d 个 server [%s] → --settings %s",
                len(mcp_servers), ", ".join(server_names), tmp.name,
            )
            return ["--settings", tmp.name], tmp.name
        except Exception as e:
            logger.warning("🖥️  CLI MCP 注入：生成临时 settings 文件失败: %s", e)
            return [], None

    @staticmethod
    def _resolve_cmd(cli_cmd: str) -> list:
        """
        解析 CLI 命令，处理 Windows 下 .cmd / .bat 脚本无法被
        asyncio.create_subprocess_exec 直接执行的问题。
        返回可直接传给 create_subprocess_exec 的参数列表前缀。
        示例：
          'codebuddy'    (Windows, .cmd) → ['cmd', '/c', 'codebuddy']
          'claude'       (Windows, .exe) → ['claude']
          'claude'       (Linux)         → ['claude']
        """
        import sys, shutil as _sh
        if sys.platform != "win32":
            return [cli_cmd]
        resolved = _sh.which(cli_cmd)
        if resolved and (resolved.lower().endswith('.cmd') or resolved.lower().endswith('.bat')):
            return ['cmd', '/c', cli_cmd]
        return [cli_cmd]

    async def _call_cli(
        self,
        messages: List[Dict],
        temperature: float,
        max_tokens: int,
    ) -> tuple:
        """通过本地 CLI 子进程调用 LLM，返回 (response_text, usage_dict)"""
        import asyncio as _asyncio
        import os as _os

        adapter    = _CLI_ADAPTERS.get(self.cli_type, _CLI_ADAPTERS["custom"])
        prompt     = self._messages_to_prompt(messages)
        use_stdin  = adapter["stdin"]
        use_stream = adapter.get("streaming", False)
        cmd_prefix = self._resolve_cmd(self.cli_cmd)
        raw_args   = adapter["build_cmd"](self.cli_cmd, self.cli_model, prompt)
        cmd = cmd_prefix + raw_args[1:]

        # 对支持 --system-prompt 的 CLI，把 system 消息通过参数传递而非拼入 stdin
        _supports_system_param = self.cli_type in ("claude", "claude-internal", "codebuddy")
        if _supports_system_param:
            _sys_text = self._extract_system_prompt(messages)
            if _sys_text:
                cmd = cmd + ["--system-prompt", _sys_text]

        _cmd_display = [
            "<system-prompt>" if (i > 0 and cmd[i-1] == "--system-prompt") else c
            for i, c in enumerate(cmd)
        ]
        logger.info("🖥️  CLI 调用: %s (type=%s, stream=%s, prompt_len=%d)",
                    " ".join(_cmd_display), self.cli_type, use_stream, len(prompt))
        logger.info("🖥️  CLI stdin 末尾（用户消息区）:\n...%s\n---", prompt[-300:])

        env = _os.environ.copy()
        if self.cli_type in ("codebuddy", "claude", "claude-internal"):
            env["CODEBUDDY_API_KEY_DISABLED"] = "1"

        stdin_data = self._messages_to_stdin(messages) if use_stdin else None

        cwd = None
        if _llm_ctx.project_id:
            try:
                from database import db as _db
                proj = await _db.fetch_one(
                    "SELECT git_repo_path FROM projects WHERE id = ?",
                    (_llm_ctx.project_id,),
                )
                if proj and proj.get("git_repo_path"):
                    import os as _os2
                    if _os2.path.isdir(proj["git_repo_path"]):
                        cwd = proj["git_repo_path"]
                        logger.info("🖥️  CLI cwd → %s", cwd)
            except Exception as _e:
                logger.debug("CLI cwd 查询失败（忽略）: %s", _e)

        # 注入 .ads/mcp_servers.json → --settings
        _settings_args, _settings_tmp = self._build_settings_args(self.cli_type, cwd)
        if _settings_args:
            cmd = cmd + _settings_args
            logger.info("🖥️  CLI 非流式：最终命令（含 --settings）: %s", " ".join(_cmd_display))
        else:
            logger.debug("🖥️  CLI 非流式：最终命令（无 MCP 注入）: %s", " ".join(_cmd_display))

        try:
            proc = await _asyncio.create_subprocess_exec(
                *cmd,
                stdin=_asyncio.subprocess.PIPE if use_stdin else None,
                stdout=_asyncio.subprocess.PIPE,
                stderr=_asyncio.subprocess.PIPE,
                env=env,
                cwd=cwd,
            )

            if use_stream:
                full_text = await self._parse_cli_stream(proc, stdin_data)
            else:
                try:
                    stdout, stderr = await _asyncio.wait_for(
                        proc.communicate(input=stdin_data), timeout=self.cli_timeout
                    )
                except _asyncio.TimeoutError:
                    proc.kill()
                    logger.error("CLI 调用超时（%ds）: %s", self.cli_timeout, self.cli_cmd)
                    return self._fallback_response(messages), None

                if proc.returncode != 0:
                    err_msg = stderr.decode("utf-8", errors="replace")[:500]
                    logger.error("CLI 调用失败 (rc=%d): %s", proc.returncode, err_msg)
                    return f"[CLI错误] {err_msg}", None

                full_text = stdout.decode("utf-8", errors="replace").strip()
                stderr_text = stderr.decode("utf-8", errors="replace").strip()
                if not full_text and stderr_text:
                    logger.warning("CLI stdout 为空，stderr: %s", stderr_text[:200])
                    return f"[CLI错误] {stderr_text[:500]}", None

            return full_text, {"input_tokens": None, "output_tokens": None}

        except FileNotFoundError:
            logger.error("CLI 可执行文件不存在: %s", self.cli_cmd)
            return self._fallback_response(messages), None
        except Exception as e:
            logger.error("CLI 调用异常: %s", e)
            return self._fallback_response(messages), None
        finally:
            if _settings_tmp:
                try:
                    _os.unlink(_settings_tmp)
                except Exception:
                    pass

    async def _parse_cli_stream(self, proc, stdin_data: bytes) -> str:
        """
        解析 stream-json 格式的 CLI 输出，返回拼接后的完整文本。
        stream-json 每行一个 JSON 对象，文本在：
          {"type":"assistant","message":{"content":[{"type":"text","text":"..."}]}}
        """
        import asyncio as _asyncio
        import json as _json

        # 先写入 stdin
        if stdin_data and proc.stdin:
            proc.stdin.write(stdin_data)
            await proc.stdin.drain()
            proc.stdin.close()

        full_text = ""
        try:
            async def _read_lines():
                nonlocal full_text
                async for raw_line in proc.stdout:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        obj = _json.loads(line)
                    except _json.JSONDecodeError:
                        continue

                    t = obj.get("type", "")
                    # assistant 消息块：提取文本
                    if t == "assistant":
                        msg = obj.get("message", {})
                        for block in msg.get("content", []):
                            if block.get("type") == "text":
                                full_text += block.get("text", "")
                    # result 块：记录错误
                    elif t == "result" and obj.get("is_error"):
                        errors = obj.get("errors", [])
                        if errors and not full_text:
                            full_text = f"[CLI错误] {errors[0][:300]}"

            await _asyncio.wait_for(_read_lines(), timeout=self.cli_timeout)
        except _asyncio.TimeoutError:
            proc.kill()
            logger.error("CLI 流式读取超时（%ds）", self.cli_timeout)
            if not full_text:
                full_text = self._fallback_response([])

        # 等进程结束
        try:
            await _asyncio.wait_for(proc.wait(), timeout=5)
        except Exception:
            pass

        return full_text.strip()

    async def _call_cli_stream(
        self,
        messages: List[Dict],
        temperature: float,
        max_tokens: int,
        resume_session_id: str = "",
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式版 CLI 调用，实时 yield text_delta 事件（供 QueryEngine CLI 模式使用）。
        stream-json 格式：每行一个 JSON，assistant 消息块里有文本。

        resume_session_id: 非空时追加 --resume <id>，让 CLI 恢复上一轮对话上下文。
        """
        import asyncio as _asyncio
        import json as _json
        import os as _os

        adapter    = _CLI_ADAPTERS.get(self.cli_type, _CLI_ADAPTERS["custom"])
        prompt     = self._messages_to_prompt(messages)
        use_stdin  = adapter["stdin"]
        use_stream = adapter.get("streaming", False)
        cmd_prefix = self._resolve_cmd(self.cli_cmd)
        raw_args   = adapter["build_cmd"](self.cli_cmd, self.cli_model, prompt)
        cmd = cmd_prefix + raw_args[1:]

        # Session Resume：支持 --resume 的 CLI 类型追加参数
        _RESUME_SUPPORTED = {"claude", "claude-internal", "codebuddy"}
        if resume_session_id and self.cli_type in _RESUME_SUPPORTED:
            cmd += ["--resume", resume_session_id]
            logger.info("🖥️  CLI Resume: session_id=%s", resume_session_id)
        elif self.cli_type in _RESUME_SUPPORTED:
            # 首轮（无 resume）：通过 --system-prompt 传递 system 消息，而非拼入 stdin
            # --resume 时跳过：CLI 会话已记录上一轮的 system prompt，重复传会被忽略或冲突
            _sys_text = self._extract_system_prompt(messages)
            if _sys_text:
                cmd = cmd + ["--system-prompt", _sys_text]

        _cmd_display = [
            "<system-prompt>" if (i > 0 and cmd[i-1] == "--system-prompt") else c
            for i, c in enumerate(cmd)
        ]
        logger.info("🖥️  CLI 流式调用: %s (type=%s)", " ".join(_cmd_display), self.cli_type)
        logger.info("🖥️  CLI 流式 stdin 末尾（用户消息区）:\n...%s\n---", prompt[-300:])

        env = _os.environ.copy()
        if self.cli_type in ("codebuddy", "claude", "claude-internal"):
            env["CODEBUDDY_API_KEY_DISABLED"] = "1"

        stdin_data = self._messages_to_stdin(messages) if use_stdin else None

        # CLI 模式：以项目 git_repo_path 作为工作目录，让 CLI 工具感知项目上下文
        cwd = None
        if _llm_ctx.project_id:
            try:
                from database import db as _db
                proj = await _db.fetch_one(
                    "SELECT git_repo_path FROM projects WHERE id = ?",
                    (_llm_ctx.project_id,),
                )
                if proj and proj.get("git_repo_path"):
                    import os as _os2
                    if _os2.path.isdir(proj["git_repo_path"]):
                        cwd = proj["git_repo_path"]
            except Exception as _e:
                logger.debug("CLI cwd 查询失败（忽略）: %s", _e)

        # 注入 .ads/mcp_servers.json → --settings
        _settings_args, _settings_tmp = self._build_settings_args(self.cli_type, cwd)
        if _settings_args:
            cmd = cmd + _settings_args
            logger.info("🖥️  CLI 流式：最终命令（含 --settings）: %s", " ".join(cmd))
        else:
            logger.debug("🖥️  CLI 流式：最终命令（无 MCP 注入）: %s", " ".join(cmd))

        try:
            proc = await _asyncio.create_subprocess_exec(
                *cmd,
                stdin=_asyncio.subprocess.PIPE if use_stdin else None,
                stdout=_asyncio.subprocess.PIPE,
                stderr=_asyncio.subprocess.PIPE,
                env=env,
                cwd=cwd,
            )

            if stdin_data and proc.stdin:
                proc.stdin.write(stdin_data)
                await proc.stdin.drain()
                proc.stdin.close()

            full_text = ""
            if use_stream:
                # stream-json + --include-partial-messages 格式：
                #   {"type":"stream_event","event":{"type":"content_block_delta",
                #     "delta":{"type":"text_delta","text":"..."}}}
                #   {"type":"stream_event","event":{"type":"content_block_delta",
                #     "delta":{"type":"thinking_delta","thinking":"..."}}}
                # 用 Queue 桥接：_reader task 解析行 → queue → yield
                queue: _asyncio.Queue = _asyncio.Queue()

                async def _reader():
                    nonlocal full_text
                    async for raw_line in proc.stdout:
                        line = raw_line.decode("utf-8", errors="replace").strip()
                        if not line:
                            continue
                        try:
                            obj = _json.loads(line)
                        except _json.JSONDecodeError:
                            continue
                        t = obj.get("type", "")
                        if t == "stream_event":
                            ev = obj.get("event", {})
                            et = ev.get("type", "")
                            delta = ev.get("delta", {})
                            dt = delta.get("type", "")
                            if et == "content_block_delta":
                                if dt == "text_delta":
                                    chunk = delta.get("text", "")
                                    if chunk:
                                        full_text += chunk
                                        await queue.put(("text", chunk))
                                elif dt == "thinking_delta":
                                    chunk = delta.get("thinking", "")
                                    if chunk:
                                        await queue.put(("thinking", chunk))
                        elif t == "assistant":
                            # 完整 assistant 消息：提取 tool_use blocks
                            msg = obj.get("message", {})
                            for blk in msg.get("content", []):
                                if blk.get("type") == "tool_use":
                                    await queue.put(("tool_start", {
                                        "tool_use_id": blk.get("id", ""),
                                        "name": blk.get("name", ""),
                                        "input": blk.get("input", {}),
                                    }))
                        elif t == "user":
                            # tool_result blocks（工具执行完毕）
                            msg = obj.get("message", {})
                            for blk in msg.get("content", []):
                                if blk.get("type") == "tool_result":
                                    content = blk.get("content", [])
                                    result_text = ""
                                    if isinstance(content, list):
                                        for c in content:
                                            if isinstance(c, dict) and c.get("type") == "text":
                                                result_text += c.get("text", "")
                                    elif isinstance(content, str):
                                        result_text = content
                                    await queue.put(("tool_result", {
                                        "tool_use_id": blk.get("tool_use_id", ""),
                                        "result": result_text[:500],
                                    }))
                        elif t == "system" and obj.get("subtype") == "init":
                            # Session Resume: CLI 输出的会话 ID，用于下次 --resume
                            sid = obj.get("session_id", "")
                            if sid:
                                await queue.put(("session_id", sid))
                        elif t == "result" and obj.get("is_error"):
                            errors = obj.get("errors", [])
                            if errors and not full_text:
                                full_text = f"[CLI错误] {errors[0][:300]}"
                                await queue.put(("text", full_text))
                    await queue.put(None)  # 结束哨兵

                reader_task = _asyncio.create_task(_reader())
                deadline = _asyncio.get_event_loop().time() + self.cli_timeout

                try:
                    while True:
                        remaining = deadline - _asyncio.get_event_loop().time()
                        if remaining <= 0:
                            reader_task.cancel()
                            proc.kill()
                            logger.error("CLI 流式调用超时（%ds）", self.cli_timeout)
                            if not full_text:
                                yield {"type": "text_delta", "delta": "[CLI错误] 调用超时"}
                            break
                        try:
                            item = await _asyncio.wait_for(queue.get(), timeout=min(remaining, 5.0))
                        except _asyncio.TimeoutError:
                            # 5 秒内没有新内容，检查进程是否还活着
                            if proc.returncode is not None:
                                break
                            continue
                        if item is None:
                            break
                        kind, chunk = item
                        if kind == "text":
                            yield {"type": "text_delta", "delta": chunk}
                        elif kind == "thinking":
                            yield {"type": "thinking_delta", "delta": chunk}
                        elif kind == "session_id":
                            # Session Resume: 把 CLI session_id 上抛给调用层存 DB
                            yield {"type": "cli_session_id", "session_id": chunk}
                        elif kind == "tool_start":
                            yield {"type": "cli_tool_start", "tool_use_id": chunk["tool_use_id"],
                                   "name": chunk["name"], "input": chunk["input"]}
                        elif kind == "tool_result":
                            yield {"type": "cli_tool_result", "tool_use_id": chunk["tool_use_id"],
                                   "result": chunk["result"]}
                except Exception as ex:
                    logger.error("CLI 流式读取异常: %s", ex)
                finally:
                    if not reader_task.done():
                        reader_task.cancel()
            else:
                # 非流式 CLI：等待全部输出，一次性 yield
                try:
                    stdout, stderr = await _asyncio.wait_for(
                        proc.communicate(), timeout=self.cli_timeout
                    )
                    full_text = stdout.decode("utf-8", errors="replace").strip()
                    if not full_text:
                        full_text = stderr.decode("utf-8", errors="replace").strip()
                    yield {"type": "text_delta", "delta": full_text}
                except _asyncio.TimeoutError:
                    proc.kill()
                    yield {"type": "text_delta", "delta": "[CLI错误] 调用超时"}

        except FileNotFoundError:
            yield {"type": "text_delta", "delta": f"[CLI错误] 找不到可执行文件: {self.cli_cmd}"}
        except Exception as e:
            yield {"type": "text_delta", "delta": f"[CLI错误] {e}"}
        finally:
            if _settings_tmp:
                try:
                    _os.unlink(_settings_tmp)
                except Exception:
                    pass
        try:
            await self._save_conversation(
                messages, full_text,
                {"input_tokens": None, "output_tokens": None},
                0,
            )
        except Exception as e:
            logger.error("CLI 流式会话记录保存失败: %s", e)

        yield {"type": "stop", "stop_reason": "end_turn", "usage": {}}

    # ---- 统一接口 ----

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """异步聊天补全（自动根据 api_format 选择后端）+ 自动记录会话"""
        ctx = _ctx_label()

        if not self.is_configured:
            logger.warning("[%s] LLM 未配置，降级处理", ctx)
            response_text = self._fallback_response(messages)
            try:
                await self._save_conversation(messages, response_text, None, 0)
            except Exception as e:
                logger.error("[%s] 保存降级会话记录失败: %s", ctx, e)
            return response_text

        # 提取 prompt 摘要用于日志
        prompt_summary = ""
        for msg in messages:
            if msg["role"] == "user":
                prompt_summary = _truncate(msg["content"], 150)
                break

        logger.info(
            "🚀 [%s] LLM 请求 → %s (model=%s, temp=%.1f, max_tokens=%d)",
            ctx, self.api_format, self.model, temperature, max_tokens,
        )
        logger.info("   📝 Prompt: %s", prompt_summary)

        start_time = time.time()
        self._pending_requests += 1
        try:
            if self.api_format == "anthropic":
                response_text, usage = await self._call_anthropic(messages, temperature, max_tokens)
            elif self.api_format == "cli":
                response_text, usage = await self._call_cli(messages, temperature, max_tokens)
            else:
                response_text, usage = await self._call_openai(messages, temperature, max_tokens)
        finally:
            self._pending_requests -= 1

        duration_ms = int((time.time() - start_time) * 1000)

        # 判断是否降级
        is_fallback = response_text.startswith("[LLM_UNAVAILABLE]")

        if is_fallback:
            logger.warning(
                "⚠️  [%s] LLM 降级响应 (%dms)",
                ctx, duration_ms,
            )
        else:
            input_t = usage.get("input_tokens", "?") if usage else "?"
            output_t = usage.get("output_tokens", "?") if usage else "?"
            logger.info(
                "✅ [%s] LLM 响应 OK (%dms) tokens: %s→%s | 响应: %s",
                ctx, duration_ms, input_t, output_t,
                _truncate(response_text, 120),
            )

        # 异步记录 LLM 会话（不阻塞主流程）
        try:
            await self._save_conversation(messages, response_text, usage, duration_ms)
        except Exception as e:
            logger.error("[%s] 保存会话记录失败: %s", ctx, e)

        return response_text

    async def _save_conversation(
        self,
        messages: List[Dict[str, str]],
        response: str,
        usage: Optional[Dict],
        duration_ms: int,
    ):
        """保存 LLM 会话记录到数据库"""
        from database import db
        from utils import generate_id, now_iso

        is_fallback = response.startswith("[LLM_UNAVAILABLE]")

        conv_id = generate_id("LLM")
        data = {
            "id": conv_id,
            "ticket_id": _llm_ctx.ticket_id,
            "requirement_id": _llm_ctx.requirement_id,
            "project_id": _llm_ctx.project_id,
            "agent_type": _llm_ctx.agent_type,
            "action": _llm_ctx.action,
            "messages": json.dumps(messages, ensure_ascii=False),
            "response": response,
            "model": self.model,
            "input_tokens": usage.get("input_tokens") if usage else None,
            "output_tokens": usage.get("output_tokens") if usage else None,
            "duration_ms": duration_ms,
            "cost_usd": _calc_cost_usd(
                self.model,
                usage.get("input_tokens", 0) if usage else 0,
                usage.get("output_tokens", 0) if usage else 0,
            ),
            "status": "fallback" if is_fallback else "success",
            "error": None,
            "created_at": now_iso(),
        }
        await db.insert("llm_conversations", data)

        # Session Transcript 镜像（仅 tokens / duration / status，不含完整 prompt/response）
        try:
            from session_logger import session_logger
            await session_logger.log_llm(
                requirement_id=_llm_ctx.requirement_id,
                agent=_llm_ctx.agent_type,
                action=_llm_ctx.action,
                ticket_id=_llm_ctx.ticket_id,
                model=self.model,
                input_tokens=data["input_tokens"],
                output_tokens=data["output_tokens"],
                duration_ms=data["duration_ms"],
                status=data["status"],
            )
        except Exception as e:
            logger.error("SessionLogger.log_llm 失败: %s", e)

        # === 推送到前端实时日志面板 ===
        from events import event_manager
        from utils import generate_id as _gen_id

        input_t = usage.get("input_tokens", 0) if usage else 0
        output_t = usage.get("output_tokens", 0) if usage else 0
        agent_label = _llm_ctx.agent_type or "System"
        status_emoji = "⚠️" if is_fallback else "🤖"
        # CLI 模式显示实际使用的 cli_model，API 模式显示 model
        display_model = self.cli_model if self.api_format == "cli" else self.model
        cli_note = f" via {self.cli_type}" if self.api_format == "cli" else ""
        msg = (
            f"{status_emoji} AI调用 [{display_model}{cli_note}] "
            f"{duration_ms}ms, tokens: {input_t}→{output_t}"
        )
        log_id = generate_id("LOG")
        created_at = data["created_at"]

        # CLI 模式：构造完整调用指令摘要
        cli_cmd_display = ""
        if self.api_format == "cli":
            adapter    = _CLI_ADAPTERS.get(self.cli_type, _CLI_ADAPTERS["custom"])
            cmd_prefix = self._resolve_cmd(self.cli_cmd)
            raw_args   = adapter["build_cmd"](self.cli_cmd, self.cli_model, "...")
            cmd_full   = cmd_prefix + raw_args[1:]
            use_stdin  = adapter.get("stdin", False)
            cli_cmd_display = " ".join(cmd_full) + (" < stdin" if use_stdin else "")

        detail_json = json.dumps({
            "message": msg,
            "model": display_model,
            "input_tokens": input_t,
            "output_tokens": output_t,
            "duration_ms": duration_ms,
            "llm_status": data["status"],
            **({"cli_cmd": cli_cmd_display} if cli_cmd_display else {}),
        }, ensure_ascii=False)

        log_payload = {
            "id": log_id,
            "ticket_id": _llm_ctx.ticket_id,
            "requirement_id": _llm_ctx.requirement_id,
            "agent_type": agent_label,
            "action": "llm_call",
            "from_status": None,
            "to_status": None,
            "detail": detail_json,
            "level": "info",
            "created_at": created_at,
        }

        if _llm_ctx.project_id:
            # 写入 ticket_logs 表（持久化）
            await db.insert("ticket_logs", {
                "id": log_id,
                "ticket_id": _llm_ctx.ticket_id,
                "subtask_id": None,
                "requirement_id": _llm_ctx.requirement_id,
                "project_id": _llm_ctx.project_id,
                "agent_type": agent_label,
                "action": "llm_call",
                "from_status": None,
                "to_status": None,
                "detail": detail_json,
                "level": "info",
                "created_at": created_at,
            })
            # 推送到项目频道
            await event_manager.publish_to_project(
                _llm_ctx.project_id, "log_added", {**log_payload, "project_id": _llm_ctx.project_id},
            )
        else:
            # 无项目上下文（全局 AI 助手）→ 推送到 global 频道
            await event_manager.publish("global", "log_added", log_payload)


    async def _save_tools_conversation(
        self,
        messages: List[Dict[str, Any]],
        input_tokens: int,
        output_tokens: int,
        duration_ms: int,
    ):
        """保存 chat_with_tools 的汇总调用记录（一次对话多轮合并为一条）"""
        try:
            from database import db
            from utils import generate_id, now_iso
            import json as _json
            # 只取最后一条 assistant 回复作为 response 摘要
            last_assistant = next(
                (m for m in reversed(messages) if m.get("role") == "assistant"), None
            )
            response_text = ""
            if last_assistant:
                c = last_assistant.get("content", "")
                if isinstance(c, str):
                    response_text = c
                elif isinstance(c, list):
                    parts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
                    response_text = " ".join(parts)

            await db.insert("llm_conversations", {
                "id": generate_id("LLM"),
                "ticket_id": _llm_ctx.ticket_id,
                "requirement_id": _llm_ctx.requirement_id,
                "project_id": _llm_ctx.project_id,
                "agent_type": _llm_ctx.agent_type,
                "action": _llm_ctx.action,
                "messages": _json.dumps(messages[-4:], ensure_ascii=False),  # 只存最后4条节省空间
                "response": response_text[:2000],
                "model": self.model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "duration_ms": duration_ms,
                "cost_usd": _calc_cost_usd(self.model, input_tokens, output_tokens),
                "status": "success",
                "error": None,
                "created_at": now_iso(),
            })
        except Exception as e:
            logger.warning("[tool-use] 保存会话记录失败: %s", e)

    async def generate(self, prompt: str, **kwargs) -> str:
        """简便方法：单次生成"""
        messages = [{"role": "user", "content": prompt}]
        return await self.chat(messages, **kwargs)

    async def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 16000,
    ) -> Any:
        """聊天并解析 JSON 响应"""
        ctx = _ctx_label()

        # 添加 JSON 格式要求
        system_msg = {
            "role": "system",
            "content": "请以纯 JSON 格式回复，不要包含 markdown 代码块标记。",
        }
        all_messages = [system_msg] + messages

        response = await self.chat(all_messages, temperature=temperature, max_tokens=max_tokens)

        # 清洗并解析 JSON
        cleaned = response.strip()
        if cleaned.startswith("```"):
            # 去掉 markdown 代码块
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)

        try:
            result = json.loads(cleaned)
            logger.info("   📦 [%s] JSON 解析成功 (keys: %s)", ctx,
                        list(result.keys()) if isinstance(result, dict) else f"list[{len(result)}]")
            return result
        except json.JSONDecodeError:
            # 尝试找到 JSON 部分
            start = cleaned.find("[") if "[" in cleaned else cleaned.find("{")
            end = cleaned.rfind("]") + 1 if "]" in cleaned else cleaned.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    result = json.loads(cleaned[start:end])
                    logger.info("   📦 [%s] JSON 二次解析成功 (从位置 %d 提取)", ctx, start)
                    return result
                except json.JSONDecodeError:
                    pass
            logger.error("   ❌ [%s] JSON 解析失败! 原始响应: %s", ctx, _truncate(cleaned, 300))
            return None

    # ==================== Tool Use / Agentic Loop ====================

    async def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        tool_executor,          # SkillExecutor 实例，需实现 async execute(name, input) -> str
        max_rounds: int = 10,
        temperature: float = 0.3,
        max_tokens: int = 16000,
        system: str = "",
    ) -> Dict[str, Any]:
        """
        带工具的 ReAct 循环。
        - tools: Anthropic 格式的 tool schema 列表
        - tool_executor: 实现 execute(tool_name, tool_input) -> str 的对象
        - 返回 {"messages": [...], "rounds": n, "finished": bool}
        """
        ctx = _ctx_label()

        if not self.is_configured:
            logger.warning("[%s] LLM 未配置，跳过 tool use", ctx)
            return {"messages": messages, "rounds": 0, "finished": False}

        # CLI 模式不支持原生 tool_use block，降级为纯文本 chat（依赖 [ACTION:xxx] 文本协议）
        if self.api_format == "cli":
            logger.warning("[%s] CLI 模式不支持 tool use，降级为文本协议", ctx)
            if system:
                all_messages = [{"role": "system", "content": system}] + list(messages)
            else:
                all_messages = list(messages)
            response = await self.chat(all_messages, temperature=temperature, max_tokens=max_tokens)
            final_messages = list(messages) + [{"role": "assistant", "content": response}]
            return {"messages": final_messages, "rounds": 1, "finished": True, "cli_fallback": True}

        history = list(messages)  # 不修改原始列表
        _total_input_tokens = 0
        _total_output_tokens = 0
        _t0 = time.time()

        for round_no in range(max_rounds):
            logger.info("🔄 [%s] Tool-use 第 %d 轮", ctx, round_no + 1)

            if self.api_format == "anthropic":
                response = await self._call_anthropic_tools(
                    history, tools, system, temperature, max_tokens
                )
            else:
                response = await self._call_openai_tools(
                    history, tools, system, temperature, max_tokens
                )

            if response is None:
                logger.error("[%s] Tool-use 第 %d 轮 LLM 调用失败", ctx, round_no + 1)
                break

            # 累计 token 消耗
            _usage = response.get("usage", {})
            _total_input_tokens  += _usage.get("input_tokens", 0) or 0
            _total_output_tokens += _usage.get("output_tokens", 0) or 0

            stop_reason = response.get("stop_reason") or response.get("finish_reason", "")
            content = response.get("content", [])

            # Sanitize：LLM 偶尔在 tool_use block 里给出 input=[] 而非 {}，
            # 原样塞回 history 会让下一轮 Anthropic 返回 400（schema 要求 object）。
            # 在追加历史前兜底修正。
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    if not isinstance(b.get("input"), dict):
                        logger.warning(
                            "[%s] tool_use.input 非 dict（%s），归一化为 {}",
                            ctx, type(b.get("input")).__name__,
                        )
                        b["input"] = {}

            # 把本轮 assistant 回复加入历史
            history.append({"role": "assistant", "content": content})

            # 检查是否需要调用工具
            tool_calls = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
            if not tool_calls:
                # 没有 tool_use block —— 模型直接给出最终回复
                logger.info("✅ [%s] Tool-use 完成（无工具调用），%d 轮", ctx, round_no + 1)
                await self._save_tools_conversation(history, _total_input_tokens, _total_output_tokens, int((time.time()-_t0)*1000))
                return {"messages": history, "rounds": round_no + 1, "finished": True}

            # 执行所有工具调用，收集结果
            tool_results = []
            should_finish = False
            for block in tool_calls:
                tool_name = block.get("name", "")
                tool_input = block.get("input", {})
                tool_use_id = block.get("id", f"tu_{round_no}")

                logger.info("🔧 [%s] 调用工具: %s, 参数: %s", ctx, tool_name,
                            str(tool_input)[:200])

                result_text = await tool_executor.execute(tool_name, tool_input)
                logger.info("   └─ 结果: %s", result_text[:200])

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": result_text,
                })

                if tool_name == "finish":
                    should_finish = True

            # 工具结果作为 user 消息追加
            history.append({"role": "user", "content": tool_results})

            if should_finish:
                logger.info("✅ [%s] finish 工具调用，结束循环", ctx)
                await self._save_tools_conversation(history, _total_input_tokens, _total_output_tokens, int((time.time()-_t0)*1000))
                return {"messages": history, "rounds": round_no + 1, "finished": True}

        logger.warning("[%s] Tool-use 达到最大轮数 %d，强制结束", ctx, max_rounds)
        await self._save_tools_conversation(history, _total_input_tokens, _total_output_tokens, int((time.time()-_t0)*1000))
        return {"messages": history, "rounds": max_rounds, "finished": False}

    async def _call_anthropic_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> Optional[Dict[str, Any]]:
        """Anthropic tool use 调用，返回原始 API response dict"""
        url = f"{self.base_url}/v1/messages"

        # 过滤 system 消息到 system 字段
        sys_parts = [system] if system else []
        user_messages = []
        for msg in messages:
            if msg["role"] == "system":
                c = msg["content"]
                sys_parts.append(c if isinstance(c, str) else str(c))
            else:
                user_messages.append(msg)

        if not user_messages:
            user_messages = [{"role": "user", "content": "请开始工作。"}]

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": user_messages,
            "max_tokens": max_tokens,
            "tools": tools,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if sys_parts:
            _sys_text = "\n".join(sys_parts).strip()
            _CACHE_MARKER = "<!--CACHE_BOUNDARY-->"
            if _CACHE_MARKER in _sys_text:
                _stable, _dynamic = _sys_text.split(_CACHE_MARKER, 1)
                payload["system"] = [
                    {"type": "text", "text": _stable.strip(),
                     "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": _dynamic.strip()},
                ]
            else:
                payload["system"] = _sys_text

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    url, headers=self._anthropic_headers(), json=payload
                )
                resp.raise_for_status()
                data = resp.json()
                usage = data.get("usage", {})
                return {
                    "stop_reason": data.get("stop_reason", ""),
                    "content": data.get("content", []),
                    "usage": usage,
                }
        except Exception as e:
            logger.error("Anthropic tool-use 调用失败: %s", e)
            return None

    async def _call_anthropic_tools_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        system: str,
        temperature: float,
        max_tokens: int,
        enable_thinking: bool = False,   # J-3 Extended Thinking
        thinking_budget: int = 8000,     # thinking token 预算（API 要求 >= 1024）
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式 Anthropic tool_use 调用。
        yield 事件：
          {"type": "text_delta",    "delta": "..."}
          {"type": "tool_use_block","id": "...", "name": "...", "input": {...}}
          {"type": "stop",          "stop_reason": "end_turn"|"tool_use", "usage": {...}}
          {"type": "error",         "message": "..."}
        """
        url = f"{self.base_url}/v1/messages"

        sys_parts = [system] if system else []
        user_messages = []
        for msg in messages:
            if msg["role"] == "system":
                c = msg["content"]
                sys_parts.append(c if isinstance(c, str) else str(c))
            else:
                user_messages.append(msg)
        if not user_messages:
            user_messages = [{"role": "user", "content": "请开始工作。"}]

        # J-3: Extended Thinking — 开启时不能传 temperature（API 限制）
        use_thinking = enable_thinking and _model_supports_thinking(self.model)
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": user_messages,
            "max_tokens": max_tokens + (thinking_budget if use_thinking else 0),
            "tools": tools,
            "stream": True,
        }
        if use_thinking:
            payload["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
            # thinking 模式不支持 temperature 参数
        elif temperature is not None:
            payload["temperature"] = temperature
        if sys_parts:
            system_text = "\n".join(sys_parts).strip()
            # Prompt Cache：若 system 含 <!--CACHE_BOUNDARY-->，分成两块
            # 稳定部分（Rules + 项目基本信息 + Skills + 能力描述）加 cache_control
            # 动态部分（知识库 / 需求 / 工单 / 文件树）不缓存
            _CACHE_MARKER = "<!--CACHE_BOUNDARY-->"
            if _CACHE_MARKER in system_text:
                stable, dynamic = system_text.split(_CACHE_MARKER, 1)
                payload["system"] = [
                    {"type": "text", "text": stable.strip(),
                     "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": dynamic.strip()},
                ]
            else:
                payload["system"] = system_text

        # 用于拼装 tool_use block 的 input JSON（流式时分片传来）
        _blocks: Dict[int, Dict] = {}  # index -> block
        _input_buf: Dict[int, str] = {}  # index -> partial json string
        _stop_reason = "end_turn"
        _usage: Dict = {}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST", url, headers=self._anthropic_headers(), json=payload
                ) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        yield {"type": "error", "message": f"HTTP {resp.status_code}: {body[:200]}"}
                        return

                    async for raw_line in resp.aiter_lines():
                        if not raw_line.startswith("data: "):
                            continue
                        data_str = raw_line[6:].strip()
                        if not data_str or data_str == "[DONE]":
                            continue
                        try:
                            ev = json.loads(data_str)
                        except Exception:
                            continue

                        etype = ev.get("type", "")

                        if etype == "content_block_start":
                            idx = ev["index"]
                            blk = ev.get("content_block", {})
                            _blocks[idx] = dict(blk)
                            if blk.get("type") == "tool_use":
                                _input_buf[idx] = ""
                            elif blk.get("type") == "thinking":
                                _input_buf[idx] = ""  # 用同一个 buf 收集 thinking 文本

                        elif etype == "content_block_delta":
                            idx = ev["index"]
                            delta = ev.get("delta", {})
                            dtype = delta.get("type", "")
                            if dtype == "text_delta":
                                yield {"type": "text_delta", "delta": delta.get("text", "")}
                            elif dtype == "input_json_delta":
                                _input_buf[idx] = _input_buf.get(idx, "") + delta.get("partial_json", "")
                            elif dtype == "thinking_delta":
                                # J-3: 流式推理文本，实时 yield（前端可选接收）
                                thinking_chunk = delta.get("thinking", "")
                                _input_buf[idx] = _input_buf.get(idx, "") + thinking_chunk
                                if thinking_chunk:
                                    yield {"type": "thinking_delta", "delta": thinking_chunk}

                        elif etype == "content_block_stop":
                            idx = ev["index"]
                            blk = _blocks.get(idx, {})
                            if blk.get("type") == "tool_use":
                                try:
                                    parsed_input = json.loads(_input_buf.get(idx, "{}") or "{}")
                                except Exception:
                                    parsed_input = {}
                                if not isinstance(parsed_input, dict):
                                    parsed_input = {}
                                yield {
                                    "type": "tool_use_block",
                                    "id": blk.get("id", f"tu_{idx}"),
                                    "name": blk.get("name", ""),
                                    "input": parsed_input,
                                }
                            elif blk.get("type") == "thinking":
                                # J-3: thinking block 完成，发送完整推理文本
                                thinking_text = _input_buf.get(idx, "")
                                if thinking_text:
                                    yield {"type": "thinking_done", "text": thinking_text}

                        elif etype == "message_delta":
                            _stop_reason = ev.get("delta", {}).get("stop_reason", "end_turn") or "end_turn"
                            _usage = ev.get("usage", {})

                        elif etype == "message_stop":
                            yield {"type": "stop", "stop_reason": _stop_reason, "usage": _usage}

        except Exception as e:
            logger.error("Anthropic 流式 tool-use 异常: %s", e)
            yield {"type": "error", "message": str(e)}

    async def chat_with_tools_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        tool_executor,
        max_rounds: int = 10,
        temperature: float = 0.3,
        max_tokens: int = 16000,
        system: str = "",
        budget=None,   # Optional[query_engine.Budget]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        带工具的 ReAct 流式循环。
        yield 事件（前端直接消费）：
          text_delta / tool_start / tool_done / action / error / round_done / message_done
          budget_exceeded（预算超限时）
        """
        ctx = _ctx_label()

        if not self.is_configured:
            yield {"type": "text_delta", "delta": "[LLM 未配置，无法回复]"}
            yield {"type": "message_done", "rounds": 0}
            return

        # CLI 模式不支持流式 tool use，降级为非流式文本 chat 并逐字符 yield
        if self.api_format == "cli":
            logger.warning("[%s] CLI 模式不支持流式 tool use，降级为文本协议", ctx)
            if system:
                all_messages = [{"role": "system", "content": system}] + list(messages)
            else:
                all_messages = list(messages)
            response = await self.chat(all_messages, temperature=temperature, max_tokens=max_tokens)
            yield {"type": "text_delta", "delta": response}
            yield {"type": "message_done", "rounds": 1, "cli_fallback": True}
            return


        _total_input = 0
        _total_output = 0
        _t0 = time.time()

        for round_no in range(max_rounds):
            # 预算检查（每轮开始前）
            if budget is not None:
                if reason := budget.check():
                    logger.warning("[%s] 预算超限，中断流式循环: %s", ctx, reason)
                    yield {"type": "budget_exceeded", "reason": reason}
                    yield {"type": "message_done", "rounds": round_no}
                    return
            logger.info("🔄 [%s] 流式 Tool-use 第 %d 轮", ctx, round_no + 1)

            current_text = ""
            tool_use_blocks: List[Dict] = []
            stop_reason = "end_turn"

            async for ev in self._call_anthropic_tools_stream(
                history, tools, system, temperature, max_tokens
            ):
                etype = ev["type"]

                if etype == "text_delta":
                    current_text += ev["delta"]
                    yield ev  # 直接透传给前端

                elif etype == "tool_use_block":
                    tool_use_blocks.append(ev)

                elif etype == "stop":
                    stop_reason = ev.get("stop_reason", "end_turn")
                    usage = ev.get("usage", {})
                    round_input  = usage.get("input_tokens",  0) or 0
                    round_output = usage.get("output_tokens", 0) or 0
                    _total_input  += round_input
                    _total_output += round_output
                    # 消耗预算（Token + 1 轮）
                    if budget is not None:
                        budget.consume(tokens=round_input + round_output, turns=1)

                elif etype == "error":
                    yield ev
                    return

            # 把 assistant 回复存入历史（重建 content blocks 格式）
            assistant_content: List[Dict] = []
            if current_text:
                assistant_content.append({"type": "text", "text": current_text})
            for tb in tool_use_blocks:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tb["id"],
                    "name": tb["name"],
                    "input": tb["input"],
                })
            history.append({"role": "assistant", "content": assistant_content})

            # 没有工具调用 → 对话结束
            if stop_reason != "tool_use" or not tool_use_blocks:
                logger.info("✅ [%s] 流式 Tool-use 完成（%d 轮）", ctx, round_no + 1)
                await self._save_tools_conversation(
                    history, _total_input, _total_output, int((time.time() - _t0) * 1000)
                )
                yield {"type": "message_done", "rounds": round_no + 1}
                return

            # 执行工具，推 tool_start / tool_done 事件
            tool_results = []
            for tb in tool_use_blocks:
                tool_name = tb["name"]
                tool_input = tb["input"]
                tool_use_id = tb["id"]

                logger.info("🔧 [%s] 流式调用工具: %s", ctx, tool_name)
                yield {"type": "tool_start", "tool": tool_name, "tool_use_id": tool_use_id,
                       "input": {k: str(v)[:80] for k, v in (tool_input or {}).items()}}

                result_text = await tool_executor.execute(tool_name, tool_input)

                # 从 executor 取最新的 summary（tool_done 已推送过了，这里同步 yield）
                summary = ""
                if tool_executor.thinking_steps:
                    summary = tool_executor.thinking_steps[-1].get("summary", "")
                yield {"type": "tool_done", "tool": tool_name, "summary": summary}

                # 检查是否有 action 卡片需要推
                current_action = tool_executor.primary_action_result
                if current_action and current_action.get("type") not in ("error",):
                    yield {"type": "action", **current_action}

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": result_text,
                })

                if tool_name == "finish":
                    history.append({"role": "user", "content": tool_results})
                    await self._save_tools_conversation(
                        history, _total_input, _total_output, int((time.time() - _t0) * 1000)
                    )
                    yield {"type": "message_done", "rounds": round_no + 1}
                    return

            history.append({"role": "user", "content": tool_results})

        logger.warning("[%s] 流式 Tool-use 达到最大轮数 %d", ctx, max_rounds)
        await self._save_tools_conversation(
            history, _total_input, _total_output, int((time.time() - _t0) * 1000)
        )
        yield {"type": "message_done", "rounds": max_rounds}

    async def _call_openai_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> Optional[Dict[str, Any]]:
        """OpenAI function calling，将结果转换为 Anthropic 格式的 content blocks"""
        from agents.skills import schemas_to_openai_tools

        url = f"{self.base_url}/chat/completions"

        oai_messages = []
        if system:
            oai_messages.append({"role": "system", "content": system})

        # 将 Anthropic-style history 转回 OpenAI-style
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if role == "system":
                oai_messages.append({"role": "system", "content": content if isinstance(content, str) else str(content)})
            elif role == "assistant":
                if isinstance(content, list):
                    # content blocks → tool_calls / text
                    text_parts = []
                    tool_calls_oai = []
                    for block in content:
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_use":
                            tool_calls_oai.append({
                                "id": block.get("id", ""),
                                "type": "function",
                                "function": {
                                    "name": block.get("name", ""),
                                    "arguments": json.dumps(block.get("input", {})),
                                },
                            })
                    oai_msg: Dict[str, Any] = {"role": "assistant", "content": " ".join(text_parts) or None}
                    if tool_calls_oai:
                        oai_msg["tool_calls"] = tool_calls_oai
                    oai_messages.append(oai_msg)
                else:
                    oai_messages.append({"role": "assistant", "content": content})
            elif role == "user":
                if isinstance(content, list):
                    # tool_result blocks
                    for block in content:
                        if block.get("type") == "tool_result":
                            oai_messages.append({
                                "role": "tool",
                                "tool_call_id": block.get("tool_use_id", ""),
                                "content": block.get("content", ""),
                            })
                else:
                    oai_messages.append({"role": "user", "content": content})

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": oai_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "tools": schemas_to_openai_tools(tools),
            "tool_choice": "auto",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    url, headers=self._openai_headers(), json=payload
                )
                resp.raise_for_status()
                data = resp.json()

            choice = data["choices"][0]
            oai_msg = choice["message"]
            finish_reason = choice.get("finish_reason", "")

            # 转换为 Anthropic content blocks 格式（统一内部表示）
            content_blocks: List[Dict[str, Any]] = []
            if oai_msg.get("content"):
                content_blocks.append({"type": "text", "text": oai_msg["content"]})
            for tc in (oai_msg.get("tool_calls") or []):
                fn = tc.get("function", {})
                try:
                    inp = json.loads(fn.get("arguments", "{}"))
                except Exception:
                    inp = {}
                content_blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": fn.get("name", ""),
                    "input": inp,
                })

            stop_reason = "tool_use" if oai_msg.get("tool_calls") else "end_turn"
            return {"stop_reason": stop_reason, "content": content_blocks}
        except Exception as e:
            logger.error("OpenAI tool-use 调用失败: %s", e)
            return None

    async def test_connection(self) -> Dict[str, Any]:
        """测试 LLM 连接"""
        if not self.is_configured:
            return {"status": "not_configured", "message": "LLM 未配置"}

        # CLI 模式：检查可执行文件是否存在，并尝试 --version
        if self.api_format == "cli":
            import shutil, asyncio as _asyncio
            resolved = shutil.which(self.cli_cmd)
            if not resolved:
                return {"status": "error", "message": f"找不到 CLI 工具: {self.cli_cmd}（请确认已安装并在 PATH 中）"}
            try:
                # Windows 下 .cmd/.bat 需要 cmd /c 包装
                cmd_prefix = self._resolve_cmd(self.cli_cmd)
                version_cmd = cmd_prefix + ["--version"]
                proc = await _asyncio.create_subprocess_exec(
                    *version_cmd,
                    stdout=_asyncio.subprocess.PIPE,
                    stderr=_asyncio.subprocess.PIPE,
                )
                stdout, stderr = await _asyncio.wait_for(proc.communicate(), timeout=10)
                version_str = (stdout or stderr).decode("utf-8", errors="replace").strip()[:100]
                logger.info("🖥️  CLI 连接测试通过: %s", version_str)
                return {
                    "status": "ok",
                    "message": f"CLI 就绪 (type={self.cli_type})",
                    "response": version_str,
                }
            except _asyncio.TimeoutError:
                return {"status": "error", "message": f"CLI --version 超时: {self.cli_cmd}"}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        try:
            logger.info("🔗 测试 LLM 连接: %s (%s)", self.base_url, self.api_format)
            result = await self.generate("Hello, respond with 'ok'.")
            if result.startswith("[LLM_UNAVAILABLE]"):
                logger.warning("🔗 LLM 连接测试失败：调用已降级（详见上方错误日志）")
                return {
                    "status": "error",
                    "message": "LLM 调用失败（已降级到规则引擎）。常见原因：模型名 / API Key / 网络不可达。详见后端日志。",
                }
            logger.info("🔗 LLM 连接测试通过")
            return {
                "status": "ok",
                "message": f"连接正常 (format={self.api_format})",
                "response": result[:100],
            }
        except Exception as e:
            logger.error("🔗 LLM 连接测试失败: %s", e)
            return {"status": "error", "message": str(e)}

    def _fallback_response(self, messages: List[Dict[str, str]]) -> str:
        """LLM 不可用时的降级响应"""
        if not self.is_configured:
            logger.warning("LLM 未配置（缺少 LLM_BASE_URL 或 LLM_API_KEY），使用规则引擎降级。请配置 .env 文件。")
        else:
            logger.warning("LLM 调用失败，使用规则引擎降级。")
        return "[LLM_UNAVAILABLE] LLM 服务不可用，使用规则引擎降级处理。"


# 全局 LLM 客户端
llm_client = LLMClient()
