"""
WebSearchAction — 联网搜索

优先使用腾讯元宝搜索 API（需配置 TENCENTCLOUD_WSA_APIKEY 环境变量），
降级到基于 fetch_url 的多引擎搜索（无需 API key）。
"""
import logging
import os
import re
import urllib.parse
from typing import Any, Dict, List

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.chat.web_search")

MAX_RESULTS = 8
_WSA_API_KEY = os.getenv("TENCENTCLOUD_WSA_APIKEY", "")


class WebSearchAction(ActionBase):

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return "联网搜索，获取最新信息"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "联网搜索，获取互联网上的最新信息。\n"
                "适合：查询最新版本、技术文档、新闻资讯、API 参考等。\n"
                "返回：搜索结果列表（标题 + URL + 摘要）。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，如 'UE5.8 release notes' 或 'Python asyncio 教程'",
                    },
                    "num_results": {
                        "type": "integer",
                        "description": f"返回结果数量，默认 5，最多 {MAX_RESULTS}",
                    },
                },
                "required": ["query"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        query       = (context.get("query") or "").strip()
        num_results = min(int(context.get("num_results") or 5), MAX_RESULTS)

        if not query:
            return ActionResult(success=False, error="query 不能为空")

        # 优先腾讯元宝 API
        if _WSA_API_KEY:
            result = await self._search_via_wsa(query, num_results)
            if result.success:
                return result
            logger.warning("腾讯元宝搜索失败，降级到多引擎: %s", result.error)

        # 降级：多引擎 fetch 方案
        return await self._search_via_fetch(query, num_results)

    # ── 腾讯元宝搜索 API ──────────────────────────────────────────────────────

    async def _search_via_wsa(self, query: str, num: int) -> ActionResult:
        try:
            import httpx
            url = "https://wsa.cloud.tencent.com/search"
            headers = {"Authorization": f"Bearer {_WSA_API_KEY}",
                       "Content-Type": "application/json"}
            payload = {"query": query, "count": num}
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            results = []
            for item in (data.get("data") or data.get("results") or [])[:num]:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("summary") or item.get("snippet") or "",
                })
            return ActionResult(
                success=True,
                data={"type": "web_search_result", "results": results,
                      "query": query, "source": "tencent_wsa"},
                message=f"搜索「{query}」找到 {len(results)} 条结果",
            )
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    # ── 多引擎 fetch 方案 ─────────────────────────────────────────────────────

    async def _search_via_fetch(self, query: str, num: int) -> ActionResult:
        """通过 fetch_url 调用搜索引擎，解析结果页。"""
        from actions.chat.fetch_url import FetchUrlAction

        q = urllib.parse.quote_plus(query)
        # 中文查询用 Bing 中国版，英文查询用 Bing 国际版
        is_chinese = bool(re.search(r'[一-鿿]', query))
        search_url = (f"https://cn.bing.com/search?q={q}&setlang=zh-hans"
                      if is_chinese else
                      f"https://www.bing.com/search?q={q}")

        fetcher = FetchUrlAction()
        fetch_result = await fetcher.run({"url": search_url})
        if not fetch_result.success:
            return ActionResult(
                success=False,
                error=f"搜索请求失败: {fetch_result.error}",
            )

        raw_html = (fetch_result.data or {}).get("content", "")
        results = self._parse_bing_results(raw_html, num)

        if not results:
            # 解析失败时返回搜索链接让用户自己看
            return ActionResult(
                success=True,
                data={"type": "web_search_result", "results": [],
                      "query": query, "search_url": search_url,
                      "source": "fetch_fallback"},
                message=f"无法解析搜索结果，搜索链接：{search_url}",
            )

        return ActionResult(
            success=True,
            data={"type": "web_search_result", "results": results,
                  "query": query, "source": "bing_fetch"},
            message=f"搜索「{query}」找到 {len(results)} 条结果",
        )

    def _parse_bing_results(self, html: str, num: int) -> List[Dict]:
        """从 Bing 搜索结果页解析标题/URL/摘要。"""
        results = []
        # 简单正则提取（不依赖 BeautifulSoup）
        # 标题+链接
        title_pattern = re.compile(
            r'<a[^>]+href="(https?://[^"]+)"[^>]*>\s*<h2[^>]*>(.*?)</h2>',
            re.DOTALL | re.IGNORECASE,
        )
        # 摘要
        snippet_pattern = re.compile(
            r'<p[^>]*class="[^"]*b_lineclamp[^"]*"[^>]*>(.*?)</p>',
            re.DOTALL | re.IGNORECASE,
        )
        snippets = [re.sub(r'<[^>]+>', '', s).strip()
                    for s in snippet_pattern.findall(html)]

        for i, (url, title) in enumerate(title_pattern.findall(html)):
            if i >= num:
                break
            clean_title = re.sub(r'<[^>]+>', '', title).strip()
            snippet = snippets[i] if i < len(snippets) else ""
            if clean_title and url:
                results.append({
                    "title": clean_title[:200],
                    "url": url,
                    "snippet": snippet[:300],
                })

        return results
