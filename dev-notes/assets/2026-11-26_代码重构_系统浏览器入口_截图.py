"""隔离 Edge 验证：运行真实地址栏函数和 HTTP 路由，两种打开目标网页的动作均用替身。"""
import asyncio
from pathlib import Path
import re
import sys
from unittest.mock import patch
from urllib.parse import urlsplit
import webbrowser

from fastapi import FastAPI
import httpx
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from api.system import router

ORIGIN = "http://devnote.test"
PATH = "/api/open-in-browser"
PAGE = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><style>
*{box-sizing:border-box}body{margin:0;background:#eff4f3;color:#193b3b;font:16px/1.6 "Microsoft YaHei",sans-serif}
main{border-top:6px solid #176854;padding:24px 30px}small,footer{color:#48655f}h1{font-size:26px;margin:5px 0}
p{margin:4px 0 14px}.bar{display:flex;background:#fff;padding:10px;gap:8px}input{flex:1;padding:5px}
button{color:#174d41;padding:4px 12px}table{width:100%;border-collapse:collapse;background:white;margin:14px 0}
th,td{text-align:left;border-bottom:1px solid #d7e2df;padding:8px 12px}th{background:#dfece6}
footer{font-size:14px}</style><main><small>代码重构　/　DEVNOTE 19　·　Edge 隔离验证</small>
<h1>系统浏览器何时启动，何时回退</h1><p>地址栏逻辑和 API 来自项目，表格记录实际响应与替身调用。</p>
<div class="bar"><input id="mainWsWebUrlInput" aria-label="网址">
<button title="在系统浏览器打开" onclick="adsShell.openWebTabExternal('demo')">在系统浏览器打开 ↗</button></div>
<table><thead><tr><th>输入或条件</th><th>HTTP</th><th>系统调用</th><th>页面处理</th></tr></thead>
<tbody></tbody></table><footer>所有目标地址均为测试示例；未访问外部网页。</footer></main></html>"""


def product_functions():
    src = (ROOT / "frontend/app.js").read_text(encoding="utf8")
    names = ["api", "_normalizeWebUrl", "openWebTabExternal", "_openUrlInSystemBrowser"]
    return "\n".join(re.search(rf"^([ \t]*)(?:async )?function {name}\(.*?^\1\}}",
                               src, re.M | re.S).group() for name in names)


async def capture():
    app = FastAPI()
    app.include_router(router)
    offline, replies = False, []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client, \
            async_playwright() as pw:
        browser = await pw.chromium.launch(channel="msedge")
        page = await browser.new_page(viewport={"width": 920, "height": 500})
        with patch.object(webbrowser, "open", return_value=True) as launch:
            async def forward(route):
                u = urlsplit(route.request.url)
                if route.request.url == ORIGIN + "/":
                    return await route.fulfill(content_type="text/html; charset=utf-8", body=PAGE)
                if route.request.method != "GET" or f"{u.scheme}://{u.netloc}" != ORIGIN or u.path != PATH:
                    return await route.abort()
                if offline:
                    replies.append("断网")
                    return await route.abort()
                r = await client.get(PATH + "?" + u.query)
                replies.append(r.status_code)
                await route.fulfill(status=r.status_code, content_type="application/json", body=r.content)

            await page.route("**/*", forward)
            await page.goto(ORIGIN + "/")
            await page.add_script_tag(content=product_functions() + """
                const API='/api', state={mainTabs:[{id:'demo'}]}, adsShell={openWebTabExternal};
                const popups=[], notices=[];
                window.open=(...args)=>{popups.push(args);return null};
                function showToast(message,type){notices.push([message,type])}
                const realOpen=_openUrlInSystemBrowser;
                _openUrlInSystemBrowser=(url)=>window.lastAction=realOpen(url);
            """)
            cases = [
                ("混合大小写协议", "HTTPS://Example.org/Docs?q=A%26B#Top", 200, "https://Example.org/Docs?q=A%26B#Top"),
                ("缺少主机名", "https://", 400, None),
                ("系统浏览器不可用", "https://example.org/desktop", 500, "https://example.org/desktop"),
                ("服务断网", "https://example.org/offline", "断网", None),
            ]
            for i, (label, url, status, target) in enumerate(cases, 1):
                launch.reset_mock()
                launch.return_value = status != 500
                offline = status == "断网"
                await page.evaluate("popups.length=notices.length=0")
                await page.locator("input").fill(url)
                await page.locator("button").click()
                await page.evaluate("()=>window.lastAction")
                assert len(replies) == i and replies[-1] == status
                if target:
                    launch.assert_called_once_with(target)
                else:
                    launch.assert_not_called()
                popups, notices = await page.evaluate("[popups, notices]")
                if status == 400:
                    assert notices == [["http/https URL 格式无效", "error"]] and not popups
                    outcome = notices[0][0]
                elif status == 200:
                    assert not popups and not notices
                    outcome = "无新窗口重试"
                else:
                    assert popups == [[url, "_blank", "noopener"]] and not notices
                    outcome = "请求新窗口 1 次"
                await page.evaluate("""fields=>{const row=document.querySelector('tbody').insertRow();
                    for(const s of fields) row.insertCell().textContent=s}""",
                                    [label, status, f"{launch.call_count} 次", outcome])
            await page.locator("main").screenshot(path=str(Path(__file__).with_suffix(".png")))
            print("200 / 400 / 500 / offline; desktop calls: 1,0,1,0; window requests: 0,0,1,1")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(capture())
