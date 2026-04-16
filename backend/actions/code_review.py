"""Action: 代码审查（读取实际代码内容，非盲审）"""
import logging
from typing import Any, Dict
from actions.base import ActionBase, ActionResult
from actions.action_node import ActionNode
from actions.schemas import TestReviewOutput
from llm_client import llm_client

logger = logging.getLogger("action.code_review")


class CodeReviewAction(ActionBase):

    @property
    def name(self) -> str:
        return "code_review"

    @property
    def description(self) -> str:
        return "读取实际代码内容进行审查（命名/安全/复杂度/规范）"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        ticket_title = context.get("ticket_title", "")
        dev_result = context.get("dev_result", {})
        existing_code = context.get("existing_code", {})
        docs_prefix = context.get("docs_prefix", "docs/")

        # SOP 配置
        sop = context.get("sop_config", {})
        max_code_chars = sop.get("max_code_chars", 3000)

        # 收集代码片段（dev_result 产出 + 仓库已有）
        code_snippets = ""
        total = 0

        # 优先审查本次产出的代码
        if isinstance(dev_result, dict):
            files = dev_result.get("files", {})
            if isinstance(files, dict):
                for fp, content in files.items():
                    if fp.endswith((".md", ".txt")):
                        continue
                    snippet = content[:1500] if isinstance(content, str) else ""
                    if snippet and total < max_code_chars:
                        code_snippets += f"\n### {fp}\n```\n{snippet}\n```\n"
                        total += len(snippet)

        # 补充仓库已有代码
        if total < max_code_chars and existing_code:
            for fp, content in existing_code.items():
                if total >= max_code_chars:
                    break
                if fp.endswith((".md", ".txt")):
                    continue
                snippet = content[:1000]
                code_snippets += f"\n### {fp} (仓库已有)\n```\n{snippet}\n```\n"
                total += len(snippet)

        if not code_snippets:
            return ActionResult(
                success=True,
                data={"score": 7, "issues": [], "suggestions": []},
                message="无代码可审查",
            )

        req_context = f"""## 审查任务: {ticket_title}

## 代码内容
{code_snippets}

## 审查要点
1. 命名规范（变量/函数/文件是否清晰）
2. 代码安全（XSS/注入/硬编码密钥）
3. 逻辑正确性（边界条件/空值处理）
4. 代码风格（缩进/注释/一致性）
5. 可维护性（函数长度/复杂度/重复代码）"""

        node = ActionNode(
            key="code_review",
            expected_type=TestReviewOutput,
            instruction="审查以上代码，给出评分和具体问题。评分 1-10，7 分及以上为良好。",
        )
        await node.fill(req=req_context, llm=llm_client, max_tokens=1500)

        review = node.instruct_content
        score = review.score if review else 7

        review_md = f"""# 代码审查 — {ticket_title}

## 评分: {score}/10 {'✅' if score >= 7 else '⚠️'}

## 问题
{chr(10).join(f'- ❌ {i}' for i in (review.issues if review else [])) or '无'}

## 建议
{chr(10).join(f'- 💡 {s}' for s in (review.suggestions if review else [])) or '无'}

## 审查的代码
{chr(10).join(f'- {fp}' for fp in (dev_result.get('files', {}).keys() if isinstance(dev_result, dict) else []))}
"""

        logger.info("🔍 代码审查: %s → %d/10", ticket_title[:20], score)

        return ActionResult(
            success=True,
            data={"score": score, "issues": review.issues if review else [], "suggestions": review.suggestions if review else []},
            files={f"{docs_prefix}code-review.md": review_md},
        )
