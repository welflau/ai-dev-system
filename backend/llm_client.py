"""
AI 自动开发系统 - LLM 客户端
支持 Anthropic Messages API（原生）和 OpenAI 兼容 API
通过 LLM_API_FORMAT 环境变量切换：anthropic / openai（默认 anthropic）
"""
import json
import logging
import time
import httpx
from typing import Any, Dict, List, Optional
from config import settings

logger = logging.getLogger("llm")


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


class LLMClient:
    """LLM 客户端 — 支持 Anthropic Messages API 和 OpenAI 兼容 API"""

    def __init__(self):
        self.base_url = settings.LLM_BASE_URL.rstrip("/")
        self.api_key = settings.LLM_API_KEY
        self.model = settings.LLM_MODEL
        self.timeout = settings.LLM_TIMEOUT
        self.max_retries = settings.LLM_MAX_RETRIES
        self.api_format = settings.LLM_API_FORMAT  # "anthropic" or "openai"

    @property
    def is_configured(self) -> bool:
        """是否已配置 LLM"""
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

        if self.api_format == "anthropic":
            response_text, usage = await self._call_anthropic(messages, temperature, max_tokens)
        else:
            response_text, usage = await self._call_openai(messages, temperature, max_tokens)

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
            "status": "fallback" if is_fallback else "success",
            "error": None,
            "created_at": now_iso(),
        }
        await db.insert("llm_conversations", data)

        # === 推送到前端实时日志面板 ===
        if _llm_ctx.project_id:
            from events import event_manager

            input_t = usage.get("input_tokens", 0) if usage else 0
            output_t = usage.get("output_tokens", 0) if usage else 0
            agent_label = _llm_ctx.agent_type or "System"
            action_label = _llm_ctx.action or "chat"
            status_emoji = "⚠️" if is_fallback else "🤖"
            msg = (
                f"{status_emoji} AI调用 [{self.model}] "
                f"{duration_ms}ms, tokens: {input_t}→{output_t}"
            )

            log_id = generate_id("LOG")
            created_at = data["created_at"]
            detail_json = json.dumps({
                "message": msg,
                "model": self.model,
                "input_tokens": input_t,
                "output_tokens": output_t,
                "duration_ms": duration_ms,
                "llm_status": data["status"],
            }, ensure_ascii=False)

            # 写入 ticket_logs 表（持久化，历史可查）
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

            # SSE 实时推送
            await event_manager.publish_to_project(
                _llm_ctx.project_id, "log_added", {
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
                },
            )

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

    async def test_connection(self) -> Dict[str, Any]:
        """测试 LLM 连接"""
        if not self.is_configured:
            return {"status": "not_configured", "message": "LLM 未配置"}

        try:
            logger.info("🔗 测试 LLM 连接: %s (%s)", self.base_url, self.api_format)
            result = await self.generate("Hello, respond with 'ok'.")
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
