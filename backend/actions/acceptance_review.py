"""Action: 产品验收（使用 ActionNode 结构化输出）"""
import logging
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
        return "验收开发结果是否符合需求"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        ticket_title = context.get("ticket_title", "")
        ticket_description = context.get("ticket_description", "")
        dev_result = context.get("dev_result", {})
        docs_prefix = context.get("docs_prefix", "docs/")
        existing_files = context.get("existing_files", [])

        # 汇总文件信息：dev_result 产出 + 仓库已有文件
        files_info = ""
        if isinstance(dev_result, dict):
            fd = dev_result.get("files", {})
            if isinstance(fd, dict):
                files_info = ", ".join(list(fd.keys())[:5])

        # 仓库实际文件列表（补充 dev_result 可能遗漏的）
        repo_files = [f for f in existing_files if not f.startswith(("docs/", "tests/", ".git", "build/"))]
        repo_info = ", ".join(repo_files[:10]) if repo_files else "无"

        req_context = f"""任务: {ticket_title}
需求: {ticket_description[:300]}
本次产出文件: {files_info or '无'}
仓库已有代码文件: {repo_info}
开发备注: {str(dev_result.get('notes', ''))[:200]}

注意: 仓库中已有的文件视为已完成，不要因为本次 dev_result 没列出就判定缺失。"""

        node = ActionNode(
            key="acceptance_review",
            expected_type=ReviewOutput,
            instruction="验收以下开发结果是否符合需求。",
        )
        await node.fill(req=req_context, llm=llm_client, max_tokens=1000)

        review = node.instruct_content
        passed = review.passed if review else True
        status = "acceptance_passed" if passed else "acceptance_rejected"

        review_md = f"""# 验收评审 - {ticket_title}

## 结果: {'✅ 通过' if passed else '❌ 不通过'}
- 评分: {review.score if review else '-'}/10
- 反馈: {review.feedback if review else '-'}

## 问题
{chr(10).join(f'- {i}' for i in (review.issues if review else [])) or '无'}
"""

        return ActionResult(
            success=True,
            data={"status": status, "review": review.model_dump() if review else {}},
            files={f"{docs_prefix}acceptance-review.md": review_md},
        )
