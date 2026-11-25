"""运行于独立进程和随机本地端口。需要后端依赖、Playwright 和 Edge。"""
import asyncio
import socket
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from api.event_streams import global_router, scoped_router
from events import event_manager


PAGE = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>SSE 频道实测</title><style>
*{box-sizing:border-box}body{margin:0;background:#eff4f4;color:#1e343b;font:16px/1.6 'Microsoft YaHei',sans-serif}
main{padding:25px 32px 27px;border-top:6px solid #176854}small{color:#456568}h1{font-size:28px;margin:6px 0}
p{margin:0 0 16px}table{border-collapse:collapse;width:100%;background:white;text-align:left}
th,td{padding:8px 12px;border-bottom:1px solid #d8e5e2}th{background:#dfebe9;font-size:14px}
td:nth-child(2){font:15px Consolas,monospace}td:last-child{white-space:pre-line}
footer{margin-top:17px;color:#115a47;font-weight:bold}</style>
<main><small>代码重构　/　DEVNOTE 16　·　浏览器实测</small><h1>同名事件，按频道投递</h1>
<p>三个原生 EventSource 同时监听 log_added。下表由浏览器收到的合成数据生成。</p>
<table><thead><tr><th>监听频道</th><th>收到的事件</th><th>JSON 解析后的消息</th></tr></thead>
<tbody></tbody></table><footer></footer></main>
<script>
const sources = [], logs = [], finished = new Set();
for (const [channel,path] of [['全局','/api/events/global'],['项目 demo','/api/projects/demo/events'],
                              ['工单 demo','/api/tickets/demo/events']]) {
  const es = new EventSource(path); sources.push(es);
  es.addEventListener('log_added', e => {
    const fields = [channel, e.type, JSON.parse(e.data).message];
    logs.push(fields);
    const row = document.querySelector('tbody').insertRow();
    for (const s of fields) row.insertCell().textContent = s;
  });
  es.addEventListener('batch_end', () => finished.add(channel));
}
</script></html>"""


async def capture():
    app = FastAPI()
    app.include_router(global_router)
    app.include_router(scoped_router)

    @app.get("/", response_class=HTMLResponse)
    async def report():
        return PAGE

    samples = [
        ("global", "全局", "全局日志\n第二行仍在同一条消息内"),
        ("project:demo", "项目 demo", "项目进度：已更新"),
        ("ticket:demo", "工单 demo", "工单状态：已完成"),
    ]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{sock.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="error"))
        task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    if task.done():
                        await task
                        raise RuntimeError("临时服务未启动")
                    await asyncio.sleep(0.02)
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(channel="msedge")
                page = await browser.new_page(viewport={"width": 880, "height": 480})
                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_function("sources.every(s => s.readyState === EventSource.OPEN)")
                counts = {k: len(v) for k, v in event_manager._subscribers.items()}
                assert counts == {k: 1 for k, _, _ in samples}
                for channel, _, message in samples:
                    await event_manager.publish(channel, "log_added", {"message": message})
                for channel, _, _ in samples:
                    await event_manager.publish(channel, "batch_end", {})
                await page.wait_for_function("finished.size === 3")
                actual = await page.evaluate("logs")
                assert sorted(actual) == sorted([label, "log_added", msg] for _, label, msg in samples)
                await page.evaluate("sources.forEach(s => s.close())")
                async with asyncio.timeout(5):
                    while event_manager._subscribers:
                        await asyncio.sleep(0.02)
                remaining = sum(map(len, event_manager._subscribers.values()))
                status = f"浏览器收到 {len(actual)} 条日志　·　连接关闭后，服务端订阅数：{sum(counts.values())} → {remaining}"
                await page.locator("footer").evaluate("(el, msg) => el.textContent = msg", status)
                await page.locator("main").screenshot(path=str(Path(__file__).with_suffix(".png")))
                await browser.close()
                print(status)
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, 10)


if __name__ == "__main__":
    asyncio.run(capture())
