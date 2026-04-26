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

        # v0.19.x A-方案：UE 项目走专属 lint 分支（7 条静态规则 + 可选 Layer 2 UBT SingleFile）
        traits = self._extract_traits(context)
        if any(t.startswith("engine:ue") for t in traits):
            return await self._run_ue_self_test(context, files)

        checks = []
        passed = 0
        total = 0

        if not files:
            return ActionResult(success=True, data={"self_test": {"passed": True, "total": 0, "checks": [], "summary": "无文件"}})

        file_names = list(files.keys())

        # === Phase 0: 提前落盘 ===
        # 历史：flush 只在截图阶段做、只在有入口前端项目做，导致 SelfTest 跑完磁盘还
        # 可能是空的，orchestrator 的 write_and_commit 失败时 SelfTest 也不会发现。
        # 现在：所有场景一开始就 flush，后续检查等价于"磁盘刚写内容"。
        sop_cfg = context.get("sop_config") or {}
        verify_disk = bool(sop_cfg.get("verify_disk_files", True))
        if project_id and files:
            try:
                await self._flush_files_to_repo(project_id, files)
            except Exception as e:
                logger.warning("SelfTest 预落盘失败: %s", e)

        # 1. 文件产出
        total += 1
        checks.append({"name": "文件产出", "passed": True, "detail": f"{len(file_names)} 个文件"})
        passed += 1

        # 2. 入口文件（磁盘为准）
        total += 1
        has_entry = False
        if project_id:
            try:
                from git_manager import git_manager
                repo_dir = git_manager._repo_path(project_id)
                has_entry = any((repo_dir / f).exists() for f in ("index.html", "main.py", "app.py"))
            except Exception:
                # 磁盘读异常时降级到内存检查
                has_entry = any(f in files for f in ("index.html", "main.py", "app.py"))
        else:
            has_entry = any(f in files for f in ("index.html", "main.py", "app.py"))
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

        # === 6. 磁盘落地验证（核心：防"自测通过但文件未落盘"的假阳性） ===
        if verify_disk and project_id:
            total += 1
            disk_check = await self._verify_disk_files(project_id, files)
            checks.append({
                "name": "磁盘落地",
                "passed": disk_check["ok"],
                "detail": disk_check["detail"],
            })
            if disk_check["ok"]:
                passed += 1

        summary = f"自测 {passed}/{total} 通过" + (" ✅" if passed == total else " ⚠️")

        # === 7. 截图预览（前端项目 + 有入口文件时）===
        # 不再重复 flush —— Phase 0 已经写过盘
        screenshots = []
        if has_entry and module in ("frontend", "design", "other") and project_id:
            screenshots = await self._take_screenshot(project_id, title, docs_prefix)
            if screenshots:
                total += 1
                passed += 1
                checks.append({"name": "页面截图", "passed": True, "detail": f"{len(screenshots)} 张截图"})
                summary = f"自测 {passed}/{total} 通过" + (" ✅" if passed == total else " ⚠️")

        # 生成 diff（对比已有代码和新产出）
        existing_code = context.get("existing_code", {})
        diff_md = self._generate_diff(files, existing_code)

        # 生成开发笔记
        is_fallback = "[降级]" in str(context.get("dev_result", {}).get("notes", ""))

        screenshot_md = ""
        if screenshots:
            screenshot_md = "\n## 页面预览截图\n\n"
            for s in screenshots:
                rel_url = f"screenshots/{s['filename']}"
                screenshot_md += f"![{s['label']}]({rel_url})\n\n"

        notes_md = f"""# 开发笔记 — {title}

> {datetime.now().strftime('%Y-%m-%d %H:%M')} | {'LLM' if not is_fallback else '降级'}

## 产出文件
{chr(10).join(f'- [{fp}](/app#repo?file={fp}) ({len(c)} chars)' for fp, c in files.items() if not fp.endswith('dev-notes.md'))}

## 自测: {summary}

| 检查项 | 结果 | 说明 |
|--------|------|------|
{chr(10).join(f'| {c["name"]} | {"✅" if c["passed"] else "❌"} | {c["detail"]} |' for c in checks)}
{diff_md}{screenshot_md}"""

        result_files = {f"{docs_prefix}dev-notes.md": notes_md}

        return ActionResult(
            success=True,
            data={"self_test": {"passed": passed == total, "total": total, "passed_count": passed, "checks": checks, "summary": summary, "screenshots": screenshots}},
            files=result_files,
        )

    def _generate_diff(self, new_files: Dict[str, str], existing_code: Dict[str, str]) -> str:
        """生成新旧代码 diff（unified diff 格式）"""
        import difflib

        if not new_files:
            return ""

        diff_sections = []
        for fp, new_content in new_files.items():
            if fp.endswith((".md", ".txt")):
                continue

            old_content = existing_code.get(fp, "")
            if not old_content:
                # 新建文件
                lines = new_content.split("\n")
                preview = lines[:20]
                diff_sections.append(f"### {fp} (新建, {len(new_content)} chars)\n```\n" + "\n".join(f"+ {l}" for l in preview) + ("\n+ ... (更多)" if len(lines) > 20 else "") + "\n```")
            else:
                # 修改文件 — 生成 unified diff
                old_lines = old_content.splitlines(keepends=True)
                new_lines = new_content.splitlines(keepends=True)
                diff = list(difflib.unified_diff(old_lines, new_lines, fromfile=f"a/{fp}", tofile=f"b/{fp}", lineterm=""))

                if diff:
                    # 只保留前 50 行 diff
                    diff_text = "\n".join(diff[:50])
                    if len(diff) > 50:
                        diff_text += f"\n... (共 {len(diff)} 行变更)"
                    diff_sections.append(f"### {fp} (修改)\n```diff\n{diff_text}\n```")
                else:
                    diff_sections.append(f"### {fp} (无变化)")

        if not diff_sections:
            return ""

        return "\n## 代码变更 (Diff)\n\n" + "\n\n".join(diff_sections) + "\n"

    async def _flush_files_to_repo(self, project_id: str, files: Dict[str, str]):
        """把代码 + 文档文件都写入仓库磁盘（orchestrator 后面会 git add+commit）
        注：从前只写代码；现在连 .md/.txt 也一起写，_verify_disk_files 才能验证
        文档类产出（如 dev-notes.md）也成功落地。"""
        try:
            from git_manager import git_manager
            for fp, content in files.items():
                await git_manager.write_file(project_id, fp, content)
            logger.debug("预写入 %d 个文件到仓库", len(files))
        except Exception as e:
            logger.warning("预写入文件失败: %s", e)

    async def _verify_disk_files(self, project_id: str, files: Dict[str, str]) -> Dict[str, Any]:
        """逐文件验证磁盘上存在且大小合理（防"自测通过但文件未落盘"的假阳性）
        返回 {"ok": bool, "detail": str}"""
        from git_manager import git_manager
        try:
            repo = git_manager._repo_path(project_id)
        except Exception as e:
            return {"ok": False, "detail": f"仓库路径异常: {e}"}

        if not repo.exists():
            return {"ok": False, "detail": "仓库目录不存在"}

        problems: List[str] = []
        checked = 0
        for fp, expected_content in files.items():
            p = repo / fp
            if not p.exists():
                problems.append(f"{fp}: 未落盘")
                continue
            try:
                actual_size = p.stat().st_size
            except Exception as e:
                problems.append(f"{fp}: stat 失败 ({e})")
                continue
            expected_size = len((expected_content or "").encode("utf-8"))
            # 预期非空但磁盘接近空
            if expected_size > 50 and actual_size < expected_size * 0.5:
                problems.append(f"{fp}: 磁盘 {actual_size}B 远小于预期 {expected_size}B")
                continue
            checked += 1

        if problems:
            return {"ok": False, "detail": "; ".join(problems[:3])}
        return {"ok": True, "detail": f"{checked} 个文件已落盘"}

    async def _take_screenshot(self, project_id: str, title: str, docs_prefix: str = "docs/") -> List[Dict]:
        """启动 HTTP server → Playwright 截图 → 保存到工单文档目录"""
        from git_manager import git_manager

        repo_dir = git_manager._repo_path(project_id)
        index_path = repo_dir / "index.html"
        if not index_path.exists():
            return []

        # 截图保存到工单文档路径下（如 docs/{req_id}/{ticket_id}/screenshots/）
        screenshots_dir = repo_dir / docs_prefix.rstrip("/") / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)

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

            fname = f"dev_{int(time.time())}.png"
            fpath = screenshots_dir / fname
            ok = await self._capture(port, str(fpath))
            if ok:
                rel_path = f"{docs_prefix}screenshots/{fname}"
                results.append({
                    "filename": fname,
                    "label": f"开发自测 — {title[:30]}",
                    "url": rel_path,
                    "path": str(fpath),
                })
                logger.info("📸 截图已保存: %s", rel_path)

        finally:
            if proc:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    proc.kill()

        return results

    async def _capture(self, port: int, output_path: str) -> bool:
        """截图：依次尝试 Playwright → Chrome headless → 跳过"""
        url = f"http://localhost:{port}/"

        # 方法 1: Playwright
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(viewport={"width": 1280, "height": 800})
                await page.goto(url, wait_until="networkidle", timeout=15000)
                await asyncio.sleep(1)
                await page.screenshot(path=output_path, full_page=True)
                await browser.close()
                logger.info("📸 Playwright 截图成功")
                return True
        except Exception as e:
            logger.debug("Playwright 截图失败: %s", e)

        # 方法 2: Chrome headless (系统已安装的 Chrome)
        try:
            import shutil
            chrome = shutil.which("chrome") or shutil.which("google-chrome")
            if not chrome:
                for p in [
                    "C:/Program Files/Google/Chrome/Application/chrome.exe",
                    "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
                ]:
                    if Path(p).exists():
                        chrome = p
                        break

            if chrome:
                result = subprocess.run([
                    chrome, "--headless", "--disable-gpu", "--no-sandbox",
                    f"--screenshot={output_path}",
                    f"--window-size=1280,800",
                    url,
                ], capture_output=True, timeout=15)
                if Path(output_path).exists() and Path(output_path).stat().st_size > 0:
                    logger.info("📸 Chrome headless 截图成功")
                    return True
        except Exception as e:
            logger.debug("Chrome 截图失败: %s", e)

        logger.warning("截图全部失败，跳过")
        return False

    # ==================== v0.19.x UE 自测（A 方案） ====================

    def _extract_traits(self, context: Dict[str, Any]) -> List[str]:
        """从 context 取 project traits（orchestrator._build_context 未来应直接注入）"""
        traits = context.get("traits")
        if isinstance(traits, list):
            return [str(t) for t in traits if t]
        # 未注入时从 DB 查（小成本，不常走）
        pid = context.get("project_id")
        if not pid:
            return []
        try:
            import asyncio, json
            from database import db
            async def _fetch():
                row = await db.fetch_one("SELECT traits FROM projects WHERE id = ?", (pid,))
                raw = (row or {}).get("traits") or "[]"
                return json.loads(raw) if isinstance(raw, str) else list(raw or [])
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return []  # 不阻塞；异步调用者直接传 traits 进来更好
            return loop.run_until_complete(_fetch())
        except Exception:
            return []

    async def _run_ue_self_test(
        self, context: Dict[str, Any], files: Dict[str, str]
    ) -> ActionResult:
        """UE 项目自测：Layer 1 静态规则（必做）+ Layer 2 UBT SingleFile（可选）

        blocking issues > 0 → 立即 status=fail（省 UBT 时间）；进入 fix_issues 循环。
        """
        from pathlib import Path as _P
        project_id = context.get("project_id", "")
        sop_cfg = context.get("sop_config") or {}

        # 先落盘（复用既有 flush 逻辑）
        if project_id and files:
            try:
                await self._flush_files_to_repo(project_id, files)
            except Exception as e:
                logger.warning("UE SelfTest 预落盘失败: %s", e)

        # 定位仓库
        try:
            from git_manager import git_manager
            repo_path = _P(str(git_manager._repo_path(project_id))) if project_id else None
        except Exception:
            repo_path = None
        if not repo_path or not repo_path.is_dir():
            return ActionResult(success=True, data={
                "self_test": {"passed": True, "total": 0, "summary": "repo 不存在，跳过"},
            })

        # Layer 1 跑 7 条规则
        from actions.ue_lint import run_all_rules
        from actions.ue_lint.rules import summarize

        files_written = list(files.keys()) if files else []
        # engine_version 从 projects 表的 ue_engine_version 列（v0.18 落的）取
        lint_ctx = {
            "ue_engine_version": context.get("ue_engine_version") or "5.3",
        }
        issues = run_all_rules(files_written, repo_path, lint_ctx)
        summary = summarize(issues)

        blocking = [i for i in issues if i.get("blocking")]
        warnings = [i for i in issues if not i.get("blocking")]

        logger.info(
            "🔍 UE Layer 1 lint: %d issues (%d blocking, %d warnings)",
            len(issues), len(blocking), len(warnings),
        )

        if blocking:
            return ActionResult(success=False, data={
                "self_test": {
                    "passed": False,
                    "total": len(issues),
                    "summary": f"UE 静态预检失败：{len(blocking)} blocking / {len(warnings)} warning",
                    "phase": "layer1_static",
                    "issues": issues,
                    "ue_lint_summary": summary,
                    # 让 Reflexion 能直接结构化消费
                    "ue_blocking_issues": blocking,
                },
            })

        # Layer 2：UBT -SingleFile 预编译（SOP 开关，默认开但首次跑慢时可关）
        if sop_cfg.get("ue_precompile", False):
            # 默认不开（首版先用 Layer 1 + 下游 engine_compile stage，避免双重编译）
            # 真要开时由 SOP development.config.ue_precompile=true 显式开
            from actions.ue_compile_check import UECompileCheckAction
            changed_cpp = [f for f in files_written if f.endswith((".cpp", ".h"))]
            if changed_cpp:
                # UE 的 SingleFile 只支持 .cpp，挑第一个
                single = [f for f in changed_cpp if f.endswith(".cpp")][:1]
                if single:
                    result = await UECompileCheckAction().run({
                        **context,
                        "single_files": [str(repo_path / single[0])],
                        "timeout_seconds": sop_cfg.get("ue_precompile_timeout", 120),
                    })
                    d = result.data or {}
                    if d.get("status") != "success":
                        return ActionResult(success=False, data={
                            "self_test": {
                                "passed": False,
                                "total": len(issues) + 1,
                                "summary": f"UE SingleFile 预编失败（{len(d.get('errors') or [])} errors）",
                                "phase": "layer2_precompile",
                                "issues": issues,
                                "ue_lint_summary": summary,
                                "precompile_result": d,
                            },
                        })

        # Layer 3：可选截效果图（SOP config: ue_screenshot=true，默认关因为需要 GPU + 启动慢）
        screenshots: List[str] = []
        if sop_cfg.get("ue_screenshot", False):
            try:
                from actions.ue_screenshot import UEScreenshotAction
                shot_result = await UEScreenshotAction().run({
                    **context,
                    "timeout_seconds": sop_cfg.get("ue_screenshot_timeout", 180),
                    "log_callback": context.get("log_callback"),
                })
                sd = shot_result.data or {}
                screenshots = sd.get("screenshots") or []
                logger.info("📸 UE 截图: %d 张", len(screenshots))
            except Exception as e:
                logger.warning("UE 截图失败（忽略）: %s", e)

        return ActionResult(success=True, data={
            "self_test": {
                "passed": True,
                "total": len(issues),
                "summary": f"UE 自测通过 ({len(warnings)} warnings)" + (f"，{len(screenshots)} 张截图" if screenshots else ""),
                "phase": "passed",
                "issues": issues,
                "ue_lint_summary": summary,
                "screenshots": screenshots,
            },
        })
