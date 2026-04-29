"""
FetchUrlAction — 访问外部 URL 并返回文本内容

对 LLM 暴露为 tool，让 AI 助手能读取用户粘贴的链接（文档、README、API 规范等）。
HTML 页面自动提取正文文字；MD/TXT 直接返回。内容超长时截断到 8000 字符。
"""
from __future__ import annotations

import html
import logging
import re
from html.parser import HTMLParser
from typing import Any, Dict
from urllib.parse import urlparse

import httpx

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("action.fetch_url")

MAX_CONTENT_CHARS = 8000
REQUEST_TIMEOUT = 15


class _TextExtractor(HTMLParser):
    """极简 HTML → 纯文本提取器（跳过 script/style/head 块）"""

    _SKIP_TAGS = {"script", "style", "head", "noscript", "svg", "iframe"}

    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in ("p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr"):
            self._parts.append("\n")

    def handle_data(self, data):
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        text = "".join(self._parts)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        return text.strip()


def _extract_html_text(raw: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(raw)
        return parser.get_text()
    except Exception:
        # 粗暴 fallback：去掉所有标签
        return re.sub(r"<[^>]+>", " ", html.unescape(raw)).strip()


def _is_safe_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


class FetchUrlAction(ActionBase):

    @property
    def name(self) -> str:
        return "fetch_url"

    @property
    def description(self) -> str:
        return "访问外部 URL，获取网页或文档内容"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "访问一个外部 URL 并读取其文本内容（网页、Markdown 文档、README、API 规范等）。\n"
                "当用户粘贴了一个链接并想让你读取其内容时调用。\n"
                "返回提取到的正文文字（HTML 自动去除标签），最多 8000 字符。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "要访问的 URL，必须以 http:// 或 https:// 开头",
                    },
                },
                "required": ["url"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        url = (context.get("url") or "").strip()

        if not url:
            return ActionResult(success=False, error="url 不能为空")

        if not _is_safe_url(url):
            return ActionResult(success=False, error="无效的 URL，必须以 http:// 或 https:// 开头")

        logger.info("FetchUrlAction: GET %s", url)

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=REQUEST_TIMEOUT,
                headers={"User-Agent": "Mozilla/5.0 (AI-Dev-System/1.0)"},
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()

            content_type = resp.headers.get("content-type", "").lower()
            raw = resp.text

            if "html" in content_type:
                text = _extract_html_text(raw)
            else:
                text = raw  # MD / TXT / JSON 等直接返回

            if len(text) > MAX_CONTENT_CHARS:
                text = text[:MAX_CONTENT_CHARS] + f"\n\n[内容过长，已截断至 {MAX_CONTENT_CHARS} 字符]"

            logger.info("FetchUrlAction: 获取 %d 字符 (status=%s)", len(text), resp.status_code)
            return ActionResult(
                success=True,
                data={
                    "url": url,
                    "content": text,
                    "content_type": content_type,
                    "status_code": resp.status_code,
                },
                message=f"已获取 {url} 的内容（{len(text)} 字符）",
            )

        except httpx.TimeoutException:
            return ActionResult(success=False, error=f"请求超时（{REQUEST_TIMEOUT}s），URL 不可达或响应太慢")
        except httpx.HTTPStatusError as e:
            return ActionResult(success=False, error=f"HTTP {e.response.status_code}：{url}")
        except Exception as e:
            logger.warning("FetchUrlAction 失败: %s", e)
            return ActionResult(success=False, error=f"访问失败：{e}")
