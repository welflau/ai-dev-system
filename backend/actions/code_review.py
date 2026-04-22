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

        # SOP 配置。硬 floor 8000 字符：就算 SOP yaml 里留的是旧的 3000（系统未重载 yaml）
        # 也不会让 LLM 看到被截断到 40% 的 HTML 误判为"不完整"。
        # 历史教训：max_code_chars=3000 + 硬截断 1500 → LLM 打 3-4/10 的假报告。
        sop = context.get("sop_config", {})
        max_code_chars = max(int(sop.get("max_code_chars", 12000) or 12000), 8000)
        per_file_limit = max(int(sop.get("per_file_code_chars", max_code_chars // 2) or 0), max_code_chars // 2)

        def _fit(content: str, budget: int) -> str:
            """按 budget 截断；如果真截断了，追加显式 marker，避免 LLM 误判。"""
            if not isinstance(content, str):
                return ""
            if len(content) <= budget:
                return content
            return content[:budget] + f"\n\n/* ... [代码片段截断显示，原文件共 {len(content)} 字符；当前只展示前 {budget}，非代码本身不完整] ... */\n"

        # 收集代码片段（dev_result 产出 + 仓库已有）。关键：dev_result 已经包含的文件
        # 不能再从 existing_code 二次渲染——否则 prompt 里出现两份"### index.html"，
        # 两份都截断，LLM 看到拼合后的残缺代码就误判为"代码不完整"。
        code_snippets = ""
        total = 0
        seen_paths: set = set()

        # 优先审查本次产出的代码
        if isinstance(dev_result, dict):
            files = dev_result.get("files", {})
            if isinstance(files, dict):
                for fp, content in files.items():
                    if fp.endswith((".md", ".txt")):
                        continue
                    if total >= max_code_chars:
                        code_snippets += f"\n### {fp}\n```\n[跳过 — 已达 max_code_chars={max_code_chars} 上限]\n```\n"
                        seen_paths.add(fp)
                        continue
                    remaining = max_code_chars - total
                    snippet = _fit(content, min(per_file_limit, remaining))
                    if snippet:
                        code_snippets += f"\n### {fp}\n```\n{snippet}\n```\n"
                        total += len(snippet)
                        seen_paths.add(fp)

        # 补充仓库已有代码（跳过 dev_result 已覆盖的路径）
        if total < max_code_chars and existing_code:
            for fp, content in existing_code.items():
                if fp in seen_paths:
                    continue
                if total >= max_code_chars:
                    break
                if fp.endswith((".md", ".txt")):
                    continue
                remaining = max_code_chars - total
                snippet = _fit(content, min(per_file_limit, remaining))
                if snippet:
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
