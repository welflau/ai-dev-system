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


class LLMClient:
    """LLM 客户端 — 支持 Anthropic Messages API 和 OpenAI 兼容 API"""

    def __init__(self):
        self.base_url = settings.LLM_BASE_URL.rstrip("/")
        self.api_key = settings.LLM_API_KEY
        self.model = settings.LLM_MODEL
        self.timeout = settings.LLM_TIMEOUT
        self.max_retries = settings.LLM_MAX_RETRIES
        self.api_format = settings.LLM_API_FORMAT  # "anthropic" or "openai"
        self._pending_requests: int = 0   # 当前在途 LLM 请求数（供 /api/metrics 读取）

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
        self._pending_requests += 1
        try:
            if self.api_format == "anthropic":
                response_text, usage = await self._call_anthropic(messages, temperature, max_tokens)
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
        thinking_budget: int = 8000,     # thinking token 预算
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

        history = list(messages)
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
