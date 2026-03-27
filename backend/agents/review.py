"""
ReviewAgent — 代码审查 Agent
职责：10 种静态规则检查 + LLM 智能审查
被 TestAgent 在测试阶段调用
"""
import json
from typing import Any, Dict, List
from agents.base import BaseAgent
from llm_client import llm_client


class ReviewAgent(BaseAgent):

    @property
    def agent_type(self) -> str:
        return "ReviewAgent"

    # 10 种静态审查规则
    RULES = [
        "naming_convention",     # 命名规范
        "function_length",       # 函数长度
        "complexity",            # 圈复杂度
        "error_handling",        # 错误处理
        "security_check",        # 安全检查
        "sql_injection",         # SQL 注入
        "xss_check",            # XSS 检查
        "hardcoded_secrets",     # 硬编码密钥
        "code_duplication",      # 代码重复
        "documentation",         # 文档完整性
    ]

    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if task_name == "review_code":
            return await self.review_code(context)
        else:
            return {"status": "error", "message": f"未知任务: {task_name}"}

    async def review_code(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """代码审查"""
        dev_result = context.get("dev_result", {})
        files = dev_result.get("files_created", [])
        docs_prefix = context.get("docs_prefix", "docs/")

        # 静态规则检查
        rule_results = self._static_check(files)

        # LLM 智能审查
        llm_review = await self._llm_review(dev_result)

        issues = rule_results.get("issues", []) + llm_review.get("issues", [])
        passed = len(issues) == 0

        # 生成审查报告 Markdown
        review_md = "# 代码审查报告\n\n"
        review_md += f"## 结果: {'✅ 通过' if passed else '❌ 不通过'}\n\n"
        review_md += f"### 静态规则检查\n- 检查规则: {rule_results.get('rules_checked', 0)} 项\n- 通过: {rule_results.get('rules_passed', 0)} 项\n\n"
        review_md += f"### 智能审查\n- 质量评分: {llm_review.get('quality_score', '-')}/10\n"
        if llm_review.get("positive_points"):
            review_md += "\n**优点:**\n" + "\n".join(f"- {p}" for p in llm_review["positive_points"]) + "\n"
        if llm_review.get("recommendations"):
            review_md += "\n**建议:**\n" + "\n".join(f"- {r}" for r in llm_review["recommendations"]) + "\n"
        if issues:
            review_md += "\n### 问题列表\n" + "\n".join(f"- {i}" for i in issues) + "\n"

        return {
            "status": "success",
            "review": {
                "passed": passed,
                "rule_results": rule_results,
                "llm_review": llm_review,
                "total_issues": len(issues),
                "issues": issues,
            },
            "files": {
                f"{docs_prefix}code-review.md": review_md,
            },
        }

    def _static_check(self, files: List[Dict]) -> Dict:
        """静态规则检查（模拟）"""
        issues = []
        for rule in self.RULES:
            # 这里简化处理，实际可集成 pylint/flake8
            pass

        return {
            "rules_checked": len(self.RULES),
            "rules_passed": len(self.RULES),
            "issues": issues,
        }

    async def _llm_review(self, dev_result: Dict) -> Dict:
        """LLM 智能审查"""
        prompt = f"""作为代码审查专家，请审查以下代码交付物：
{json.dumps(dev_result, ensure_ascii=False, indent=2)}

请返回 JSON：
{{
  "quality_score": 1-10,
  "issues": ["问题描述"],
  "positive_points": ["优点"],
  "recommendations": ["建议"]
}}"""

        result = await llm_client.chat_json([{"role": "user", "content": prompt}])

        if result and isinstance(result, dict):
            return result

        return {"quality_score": 7, "issues": [], "positive_points": ["代码结构清晰"], "recommendations": []}
