"""
WritePRDAction — 策划 Agent 的核心 Action

对每张工单产出一份标准化 PRD（用户故事 + 验收标准 + 边界条件 + 资产需求线索），
写入 docs/Reqs/{req_id}/{ticket_id}/PRD.md。
提供给 ArchitectAgent 和 DevAgent 作为设计和开发的明确依据。
"""
import logging
from typing import Any, Dict

from actions.base import ActionBase, ActionResult
from actions.action_node import ActionNode
from pydantic import BaseModel

logger = logging.getLogger("action.write_prd")


class PRDOutput(BaseModel):
    """策划 PRD 产出物"""
    user_story: str = ""          # 用户故事：As a ... I want to ... So that ...
    functional_requirements: str = ""  # 功能需求描述（Markdown 列表）
    acceptance_criteria: str = ""      # 验收标准（必须可量化，每条可测试）
    boundary_conditions: str = ""      # 边界条件和不做的事
    asset_hints: str = ""             # 资产需求线索（音频/图片/动画/特效）


class WritePRDAction(ActionBase):

    @property
    def name(self) -> str:
        return "write_prd"

    @property
    def description(self) -> str:
        return "为工单产出标准化 PRD（用户故事/验收标准/边界条件/资产线索）"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        from llm_client import llm_client

        ticket_title = context.get("ticket_title", "")
        ticket_desc  = context.get("ticket_description", "")
        req_title    = context.get("requirement_title", "")
        req_desc     = context.get("requirement_description", "")
        docs_prefix  = context.get("docs_prefix", "docs/")
        traits       = context.get("traits", [])

        # 领域知识 + 项目历史（由 KnowledgeLoader 注入）
        domain_kb      = context.get("domain_knowledge", "")
        project_kb     = context.get("project_knowledge", "")
        agent_spec     = context.get("agent_spec", "")

        knowledge_section = ""
        if domain_kb:
            knowledge_section += f"\n## 领域设计参考\n{domain_kb}\n"
        if project_kb:
            knowledge_section += f"\n## 项目历史经验\n{project_kb}\n"
        if agent_spec:
            knowledge_section += f"\n## 策划规范\n{agent_spec}\n"

        # Smart Probe：评估需求清晰度
        clarity_hint = ""
        unclear_fields = []
        if not ticket_desc or len(ticket_desc) < 30:
            unclear_fields.append("功能描述不够详细")
        if "验收" not in (ticket_desc or "") and "标准" not in (ticket_desc or ""):
            unclear_fields.append("未提供验收标准")
        if unclear_fields:
            clarity_hint = f"\n⚠️ 注意：以下信息不明确，请在 PRD 中合理假设并用 [假设] 标注：{', '.join(unclear_fields)}\n"

        req_context = f"""## 所属需求
标题：{req_title}
描述：{req_desc}

## 当前工单
标题：{ticket_title}
描述：{ticket_desc or '（无详细描述，请基于需求合理推断）'}

## 项目特征
{', '.join(traits) if traits else '未知'}
{clarity_hint}{knowledge_section}
## 策划规则

**验收标准必须可量化**（举例）：
- ❌ 错误："界面美观"、"功能正常"
- ✅ 正确："点击按钮后 300ms 内弹出弹窗"、"列表最多显示 50 条，超出分页"

**资产需求线索** 列出需要的：图标/插画/背景图/音效/背景音乐/骨骼动画/粒子特效等。
留空填写"暂无"。

**不做的事** 明确写出 scope 之外的内容，防止 DevAgent 过度实现。"""

        node = ActionNode(
            key="write_prd",
            expected_type=PRDOutput,
            instruction="[MODE: DESIGN] 你是专职策划，为工单产出结构化 PRD。验收标准每条必须可量化可测试，不写模糊描述。",
        )

        await node.fill(req=req_context, llm=llm_client, max_tokens=3000)
        output = node.instruct_content

        if not output or not output.acceptance_criteria:
            logger.warning("WritePRDAction LLM 输出不完整，使用降级 PRD")
            output = PRDOutput(
                user_story=f"作为用户，我需要 {ticket_title}",
                functional_requirements=f"- {ticket_desc or ticket_title}",
                acceptance_criteria="- 功能可正常使用（待细化）",
                boundary_conditions="- 暂无特殊限制",
                asset_hints="暂无",
            )

        # 构建 PRD Markdown
        prd_md = f"""# PRD — {ticket_title}

> 所属需求：{req_title}

## 用户故事
{output.user_story}

## 功能需求
{output.functional_requirements}

## 验收标准
{output.acceptance_criteria}

## 边界条件（不做的事）
{output.boundary_conditions}

## 资产需求线索
{output.asset_hints}
"""

        logger.info("✅ WritePRDAction 完成: %s", ticket_title[:30])

        return ActionResult(
            success=True,
            data={
                "prd_content": prd_md,
                "acceptance_criteria": output.acceptance_criteria,
                "asset_hints": output.asset_hints,
                "clarity_issues": unclear_fields,
            },
            files={f"{docs_prefix}PRD.md": prd_md},
            message=f"PRD 已生成：{ticket_title}",
        )
