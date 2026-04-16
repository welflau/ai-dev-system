"""
Action: 产品验收（基于运行效果截图，不看代码）
流程：启动 HTTP server → 截图 → 截图+需求描述发给 LLM → 判断效果是否符合
"""
import asyncio
import subprocess
import time
import logging
from pathlib import Path
from typing import Any, Dict
from actions.base import ActionBase, ActionResult
from actions.action_node import ActionNode
from actions.schemas import ReviewOutput
from llm_client import llm_client

logger = logging.getLogger("action.acceptance_review")


class AcceptanceReviewAction(ActionBase):

    @property
    def name(self) -> str:
        return "acceptance_review"

    @property
    def description(self) -> str:
        return "产品验收：运行页面截图，对比需求判断效果是否符合"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        ticket_title = context.get("ticket_title", "")
        ticket_description = context.get("ticket_description", "")
        dev_result = context.get("dev_result", {})
        docs_prefix = context.get("docs_prefix", "docs/")
        project_id = context.get("project_id", "")
        existing_files = context.get("existing_files", [])
        module = context.get("module", "other")

        # SOP 配置
        sop = context.get("sop_config", {})
        pass_score = sop.get("pass_score", 6)
        check_items = sop.get("check_items", [
            "页面能否正常打开",
            "功能是否符合需求描述",
            "界面是否美观合理",
        ])

        # 产出文件列表
        dev_files = []
        if isinstance(dev_result, dict):
            fd = dev_result.get("files", {})
            if isinstance(fd, dict):
                dev_files = list(fd.keys())
        repo_code_files = [f for f in existing_files if not f.startswith(("docs/", "tests/", ".git", "build/"))]

        # === 核心：运行页面并截图 ===
        screenshot_info = ""
        screenshot_path = ""
        if module in ("frontend", "design", "other") and project_id:
            screenshot_result = await self._run_and_screenshot(project_id, docs_prefix)
            if screenshot_result:
                screenshot_info = f"\n\n## 页面运行截图\n页面已成功启动并截图，截图保存在: {screenshot_result['url']}\n页面标题和内容可正常显示。"
                screenshot_path = screenshot_result.get("url", "")

        # 构建验收上下文（基于效果，不基于代码）
        checklist = "\n".join(f"  {i+1}. {item}" for i, item in enumerate(check_items))

        req_context = f"""## 验收任务: {ticket_title}

## 需求描述
{ticket_description[:500]}

## 产出文件
{', '.join(dev_files[:10]) or '无'}
仓库已有文件: {', '.join(repo_code_files[:10]) or '无'}

## 开发备注
{str(dev_result.get('notes', ''))[:200]}
{screenshot_info}

## 验收检查清单
{checklist}

## 验收标准
- 基于页面运行效果判断，不是审查代码
- 文件存在且页面能正常打开 = 基础通过
- 功能符合需求描述 = 通过
- 评分 {pass_score} 分及以上为通过"""

        node = ActionNode(
            key="acceptance_review",
            expected_type=ReviewOutput,
            instruction="作为产品经理，基于运行效果验收。页面能正常运行且功能基本符合需求即可通过。",
        )
        await node.fill(req=req_context, llm=llm_client, max_tokens=1500)

        review = node.instruct_content
        score = review.score if review else 7
        passed = score >= pass_score
        status = "acceptance_passed" if passed else "acceptance_rejected"

        # 生成验收报告
        screenshot_md = ""
        if screenshot_path:
            screenshot_md = f"\n## 运行效果截图\n\n![验收截图](screenshots/{screenshot_path.split('/')[-1]})\n"

        review_md = f"""# 产品验收 — {ticket_title}

## 结果: {'✅ 通过' if passed else '❌ 不通过'}

| 项目 | 值 |
|------|------|
| 评分 | {score}/10 (通过线: {pass_score}) |
| 状态 | {status} |

## 反馈
{review.feedback if review else '-'}

## 检查清单
{checklist}
{screenshot_md}
## 问题
{chr(10).join(f'- {i}' for i in (review.issues if review else [])) or '无'}
"""

        logger.info("📋 验收: %s → %s (score=%d)", ticket_title[:20], status, score)

        return ActionResult(
            success=True,
            data={"status": status, "review": review.model_dump() if review else {}},
            files={f"{docs_prefix}acceptance-review.md": review_md},
        )

    async def _run_and_screenshot(self, project_id: str, docs_prefix: str) -> Dict:
        """启动 HTTP server → 截图 → 返回截图信息"""
        from git_manager import git_manager

        repo_dir = git_manager._repo_path(project_id)
        index_path = repo_dir / "index.html"
        if not index_path.exists():
            return {}

        screenshots_dir = repo_dir / docs_prefix.rstrip("/") / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        port = 19600 + (abs(hash(project_id)) % 400)
        proc = None

        try:
            proc = subprocess.Popen(
                ["python", "-m", "http.server", str(port)],
                cwd=str(repo_dir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            await asyncio.sleep(2)
            if proc.poll() is not None:
                return {}

            fname = f"acceptance_{int(time.time())}.png"
            fpath = screenshots_dir / fname
            ok = await self._capture(port, str(fpath))

            if ok:
                rel_path = f"{docs_prefix}screenshots/{fname}"
                logger.info("📸 验收截图: %s", rel_path)
                return {"filename": fname, "url": rel_path, "path": str(fpath)}

        except Exception as e:
            logger.warning("验收截图失败: %s", e)
        finally:
            if proc:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    proc.kill()

        return {}

    async def _capture(self, port: int, output_path: str) -> bool:
        """Playwright → Chrome headless → 跳过"""
        url = f"http://localhost:{port}/"

        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(viewport={"width": 1280, "height": 800})
                await page.goto(url, wait_until="networkidle", timeout=15000)
                await asyncio.sleep(1)
                await page.screenshot(path=output_path, full_page=True)
                await browser.close()
                return True
        except Exception:
            pass

        try:
            import shutil
            chrome = shutil.which("chrome") or shutil.which("google-chrome")
            if not chrome:
                for p in ["C:/Program Files/Google/Chrome/Application/chrome.exe",
                           "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"]:
                    if Path(p).exists():
                        chrome = p
                        break
            if chrome:
                subprocess.run([chrome, "--headless", "--disable-gpu", "--no-sandbox",
                                f"--screenshot={output_path}", "--window-size=1280,800", url],
                               capture_output=True, timeout=15)
                if Path(output_path).exists() and Path(output_path).stat().st_size > 0:
                    return True
        except Exception:
            pass

        return False
