"""从仓库根目录直接运行。Edge 使用聊天面板的实际渲染函数；仅转发临时样本。"""
import asyncio
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory

from fastapi import FastAPI
import httpx
from PIL import Image, ImageDraw
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from api.local_images import router

ORIGIN = "http://127.0.0.1"
URL = "/api/local-file"
REPORT = """<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><style>
*{box-sizing:border-box}body{margin:0;background:#fafbf9;color:#233930;font:16px/1.6 "Microsoft YaHei",sans-serif}
main{padding:24px 34px;border-top:6px solid #176b57}small{color:#24634e;letter-spacing:1px}
h1{font-size:28px;margin:6px 0}p{margin:4px 0 14px;color:#4d6158}figure{margin:0 0 20px}
img{display:block;border-radius:4px}figcaption{font-size:14px;color:#4d6158;margin-top:4px}
table{border-collapse:collapse;width:100%;background:white}td,th{padding:8px 12px;border-bottom:1px solid #d8e4dc;text-align:left}
th{background:#e0ece4}td:nth-child(2){font:600 16px monospace}</style>
<main><small>代码重构　 /　 DEVNOTE 20　 /　 EDGE 实测</small><h1>聊天面板怎样预览本地图片</h1>
<p>色卡由脚本临时生成，表格记录浏览器在同一次验证中收到的响应。</p>
<figure><div id="chatFileView"></div><figcaption></figcaption></figure>
<table><thead><tr><th>操作</th><th>HTTP</th><th>响应类型</th><th>浏览器读数</th></tr></thead><tbody></tbody></table></main></html>"""


async def capture(folder):
    sample = folder / "色卡 & 样片.PNG"
    unsupported = folder / "note.txt"
    missing = folder / "missing.png"
    sheet = Image.new("RGB", (480, 72))
    brush = ImageDraw.Draw(sheet)
    for i, color in enumerate(("#194750", "#267067", "#419779", "#9abf85", "#efd390", "#d48c68")):
        brush.rectangle((80*i, 0, 80*i+79, 71), fill=color)
    sheet.save(sample)
    unsupported.write_text("DevNote 20", encoding="utf8")

    src = (ROOT / "frontend/app.js").read_text(encoding="utf8")
    functions = "\n".join(re.search(rf"^function {name}\(.*?^\}}", src, re.M | re.S).group()
                          for name in ("escapeHtml", "_renderChatFileBody"))
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client, \
            async_playwright() as pw:
        browser = await pw.chromium.launch(channel="msedge")
        page = await browser.new_page(viewport={"width": 900, "height": 600})
        async def forward(route):
            req = route.request
            if req.url == ORIGIN + "/":
                return await route.fulfill(content_type="text/html; charset=utf-8", body=REPORT)
            url = httpx.URL(req.url)
            if (req.method != "GET" or not req.url.startswith(ORIGIN + URL + "?") or
                    url.params.get("path") not in {str(sample), str(unsupported), str(missing)}):
                return await route.abort()
            headers = {"Range": req.headers["range"]} if "range" in req.headers else {}
            r = await client.get(req.url, headers=headers)
            await route.fulfill(status=r.status_code, headers=dict(r.headers), body=r.content)
        await page.route("**/*", forward)
        await page.goto(ORIGIN + "/")
        await page.add_script_tag(content=functions)
        async with page.expect_response(lambda r: r.url.startswith(ORIGIN + URL)) as pending:
            await page.evaluate("data => _renderChatFileBody({loaded:data})",
                                {"kind": "image", "filename": sample.name, "path": str(sample)})
        preview = await pending.value
        assert preview.status == 200 and await preview.body() == sample.read_bytes()
        assert preview.headers["content-type"] == "image/png"
        size = await page.locator("#chatFileView img").evaluate(
            "async img=>{await img.decode(); return [img.naturalWidth,img.naturalHeight]}")
        assert size == [480, 72]
        await page.locator("figcaption").evaluate("(el,s)=>el.textContent=s", sample.name)
        rows = [["预览色卡", preview.status, preview.headers["content-type"], f"解码：{size[0]} × {size[1]} 像素"]]
        partial = await page.evaluate("""async () => {
            const r=await fetch(document.querySelector('img').src, {headers:{Range:'bytes=0-7'}});
            return [r.status,r.headers.get('content-type'),r.headers.get('content-range'),
                    Array.from(new Uint8Array(await r.arrayBuffer()))]}""")
        assert partial == [206, "image/png", f"bytes 0-7/{sample.stat().st_size}", list(sample.read_bytes()[:8])]
        rows.append(["只取前 8 字节", *partial[:3]])
        for name, path, status, detail in [("普通文本", unsupported, 400, "不支持的文件类型"),
                                           ("缺失图片", missing, 404, "文件不存在")]:
            actual = await page.evaluate("""async p => {
                const r=await fetch('/api/local-file?path='+encodeURIComponent(p));
                return [r.status,r.headers.get('content-type'),(await r.json()).detail]}""", str(path))
            assert actual == [status, "application/json", detail]
            rows.append([name, *actual])
        await page.evaluate("""rows=>{for(const fields of rows){const tr=document.querySelector('tbody').insertRow();
            for(const field of fields)tr.insertCell().textContent=field}}""", rows)
        await page.locator("main").screenshot(path=str(Path(__file__).with_suffix(".png")))
        await browser.close()
        print("Edge: decoded 480x72; original PNG and range matched; HTTP 200/206/400/404")


if __name__ == "__main__":
    with TemporaryDirectory() as temp:
        asyncio.run(capture(Path(temp)))
