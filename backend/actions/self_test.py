"""Action: 开发自测 + 截图"""
import re
import asyncio
import subprocess
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List
from actions.base import ActionBase, ActionResult

logger = logging.getLogger("action.self_test")


class SelfTestAction(ActionBase):

    @property
    def name(self) -> str:
        return "self_test"

    @property
    def description(self) -> str:
        return "开发完成后自动检查 + 截图预览"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        project_id = context.get("project_id", "")
        files = context.get("_files", {})
        title = context.get("ticket_title", "")
        docs_prefix = context.get("docs_prefix", "docs/")
        module = context.get("module", "other")

        checks = []
        passed = 0
        total = 0

        if not files:
            return ActionResult(success=True, data={"self_test": {"passed": True, "total": 0, "checks": [], "summary": "无文件"}})

        file_names = list(files.keys())

        # 1. 文件产出
        total += 1
        checks.append({"name": "文件产出", "passed": True, "detail": f"{len(file_names)} 个文件"})
        passed += 1

        # 2. 入口文件
        total += 1
        has_entry = any(f in files for f in ("index.html", "main.py", "app.py"))
        if not has_entry and project_id:
            try:
                from git_manager import git_manager
                repo_dir = git_manager._repo_path(project_id)
                has_entry = any((repo_dir / f).exists() for f in ("index.html", "main.py", "app.py"))
            except Exception:
                pass
        checks.append({"name": "入口文件", "passed": has_entry, "detail": "存在" if has_entry else "缺少"})
        if has_entry: passed += 1

        # 3. 代码非空
        total += 1
        non_empty = all(len(c.strip()) > 10 for c in files.values() if not c.strip().startswith("#"))
        checks.append({"name": "代码非空", "passed": non_empty, "detail": "通过" if non_empty else "存在空文件"})
        if non_empty: passed += 1

        # 4. 语法检查
        total += 1
        syntax_ok, syntax_errors = True, []
        for fp, content in files.items():
            if fp.endswith(".py"):
                try:
                    compile(content, fp, "exec")
                except SyntaxError as e:
                    syntax_errors.append(f"{fp}: {e.msg} (line {e.lineno})")
                    syntax_ok = False
            elif fp.endswith(".html"):
                if "<html" not in content.lower() and "<!doctype" not in content.lower() and not fp.endswith(".md"):
                    syntax_errors.append(f"{fp}: 缺少 HTML 结构")
                    syntax_ok = False
        checks.append({"name": "语法检查", "passed": syntax_ok, "detail": "通过" if syntax_ok else "; ".join(syntax_errors[:3])})
        if syntax_ok: passed += 1

        # 5. 文件名规范
        total += 1
        has_chinese = any(any('\u4e00' <= c <= '\u9fff' for c in fp) for fp in file_names)
        checks.append({"name": "文件名规范", "passed": not has_chinese, "detail": "全英文" if not has_chinese else "存在中文文件名"})
        if not has_chinese: passed += 1

        summary = f"自测 {passed}/{total} 通过" + (" ✅" if passed == total else " ⚠️")

        # === 6. 截图预览（前端项目 + 有入口文件时）===
        screenshots = []
        if has_entry and module in ("frontend", "design", "other") and project_id:
            screenshots = await self._take_screenshot(project_id, title)
            if screenshots:
                total += 1
                passed += 1
                checks.append({"name": "页面截图", "passed": True, "detail": f"{len(screenshots)} 张截图"})
                summary = f"自测 {passed}/{total} 通过" + (" ✅" if passed == total else " ⚠️")

        # 生成开发笔记
        is_fallback = "[降级]" in str(context.get("dev_result", {}).get("notes", ""))

        screenshot_md = ""
        if screenshots:
            screenshot_md = "\n## 页面预览截图\n\n"
            for s in screenshots:
                screenshot_md += f"![{s['label']}]({s['url']})\n\n"

        notes_md = f"""# 开发笔记 — {title}

> {datetime.now().strftime('%Y-%m-%d %H:%M')} | {'LLM' if not is_fallback else '降级'}

## 产出文件
{chr(10).join(f'- [{fp}](/app#repo?file={fp}) ({len(c)} chars)' for fp, c in files.items() if not fp.endswith('dev-notes.md'))}

## 自测: {summary}

| 检查项 | 结果 | 说明 |
|--------|------|------|
{chr(10).join(f'| {c["name"]} | {"✅" if c["passed"] else "❌"} | {c["detail"]} |' for c in checks)}
{screenshot_md}"""

        result_files = {f"{docs_prefix}dev-notes.md": notes_md}

        return ActionResult(
            success=True,
            data={"self_test": {"passed": passed == total, "total": total, "passed_count": passed, "checks": checks, "summary": summary, "screenshots": screenshots}},
            files=result_files,
        )

    async def _take_screenshot(self, project_id: str, title: str) -> List[Dict]:
        """启动 HTTP server → Playwright 截图 → 返回截图信息"""
        from git_manager import git_manager
        from config import BASE_DIR

        repo_dir = git_manager._repo_path(project_id)
        index_path = repo_dir / "index.html"
        if not index_path.exists():
            return []

        screenshots_dir = BASE_DIR / "screenshots"
        screenshots_dir.mkdir(exist_ok=True)

        # 启动临时 HTTP server
        port = 19500 + (abs(hash(project_id)) % 500)
        proc = None
        results = []

        try:
            proc = subprocess.Popen(
                ["python", "-m", "http.server", str(port)],
                cwd=str(repo_dir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            await asyncio.sleep(2)

            if proc.poll() is not None:
                return []

            # Playwright 截图
            try:
                from playwright.async_api import async_playwright
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    page = await browser.new_page(viewport={"width": 1280, "height": 800})

                    await page.goto(f"http://localhost:{port}/", wait_until="networkidle", timeout=15000)

                    # 等页面渲染完（JS 动态内容）
                    await asyncio.sleep(1)

                    fname = f"dev_{project_id[-6:]}_{int(time.time())}.png"
                    fpath = screenshots_dir / fname
                    await page.screenshot(path=str(fpath), full_page=True)

                    results.append({
                        "filename": fname,
                        "label": f"开发自测 — {title[:30]}",
                        "url": f"/screenshots/{fname}",
                        "path": str(fpath),
                    })

                    logger.info("📸 开发截图已保存: %s", fname)
                    await browser.close()

            except ImportError:
                logger.debug("Playwright 未安装，跳过截图")
            except Exception as e:
                logger.warning("截图失败（跳过）: %s", e)

        finally:
            if proc:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    proc.kill()

        return results
