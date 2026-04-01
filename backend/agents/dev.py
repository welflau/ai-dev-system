"""
DevAgent — 开发 Agent
职责：接单开发代码 → 自测 → 输出开发笔记和测试结果
"""
import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List
from datetime import datetime
from agents.base import BaseAgent
from llm_client import llm_client

logger = logging.getLogger("dev_agent")


class DevAgent(BaseAgent):

    @property
    def agent_type(self) -> str:
        return "DevAgent"

    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if task_name == "develop":
            return await self.develop(context)
        elif task_name == "rework":
            return await self.rework(context)
        elif task_name == "fix_issues":
            return await self.fix_issues(context)
        else:
            return {"status": "error", "message": f"未知任务: {task_name}"}

    async def develop(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """开发任务"""
        ticket_title = context.get("ticket_title", "")
        ticket_description = context.get("ticket_description", "")
        architecture = context.get("architecture", {})
        module = context.get("module", "other")
        existing_code = context.get("existing_code", {})

        # 精简架构信息（只保留关键字段，避免 token 爆炸）
        arch_summary = ""
        if architecture:
            arch = architecture.get("architecture", architecture)
            # 只保留模块设计和技术栈
            compact = {}
            for key in ("architecture_type", "tech_stack", "module_design", "key_components"):
                if key in arch:
                    compact[key] = arch[key]
            arch_summary = json.dumps(compact, ensure_ascii=False, indent=1) if compact else json.dumps(arch, ensure_ascii=False)[:1500]

        # 精简已有代码（只保留入口文件，限制总长度）
        code_section = ""
        if existing_code:
            # 优先 index.html，其次 main.py
            for fp in ["index.html", "main.py", "app.py"]:
                if fp in existing_code:
                    content = existing_code[fp][:2000]
                    code_section = f"\n## 现有入口文件 {fp}（在此基础上修改）\n```\n{content}\n```\n"
                    break

        prompt = f"""根据架构设计实现功能。返回纯 JSON。

## 任务: {ticket_title}
{ticket_description}

## 架构
{arch_summary}
{code_section}
## 返回 JSON 格式:
{{"files": {{"文件路径": "完整文件内容"}}, "notes": "备注"}}

要求:
1. files 的 key 是英文文件路径，value 是完整代码
2. 前端项目：所有代码内联到 index.html（CSS 用 <style>，JS 用 <script>），可直接浏览器打开
3. 如果 index.html 已存在，在其基础上添加功能，不要从零重写
4. 只输出需要新建或修改的文件
5. 生成完整可运行代码，不要省略
"""

        result = await llm_client.chat_json(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=16000,
        )

        if result and isinstance(result, dict) and result.get("files"):
            files = result.get("files", {})
            logger.info("✅ DevAgent LLM 返回 %d 个文件", len(files))
            dev_output = {
                "status": "success",
                "dev_result": result,
                "estimated_hours": result.get("estimated_hours", 4),
                "files": files if isinstance(files, dict) else {},
            }
        else:
            # LLM 返回但无 files，或返回 None
            logger.warning("⚠️ DevAgent LLM 返回无效（result=%s），使用降级模板", type(result).__name__)
            dev_output = self._fallback_develop(context)

        # === 自测：开发完成后运行基础测试 ===
        project_id = context.get("project_id", "")
        docs_prefix = context.get("docs_prefix", "docs/")
        self_test = await self._self_test(project_id, dev_output.get("files", {}), docs_prefix)

        # 生成开发笔记（含自测结果）
        dev_notes = self._generate_dev_notes(context, dev_output, self_test)
        dev_output["files"][f"{docs_prefix}dev-notes.md"] = dev_notes
        # 把截图二进制数据单独放到 _media_files，orchestrator 负责写入
        if self_test.get("media_files"):
            dev_output["_media_files"] = self_test.pop("media_files")
        dev_output["self_test"] = self_test

        return dev_output

    async def _self_test(self, project_id: str, files: Dict[str, str], docs_prefix: str = "docs/") -> Dict:
        """开发完成后自测：检查文件完整性 + 语法 + 入口文件 + HTML 截图"""
        checks = []
        passed = 0
        total = 0

        if not files:
            return {"passed": False, "total": 0, "passed_count": 0, "checks": [], "summary": "无文件产出"}

        # 检查 1: 文件数量
        total += 1
        file_names = list(files.keys())
        checks.append({"name": "文件产出", "passed": True, "detail": f"生成 {len(file_names)} 个文件: {', '.join(file_names)}"})
        passed += 1

        # 检查 2: 入口文件存在
        total += 1
        has_entry = any(f in files for f in ("index.html", "main.py", "app.py"))
        # 也检查仓库中是否已有入口文件
        if not has_entry and project_id:
            try:
                from git_manager import git_manager
                repo_dir = git_manager._repo_path(project_id)
                has_entry = any((repo_dir / f).exists() for f in ("index.html", "main.py", "app.py"))
            except Exception:
                pass
        checks.append({"name": "入口文件", "passed": has_entry, "detail": "index.html 或 main.py 存在" if has_entry else "缺少入口文件"})
        if has_entry:
            passed += 1

        # 检查 3: 代码非空
        total += 1
        non_empty = all(len(content.strip()) > 10 for content in files.values() if not content.strip().startswith("#"))
        checks.append({"name": "代码非空", "passed": non_empty, "detail": "所有文件均包含实际代码" if non_empty else "存在空文件或仅有注释的文件"})
        if non_empty:
            passed += 1

        # 检查 4: JS 语法（内存检查，不需要仓库）
        total += 1
        syntax_ok = True
        syntax_errors = []
        for fp, content in files.items():
            if fp.endswith(".js") or fp.endswith(".jsx"):
                # 简单检查：括号匹配
                if content.count("{") != content.count("}") or content.count("(") != content.count(")"):
                    syntax_errors.append(f"{fp}: 括号不匹配")
                    syntax_ok = False
            elif fp.endswith(".py"):
                try:
                    compile(content, fp, "exec")
                except SyntaxError as e:
                    syntax_errors.append(f"{fp}: {e.msg} (line {e.lineno})")
                    syntax_ok = False
            elif fp.endswith(".html"):
                if "<html" not in content.lower() and "<!doctype" not in content.lower():
                    if not fp.endswith(".md"):
                        syntax_errors.append(f"{fp}: 缺少 HTML 基础结构")
                        syntax_ok = False
        checks.append({"name": "语法检查", "passed": syntax_ok, "detail": "通过" if syntax_ok else "; ".join(syntax_errors[:3])})
        if syntax_ok:
            passed += 1

        # 检查 5: 无中文文件名
        total += 1
        has_chinese_name = any(any('\u4e00' <= c <= '\u9fff' for c in fp) for fp in file_names)
        checks.append({"name": "文件名规范", "passed": not has_chinese_name, "detail": "全部英文命名" if not has_chinese_name else "存在中文文件名"})
        if not has_chinese_name:
            passed += 1

        all_passed = passed == total
        summary = f"自测 {passed}/{total} 通过" + (" ✅" if all_passed else " ⚠️")
        logger.info("🔍 DevAgent 自测: %s", summary)

        # === 截图：对 HTML 入口文件用 Playwright 截图 ===
        media_files: Dict[str, bytes] = {}
        screenshot_refs: List[str] = []   # 在 dev-notes.md 里引用的相对路径
        try:
            html_files = [fp for fp in files if fp.endswith(".html")]
            if html_files and project_id:
                from git_manager import git_manager
                repo_dir = git_manager._repo_path(project_id)
                medias_rel = f"{docs_prefix}Medias/"   # 相对仓库根
                screenshots = await self._take_html_screenshots(repo_dir, html_files, files)
                for name, img_bytes in screenshots.items():
                    media_files[f"{medias_rel}{name}"] = img_bytes
                    screenshot_refs.append(f"./Medias/{name}")
                    logger.info("📸 截图完成: %s (%d bytes)", name, len(img_bytes))
        except Exception as e:
            logger.warning("截图失败（不影响主流程）: %s", e)

        return {
            "passed": all_passed,
            "total": total,
            "passed_count": passed,
            "checks": checks,
            "summary": summary,
            "screenshot_refs": screenshot_refs,
            "media_files": media_files,   # {仓库相对路径: bytes}
        }

    async def _take_html_screenshots(
        self, repo_dir: Path, html_files: List[str], files: Dict[str, str]
    ) -> Dict[str, bytes]:
        """用 Playwright 对 HTML 文件截图，返回 {文件名: png字节}"""
        import tempfile, os
        from playwright.async_api import async_playwright

        results: Dict[str, bytes] = {}
        # 先把文件写到临时目录
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            # 把所有产出文件写进去（保持相对路径）
            for fp, content in files.items():
                dest = tmp / fp
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(viewport={"width": 1280, "height": 800})
                for fp in html_files[:3]:   # 最多截 3 个页面
                    html_path = tmp / fp
                    if not html_path.exists():
                        continue
                    try:
                        await page.goto(f"file:///{html_path.as_posix()}", wait_until="networkidle", timeout=10000)
                        await page.wait_for_timeout(800)   # 等渲染
                        img = await page.screenshot(full_page=False, type="png")
                        # 文件名：用路径末段
                        safe_name = fp.replace("/", "_").replace("\\", "_")
                        if not safe_name.endswith(".png"):
                            safe_name = safe_name.rsplit(".", 1)[0] + ".png"
                        results[f"screenshot_{safe_name}"] = img
                    except Exception as e:
                        logger.warning("截图 %s 失败: %s", fp, e)
                await browser.close()
        return results

    def _generate_dev_notes(self, context: Dict, dev_output: Dict, self_test: Dict) -> str:
        """生成开发笔记（含自测结果）"""
        title = context.get("ticket_title", "")
        desc = context.get("ticket_description", "")
        files = dev_output.get("files", {})
        notes = dev_output.get("dev_result", {}).get("notes", "")
        is_fallback = "[降级]" in str(dev_output.get("dev_result", {}).get("key_implementations", ""))

        # 自测结果表格
        checks = self_test.get("checks", [])
        test_table = "| 检查项 | 结果 | 说明 |\n|--------|------|------|\n"
        for c in checks:
            icon = "✅" if c["passed"] else "❌"
            test_table += f"| {c['name']} | {icon} | {c['detail']} |\n"

        # 文件清单
        file_list = "\n".join(f"- `{fp}` ({len(content)} chars)" for fp, content in files.items() if not fp.endswith("dev-notes.md"))

        md = f"""# 开发笔记 — {title}

> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}
> 模式: {'LLM 生成' if not is_fallback else '规则引擎降级'}

## 任务描述
{desc[:300]}

## 产出文件
{file_list}

## 自测结果
{self_test.get('summary', '-')}

{test_table}
"""
        # 截图
        screenshot_refs = self_test.get("screenshot_refs", [])
        if screenshot_refs:
            md += "\n## 运行截图\n\n"
            for ref in screenshot_refs:
                md += f"![截图]({ref})\n\n"

        md += f"\n## 开发备注\n{notes or '无'}\n"
        return md

    def _fallback_develop(self, context: Dict) -> Dict:
        """规则引擎降级：生成可运行的代码"""
        import re
        title = context.get("ticket_title", "feature")
        description = context.get("ticket_description", "")
        module = context.get("module", "other")
        existing_code = context.get("existing_code", {})

        # 英文安全文件名
        safe = re.sub(r'[^a-zA-Z0-9_]', '', re.sub(r'[\u4e00-\u9fff]+', '', title.replace(" ", "_").replace("-", "_")))
        if not safe:
            safe = f"feature_{abs(hash(title)) % 10000}"
        safe = safe[:30].lower()

        files = {}

        if module in ("frontend", "design", "other"):
            # 如果 index.html 已存在，不覆盖，只生成说明
            if "index.html" in existing_code:
                files[f"src/{safe}.js"] = f"""// {title} - 功能模块
// TODO: 实现 {description[:80]}
console.log('{safe} module loaded');
"""
            else:
                # 生成完整可运行的 index.html
                files["index.html"] = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f0f2f5; min-height: 100vh; display: flex; justify-content: center; align-items: center; }}
        .container {{ background: white; border-radius: 12px; padding: 40px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); max-width: 600px; width: 90%; text-align: center; }}
        h1 {{ color: #1a1a2e; margin-bottom: 16px; font-size: 2rem; }}
        p {{ color: #666; line-height: 1.6; margin-bottom: 20px; }}
        .badge {{ display: inline-block; background: #e8f5e9; color: #2e7d32; padding: 4px 12px; border-radius: 20px; font-size: 14px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{title}</h1>
        <p>{description[:200] if description else 'AI 自动开发系统生成的页面'}</p>
        <span class="badge">✅ 运行中</span>
    </div>
</body>
</html>"""

        elif module in ("backend", "api"):
            files["main.py"] = f"""\"\"\"
{title} - 后端服务
\"\"\"
from http.server import HTTPServer, SimpleHTTPRequestHandler
import json

class APIHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({{"status": "ok", "service": "{safe}"}}).encode())
        else:
            super().do_GET()

if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', 8080), APIHandler)
    print('Server running on http://localhost:8080')
    server.serve_forever()
"""

        elif module == "database":
            files[f"src/models/{safe}.py"] = f"""\"\"\"
{title} - 数据模型
\"\"\"

{safe.upper()}_SCHEMA = {{
    "table": "{safe}",
    "columns": [
        {{"name": "id", "type": "TEXT PRIMARY KEY"}},
        {{"name": "name", "type": "TEXT NOT NULL"}},
        {{"name": "created_at", "type": "TEXT NOT NULL"}},
    ]
}}
"""

        return {
            "status": "success",
            "dev_result": {
                "files": files,
                "key_implementations": [f"[降级] {title}"],
                "estimated_hours": 2,
                "notes": "[规则引擎降级] LLM 不可用，生成基础可运行代码",
            },
            "estimated_hours": 2,
            "files": files,
        }

    async def rework(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """返工（验收不通过打回）"""
        rejection_reason = context.get("rejection_reason", "")
        return await self.develop({
            **context,
            "ticket_description": f"{context.get('ticket_description', '')} [返工原因] {rejection_reason}",
        })

    async def fix_issues(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """修复问题（测试不通过打回）"""
        test_issues = context.get("test_issues", [])
        return await self.develop({
            **context,
            "ticket_description": f"{context.get('ticket_description', '')} [测试问题] {json.dumps(test_issues, ensure_ascii=False)}",
        })
