"""
代码审查代理（ReviewAgent）
负责代码质量审查、安全漏洞扫描、规范检查

LLM 模式：使用大模型进行智能代码审查
降级模式：基于规则引擎进行基础检查
"""
import os
import re
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from models.enums import AgentType

logger = logging.getLogger(__name__)

# LLM 代码审查系统提示词
REVIEW_SYSTEM_PROMPT = """你是一位资深代码审查专家。
你的职责是对项目代码进行全面审查，发现问题并给出改进建议。

审查维度：
1. **代码规范**：PEP 8 / 命名规范 / 代码组织
2. **安全漏洞**：SQL 注入、XSS、路径穿越、密钥泄露、不安全的输入处理
3. **性能问题**：N+1 查询、内存泄露、冗余计算
4. **架构设计**：模块耦合度、职责划分、设计模式运用
5. **错误处理**：异常捕获、边界条件、资源释放
6. **测试覆盖**：是否有足够的测试、测试质量

输出要求：
- 使用 Markdown 格式
- 按严重程度分级：🔴 严重 / 🟡 警告 / 🔵 建议
- 每个问题给出具体文件和行号（如果可能）
- 给出修复建议和代码示例
- 最后给出总评分（A/B/C/D/F）

你必须返回严格的 JSON 格式（不要包含 markdown 代码块标记），结构如下：
{
  "files": [
    {
      "path": "docs/code_review.md",
      "content": "完整的审查报告 Markdown 内容"
    }
  ],
  "summary": "一句话描述审查结果",
  "score": "B+",
  "issues": {
    "critical": 0,
    "warning": 3,
    "suggestion": 5
  }
}"""


class ReviewAgent:
    """代码审查代理 - LLM 智能审查 + 规则引擎降级"""

    def __init__(self, work_dir: str = "projects", llm_client=None):
        self.agent_type = AgentType.REVIEW
        self.work_dir = work_dir
        self.llm_client = llm_client

    def get_capabilities(self) -> List[str]:
        return [
            "代码规范检查",
            "安全漏洞扫描",
            "性能问题检测",
            "架构设计审查",
            "代码质量评分",
        ]

    def get_supported_tasks(self) -> List[str]:
        return ["review"]

    @property
    def _llm_available(self) -> bool:
        return self.llm_client is not None and self.llm_client.enabled

    def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行代码审查任务

        Args:
            task_name: 任务名称
            context: 包含 project_id, requirement, existing_files, dev_outputs 等

        Returns:
            包含 success, files_created, output 的结果
        """
        project_id = context.get("project_id", "unknown")
        project_dir = os.path.join(self.work_dir, project_id)

        try:
            # 收集项目代码文件
            code_files = self._collect_code_files(project_dir)

            if not code_files:
                # 没有代码文件，生成占位报告
                return self._generate_empty_report(project_dir, task_name)

            # 尝试 LLM 模式
            llm_result = self._llm_review(task_name, project_dir, code_files, context)
            if llm_result:
                return {
                    "success": True,
                    "agent": self.agent_type.value,
                    "task": task_name,
                    **llm_result,
                }

            # 降级：规则引擎审查
            result = self._rule_review(project_dir, code_files, context)
            return {
                "success": True,
                "agent": self.agent_type.value,
                "task": task_name,
                **result,
            }
        except Exception as e:
            logger.error(f"ReviewAgent 执行异常: {e}")
            return {
                "success": False,
                "agent": self.agent_type.value,
                "task": task_name,
                "error": str(e),
            }

    def _collect_code_files(self, project_dir: str) -> List[Dict[str, str]]:
        """收集项目中的代码文件"""
        code_files = []
        code_extensions = {
            ".py", ".js", ".ts", ".html", ".css",
            ".json", ".yml", ".yaml", ".toml", ".sql",
        }

        if not os.path.exists(project_dir):
            return code_files

        for root, dirs, files in os.walk(project_dir):
            # 跳过常见非代码目录
            dirs[:] = [d for d in dirs if d not in {
                "__pycache__", ".git", "node_modules", ".venv", "venv"
            }]
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext in code_extensions:
                    full_path = os.path.join(root, fname)
                    rel_path = os.path.relpath(full_path, project_dir).replace("\\", "/")
                    try:
                        with open(full_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        # 限制单个文件大小（避免 LLM 上下文爆炸）
                        if len(content) > 10000:
                            content = content[:10000] + "\n# ... (文件截断，共 {} 行)".format(
                                content.count("\n") + 1
                            )
                        code_files.append({
                            "path": rel_path,
                            "content": content,
                            "extension": ext,
                            "lines": content.count("\n") + 1,
                        })
                    except (UnicodeDecodeError, PermissionError):
                        pass

        return code_files

    def _llm_review(
        self,
        task_name: str,
        project_dir: str,
        code_files: List[Dict[str, str]],
        context: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """LLM 模式：智能代码审查"""
        if not self._llm_available:
            return None

        # 构建代码摘要
        code_summary = []
        for f in code_files[:15]:  # 最多 15 个文件
            code_summary.append(f"### {f['path']} ({f['lines']} 行)\n```\n{f['content']}\n```")

        requirement = context.get("requirement", "")
        project_name = context.get("project_name", "项目")

        prompt = f"""请对以下项目进行全面代码审查：

