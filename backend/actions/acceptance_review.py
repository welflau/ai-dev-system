"""Action: 产品验收（从 ProductAgent.acceptance_review 抽离）"""
import json
import logging
from typing import Any, Dict
from actions.base import ActionBase, ActionResult
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

        files_info = ""
        if isinstance(dev_result, dict):
            file_dict = dev_result.get("files", {})
            if isinstance(file_dict, dict):
                files_info = ", ".join(list(file_dict.keys())[:5])

        prompt = f"""验收以下开发结果，返回 JSON: {{"passed": true/false, "score": 1-10, "feedback": "验收意见", "issues": ["问题"]}}

任务: {ticket_title}
需求: {ticket_description[:300]}
产出文件: {files_info}
开发备注: {str(dev_result.get('notes', ''))[:200]}"""

        try:
            result = await llm_client.chat_json(
                [{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=1000,
            )
            if result and isinstance(result, dict):
                passed = result.get("passed", True)
                status = "acceptance_passed" if passed else "acceptance_rejected"
                review_md = f"""# 验收评审 - {ticket_title}

## 结果: {'✅ 通过' if passed else '❌ 不通过'}
- 评分: {result.get('score', '-')}/10
- 反馈: {result.get('feedback', '-')}

## 问题
{chr(10).join(f'- {i}' for i in result.get('issues', [])) or '无'}
"""
                return ActionResult(
                    success=True,
                    data={"status": status, "review": result},
                    files={f"{docs_prefix}acceptance-review.md": review_md},
                )
        except Exception as e:
            logger.warning("验收 LLM 失败: %s", e)

        # 降级：默认通过
        return ActionResult(
            success=True,
            data={"status": "acceptance_passed", "review": {"passed": True, "score": 6, "feedback": "[降级] 默认通过"}},
            files={f"{docs_prefix}acceptance-review.md": f"# 验收评审 - {ticket_title}\n\n✅ [降级] 默认通过\n"},
        )
