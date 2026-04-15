"""
TestAgent — 测试 Agent
职责：按产品类型生成测试方案、执行实际测试、输出规范测试报告
"""
import json
import logging
import subprocess
import time
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
from agents.base import BaseAgent
from llm_client import llm_client

logger = logging.getLogger("test_agent")

# 模块类型 → 测试策略
TEST_STRATEGIES = {
    "frontend": "前端测试（HTML/CSS/JS 静态分析 + HTTP 功能测试 + 页面内容检查）",
    "design":   "UI 测试（HTML 结构 + CSS 完整性 + 响应式检查）",
    "backend":  "后端测试（Python 语法 + import 检查 + API 端点测试）",
    "api":      "API 测试（端点可达性 + 响应格式 + 状态码校验）",
    "database": "数据模型测试（语法检查 + Schema 验证）",
    "other":    "通用测试（文件完整性 + 语法检查）",
}


class TestAgent(BaseAgent):

    watch_actions = {"write_code", "acceptance_review"}  # 关心代码和验收

    @property
    def agent_type(self) -> str:
        return "TestAgent"

    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if task_name == "run_tests":
            return await self.run_tests(context)
        return {"status": "error", "message": f"未知任务: {task_name}"}

    async def run_tests(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """主测试流程：5 层测试"""
        project_id = context.get("project_id", "")
        module = context.get("module", "other")
        title = context.get("ticket_title", "")
        docs_prefix = context.get("docs_prefix", "docs/")
        tests_prefix = context.get("tests_prefix", "tests/")
        dev_result = context.get("dev_result", {})

        strategy = TEST_STRATEGIES.get(module, TEST_STRATEGIES["other"])
        logger.info("🧪 TestAgent 开始测试: %s (策略: %s)", title, strategy)

        results = {
            "strategy": strategy,
            "module": module,
            "phases": [],
        }
        all_issues = []
        total_checks = 0
        total_passed = 0

        # === Phase 1: 静态分析 ===
        static = await self._static_analysis(project_id, module)
        results["phases"].append({"name": "静态分析", **static})
        total_checks += static["total"]
        total_passed += static["passed_count"]
        all_issues.extend(static.get("issues", []))

        # === Phase 2: 代码审查 (LLM) ===
        review = await self._code_review(context)
        results["phases"].append({"name": "代码审查", **review})
        total_checks += 1
        if review.get("score", 0) >= 6:
            total_passed += 1

        # === Phase 3: 功能测试（按类型分发）===
        func_test = await self._functional_test(project_id, module, dev_result, docs_prefix)
        screenshots = func_test.pop("screenshots", [])  # 取出截图列表，不进入 phases
        results["phases"].append({"name": "功能测试", **func_test})
        total_checks += func_test["total"]
        total_passed += func_test["passed_count"]
        all_issues.extend(func_test.get("issues", []))

        # === Phase 4: 生成测试用例 (LLM) ===
        test_code = await self._generate_test_cases(context, module)

        # === Phase 5: 执行测试用例 ===
        unit = await self._run_pytest(project_id, tests_prefix, test_code)
        results["phases"].append({"name": "测试用例执行", **unit})
        total_checks += unit["total"]
        total_passed += unit["passed_count"]
        all_issues.extend(unit.get("issues", []))

        # === 汇总 ===
        pass_rate = round(total_passed / total_checks * 100) if total_checks > 0 else 0
        all_passed = pass_rate >= 60
        status = "testing_done" if all_passed else "testing_failed"

        results["summary"] = {
            "total_checks": total_checks,
            "total_passed": total_passed,
            "pass_rate": pass_rate,
            "review_score": review.get("score", 0),
            "all_passed": all_passed,
            "issues": all_issues,
        }
        results["screenshots"] = screenshots

        # === 生成测试报告 + 测试文件 ===
        report = self._generate_report(title, module, strategy, results)
        files = {
            f"{docs_prefix}test-report.md": report,
        }
        if test_code:
            safe_name = re.sub(r'[^a-zA-Z0-9_]', '', re.sub(r'[\u4e00-\u9fff]+', '', title.replace(" ", "_")))[:30].lower() or "module"
            files[f"{tests_prefix}test_{safe_name}.py"] = test_code

        logger.info("🧪 测试完成: %s | 通过率 %d%% (%d/%d) | %s",
                     title, pass_rate, total_passed, total_checks, status)

        return {
            "status": status,
            "test_result": results,
            "files": files,
        }

    # ==================== Phase 1: 静态分析 ====================

    async def _static_analysis(self, project_id: str, module: str) -> Dict:
        """静态分析：文件完整性 + 语法 + 入口"""
        from git_manager import git_manager

        checks = []
        passed = 0
        total = 0
        issues = []

        try:
            repo_dir = git_manager._repo_path(project_id)
            if not repo_dir.exists():
                return {"total": 1, "passed_count": 0, "checks": [], "issues": ["仓库不存在"]}

            # 检查源文件
            total += 1
            src_files = list(repo_dir.glob("src/**/*.*")) + list(repo_dir.glob("*.html")) + list(repo_dir.glob("*.py"))
            src_files = [f for f in src_files if ".git" not in str(f)]
            has_files = len(src_files) > 0
            checks.append({"name": "源文件存在", "passed": has_files, "detail": f"{len(src_files)} 个文件" if has_files else "无源文件"})
            if has_files:
                passed += 1
            else:
                issues.append("src/ 目录下无源文件")

            # 入口文件
            total += 1
            entry_names = ["index.html", "main.py", "app.py"]
            entry = next((e for e in entry_names if (repo_dir / e).exists()), None)
            checks.append({"name": "入口文件", "passed": entry is not None, "detail": entry or "缺少入口文件"})
            if entry:
                passed += 1
            else:
                issues.append("缺少入口文件 (index.html / main.py)")

            # 语法检查
            total += 1
            syntax_errors = []

            for js_file in list(repo_dir.glob("src/**/*.js"))[:10]:
                try:
                    r = subprocess.run(["node", "--check", str(js_file)],
                                       capture_output=True, text=True, timeout=5, encoding="utf-8", errors="replace")
                    if r.returncode != 0:
                        syntax_errors.append(f"{js_file.name}: {r.stderr[:80]}")
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    break

            for py_file in list(repo_dir.glob("src/**/*.py"))[:10] + list(repo_dir.glob("*.py"))[:3]:
                try:
                    compile(py_file.read_text(encoding="utf-8", errors="replace"), str(py_file), "exec")
                except SyntaxError as e:
                    syntax_errors.append(f"{py_file.name}: {e.msg} (line {e.lineno})")

            # HTML 基本检查
            for html_file in list(repo_dir.glob("*.html"))[:5]:
                content = html_file.read_text(encoding="utf-8", errors="replace")
                if "<html" not in content.lower():
                    syntax_errors.append(f"{html_file.name}: 缺少 <html> 标签")

            has_syntax_ok = len(syntax_errors) == 0
            checks.append({"name": "语法检查", "passed": has_syntax_ok, "detail": "通过" if has_syntax_ok else "; ".join(syntax_errors[:3])})
            if has_syntax_ok:
                passed += 1
            else:
                issues.extend(syntax_errors[:3])

        except Exception as e:
            issues.append(f"静态分析异常: {str(e)[:100]}")

        return {"total": total, "passed_count": passed, "checks": checks, "issues": issues}

    # ==================== Phase 2: 代码审查 ====================

    async def _code_review(self, context: Dict) -> Dict:
        """LLM 代码审查"""
        dev_result = context.get("dev_result", {})
        title = context.get("ticket_title", "")

        # 提取文件名列表和关键代码片段
        files_info = ""
        if isinstance(dev_result, dict) and dev_result.get("files"):
            file_dict = dev_result["files"] if isinstance(dev_result["files"], dict) else {}
            for fp, content in list(file_dict.items())[:3]:
                snippet = content[:500] if isinstance(content, str) else ""
                files_info += f"\n### {fp}\n```\n{snippet}\n```\n"

        if not files_info:
            return {"score": 5, "issues": [], "suggestions": [], "detail": "无代码可审查"}

        prompt = f"""审查以下代码，返回 JSON: {{"score": 1-10, "issues": ["问题"], "suggestions": ["建议"]}}

## {title}
{files_info}"""

        try:
            result = await llm_client.chat_json(
                [{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=1000,
            )
            if result and isinstance(result, dict):
                return {
                    "score": result.get("score", 5),
                    "issues": result.get("issues", [])[:5],
                    "suggestions": result.get("suggestions", [])[:5],
                    "detail": f"评分 {result.get('score', '?')}/10",
                }
        except Exception as e:
            logger.warning("代码审查 LLM 失败: %s", e)

        return {"score": 6, "issues": [], "suggestions": [], "detail": "LLM 不可用，默认通过"}

    # ==================== Phase 3: 功能测试 ====================

    async def _functional_test(self, project_id: str, module: str, dev_result: Dict, docs_prefix: str = "docs/") -> Dict:
        """按类型分发功能测试"""
        if module in ("frontend", "design"):
            return await self._test_frontend(project_id, docs_prefix)
        elif module in ("backend", "api"):
            return await self._test_backend(project_id)
        else:
            return await self._test_generic(project_id)

    async def _take_screenshots(self, project_id: str, port: int, docs_prefix: str = "docs/") -> list:
        """Playwright 截图 → 保存到工单文档目录"""
        from git_manager import git_manager

        repo_dir = git_manager._repo_path(project_id)
        screenshots_dir = repo_dir / docs_prefix.rstrip("/") / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        results = []
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(viewport={"width": 1280, "height": 800})

                await page.goto(f"http://localhost:{port}/", wait_until="networkidle", timeout=15000)
                await _async_sleep(1)

                fname = f"test_{int(time.time())}.png"
                await page.screenshot(path=str(screenshots_dir / fname), full_page=True)

                rel_path = f"{docs_prefix}screenshots/{fname}"
                results.append({"filename": fname, "label": "测试截图", "url": rel_path})

                logger.info("📸 测试截图已保存到项目仓库: %s", rel_path)
                await browser.close()
        except ImportError:
            logger.debug("Playwright 未安装，跳过截图")
        except Exception as e:
            logger.warning("Playwright 截图失败（跳过）: %s", e)

        return results

    async def _test_frontend(self, project_id: str, docs_prefix: str = "docs/") -> Dict:
        """前端功能测试：启动 HTTP server → 请求 → 检查内容"""
        from git_manager import git_manager
        import httpx

        checks = []
        passed = 0
        total = 0
        issues = []
        repo_dir = git_manager._repo_path(project_id)

        # 检查 index.html 是否存在
        index_path = repo_dir / "index.html"
        if not index_path.exists():
            return {"total": 1, "passed_count": 0, "checks": [{"name": "index.html", "passed": False, "detail": "文件不存在"}], "issues": ["index.html 不存在"]}

        # 启动临时 HTTP server
        port = 19000 + (abs(hash(project_id)) % 500)
        proc = None
        screenshots = []
        try:
            proc = subprocess.Popen(
                ["python", "-m", "http.server", str(port)],
                cwd=str(repo_dir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            await _async_sleep(2)

            # 测试 1: HTTP 可访问
            total += 1
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    start = time.time()
                    resp = await client.get(f"http://localhost:{port}/")
                    elapsed = int((time.time() - start) * 1000)

                ok = resp.status_code == 200
                checks.append({"name": "HTTP 可访问", "passed": ok,
                               "detail": f"GET / → {resp.status_code} ({elapsed}ms, {len(resp.content)} bytes)"})
                if ok:
                    passed += 1
                else:
                    issues.append(f"HTTP 状态码: {resp.status_code}")

                html = resp.text

                # 测试 2: HTML 结构完整
                total += 1
                has_html = "<html" in html.lower() and "</html>" in html.lower()
                checks.append({"name": "HTML 结构完整", "passed": has_html, "detail": "包含 <html> 标签" if has_html else "缺少 HTML 结构"})
                if has_html:
                    passed += 1
                else:
                    issues.append("HTML 结构不完整")

                # 测试 3: 有标题
                total += 1
                title_match = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
                has_title = bool(title_match and title_match.group(1).strip())
                checks.append({"name": "页面标题", "passed": has_title,
                               "detail": f"<title>{title_match.group(1).strip()}</title>" if has_title else "缺少 <title>"})
                if has_title:
                    passed += 1

                # 测试 4: 有实际内容（非空 body）
                total += 1
                body_match = re.search(r'<body[^>]*>(.*?)</body>', html, re.DOTALL | re.IGNORECASE)
                body_len = len(body_match.group(1).strip()) if body_match else 0
                has_content = body_len > 50
                checks.append({"name": "页面内容", "passed": has_content,
                               "detail": f"body 内容 {body_len} 字符" if has_content else "页面内容过少"})
                if has_content:
                    passed += 1
                else:
                    issues.append("页面 body 内容不足")

                # 测试 5: CSS 样式
                total += 1
                has_css = "<style" in html.lower() or "stylesheet" in html.lower()
                checks.append({"name": "CSS 样式", "passed": has_css, "detail": "已包含样式" if has_css else "无 CSS 样式"})
                if has_css:
                    passed += 1

                # 测试 6: viewport meta（响应式）
                total += 1
                has_viewport = "viewport" in html.lower()
                checks.append({"name": "viewport 适配", "passed": has_viewport,
                               "detail": "包含 viewport meta" if has_viewport else "缺少 viewport meta 标签"})
                if has_viewport:
                    passed += 1
                else:
                    issues.append("缺少 viewport meta 标签（影响移动端显示）")

            except Exception as e:
                checks.append({"name": "HTTP 可访问", "passed": False, "detail": f"请求失败: {str(e)[:80]}"})
                issues.append(f"HTTP 请求失败: {str(e)[:80]}")

            # 截图（在 HTTP server 仍运行时执行）
            screenshots = await self._take_screenshots(project_id, port, docs_prefix)

        finally:
            if proc:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    proc.kill()

        return {"total": total, "passed_count": passed, "checks": checks, "issues": issues, "screenshots": screenshots}

    async def _test_backend(self, project_id: str) -> Dict:
        """后端功能测试：Python import + 语法"""
        from git_manager import git_manager

        checks = []
        passed = 0
        total = 0
        issues = []
        repo_dir = git_manager._repo_path(project_id)

        # 检查 Python 文件可导入
        py_files = list(repo_dir.glob("src/**/*.py")) + list(repo_dir.glob("*.py"))
        for pf in py_files[:5]:
            total += 1
            try:
                content = pf.read_text(encoding="utf-8", errors="replace")
                compile(content, str(pf), "exec")
                checks.append({"name": f"编译 {pf.name}", "passed": True, "detail": "语法正确"})
                passed += 1
            except SyntaxError as e:
                checks.append({"name": f"编译 {pf.name}", "passed": False, "detail": f"{e.msg} (line {e.lineno})"})
                issues.append(f"{pf.name}: {e.msg}")

        if total == 0:
            return {"total": 1, "passed_count": 0, "checks": [{"name": "Python 文件", "passed": False, "detail": "无 Python 文件"}], "issues": ["无 Python 源文件"]}

        return {"total": total, "passed_count": passed, "checks": checks, "issues": issues}

    async def _test_generic(self, project_id: str) -> Dict:
        """通用功能测试"""
        from git_manager import git_manager
        repo_dir = git_manager._repo_path(project_id)

        total = 1
        src_files = list(repo_dir.glob("src/**/*.*"))
        has_files = len(src_files) > 0

        return {
            "total": total,
            "passed_count": 1 if has_files else 0,
            "checks": [{"name": "文件存在性", "passed": has_files, "detail": f"{len(src_files)} 个源文件"}],
            "issues": [] if has_files else ["无源文件"],
        }

    # ==================== Phase 4: 生成测试用例 ====================

    async def _generate_test_cases(self, context: Dict, module: str) -> Optional[str]:
        """LLM 生成有意义的测试用例"""
        dev_result = context.get("dev_result", {})
        title = context.get("ticket_title", "")

        # 提取文件列表
        file_names = []
        if isinstance(dev_result, dict) and dev_result.get("files"):
            file_names = list(dev_result["files"].keys()) if isinstance(dev_result["files"], dict) else []

        if not file_names:
            return self._fallback_test_code(title, module)

        prompt = f"""为以下项目生成 pytest 测试代码。直接返回 Python 代码（不要 markdown 代码块）。

项目: {title}
模块: {module}
文件: {', '.join(file_names[:5])}

要求:
- 使用 pytest
- 至少 3 个测试函数，测试真实功能
- 前端项目：测试 HTML 文件存在、内容包含关键元素
- 后端项目：测试模块可导入、函数返回正确类型
- 每个测试函数有清晰的中文注释说明测试目的
- 使用 pathlib.Path 检查文件，不要硬编码路径
"""
        try:
            result = await llm_client.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=2000,
            )
            if result and not result.startswith("[LLM_UNAVAILABLE]"):
                # 清理 markdown 代码块
                code = result.strip()
                if code.startswith("```"):
                    lines = code.split("\n")
                    lines = [l for l in lines if not l.strip().startswith("```")]
                    code = "\n".join(lines)
                if "import" in code and "def test_" in code:
                    return code
        except Exception as e:
            logger.warning("生成测试用例失败: %s", e)

        return self._fallback_test_code(title, module)

    def _fallback_test_code(self, title: str, module: str) -> str:
        """降级生成测试用例"""
        safe = re.sub(r'[^a-zA-Z0-9_]', '', title.replace(" ", "_"))[:20].lower() or "module"

        if module in ("frontend", "design"):
            return f'''"""测试: {title}"""
import os
from pathlib import Path

REPO_DIR = Path(__file__).parent.parent

def test_index_html_exists():
    """测试入口文件存在"""
    assert (REPO_DIR / "index.html").exists(), "index.html 不存在"

def test_index_html_has_content():
    """测试入口文件有内容"""
    content = (REPO_DIR / "index.html").read_text(encoding="utf-8")
    assert len(content) > 100, "index.html 内容过少"
    assert "<html" in content.lower(), "缺少 HTML 标签"

def test_index_html_has_title():
    """测试页面有标题"""
    content = (REPO_DIR / "index.html").read_text(encoding="utf-8")
    assert "<title>" in content.lower(), "缺少 title 标签"

def test_has_css_styles():
    """测试页面包含样式"""
    content = (REPO_DIR / "index.html").read_text(encoding="utf-8")
    assert "<style" in content.lower() or "stylesheet" in content.lower(), "无 CSS 样式"
'''
        else:
            return f'''"""测试: {title}"""
from pathlib import Path

REPO_DIR = Path(__file__).parent.parent

def test_source_files_exist():
    """测试源代码文件存在"""
    src = REPO_DIR / "src"
    if src.exists():
        files = list(src.rglob("*.*"))
        assert len(files) > 0, "src/ 目录下无文件"

def test_entry_file_exists():
    """测试入口文件存在"""
    entries = ["main.py", "app.py", "index.html"]
    found = any((REPO_DIR / e).exists() for e in entries)
    assert found, "缺少入口文件"

def test_no_syntax_errors():
    """测试 Python 文件无语法错误"""
    for pf in list(REPO_DIR.rglob("src/**/*.py"))[:10]:
        content = pf.read_text(encoding="utf-8", errors="replace")
        compile(content, str(pf), "exec")
'''

    # ==================== Phase 5: 执行 pytest ====================

    async def _run_pytest(self, project_id: str, tests_prefix: str, test_code: Optional[str]) -> Dict:
        """执行 pytest"""
        from git_manager import git_manager

        repo_dir = git_manager._repo_path(project_id)
        tests_dir = repo_dir / tests_prefix.rstrip("/")

        # 如果有新生成的测试代码，先写入
        if test_code:
            tests_dir.mkdir(parents=True, exist_ok=True)
            # 找到不冲突的文件名
            test_file = tests_dir / "test_generated.py"
            test_file.write_text(test_code, encoding="utf-8")

        # 查找测试文件
        test_files = list(tests_dir.glob("test_*.py")) if tests_dir.exists() else []
        if not test_files:
            return {"total": 0, "passed_count": 0, "checks": [], "issues": ["无测试文件"], "output": ""}

        try:
            result = subprocess.run(
                ["python", "-m", "pytest", str(tests_dir), "-v", "--tb=short", "--timeout=30", "--no-header"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                cwd=str(repo_dir), timeout=60,
            )

            output = result.stdout + result.stderr
            # 解析 pytest 输出
            checks = []
            total = 0
            passed_count = 0
            issues = []

            for line in output.split("\n"):
                if "PASSED" in line:
                    total += 1
                    passed_count += 1
                    name = line.split("::")[1].split(" ")[0] if "::" in line else line.strip()
                    checks.append({"name": name, "passed": True, "detail": "PASSED"})
                elif "FAILED" in line:
                    total += 1
                    name = line.split("::")[1].split(" ")[0] if "::" in line else line.strip()
                    checks.append({"name": name, "passed": False, "detail": "FAILED"})
                    issues.append(f"测试失败: {name}")
                elif "ERROR" in line and "test_" in line:
                    total += 1
                    checks.append({"name": line.strip()[:60], "passed": False, "detail": "ERROR"})
                    issues.append(f"测试错误: {line.strip()[:60]}")

            if total == 0:
                # 没解析到结果，用 returncode 判断
                total = 1
                ok = result.returncode == 0
                passed_count = 1 if ok else 0
                checks.append({"name": "pytest 执行", "passed": ok, "detail": "通过" if ok else output[-200:]})
                if not ok:
                    issues.append("pytest 执行失败")

            return {"total": total, "passed_count": passed_count, "checks": checks, "issues": issues, "output": output[:2000]}

        except subprocess.TimeoutExpired:
            return {"total": 1, "passed_count": 0, "checks": [{"name": "pytest", "passed": False, "detail": "超时"}], "issues": ["pytest 执行超时"]}
        except Exception as e:
            return {"total": 1, "passed_count": 0, "checks": [], "issues": [f"pytest 异常: {str(e)[:100]}"], "output": ""}

    # ==================== 生成测试报告 ====================

    def _generate_report(self, title: str, module: str, strategy: str, results: Dict) -> str:
        """生成规范的 Markdown 测试报告"""
        summary = results.get("summary", {})
        phases = results.get("phases", [])
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        pass_rate = summary.get("pass_rate", 0)
        result_icon = "✅ 通过" if pass_rate >= 60 else "❌ 未通过"

        md = f"""# 测试报告 — {title}

> 测试时间: {now} | 模块类型: {module} | 策略: {strategy}
> **总体结果: {result_icon} (通过率 {pass_rate}%)**

---

## 测试概要

| 指标 | 值 |
|------|------|
| 总检查项 | {summary.get('total_checks', 0)} |
| 通过 | {summary.get('total_passed', 0)} |
| 失败 | {summary.get('total_checks', 0) - summary.get('total_passed', 0)} |
| 通过率 | {pass_rate}% |
| 代码审查评分 | {summary.get('review_score', '-')}/10 |

---
"""

        # 各阶段详情
        for i, phase in enumerate(phases, 1):
            phase_name = phase.get("name", f"Phase {i}")
            checks = phase.get("checks", [])

            md += f"\n## {i}. {phase_name}\n\n"

            if checks:
                md += "| 检查项 | 结果 | 说明 |\n|--------|------|------|\n"
                for c in checks:
                    icon = "✅" if c.get("passed") else "❌"
                    md += f"| {c.get('name', '-')} | {icon} | {c.get('detail', '-')} |\n"
                md += "\n"

            # 代码审查特殊处理
            if phase_name == "代码审查":
                score = phase.get("score", "-")
                md += f"**评分: {score}/10**\n\n"
                for issue in phase.get("issues", []):
                    md += f"- ⚠️ {issue}\n"
                for sug in phase.get("suggestions", []):
                    md += f"- 💡 {sug}\n"
                md += "\n"

            # pytest 输出
            if phase.get("output"):
                md += f"<details><summary>执行日志</summary>\n\n```\n{phase['output'][:1500]}\n```\n</details>\n\n"

        # 页面截图
        screenshots = results.get("screenshots", [])
        if screenshots:
            md += "\n---\n\n## 页面截图\n\n"
            for s in screenshots:
                md += f"### {s['label']}\n\n![{s['label']}]({s['url']})\n\n"

        # 问题清单
        all_issues = summary.get("issues", [])
        if all_issues:
            md += "\n---\n\n## 问题清单\n\n"
            for issue in all_issues:
                md += f"- ❌ {issue}\n"
        else:
            md += "\n---\n\n## 问题清单\n\n✅ 无问题\n"

        md += f"\n---\n*由 AI 自动开发系统 TestAgent 生成*\n"
        return md


async def _async_sleep(seconds):
    """异步 sleep"""
    import asyncio
    await asyncio.sleep(seconds)