项目名称：{project_name}
需求描述：{requirement}
任务：{task_name}

项目包含 {len(code_files)} 个代码文件：

{chr(10).join(code_summary)}

请从代码规范、安全性、性能、架构、错误处理等维度进行审查。"""

        try:
            response = self.llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                system=REVIEW_SYSTEM_PROMPT,
                temperature=0.3,
                max_tokens=8192,
            )
            if not response or response == "[LLM_UNAVAILABLE]":
                return None
            return self._parse_llm_response(response, project_dir)
        except Exception as e:
            logger.warning(f"ReviewAgent LLM 审查失败: {e}")
            return None

    def _parse_llm_response(
        self, response: str, project_dir: str
    ) -> Optional[Dict[str, Any]]:
        """解析 LLM JSON 响应并写入文件"""
        text = response.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"ReviewAgent LLM 响应 JSON 解析失败: {text[:200]}")
            return None

        files = data.get("files", [])
        if not files:
            return None

        files_created = []
        for f in files:
            path = f.get("path", "")
            content = f.get("content", "")
            if path and content:
                full_path = os.path.join(project_dir, path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "w", encoding="utf-8") as fp:
                    fp.write(content)
                files_created.append(full_path)

        if not files_created:
            return None

        issues = data.get("issues", {})
        score = data.get("score", "N/A")
        summary = data.get("summary", f"代码审查完成，评分: {score}")

        return {
            "files_created": files_created,
            "output": summary,
            "score": score,
            "issues": issues,
            "mode": "llm",
        }

    def _rule_review(
        self,
        project_dir: str,
        code_files: List[Dict[str, str]],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """规则引擎模式：基于预定义规则的代码审查"""
        project_name = context.get("project_name", "项目")
        issues_critical = []
        issues_warning = []
        issues_suggestion = []

        for f in code_files:
            path = f["path"]
            content = f["content"]
            ext = f["extension"]
            lines = content.split("\n")

            # ========== 安全检查 ==========

            # 1. 硬编码密钥/密码
            secret_patterns = [
                (r'(?:password|passwd|pwd)\s*=\s*["\'][^"\']+["\']', "硬编码密码"),
                (r'(?:secret|token|api_key)\s*=\s*["\'][A-Za-z0-9+/=]{10,}["\']', "硬编码密钥/Token"),
                (r'(?:sk-|ak-)[A-Za-z0-9]{20,}', "疑似 API Key 明文"),
            ]
            for pattern, desc in secret_patterns:
                for i, line in enumerate(lines):
                    if re.search(pattern, line, re.IGNORECASE):
                        # 排除注释和示例
                        stripped = line.strip()
                        if stripped.startswith("#") or stripped.startswith("//"):
                            continue
                        if "example" in line.lower() or "placeholder" in line.lower():
                            continue
                        issues_critical.append({
                            "file": path, "line": i + 1,
                            "rule": "SEC-001", "desc": desc,
                            "content": line.strip()[:80],
                        })

            # 2. SQL 注入风险（字符串拼接 SQL）
            sql_injection_patterns = [
                r'(?:execute|cursor\.execute)\s*\(\s*f["\']',
                r'(?:execute|cursor\.execute)\s*\([^)]*%\s',
                r'(?:execute|cursor\.execute)\s*\([^)]*\+\s',
            ]
            for pattern in sql_injection_patterns:
                for i, line in enumerate(lines):
                    if re.search(pattern, line):
                        issues_critical.append({
                            "file": path, "line": i + 1,
                            "rule": "SEC-002", "desc": "SQL 注入风险（字符串拼接）",
                            "content": line.strip()[:80],
                        })

            # 3. 路径穿越
            for i, line in enumerate(lines):
                if "os.path.join" in line and "user" in line.lower():
                    if "os.path.abspath" not in content[max(0, content.find(line) - 200):content.find(line) + 200]:
                        issues_warning.append({
                            "file": path, "line": i + 1,
                            "rule": "SEC-003", "desc": "路径拼接未做穿越检查",
                            "content": line.strip()[:80],
                        })

            # ========== Python 专项检查 ==========
            if ext == ".py":
                # 4. 裸 except
                for i, line in enumerate(lines):
                    if re.match(r'\s*except\s*:', line):
                        issues_warning.append({
                            "file": path, "line": i + 1,
                            "rule": "PY-001", "desc": "裸 except 会吞掉所有异常",
                            "content": line.strip(),
                        })

                # 5. 未使用 with 打开文件
                for i, line in enumerate(lines):
                    if re.search(r'\b(?:open)\s*\(', line) and "with" not in line:
                        # 检查前一行是否有 with
                        prev = lines[i - 1].strip() if i > 0 else ""
                        if "with" not in prev:
                            issues_warning.append({
                                "file": path, "line": i + 1,
                                "rule": "PY-002", "desc": "建议使用 with 语句打开文件",
                                "content": line.strip()[:80],
                            })

                # 6. 函数过长（> 50 行）
                func_start = None
                func_name = ""
                for i, line in enumerate(lines):
                    m = re.match(r'\s*def\s+(\w+)', line)
                    if m:
                        if func_start is not None:
                            length = i - func_start
                            if length > 50:
                                issues_suggestion.append({
                                    "file": path, "line": func_start + 1,
                                    "rule": "PY-003",
                                    "desc": f"函数 `{func_name}` 过长（{length} 行），建议拆分",
                                    "content": "",
                                })
                        func_start = i
                        func_name = m.group(1)
                if func_start is not None:
                    length = len(lines) - func_start
                    if length > 50:
                        issues_suggestion.append({
                            "file": path, "line": func_start + 1,
                            "rule": "PY-003",
                            "desc": f"函数 `{func_name}` 过长（{length} 行），建议拆分",
                            "content": "",
                        })

                # 7. import * 检查
                for i, line in enumerate(lines):
                    if re.match(r'\s*from\s+\S+\s+import\s+\*', line):
                        issues_warning.append({
                            "file": path, "line": i + 1,
                            "rule": "PY-004", "desc": "避免使用 import *，明确导入所需内容",
                            "content": line.strip(),
                        })

                # 8. TODO/FIXME/HACK 标记
                for i, line in enumerate(lines):
                    for tag in ["TODO", "FIXME", "HACK", "XXX"]:
                        if tag in line.upper():
                            issues_suggestion.append({
                                "file": path, "line": i + 1,
                                "rule": "PY-005", "desc": f"发现 {tag} 标记，建议跟进处理",
                                "content": line.strip()[:80],
                            })
                            break

            # ========== 通用检查 ==========

            # 9. 行过长（> 120 字符）
            long_lines = [(i + 1) for i, line in enumerate(lines) if len(line.rstrip()) > 120]
            if long_lines:
                issues_suggestion.append({
                    "file": path, "line": long_lines[0],
                    "rule": "STYLE-001",
                    "desc": f"发现 {len(long_lines)} 行超过 120 字符",
                    "content": f"行号: {', '.join(str(l) for l in long_lines[:5])}{'...' if len(long_lines) > 5 else ''}",
                })

            # 10. 文件缺少 docstring（Python）
            if ext == ".py" and lines:
                first_non_empty = ""
                for line in lines:
                    stripped = line.strip()
                    if stripped:
                        first_non_empty = stripped
                        break
                if first_non_empty and not first_non_empty.startswith(('"""', "'''", "#", "import", "from")):
                    issues_suggestion.append({
                        "file": path, "line": 1,
                        "rule": "DOC-001", "desc": "文件缺少模块级 docstring",
                        "content": "",
                    })

        # ========== 生成审查报告 ==========
        total_issues = len(issues_critical) + len(issues_warning) + len(issues_suggestion)

        # 评分
        if len(issues_critical) > 3:
            score = "D"
        elif len(issues_critical) > 0:
            score = "C"
        elif len(issues_warning) > 5:
            score = "B"
        elif len(issues_warning) > 0:
            score = "B+"
        elif len(issues_suggestion) > 5:
            score = "A-"
        else:
            score = "A"

        # 生成 Markdown 报告
        report = self._generate_report_md(
            project_name, code_files, score,
            issues_critical, issues_warning, issues_suggestion,
        )

        # 写入文件
        docs_dir = os.path.join(project_dir, "docs")
        os.makedirs(docs_dir, exist_ok=True)
        report_path = os.path.join(docs_dir, "code_review.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)

        return {
            "files_created": [report_path],
            "output": f"代码审查完成：评分 {score}，发现 {total_issues} 个问题"
                      f"（🔴 {len(issues_critical)} 严重 / 🟡 {len(issues_warning)} 警告 / 🔵 {len(issues_suggestion)} 建议）",
            "score": score,
            "issues": {
                "critical": len(issues_critical),
                "warning": len(issues_warning),
                "suggestion": len(issues_suggestion),
            },
            "mode": "template",
        }

    def _generate_report_md(
        self,
        project_name: str,
        code_files: List[Dict[str, str]],
        score: str,
        critical: List[Dict],
        warning: List[Dict],
        suggestion: List[Dict],
    ) -> str:
        """生成 Markdown 审查报告"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        total = len(critical) + len(warning) + len(suggestion)

        # 文件统计
        total_lines = sum(f["lines"] for f in code_files)
        ext_stats = {}
        for f in code_files:
            ext = f["extension"]
            ext_stats[ext] = ext_stats.get(ext, 0) + 1

        ext_summary = ", ".join(f"{ext}: {count} 个" for ext, count in sorted(ext_stats.items()))

        report = f"""# {project_name} - 代码审查报告

> 由 AI 自动开发系统自动生成 | {now}

## 📊 总评

| 指标 | 值 |
|------|------|
| **综合评分** | **{score}** |
| 扫描文件 | {len(code_files)} 个 ({ext_summary}) |
| 总代码行 | {total_lines:,} 行 |
| 问题总数 | {total} 个 |
| 🔴 严重 | {len(critical)} |
| 🟡 警告 | {len(warning)} |
| 🔵 建议 | {len(suggestion)} |

---

"""

        if critical:
            report += "## 🔴 严重问题\n\n"
            report += "必须修复的问题，可能导致安全漏洞或系统崩溃。\n\n"
            for issue in critical:
                report += f"### [{issue['rule']}] {issue['desc']}\n\n"
                report += f"- **文件**: `{issue['file']}` (第 {issue['line']} 行)\n"
                if issue.get("content"):
                    report += f"- **代码**: `{issue['content']}`\n"
                report += "\n"

        if warning:
            report += "## 🟡 警告\n\n"
            report += "建议修复，可能导致潜在问题或维护困难。\n\n"
            for issue in warning:
                report += f"### [{issue['rule']}] {issue['desc']}\n\n"
                report += f"- **文件**: `{issue['file']}` (第 {issue['line']} 行)\n"
                if issue.get("content"):
                    report += f"- **代码**: `{issue['content']}`\n"
                report += "\n"

        if suggestion:
            report += "## 🔵 改进建议\n\n"
            report += "优化建议，有助于提升代码质量和可维护性。\n\n"
            for issue in suggestion:
                report += f"### [{issue['rule']}] {issue['desc']}\n\n"
                report += f"- **文件**: `{issue['file']}` (第 {issue['line']} 行)\n"
                if issue.get("content"):
                    report += f"- **代码**: `{issue['content']}`\n"
                report += "\n"

        if not critical and not warning and not suggestion:
            report += "## ✅ 未发现问题\n\n"
            report += "代码质量良好，未发现明显问题。继续保持！\n\n"

        report += """---

## 📋 审查规则说明

| 规则 ID | 分类 | 说明 |
|---------|------|------|
| SEC-001 | 安全 | 硬编码密码/密钥检测 |
| SEC-002 | 安全 | SQL 注入风险检测 |
| SEC-003 | 安全 | 路径穿越风险检测 |
| PY-001 | Python | 裸 except 检测 |
| PY-002 | Python | 文件未使用 with 语句 |
| PY-003 | Python | 函数过长检测 |
| PY-004 | Python | import * 检测 |
| PY-005 | Python | TODO/FIXME 标记跟踪 |
| STYLE-001 | 风格 | 行过长检测 (>120字符) |
| DOC-001 | 文档 | 缺少 docstring |

> 本报告由规则引擎自动生成。如需更深入的审查，建议配置 LLM 以获得智能分析。
"""
        return report

    def _generate_empty_report(
        self, project_dir: str, task_name: str
    ) -> Dict[str, Any]:
        """没有代码文件时生成空报告"""
        docs_dir = os.path.join(project_dir, "docs")
        os.makedirs(docs_dir, exist_ok=True)
        report_path = os.path.join(docs_dir, "code_review.md")

        report = f"""# 代码审查报告

> 由 AI 自动开发系统自动生成 | {datetime.now().strftime("%Y-%m-%d %H:%M")}

## ⚠️ 暂无可审查的代码

项目目录中未发现代码文件。请先执行开发任务生成代码，再进行代码审查。
"""
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)

        return {
            "success": True,
            "agent": self.agent_type.value,
            "task": task_name,
            "files_created": [report_path],
            "output": "暂无可审查的代码文件",
            "score": "N/A",
            "issues": {"critical": 0, "warning": 0, "suggestion": 0},
            "mode": "template",
        }
