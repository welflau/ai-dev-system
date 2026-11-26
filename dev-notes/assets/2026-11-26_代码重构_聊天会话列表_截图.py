"""用真实前端列表函数显示只读 SQLite 样本；不访问 8001 或会话详情。"""
import asyncio
import re
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi import FastAPI
import httpx
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
with patch("dotenv.load_dotenv"), patch("dotenv.dotenv_values", return_value={}):
    from api import chat
from database import db

ORIGIN = "http://127.0.0.1"
PROJECT = "/api/projects/alpha/chat/sessions"
GLOBAL = "/api/chat/sessions"
PAGE = """<!doctype html><meta charset="utf-8"><style>
*{box-sizing:border-box}body{margin:0;background:#f6faf8;color:#203e37;font:16px/1.55 "Microsoft YaHei",sans-serif}
main{padding:23px 30px 27px;border-top:6px solid #27735e}small{color:#396956;letter-spacing:1px}
h1{font-size:27px;margin:5px 0}p{margin:2px 0 18px;color:#465e54}.cols{display:flex;gap:16px}
section{flex:1;background:#fff;border:1px solid #cbded3;border-radius:6px;padding:14px}h2{font-size:18px;margin:0 0 8px}
select{width:100%;font:16px/1.5 "Microsoft YaHei",sans-serif;color:#244a3b;border:0;background:#fff}
option{padding:5px 8px}footer{font:14px/1.5 monospace;color:#396255;margin-top:15px}
</style><main><small>代码重构　/　DEVNOTE 22　/　EDGE 实测</small><h1>项目和全局会话，各自统计消息</h1>
<p>两个列表使用产品的加载函数和临时数据库。选项中的条数来自实际 GET 响应。</p>
<div class="cols"><section><h2>项目 alpha</h2><select id="chatTraceSessionSel" size="3"></select>
<div hidden id="chatTraceBody"></div></section><section><h2>全局会话</h2>
<select id="globalChatTraceSessionSel" size="3"></select><div hidden id="globalChatTraceBody"></div></section></div>
<footer></footer></main>"""


async def capture(conn):
    app = FastAPI()
    app.include_router(chat.router)
    app.include_router(chat.global_chat_router)
    src = (ROOT / "frontend/app.js").read_text(encoding="utf8")
    functions = "\n".join(re.search(rf"^(?:async )?function {name}\(.*?^\}}", src, re.M | re.S).group()
                          for name in ("escHtml", "loadChatTrace", "loadGlobalChatTrace"))

    async def fetch_all(sql, params=()):
        return [dict(row) for row in conn.execute(sql, params)]

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client, \
            async_playwright() as pw:
        browser = await pw.chromium.launch(channel="msedge")
        page = await browser.new_page(viewport={"width": 900, "height": 450})
        observed = []

        async def forward(route):
            request = route.request
            if request.url == ORIGIN + "/":
                return await route.fulfill(content_type="text/html; charset=utf-8", body=PAGE)
            u = urlsplit(request.url)
            if (request.method != "GET" or f"{u.scheme}://{u.netloc}" != ORIGIN or
                    u.path not in {PROJECT, GLOBAL}):
                return await route.abort()
            r = await client.get(request.url)
            observed.append([u.path, r.status_code])
            await route.fulfill(status=r.status_code, content_type="application/json", body=r.content)

        with patch.object(db, "fetch_all", fetch_all):
            await page.route("**/*", forward)
            await page.goto(ORIGIN + "/")
            await page.add_script_tag(content=functions + """
                const API='/api', currentProjectId='alpha';
                let _chatTraceSessions=[], _globalChatTraceSessions=[], _chatTraceCurrentSid, _globalChatTraceCurrentSid;
                async function loadChatTraceDetail() {} async function loadGlobalChatTraceDetail() {}
            """)
            await page.evaluate("async()=>{await loadChatTrace(); await loadGlobalChatTrace()}")
            assert observed == [[PROJECT, 200], [GLOBAL, 200]]
            for selector, expected in [
                ("#chatTraceSessionSel", ["分镜讨论 · 2 条 · 01-04", "空白草案 · 0 条 · 01-02"]),
                ("#globalChatTraceSessionSel", ["全局备忘 · 1 条 · 01-05"]),
            ]:
                assert await page.locator(selector + " option").all_text_contents() == expected
            await page.locator("footer").evaluate("(e,rows)=>e.textContent=rows.map(r=>r.join(' → ')).join('　|　')",
                                                  observed)
            await page.locator("main").screenshot(path=str(Path(__file__).with_suffix(".png")))
        await browser.close()
    print("Edge: two GET 200; actual dropdown counts 2, 0 and 1")


if __name__ == "__main__":
    conn = sqlite3.connect(":memory:")
    try:
        conn.row_factory = sqlite3.Row
        conn.executescript((ROOT / "backend/tests/api/fixtures/chat_session_lists.sql").read_text(encoding="utf8"))
        asyncio.run(capture(conn))
    finally:
        conn.close()
