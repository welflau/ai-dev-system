"""隔离浏览器验证：运行真实前端函数和系统路由，桌面调用与剪贴板均用替身。"""
from contextlib import chdir
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().with_suffix(".png")
sys.path.insert(0, str(ROOT / "backend"))
from api.system import router
from services import file_manager


PAGE = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>系统路径打开验证</title>
<style>*{box-sizing:border-box}body{margin:0;background:#eef4f3;color:#18383a;font:16px/1.6 'Microsoft YaHei',sans-serif}
main{border-top:6px solid #176754;padding:24px 30px}small{color:#43665f}h1{font-size:27px;margin:5px 0}
p{margin:0 0 14px}#controls{background:#fff;padding:12px;display:flex;gap:10px;align-items:center}
table{border-collapse:collapse;width:100%;background:#fff;margin:12px 0}th,td{text-align:left;border-bottom:1px solid #d2dfdc;padding:9px 12px}
th{font-size:14px;background:#e0ebe7}footer{color:#43665f;font-size:14px}</style>
<main><small>代码重构　/　DEVNOTE 17　·　隔离浏览器验证</small><h1>文件、目录与不存在的图片</h1>
<p>真实按钮和 HTTP 路由；本页模拟 macOS，记录桌面调用参数。</p>
<section id="controls"><span id="file"></span><span id="dir"></span><button id="image">定位缺失的图片</button></section>
<table><thead><tr><th>操作</th><th>HTTP</th><th>桌面调用</th><th>页面提示</th></tr></thead><tbody></tbody></table>
<footer>桌面参数省略临时根目录；未启动 Finder。</footer></main></html>"""


def capture(root):
    app = FastAPI()
    app.include_router(router)
    folder = Path("项目 A")
    folder.mkdir()
    file = folder / "O'Brien & 笔记.txt"
    file.touch()
    missing = root / folder / "缺失.png"
    js = (ROOT / "frontend/app.js").read_text(encoding="utf-8")

    def function(start):
        return js[js.index(start):].split("\n}", 1)[0] + "\n}"

    popen = Mock()
    offline = False
    posts = []
    with TestClient(app) as client, sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1000, "height": 480})

        def handle(route):
            if route.request.url == "http://ui.test/":
                return route.fulfill(content_type="text/html; charset=utf-8", body=PAGE)
            if route.request.url != "http://ui.test/api/system/open_path" or offline:
                return route.abort()
            payload = route.request.post_data_json
            # 仅接收本次重放的临时路径，拦截服务模块内全部桌面调用。
            assert route.request.method == "POST" and payload["path"] in {str(file), str(folder), str(missing)}
            with patch.object(file_manager, "sys", SimpleNamespace(platform="darwin")), \
                    patch.object(file_manager, "subprocess", SimpleNamespace(Popen=popen)), \
                    patch.object(file_manager, "os", SimpleNamespace()):
                response = client.post("/api/system/open_path", json=payload)
            posts.append((payload["path"], response.status_code))
            route.fulfill(status=response.status_code, content_type="application/json", body=response.content)

        page.route("**/*", handle)
        page.goto("http://ui.test/")
        page.add_script_tag(content="""
            const API='/api', notices=[], copied=[];
            function showToast(msg,type){notices.push([msg,type])}
            Object.defineProperty(navigator,'clipboard',{value:{writeText:async s=>copied.push(s)}});
            """ + "\n".join(function(name) for name in (
                "async function api(", "function escapeHtml(", "function _renderFileBadge(",
                "async function openPathInExplorer(", "async function _openLocalImageFile(",
            )))
        page.evaluate("""([f,d,m])=>{
            document.querySelector('#file').innerHTML=_renderFileBadge(f,'选中文件');
            document.querySelector('#dir').innerHTML=_renderFileBadge(d,'打开目录');
            document.querySelector('#image').onclick=()=>_openLocalImageFile(m);
        }""", [str(file), str(folder), str(missing)])
        expect(page.locator("#file button")).to_have_attribute("data-filepath", str(file))
        for i, (selector, label, path, code, args) in enumerate([
            ("#file button", "选中文件", file, 200, ["open", "-R", str(file.absolute())]),
            ("#dir button", "打开目录", folder, 200, ["open", str(folder.absolute())]),
            ("#image", "定位图片", missing, 404, None),
        ], 1):
            calls = popen.call_count
            page.locator(selector).click()
            page.wait_for_function("n=>notices.length===n", arg=i)
            msg, style = page.evaluate("notices.at(-1)")
            assert posts[-1] == (str(path), code)
            if args:
                popen.assert_called_with(args)
                assert popen.call_count == calls + 1 and style == "success"
                native = " ".join([*args[:-1], f"「{path.name}」"])
            else:
                assert popen.call_count == calls and style == "error" and str(missing) in msg
                native = "无调用"
            page.evaluate("""cells=>{const row=document.querySelector('tbody').insertRow();
                for(const c of cells) row.insertCell().textContent=c}""",
                          [label, code, native, msg.replace(str(root), "〈临时目录〉")])
        assert page.evaluate("copied") == []
        page.locator("main").screenshot(path=str(OUT))
        offline = True
        page.locator("#image").click()
        page.wait_for_function("notices.length===4")
        assert page.evaluate("notices.at(-1)[1]") == "warning" and page.evaluate("copied") == [str(missing)]
        page.evaluate("() => {navigator.clipboard.writeText=async()=>{throw Error('unavailable')}}")
        page.locator("#image").click()
        page.wait_for_function("notices.length===5")
        assert page.evaluate("notices.at(-1)[1]") == "error"
        browser.close()
        print("POST: 200, 200, 404; desktop calls: 2; offline copy: confirmed / denied")


if __name__ == "__main__":
    with TemporaryDirectory() as temp, chdir(temp):
        capture(Path(temp))
