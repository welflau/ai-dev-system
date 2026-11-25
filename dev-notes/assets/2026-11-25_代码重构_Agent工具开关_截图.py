"""从真实设置卡片、样式及开关 JS 截图；浏览器内的请求只转发到隔离的 TestClient。"""
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
import config
from api.system import router


def capture(folder):
    app = FastAPI()
    app.include_router(router)
    path = folder / "settings.fixture"
    with patch.object(config, "ENV_PATH", path), patch.object(config, "settings", SimpleNamespace()), \
            TestClient(app, raise_server_exceptions=False) as client, sync_playwright() as pw:
        os.environ[config.AGENT_TOOLS_ENV_KEY] = "false"  # 此脚本是一次性独立进程
        browser = pw.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 800, "height": 400})
        trace = []
        offline = False

        def handle(route):
            request = route.request
            if request.url == "http://ui.test/":
                return route.fulfill(content_type="text/html; charset=utf-8", body=(
                    '<html lang="zh-CN" data-theme="light"><meta charset="utf-8"><body>'
                    '<main style="padding:24px;width:760px"><header>代码重构 · DevNote 15 / 隔离浏览器验证</header>'
                    '<div id="card"></div><p id="notice" role="status"></p></main></body></html>'))
            if request.url != "http://ui.test/api/settings/agent-tools":
                return route.abort()
            if offline:
                return route.abort()
            response = client.request(request.method, "/api/settings/agent-tools", content=request.post_data,
                                      headers={"Content-Type": "application/json"})
            trace.append((request.method, response.status_code))
            route.fulfill(status=response.status_code, content_type=response.headers["content-type"], body=response.content)

        page.route("**/*", handle)
        page.goto("http://ui.test/")
        front = ROOT / "frontend"
        page.evaluate("""html => {
            const doc = new DOMParser().parseFromString(html, 'text/html');
            document.querySelector('#card').append(doc.querySelector('#agentToolsToggle').closest('.settings-card'));
        }""", (front / "index.html").read_text(encoding="utf-8"))
        page.add_style_tag(path=front / "styles.css")
        js = (front / "app.js").read_text(encoding="utf-8")
        api = js[js.index("async function api("):].split("\n}", 1)[0] + "\n}"
        switch = js[js.index("async function syncAgentToolsState("):js.index("// ==================== 系统指标条")]
        page.add_script_tag(content="const API='/api'; function showToast(s){document.querySelector('#notice').textContent=s;}\n"
                            + api + "\n" + switch)
        label, slider = page.locator("#agentToolsLabel"), page.locator("label.toggle-switch")
        toggle = page.locator("#agentToolsToggle")
        page.evaluate("loadAgentToolsStatus()")
        expect(label).to_have_text("已关闭")
        slider.click()
        expect(label).to_have_text("已开启")
        expect(toggle).to_be_checked()
        shot = Path(__file__).with_suffix("")
        page.locator("main").screenshot(path=str(shot) + "_已保存.png")
        slider.click()
        expect(label).to_have_text("已关闭")
        with patch.object(config, "ENV_PATH", folder):  # 目录不能作为配置文件
            slider.click()
            expect(page.locator("#notice")).to_contain_text("保存失败")
            expect(label).to_have_text("已关闭")
            expect(toggle).not_to_be_checked()
        assert trace == [("GET", 200), ("POST", 200), ("POST", 200), ("POST", 500), ("GET", 200)]
        assert path.read_text(encoding="utf-8").strip() == "ENABLE_AGENT_TOOLS=false"
        page.locator("main").screenshot(path=str(shot) + "_保存失败.png")
        offline = True
        slider.click()
        expect(label).to_contain_text("状态未知")
        expect(toggle).to_be_disabled()
        print("API:", trace, "; offline: disabled")
        browser.close()


if __name__ == "__main__":
    with TemporaryDirectory() as work:
        capture(Path(work))
