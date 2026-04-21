# Playwright 端到端测试最佳实践

> 本项目用 Playwright 做 UI 验收（ProductAgent）和 E2E 测试（TestAgent）。

## 核心原则：验收看截图，不看 console.log

- ProductAgent 验收时**看的是浏览器截图**，不是单测输出。"后端 API 返回 200" 不等于"页面上有这个功能"
- 开发的"自测"必须包含一次 Playwright 访问页面 + 截图 + 肉眼（或 vision LLM）确认目标元素可见
- 跑 headless 模式，`headless=True` + Chromium 优先（Firefox 有时字体/布局偏差）

## 等待策略 — 永远不要 sleep

```python
# 坏 — 定时等待，慢且不稳
await page.goto("http://localhost:8080")
await asyncio.sleep(3)
await page.screenshot(path="out.png")

# 好 — 等到网络空闲
await page.goto("http://localhost:8080", wait_until="networkidle")
await page.screenshot(path="out.png")

# 更好 — 等具体元素出现
await page.goto("http://localhost:8080")
await page.wait_for_selector("#visit-counter", state="visible", timeout=5000)
await page.screenshot(path="out.png")
```

`wait_until` 可选值：
- `load` — window.load 触发即返回
- `domcontentloaded` — DOM 解析完即返回（快，但图/JS 可能没加载）
- `networkidle` — 500ms 无网络请求（最稳，但慢）

## 选择器优先级

```python
# 按稳定性从高到低：
await page.get_by_role("button", name="提交")       # 最稳，有语义
await page.get_by_test_id("submit-btn")             # 专用 test-id（最佳实践）
await page.get_by_text("提交")                      # 文字匹配
await page.locator("#submit-btn")                   # id 选择器
await page.locator(".btn-primary")                  # class — 易失效
await page.locator("body > div:nth-child(2) > button") # XPath/层级 — 极易失效
```

## 截图 — 本项目规范

```python
# 项目约定：截图存 backend/screenshots/<req_id>/<name>.png
screenshot_dir = Path(f"screenshots/{requirement_id}")
screenshot_dir.mkdir(parents=True, exist_ok=True)

# 全页截图
await page.screenshot(path=str(screenshot_dir / "full.png"), full_page=True)

# 针对性截图（只截目标元素）
counter = await page.wait_for_selector("#visit-counter")
await counter.screenshot(path=str(screenshot_dir / "counter.png"))
```

## 断言

```python
from playwright.async_api import expect

# 元素可见
await expect(page.locator("#visit-counter")).to_be_visible(timeout=5000)

# 文本内容
await expect(page.locator("#visit-count")).to_have_text("1")

# 多次访问后数字递增
await page.reload()
await expect(page.locator("#visit-count")).to_have_text("2")
```

## 本项目集成模式

```python
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

async def verify_feature(url: str, requirement_id: str, target_selector: str):
    screenshot_dir = Path(f"screenshots/{requirement_id}")
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=10000)
            try:
                await page.wait_for_selector(target_selector, state="visible", timeout=5000)
                found = True
            except Exception:
                found = False
            await page.screenshot(path=str(screenshot_dir / "verify.png"), full_page=True)
            return {"found": found, "screenshot": f"screenshots/{requirement_id}/verify.png"}
        finally:
            await browser.close()
```

## 常见坑

1. **浏览器未安装** — 首次用要跑 `playwright install chromium`，否则报 "Executable doesn't exist"。本项目 fallback 会用系统 Chrome
2. **端口未启动** — Playwright 访问前确认 DeployAgent 启动的服务在跑（`curl -I http://localhost:<port>`）
3. **动态加载内容** — SPA 里 React 组件挂载可能比 networkidle 还晚，要用 `wait_for_selector` 等具体元素
4. **字体/布局差异** — 同一 URL 在不同环境截图可能微差，验收时比对"元素存在 + 文字对"而不是像素级比对
