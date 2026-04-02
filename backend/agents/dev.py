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
        """开发任务（支持 tool-use agentic 模式）"""
        import os
        if os.getenv("ENABLE_AGENT_TOOLS", "").lower() in ("1", "true", "yes"):
            return await self.develop_with_tools(context)
        return await self._develop_oneshot(context)

    async def develop_with_tools(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Tool-use agentic 开发：LLM 通过 read/write/run 工具迭代实现代码"""
        from agents.skills import SKILL_SCHEMAS, SkillExecutor
        from llm_client import llm_client

        ticket_title = context.get("ticket_title", "")
        ticket_description = context.get("ticket_description", "")
        architecture = context.get("architecture", {})
        module = context.get("module", "other")
        knowledge_docs = context.get("knowledge_docs", "")
        project_id = context.get("project_id", "")
        is_bug = context.get("ticket_type") == "bug" or ticket_title.startswith("[BUG]")

        # 设置项目根目录（供 SkillExecutor 读取仓库文件）
        project_root = None
        if project_id:
            try:
                from git_manager import git_manager
                project_root = git_manager._repo_path(project_id)
            except Exception:
                pass

        executor = SkillExecutor(project_root=project_root)

        # 构建架构摘要
        arch_summary = ""
        if architecture:
            arch = architecture.get("architecture", architecture)
            compact = {k: arch[k] for k in ("architecture_type", "tech_stack", "module_design") if k in arch}
            arch_summary = json.dumps(compact, ensure_ascii=False, indent=1)[:1200]

        knowledge_section = f"\n## 项目知识库（请严格遵守）\n{knowledge_docs}\n" if knowledge_docs else ""
        task_type = "BUG 修复" if is_bug else "功能开发"

        system_prompt = f"""你是一名资深工程师，正在执行 {task_type} 任务。
你可以使用工具来读取现有文件、写入代码文件、运行验证命令。
{knowledge_section}
工作流程：
1. 先用 list_files 和 read_file 了解现有代码结构
2. 按照需求实现代码，用 write_file 写入文件
3. 必要时用 run_command 验证语法（仅 python -m py_compile / node --check）
4. 所有文件写完后，调用 finish 结束任务

约束：
- 前端项目所有代码内联到 index.html（CSS 用 <style>，JS 用 <script>）
- 如果 index.html 已存在，在其基础上修改，不要从头重写
- 技术栈必须与已有代码一致
- 文件路径使用英文，相对于项目根目录"""

        user_prompt = f"""## 任务：{ticket_title}

{ticket_description}

## 架构参考
{arch_summary}

请开始工作：先列出项目现有文件，然后实现需求。"""

        logger.info("🤖 DevAgent tool-use 模式：%s", ticket_title)

        loop_result = await llm_client.chat_with_tools(
            messages=[{"role": "user", "content": user_prompt}],
            tools=SKILL_SCHEMAS,
            tool_executor=executor,
            max_rounds=12,
            temperature=0.3,
            max_tokens=16000,
            system=system_prompt,
        )

        files = executor.written_files
        logger.info("✅ DevAgent tool-use 写入 %d 个文件: %s", len(files), list(files.keys()))

        if not files:
            logger.warning("⚠️ tool-use 模式无文件产出，降级到 one-shot")
            return await self._develop_oneshot(context)

        # 提取 finish 工具的 summary 作为 notes
        notes = ""
        for msg in reversed(loop_result["messages"]):
            if msg["role"] == "user" and isinstance(msg["content"], list):
                for block in msg["content"]:
                    if block.get("type") == "tool_result" and "[任务完成]" in block.get("content", ""):
                        notes = block["content"].replace("[任务完成]", "").strip()
                        break
            if notes:
                break

        dev_output = {
            "status": "success",
            "dev_result": {"files": files, "notes": notes},
            "estimated_hours": 4,
            "files": files,
            "bug_analysis": "",
            "fix_description": "",
            "changed_lines": [],
        }

        # 自测
        docs_prefix = context.get("docs_prefix", "docs/")
        self_test = await self._self_test(project_id, files, docs_prefix)
        dev_notes = self._generate_dev_notes(context, dev_output, self_test)
        dev_output["files"][f"{docs_prefix}dev-notes.md"] = dev_notes
        if self_test.get("media_files"):
            dev_output["_media_files"] = self_test.pop("media_files")
        dev_output["self_test"] = self_test

        return dev_output

    async def _develop_oneshot(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """开发任务（原 develop 方法，one-shot LLM 生成）"""
        ticket_title = context.get("ticket_title", "")
        ticket_description = context.get("ticket_description", "")
        architecture = context.get("architecture", {})
        module = context.get("module", "other")
        existing_code = context.get("existing_code", {})
        is_bug = context.get("ticket_type") == "bug" or ticket_title.startswith("[BUG]")
        knowledge_docs = context.get("knowledge_docs", "")

        # 知识库章节
        knowledge_section = f"\n## 项目知识库（请严格遵守以下规范）\n{knowledge_docs}\n" if knowledge_docs else ""

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

        if is_bug:
            bug_priority = context.get("bug_priority", "medium")
            bug_desc = context.get("bug_description", ticket_description)
            prompt = f"""你是一名负责 BUG 修复的高级工程师。请分析并修复以下 BUG，返回纯 JSON。
{knowledge_section}
## BUG 标题: {ticket_title}
## 优先级: {bug_priority}
## BUG 描述:
{bug_desc}

{code_section}
## 返回 JSON 格式:
{{"files": {{"文件路径": "完整文件内容（包含修复）"}}, "bug_analysis": "BUG 根因分析", "fix_description": "修复方案说明", "changed_lines": [{{"file": "文件路径", "before": "修改前关键代码片段", "after": "修改后关键代码片段"}}], "notes": "其他备注"}}

要求:
1. files 的 key 是英文文件路径，value 是修复后的完整代码
2. 前端项目：所有代码内联到 index.html（CSS 用 <style>，JS 用 <script>），可直接浏览器打开
3. 如果 index.html 已存在，只修复 BUG 相关部分，不要从零重写
4. bug_analysis 中说明 BUG 根因（代码/逻辑/边界条件等）
5. fix_description 中说明修复思路和方法
6. changed_lines 列出每处关键修改的前后对比（每处不超过 10 行）
7. 生成完整可运行代码，不要省略
"""
        else:
            prompt = f"""根据架构设计实现功能。返回纯 JSON。
{knowledge_section}
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
                # BUG 修复额外字段
                "bug_analysis": result.get("bug_analysis", "") if is_bug else "",
                "fix_description": result.get("fix_description", "") if is_bug else "",
                "changed_lines": result.get("changed_lines", []) if is_bug else [],
            }
        else:
            # LLM 返回但无 files，或返回 None
            logger.warning("⚠️ DevAgent LLM 返回无效（result=%s），使用降级模板", type(result).__name__)
            dev_output = self._fallback_develop(context)
            dev_output["bug_analysis"] = ""
            dev_output["fix_description"] = ""
            dev_output["changed_lines"] = []

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
        is_bug = context.get("ticket_type") == "bug" or title.startswith("[BUG]")

        # 自测结果表格
        checks = self_test.get("checks", [])
        test_table = "| 检查项 | 结果 | 说明 |\n|--------|------|------|\n"
        for c in checks:
            icon = "✅" if c["passed"] else "❌"
            test_table += f"| {c['name']} | {icon} | {c['detail']} |\n"

        # 文件清单
        file_list = "\n".join(f"- `{fp}` ({len(content)} chars)" for fp, content in files.items() if not fp.endswith("dev-notes.md"))

        # 文档标题差异化
        if is_bug:
            bug_priority = context.get("bug_priority", "medium")
            priority_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(bug_priority, "🟡")
            header = f"# BUG 修复报告 — {title}\n\n> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n> 优先级: {priority_icon} {bug_priority}\n> 模式: {'LLM 修复' if not is_fallback else '规则引擎降级'}"
        else:
            header = f"# 开发笔记 — {title}\n\n> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n> 模式: {'LLM 生成' if not is_fallback else '规则引擎降级'}"

        md = f"""{header}

## 任务描述
{desc[:300]}

## 产出文件
{file_list}

## 自测结果
{self_test.get('summary', '-')}

{test_table}
"""

        # ── BUG 专属章节 ──
        if is_bug:
            bug_analysis = dev_output.get("bug_analysis", "")
            fix_description = dev_output.get("fix_description", "")
            changed_lines = dev_output.get("changed_lines", [])

            if bug_analysis:
                md += f"\n---\n\n## 🔍 BUG 根因分析\n\n{bug_analysis}\n"

            if fix_description:
                md += f"\n## 🔧 修复方案\n\n{fix_description}\n"

            if changed_lines:
                md += "\n## 📝 代码修改对比\n\n"
                for i, change in enumerate(changed_lines[:10], 1):
                    file_path = change.get("file", f"文件{i}")
                    before = change.get("before", "").strip()
                    after = change.get("after", "").strip()
                    if before or after:
                        md += f"### 修改 {i}: `{file_path}`\n\n"
                        if before:
                            # 猜测语言
                            lang = "python" if file_path.endswith(".py") else "javascript" if file_path.endswith(".js") else "html" if file_path.endswith(".html") else ""
                            md += f"**修改前：**\n```{lang}\n{before[:500]}\n```\n\n"
                        if after:
                            lang = "python" if file_path.endswith(".py") else "javascript" if file_path.endswith(".js") else "html" if file_path.endswith(".html") else ""
                            md += f"**修改后：**\n```{lang}\n{after[:500]}\n```\n\n"

        # 截图
        screenshot_refs = self_test.get("screenshot_refs", [])
        if screenshot_refs:
            section_title = "## 修复后页面截图\n\n" if is_bug else "## 运行截图\n\n"
            md += f"\n{section_title}"
            for i, ref in enumerate(screenshot_refs, 1):
                label = f"截图 {i}"
                md += f"![{label}]({ref})\n\n"

        md += f"\n## {'修复备注' if is_bug else '开发备注'}\n{notes or '无'}\n"
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
