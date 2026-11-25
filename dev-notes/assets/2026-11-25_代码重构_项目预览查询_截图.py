"""独立进程运行；需要项目后端依赖、Playwright 和 Edge。"""
import socket
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import uvicorn
from fastapi import FastAPI
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from agents.deploy import DeployAgent
from api import project_preview, projects


PAGE = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>项目预览验证页</title>
<style>*{box-sizing:border-box}body{margin:0;background:#eff4f5;color:#183842;font:17px/1.55 'Microsoft YaHei',sans-serif}
main{padding:30px 38px;border-top:7px solid #146252}h1{margin:10px 0}p{margin:10px 0}
section{margin-top:18px;padding:14px 20px;background:white;border-left:4px solid #197663}
code{font:16px Consolas,monospace}small{color:#46615d}</style>
<main><small>代码重构 · DevNote 14　/　浏览器验证 · 临时测试项目</small>
<h1>已打开项目的内置预览</h1><p>此页来自临时项目的 <code>dist/index.html</code>。</p>
<section><small>浏览器当前地址</small><br><code id="address"></code></section></main>
<script>document.querySelector('#address').textContent=location.href</script></html>"""


def capture():
    app = FastAPI()
    app.include_router(project_preview.router)
    app.add_api_route("/api/projects/{project_id}/preview/{env_type}/{asset_path:path}",
                      projects.serve_project_preview_asset)
    project = "preview-demo"
    db = SimpleNamespace(fetch_one=AsyncMock(return_value={"id": project}))
    with TemporaryDirectory() as folder, socket.socket() as sock:
        root = Path(folder)
        (root / "dist").mkdir()
        (root / "dist/index.html").write_text(PAGE, encoding="utf-8")
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        previews = {(project, "test"): {"builtin": True, "port": port}}
        service = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
        with patch.object(DeployAgent, "_preview_servers", previews), patch.object(projects, "db", db), \
                patch.object(projects.git_manager, "_repo_path", return_value=root):
            thread = Thread(target=service.run, kwargs={"sockets": [sock]}, daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 10
                while not service.started:
                    if not thread.is_alive() or time.monotonic() > deadline:
                        raise RuntimeError("临时服务未就绪")
                    time.sleep(0.05)
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(channel="msedge")
                    page = browser.new_page(viewport={"width": 880, "height": 320})
                    lookup = page.goto(f"http://127.0.0.1:{port}/api/projects/{project}/preview")
                    assert lookup.status == 200
                    target = lookup.json()["preview_url"]
                    response = page.goto(target)
                    assert response.status == 200 and page.title() == "项目预览验证页"
                    assert page.locator("#address").inner_text() == target
                    out = Path(__file__).with_suffix(".png")
                    page.locator("main").screenshot(path=str(out))
                    browser.close()
                    print(f"lookup=200 page=200 url={target} image={out.name}")
            finally:
                service.should_exit = True
                thread.join(timeout=10)


if __name__ == "__main__":
    capture()
