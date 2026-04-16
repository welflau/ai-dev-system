"""
Action: 项目代码理解（对标 MetaGPT SummarizeCode）
在拆单前读懂项目：现有功能、技术栈、文件职责、可改动范围
"""
import json
import logging
from typing import Any, Dict, List
from pydantic import BaseModel, Field
from actions.base import ActionBase, ActionResult
from actions.action_node import ActionNode
from llm_client import llm_client

logger = logging.getLogger("action.summarize_code")


class ProjectSummary(BaseModel):
    """项目理解报告 Schema"""
    tech_stack: str = ""
    features: List[str] = Field(default_factory=list, description="现有功能清单")
    file_roles: List[Dict] = Field(default_factory=list, description="关键文件职责 [{path, role}]")
    entry_file: str = ""
    complexity: str = "medium"  # simple / medium / complex


class SummarizeCodeAction(ActionBase):

    @property
    def name(self) -> str:
        return "summarize_code"

    @property
    def description(self) -> str:
        return "读懂项目：分析现有功能、技术栈、文件职责（拆单前置步骤）"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        existing_files = context.get("existing_files", [])
        existing_code = context.get("existing_code", {})

        if not existing_files and not existing_code:
            return ActionResult(
                success=True,
                data={"project_summary": {"tech_stack": "未知", "features": [], "file_roles": [], "entry_file": "", "complexity": "medium"}},
                message="空项目，无代码可分析",
            )

        # 构建上下文
        code_files = [f for f in existing_files if not f.startswith(("docs/", "tests/", ".git", "build/"))]
        file_list = "\n".join(f"  - {f}" for f in code_files[:30])

        code_section = ""
        for fp, code in list(existing_code.items())[:3]:
            code_section += f"\n### {fp}\n```\n{code[:2000]}\n```\n"

        req_context = f"""## 项目文件
{file_list}

## 代码内容
{code_section}

分析这个项目：它做了什么、用了什么技术、每个关键文件负责什么。"""

        node = ActionNode(
            key="summarize_code",
            expected_type=ProjectSummary,
            instruction="分析项目代码，输出项目理解报告。",
        )
        await node.fill(req=req_context, llm=llm_client, max_tokens=2000)

        summary = node.instruct_content
        if summary:
            logger.info("📖 项目理解: %s | %d 功能 | %d 文件 | 复杂度=%s",
                         summary.tech_stack, len(summary.features), len(summary.file_roles), summary.complexity)
            return ActionResult(
                success=True,
                data={"project_summary": summary.model_dump()},
            )

        return ActionResult(
            success=True,
            data={"project_summary": {"tech_stack": "未知", "features": [], "file_roles": [], "entry_file": "", "complexity": "medium"}},
        )
