"""
Action: 需求拆单（基于项目理解 + 复杂度判断）
- 简单需求（改颜色/改文案）→ 1 个工单，跳过架构
- 中等需求 → 2-3 个工单
- 复杂需求 → 正常拆多个工单
"""
import logging
from typing import Any, Dict
from actions.base import ActionBase, ActionResult
from actions.action_node import ActionNode
from actions.schemas import DecomposeOutput
from llm_client import llm_client

logger = logging.getLogger("action.decompose")


class DecomposeAction(ActionBase):

    @property
    def name(self) -> str:
        return "decompose"

    @property
    def description(self) -> str:
        return "基于项目理解拆单（自动判断复杂度，简单需求不过度拆分）"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        title = context.get("title", "")
        description = context.get("description", "")
        priority = context.get("priority", "medium")
        existing_files = context.get("existing_files", [])
        existing_code = context.get("existing_code", {})
        project_summary = context.get("project_summary", {})
        docs_prefix = context.get("docs_prefix", "docs/")

        # 项目理解上下文
        summary_section = ""
        if project_summary:
            features = project_summary.get("features", [])
            file_roles = project_summary.get("file_roles", [])
            tech = project_summary.get("tech_stack", "")
            if features:
                summary_section += f"\n## 项目现有功能\n" + "\n".join(f"  - {f}" for f in features) + "\n"
            if file_roles:
                summary_section += "\n## 关键文件职责\n"
                for fr in file_roles[:10]:
                    if isinstance(fr, dict):
                        summary_section += f"  - {fr.get('path', '')}: {fr.get('role', '')}\n"
                    else:
                        summary_section += f"  - {fr}\n"
            if tech:
                summary_section += f"\n技术栈: {tech}\n"

        # 已有代码上下文
        code_context = ""
        if existing_files:
            code_files = [f for f in existing_files if not f.startswith(("docs/", "tests/", ".git", "build/"))]
            if code_files:
                code_context += f"\n## 项目文件（{len(code_files)} 个）\n" + "\n".join(f"  - {f}" for f in code_files[:15]) + "\n"

        req_context = f"""## 需求
标题: {title}
描述: {description}
优先级: {priority}
{summary_section}{code_context}
## 拆单规则

**首先判断复杂度**:
- **simple**（改颜色/改文案/改配置/修小 bug）→ 只拆 1 个工单，工单标题直接描述改动
- **medium**（新增小功能/修改交互/页面调整）→ 2-3 个工单
- **complex**（新模块/架构变更/大功能）→ 4-6 个工单

**重要**:
- 已有功能不要重复拆单
- 如果只需要修改一个文件就能完成，只拆 1 个工单
- 每个工单的 module 字段指定是 frontend/backend/design 等
- subtasks 用字符串列表（如 ["修改背景色", "调整文字对比度"]）"""

        node = ActionNode(
            key="decompose",
            expected_type=DecomposeOutput,
            instruction="作为产品经理，先判断需求复杂度（simple/medium/complex），再合理拆单。简单需求不要过度拆分。",
        )
        await node.fill(req=req_context, llm=llm_client, max_tokens=4000)

        output = node.instruct_content
        if output and output.tickets:
            complexity = output.complexity or "medium"
            prd_md = f"# PRD — {title}\n\n**复杂度**: {complexity}\n\n{output.prd_summary}\n"
            logger.info("✅ 需求拆单: %s → 复杂度=%s, %d 个工单", title[:20], complexity, len(output.tickets))
            return ActionResult(
                success=True,
                data={
                    "prd_summary": output.prd_summary,
                    "tickets": output.tickets,
                    "complexity": complexity,
                },
                files={f"{docs_prefix}PRD.md": prd_md},
            )

        # 降级
        logger.warning("⚠️ 需求拆单 LLM 失败，使用降级")
        return self._fallback(title, description, docs_prefix)

    def _fallback(self, title: str, description: str, docs_prefix: str) -> ActionResult:
        tickets = [
            {"title": f"{title}", "description": description[:200],
             "type": "feature", "module": "frontend", "priority": 2, "estimated_hours": 4,
             "subtasks": ["实现功能", "自测验证"], "dependencies": []},
        ]
        return ActionResult(
            success=True,
            data={"prd_summary": f"[降级] {title}", "tickets": tickets, "complexity": "simple"},
            files={f"{docs_prefix}PRD.md": f"# PRD — {title}\n\n{description}\n"},
        )
