"""Action: 产品验收（使用 ActionNode + SOP 配置 + 实际代码审查）"""
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
        return "验收开发结果是否符合需求（基于实际代码内容）"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        ticket_title = context.get("ticket_title", "")
        ticket_description = context.get("ticket_description", "")
        dev_result = context.get("dev_result", {})
        docs_prefix = context.get("docs_prefix", "docs/")
        existing_files = context.get("existing_files", [])
        existing_code = context.get("existing_code", {})

        # SOP 配置
        sop = context.get("sop_config", {})
        review_code_content = sop.get("review_code_content", True)
        max_code_chars = sop.get("max_code_chars", 3000)
        pass_score = sop.get("pass_score", 6)
        check_items = sop.get("check_items", [
            "入口文件是否存在且可运行",
            "代码功能是否覆盖需求描述",
            "代码风格是否规范",
        ])

        # 构建验收上下文
        # 1. 文件名列表
        dev_files = []
        if isinstance(dev_result, dict):
            fd = dev_result.get("files", {})
            if isinstance(fd, dict):
                dev_files = list(fd.keys())

        repo_code_files = [f for f in existing_files if not f.startswith(("docs/", "tests/", ".git", "build/"))]

        # 2. 实际代码内容（读真实代码，智能截断：头部+尾部）
        code_section = ""
        if review_code_content and existing_code:
            total = 0
            for fp, code in existing_code.items():
                if total >= max_code_chars:
                    break
                if len(code) <= 2000:
                    snippet = code
                else:
                    # 智能截断：头部 1500 + 尾部 500，让 LLM 知道代码是完整的
                    snippet = code[:1500] + f"\n\n... (中间省略 {len(code)-2000} 字符) ...\n\n" + code[-500:]
                code_section += f"\n### {fp} ({len(code)} 字符, 完整文件)\n```\n{snippet}\n```\n"
                total += len(snippet)

        # 3. 检查清单
        checklist = "\n".join(f"  {i+1}. {item}" for i, item in enumerate(check_items))

        req_context = f"""## 任务: {ticket_title}

## 需求描述
{ticket_description[:500]}

## 仓库代码文件
{', '.join(repo_code_files[:15]) or '无'}

## 本次开发产出
{', '.join(dev_files[:10]) or '无'}
开发备注: {str(dev_result.get('notes', ''))[:200]}
{code_section}
## 验收检查清单（请逐项检查）
{checklist}

评分标准: 1-10 分，{pass_score} 分及以上为通过。
注意: 代码因长度限制可能只展示了头部和尾部，中间省略部分不代表代码不完整。文件存在即视为已产出，请基于可见部分判断代码质量。"""

        node = ActionNode(
            key="acceptance_review",
            expected_type=ReviewOutput,
            instruction="作为产品经理，验收以下开发结果是否符合需求。逐项检查验收清单，给出评分和具体反馈。",
        )
        await node.fill(req=req_context, llm=llm_client, max_tokens=1500)

        review = node.instruct_content
        score = review.score if review else 6
        passed = score >= pass_score
        status = "acceptance_passed" if passed else "acceptance_rejected"

        # 生成验收报告
        review_md = f"""# 验收评审 — {ticket_title}

## 结果: {'✅ 通过' if passed else '❌ 不通过'}

| 项目 | 值 |
|------|------|
| 评分 | {score}/10 (通过线: {pass_score}) |
| 状态 | {status} |

## 反馈
{review.feedback if review else '-'}

## 检查清单
{checklist}

## 问题
{chr(10).join(f'- {i}' for i in (review.issues if review else [])) or '无'}

## 审查的代码文件
{', '.join(repo_code_files[:10]) or '无'}
"""

        logger.info("📋 验收: %s → %s (score=%d, pass_score=%d)",
                     ticket_title[:20], status, score, pass_score)

        return ActionResult(
            success=True,
            data={"status": status, "review": review.model_dump() if review else {}},
            files={f"{docs_prefix}acceptance-review.md": review_md},
        )
