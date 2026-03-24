"""
AI 自动开发系统 - LLM 客户端
支持 Anthropic Messages API（原生）和 OpenAI 兼容 API
通过 LLM_API_FORMAT 环境变量切换：anthropic / openai（默认 anthropic）
"""
import json
import time
import httpx
from typing import Any, Dict, List, Optional
from config import settings


# ==================== LLM 会话记录上下文 ====================

class _LLMContext:
    """线程局部变量：记录当前 LLM 调用的关联信息"""
    ticket_id: Optional[str] = None
    requirement_id: Optional[str] = None
    project_id: Optional[str] = None
    agent_type: Optional[str] = None
    action: Optional[str] = None

_llm_ctx = _LLMContext()


def set_llm_context(
    ticket_id: str = None,
    requirement_id: str = None,
    project_id: str = None,
    agent_type: str = None,
    action: str = None,
):
    """设置 LLM 调用上下文（在 Agent 执行前调用）"""
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
                system_text += msg["content"] + "\n"
            else:
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
                    print(f"[LLM] Anthropic 调用失败 (attempt {attempt+1}): {e}")
                    return self._fallback_response(messages), None
                print(f"[LLM] Anthropic 调用重试 {attempt+1}/{self.max_retries}: {e}")

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
                    print(f"[LLM] OpenAI 调用失败: {e}")
                    return self._fallback_response(messages), None

        return self._fallback_response(messages), None

    # ---- 统一接口 ----

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """异步聊天补全（自动根据 api_format 选择后端）+ 自动记录会话"""
        if not self.is_configured:
            response_text = self._fallback_response(messages)
            # 即使降级也记录会话，方便 AI 对话 Tab 追溯
            try:
                await self._save_conversation(messages, response_text, None, 0)
            except Exception as e:
                print(f"[LLM] 保存降级会话记录失败: {e}")
            return response_text

        start_time = time.time()

        if self.api_format == "anthropic":
            response_text, usage = await self._call_anthropic(messages, temperature, max_tokens)
        else:
            response_text, usage = await self._call_openai(messages, temperature, max_tokens)

        duration_ms = int((time.time() - start_time) * 1000)

        # 异步记录 LLM 会话（不阻塞主流程）
        try:
            await self._save_conversation(messages, response_text, usage, duration_ms)
        except Exception as e:
            print(f"[LLM] 保存会话记录失败: {e}")

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

    async def generate(self, prompt: str, **kwargs) -> str:
        """简便方法：单次生成"""
        messages = [{"role": "user", "content": prompt}]
        return await self.chat(messages, **kwargs)

    async def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
    ) -> Any:
        """聊天并解析 JSON 响应"""
        # 添加 JSON 格式要求
        system_msg = {
            "role": "system",
            "content": "请以纯 JSON 格式回复，不要包含 markdown 代码块标记。",
        }
        all_messages = [system_msg] + messages

        response = await self.chat(all_messages, temperature=temperature)

        # 清洗并解析 JSON
        cleaned = response.strip()
        if cleaned.startswith("```"):
            # 去掉 markdown 代码块
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # 尝试找到 JSON 部分
            start = cleaned.find("[") if "[" in cleaned else cleaned.find("{")
            end = cleaned.rfind("]") + 1 if "]" in cleaned else cleaned.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(cleaned[start:end])
                except json.JSONDecodeError:
                    pass
            return None

    async def test_connection(self) -> Dict[str, Any]:
        """测试 LLM 连接"""
        if not self.is_configured:
            return {"status": "not_configured", "message": "LLM 未配置"}

        try:
            result = await self.generate("Hello, respond with 'ok'.")
            return {
                "status": "ok",
                "message": f"连接正常 (format={self.api_format})",
                "response": result[:100],
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _fallback_response(self, messages: List[Dict[str, str]]) -> str:
        """LLM 不可用时的降级响应"""
        if not self.is_configured:
            print("[LLM] WARNING: LLM 未配置（缺少 LLM_BASE_URL 或 LLM_API_KEY），使用规则引擎降级。请配置 .env 文件。")
        else:
            print("[LLM] WARNING: LLM 调用失败，使用规则引擎降级。")
        return "[LLM_UNAVAILABLE] LLM 服务不可用，使用规则引擎降级处理。"


# 全局 LLM 客户端
llm_client = LLMClient()
