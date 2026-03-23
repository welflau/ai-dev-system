"""
LLM 客户端 - OpenAI 兼容接口
支持任意 OpenAI-compatible API（CodeBuddy / OpenAI / DeepSeek / Moonshot 等）
"""
import os
import json
import logging
import httpx
from typing import Dict, Any, List, Optional, AsyncGenerator, Generator

logger = logging.getLogger(__name__)


class LLMClient:
    """
    通用 LLM 客户端

    通过环境变量配置：
        LLM_BASE_URL  - API 基础地址（默认 https://api.openai.com/v1）
        LLM_API_KEY   - API 密钥
        LLM_MODEL     - 模型名称（默认 gpt-4）
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 120.0,
        max_retries: int = 2,
    ):
        self.base_url = (
            base_url
            or os.getenv("LLM_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        ).rstrip("/")

        self.api_key = (
            api_key
            or os.getenv("LLM_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or ""
        )

        self.model = (
            model
            or os.getenv("LLM_MODEL")
            or "gpt-4"
        )

        self.timeout = timeout
        self.max_retries = max_retries
        self._enabled = bool(self.api_key)

        if not self._enabled:
            logger.warning(
                "LLM 未配置 API Key，将使用降级模式（模板/规则引擎）。"
                "设置 LLM_API_KEY 环境变量以启用 LLM 功能。"
            )

    # ------------------------------------------------------------------
    #  核心属性
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """LLM 是否已配置且可用"""
        return self._enabled

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @property
    def chat_url(self) -> str:
        return f"{self.base_url}/chat/completions"

    # ------------------------------------------------------------------
    #  同步接口
    # ------------------------------------------------------------------

    def generate(self, prompt: str, **kwargs) -> str:
        """
        简单文本生成（同步）

        Args:
            prompt: 用户提示词
            **kwargs: 额外参数（temperature, max_tokens 等）

        Returns:
            LLM 生成的文本
        """
        messages = [{"role": "user", "content": prompt}]
        return self.chat(messages, **kwargs)

    def chat(
        self,
        messages: List[Dict[str, str]],
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: Optional[List[Dict]] = None,
        **kwargs,
    ) -> str:
        """
        聊天补全（同步）

        Args:
            messages: 对话消息列表
            system: 系统提示词（可选，会自动插入为第一条消息）
            temperature: 温度
            max_tokens: 最大 token 数
            tools: Function Calling 工具定义
            **kwargs: 其他 OpenAI 兼容参数

        Returns:
            助手回复文本
        """
        if not self._enabled:
            return self._fallback_response(messages)

        full_messages = self._build_messages(messages, system)
        payload = self._build_payload(
            full_messages, temperature, max_tokens, tools, stream=False, **kwargs
        )

        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(
                        self.chat_url,
                        headers=self.headers,
                        json=payload,
                    )
                    resp.raise_for_status()
                    data = resp.json()

                choice = data["choices"][0]
                message = choice["message"]

                # Function Calling 场景返回完整 message JSON
                if message.get("tool_calls"):
                    return json.dumps(message, ensure_ascii=False)

                return message.get("content", "")

            except httpx.HTTPStatusError as e:
                logger.error(
                    f"LLM API HTTP 错误 (attempt {attempt+1}): "
                    f"{e.response.status_code} - {e.response.text[:500]}"
                )
                if attempt == self.max_retries:
                    return self._fallback_response(messages)

            except Exception as e:
                logger.error(f"LLM API 调用异常 (attempt {attempt+1}): {e}")
                if attempt == self.max_retries:
                    return self._fallback_response(messages)

        return self._fallback_response(messages)

    def chat_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict],
        system: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        带 Function Calling 的聊天（同步）

        Returns:
            完整的 choice.message 对象（含 tool_calls）
        """
        if not self._enabled:
            return {"role": "assistant", "content": self._fallback_response(messages)}

        full_messages = self._build_messages(messages, system)
        payload = self._build_payload(
            full_messages, tools=tools, stream=False, **kwargs
        )

        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(
                        self.chat_url,
                        headers=self.headers,
                        json=payload,
                    )
                    resp.raise_for_status()
                    data = resp.json()

                return data["choices"][0]["message"]

            except Exception as e:
                logger.error(f"LLM Tool Call 异常 (attempt {attempt+1}): {e}")
                if attempt == self.max_retries:
                    return {
                        "role": "assistant",
                        "content": self._fallback_response(messages),
                    }

        return {"role": "assistant", "content": self._fallback_response(messages)}

    # ------------------------------------------------------------------
    #  流式接口
    # ------------------------------------------------------------------

    def stream(
        self,
        messages: List[Dict[str, str]],
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ) -> Generator[str, None, None]:
        """
        流式聊天补全（同步 Generator）

        Yields:
            每个增量文本片段
        """
        if not self._enabled:
            yield self._fallback_response(messages)
            return

        full_messages = self._build_messages(messages, system)
        payload = self._build_payload(
            full_messages, temperature, max_tokens, stream=True, **kwargs
        )

        try:
            with httpx.Client(timeout=self.timeout) as client:
                with client.stream(
                    "POST",
                    self.chat_url,
                    headers=self.headers,
                    json=payload,
                ) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        chunk = self._parse_sse_line(line)
                        if chunk is not None:
                            yield chunk
        except Exception as e:
            logger.error(f"LLM 流式调用异常: {e}")
            yield self._fallback_response(messages)

    # ------------------------------------------------------------------
    #  异步接口
    # ------------------------------------------------------------------

    async def agenerate(self, prompt: str, **kwargs) -> str:
        """异步文本生成"""
        messages = [{"role": "user", "content": prompt}]
        return await self.achat(messages, **kwargs)

    async def achat(
        self,
        messages: List[Dict[str, str]],
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: Optional[List[Dict]] = None,
        **kwargs,
    ) -> str:
        """异步聊天补全"""
        if not self._enabled:
            return self._fallback_response(messages)

        full_messages = self._build_messages(messages, system)
        payload = self._build_payload(
            full_messages, temperature, max_tokens, tools, stream=False, **kwargs
        )

        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        self.chat_url,
                        headers=self.headers,
                        json=payload,
                    )
                    resp.raise_for_status()
                    data = resp.json()

                choice = data["choices"][0]
                message = choice["message"]

                if message.get("tool_calls"):
                    return json.dumps(message, ensure_ascii=False)

                return message.get("content", "")

            except httpx.HTTPStatusError as e:
                logger.error(
                    f"LLM API HTTP 错误 (async, attempt {attempt+1}): "
                    f"{e.response.status_code} - {e.response.text[:500]}"
                )
                if attempt == self.max_retries:
                    return self._fallback_response(messages)

            except Exception as e:
                logger.error(f"LLM API 异步调用异常 (attempt {attempt+1}): {e}")
                if attempt == self.max_retries:
                    return self._fallback_response(messages)

        return self._fallback_response(messages)

    async def astream(
        self,
        messages: List[Dict[str, str]],
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """异步流式聊天补全"""
        if not self._enabled:
            yield self._fallback_response(messages)
            return

        full_messages = self._build_messages(messages, system)
        payload = self._build_payload(
            full_messages, temperature, max_tokens, stream=True, **kwargs
        )

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    self.chat_url,
                    headers=self.headers,
                    json=payload,
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        chunk = self._parse_sse_line(line)
                        if chunk is not None:
                            yield chunk
        except Exception as e:
            logger.error(f"LLM 异步流式调用异常: {e}")
            yield self._fallback_response(messages)

    # ------------------------------------------------------------------
    #  状态查询
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """获取 LLM 客户端状态信息"""
        return {
            "enabled": self._enabled,
            "base_url": self.base_url,
            "model": self.model,
            "has_api_key": bool(self.api_key),
            "timeout": self.timeout,
            "max_retries": self.max_retries,
        }

    def test_connection(self) -> Dict[str, Any]:
        """测试 LLM 连接"""
        if not self._enabled:
            return {
                "success": False,
                "error": "LLM 未配置 API Key",
            }

        try:
            result = self.generate("请回复 OK", max_tokens=10, temperature=0)
            return {
                "success": True,
                "model": self.model,
                "response": result[:100],
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    # ------------------------------------------------------------------
    #  内部方法
    # ------------------------------------------------------------------

    def _build_messages(
        self,
        messages: List[Dict[str, str]],
        system: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """构建完整消息列表"""
        result = []
        if system:
            result.append({"role": "system", "content": system})
        result.extend(messages)
        return result

    def _build_payload(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: Optional[List[Dict]] = None,
        stream: bool = False,
        **kwargs,
    ) -> Dict[str, Any]:
        """构建请求 payload"""
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = kwargs.pop("tool_choice", "auto")

        # 透传其他 OpenAI 兼容参数
        for key, value in kwargs.items():
            if key not in payload and value is not None:
                payload[key] = value

        return payload

    def _parse_sse_line(self, line: str) -> Optional[str]:
        """解析 SSE 行，返回增量文本或 None"""
        line = line.strip()
        if not line or not line.startswith("data:"):
            return None

        data_str = line[5:].strip()
        if data_str == "[DONE]":
            return None

        try:
            data = json.loads(data_str)
            delta = data.get("choices", [{}])[0].get("delta", {})
            return delta.get("content")
        except (json.JSONDecodeError, IndexError, KeyError):
            return None

    def _fallback_response(self, messages: List[Dict[str, str]]) -> str:
        """
        降级响应 - LLM 不可用时返回占位提示
        调用方应检查此返回并走模板/规则引擎逻辑
        """
        return "[LLM_UNAVAILABLE]"
