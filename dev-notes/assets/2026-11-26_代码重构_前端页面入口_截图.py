"""Edge 直达并刷新深链接。仅访问随机本机端口上的隔离应用。"""
import asyncio
import base64
from contextlib import asynccontextmanager
import hashlib
from pathlib import Path
import shutil
import socket
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import uvicorn
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from api import frontend_pages

DEEP = "/app/devnote18/nested"
CACHE = "no-cache, no-store, must-revalidate"
REPORT = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><style>
*{box-sizing:border-box}body{margin:0;background:#eef4f3;color:#1c383e;font:16px/1.6 "Microsoft YaHei",sans-serif}
main{border-top:6px solid #176854;padding:22px 30px}small,footer{color:#45615e}h1{font-size:27px;margin:4px 0}
p{margin:6px 0}img{display:block;max-width:100%;margin:8px 0 16px}table{width:100%;border-collapse:collapse;background:white}
td,th{text-align:left;padding:8px 12px;border-bottom:1px solid #d4e0de}th{background:#deebe7}
footer{margin-top:12px;font-size:14px}</style><main><small>代码重构　/　DEVNOTE 18　·　Edge 实测</small>
<h1>深链接刷新后仍返回首页</h1><p>刷新后的真实首页顶栏（隔离环境，未启动业务脚本）</p><img alt="首页顶栏">
<table><thead><tr><th>请求</th><th>HTTP</th><th>响应类型</th><th>浏览器收到的内容</th></tr></thead><tbody></tbody></table>
<footer></footer></main></html>"""


@asynccontextmanager
async def local_site(app):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="error"))
        task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    if task.done():
                        await task
                        raise RuntimeError("临时服务未启动")
                    await asyncio.sleep(0.02)
            yield origin
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, 10)


async def capture(folder):
    for name in ("index.html", "styles.css"):
        shutil.copyfile(ROOT / "frontend" / name, folder / name)
    app = FastAPI()
    app.include_router(frontend_pages.router)
    app.mount("/static", StaticFiles(directory=folder))
    with patch.object(frontend_pages, "frontend_dir", folder):
        async with local_site(app) as origin, async_playwright() as pw:
            browser = await pw.chromium.launch(channel="msedge")
            page = await browser.new_page(viewport={"width": 1100, "height": 640})

            async def forward(route):
                u = urlsplit(route.request.url)
                allowed = {"/app", DEEP, "/static/styles.css", "/favicon.ico"}
                if f"{u.scheme}://{u.netloc}" != origin or u.path not in allowed or route.request.method != "GET":
                    return await route.abort()
                await route.continue_()

            await page.route("**/*", forward)
            rows = []
            original = (folder / "index.html").read_bytes()
            for label, url in [("打开 /app", "/app"), ("直达 " + DEEP, DEEP), ("刷新深链接", None)]:
                r = await page.goto(origin + url) if url else await page.reload()
                body = await r.body()
                assert r.status == 200 and body == original and await page.title() == "AI 自动开发系统"
                assert r.headers["cache-control"] == CACHE and await page.locator(".top-bar .logo").is_visible()
                kind = r.headers["content-type"].split(";")[0]
                assert kind == "text/html"
                rows.append([label, r.status, kind, "首页 SHA-256：" + hashlib.sha256(body).hexdigest()[:12]])
            assert page.url == origin + DEEP
            assert await page.evaluate("Array.from(document.styleSheets).some(s=>s.href?.includes('/static/styles.css') && s.cssRules.length>0)")
            banner = base64.b64encode(await page.locator(".top-bar").screenshot()).decode()
            (folder / "index.html").unlink()  # 只替换临时副本，模拟同名目录
            (folder / "index.html").mkdir()
            result = await page.evaluate("""async ([path])=>{
                const r=await fetch(path), icon=await fetch('/favicon.ico?devnote=18');
                const xml=new DOMParser().parseFromString(await icon.text(),'image/svg+xml');
                return [r.status,r.headers.get('content-type'),(await r.json()).message,
                        icon.status,icon.headers.get('content-type'),xml.documentElement.localName];
            }""", [DEEP])
            assert result == [404, "application/json", frontend_pages.INDEX_MISSING, 200, "image/svg+xml", "svg"]
            rows += [["index.html 是目录", *result[:3]], ["读取图标", *result[3:]]]
            report = await browser.new_page(viewport={"width": 1100, "height": 640})
            await report.set_content(REPORT)
            await report.evaluate("""([rows,banner,cache])=>{
                document.querySelector('img').src='data:image/png;base64,'+banner;
                for(const fields of rows){const row=document.querySelector('tbody').insertRow();
                    for(const field of fields) row.insertCell().textContent=field}
                document.querySelector('footer').textContent='三次 HTML 响应的 Cache-Control：'+cache;
            }""", [rows, banner, CACHE])
            await report.locator("img").evaluate("img=>img.decode()")
            await report.locator("main").screenshot(path=str(Path(__file__).with_suffix(".png")))
            await browser.close()
            print("root, nested, reload: identical HTML; directory: 404 JSON; favicon: 200 SVG")


if __name__ == "__main__":
    with TemporaryDirectory() as temp:
        asyncio.run(capture(Path(temp)))
