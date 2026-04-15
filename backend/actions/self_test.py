"""Action: 开发自测（从 DevAgent._self_test 抽离）"""
import re
import logging
from datetime import datetime
from typing import Any, Dict
from actions.base import ActionBase, ActionResult

logger = logging.getLogger("action.self_test")


class SelfTestAction(ActionBase):

    @property
    def name(self) -> str:
        return "self_test"

    @property
    def description(self) -> str:
        return "开发完成后自动运行基础检查（文件/入口/语法/规范）"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        project_id = context.get("project_id", "")
        files = context.get("_files", {})  # 由 Agent 传入当前产出的文件
        title = context.get("ticket_title", "")
        docs_prefix = context.get("docs_prefix", "docs/")

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

        # 生成开发笔记
        is_fallback = "[降级]" in str(context.get("dev_result", {}).get("notes", ""))
        notes_md = f"""# 开发笔记 — {title}

> {datetime.now().strftime('%Y-%m-%d %H:%M')} | {'LLM' if not is_fallback else '降级'}

## 产出文件
{chr(10).join(f'- [{fp}](/app#repo?file={fp}) ({len(c)} chars)' for fp, c in files.items() if not fp.endswith('dev-notes.md'))}

## 自测: {summary}

| 检查项 | 结果 | 说明 |
|--------|------|------|
{chr(10).join(f'| {c["name"]} | {"✅" if c["passed"] else "❌"} | {c["detail"]} |' for c in checks)}
"""

        result_files = {f"{docs_prefix}dev-notes.md": notes_md}

        return ActionResult(
            success=True,
            data={"self_test": {"passed": passed == total, "total": total, "passed_count": passed, "checks": checks, "summary": summary}},
            files=result_files,
        )
