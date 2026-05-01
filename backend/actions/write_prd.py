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


def _smart_probe(title: str, desc: str, req_desc: str, traits: list) -> dict:
    """
    Smart Probe：5 维度评估需求清晰度（满分 25 分）
    ≥ 20：直接开发
    15-19：AI 自动补假设，用 [假设] 标注
    < 15：提醒策划补充关键信息（当前只提示，不阻断，让 AI 合理假设继续）

    维度：用户价值 / 范围边界 / 交互方式 / 数值参数 / 关联影响（各5分）
    """
    score = 0
    issues = []

    desc_full = f"{title} {desc or ''} {req_desc or ''}"

    # 1. 用户价值（有没有说明为什么要做这个）
    value_kw = ["为了", "目的", "解决", "帮助", "提升", "用户", "体验", "需求"]
    if any(kw in desc_full for kw in value_kw) or len(desc or "") > 50:
        score += 5
    else:
        issues.append("用户价值不明确（为什么要做这个功能？）")
        score += 2

    # 2. 范围边界（有没有说明做什么/不做什么）
    scope_kw = ["不包含", "暂不", "只需要", "仅", "范围", "边界", "不支持"]
    if any(kw in desc_full for kw in scope_kw):
        score += 5
    elif len(desc or "") > 100:
        score += 3  # 描述详细，部分分
        issues.append("范围边界不明确（哪些不做？）")
    else:
        score += 1
        issues.append("范围边界不明确（哪些不做？）")

    # 3. 交互方式（有没有描述用户操作流程）
    ux_kw = ["点击", "输入", "滑动", "跳转", "弹出", "展示", "显示", "列表", "按钮", "页面", "界面"]
    ux_count = sum(1 for kw in ux_kw if kw in desc_full)
    if ux_count >= 3:
        score += 5
    elif ux_count >= 1:
        score += 3
        issues.append("交互方式不够具体（用户如何操作？）")
    else:
        score += 1
        issues.append("交互方式不明确（需要 UI 交互的请描述操作流程）")

    # 4. 数值参数（有没有关键数字）
    has_num = any(c.isdigit() for c in desc_full)
    num_kw = ["最多", "最少", "限制", "上限", "下限", "数量", "大小", "时间", "秒", "毫秒", "字符"]
    if has_num or any(kw in desc_full for kw in num_kw):
        score += 5
    else:
        score += 2
        # 游戏类项目更需要数值
        if "category:game" in traits:
            issues.append("关键数值未说明（伤害/生命值/冷却时间等）")

    # 5. 关联影响（有没有提到和其他功能的关系）
    rel_kw = ["关联", "依赖", "影响", "配合", "接口", "同步", "共用", "继承", "已有", "现有"]
    if any(kw in desc_full for kw in rel_kw):
        score += 5
    elif len(desc_full) > 200:
        score += 3  # 描述详细说明考虑了关联
    else:
        score += 2

    # 根据得分决定操作
    if score >= 20:
        action = "direct"
        hint = ""
    elif score >= 15:
        action = "assume"
        hint = f"\n[Smart Probe] 清晰度 {score}/25，以下信息不明确，将自动补充合理假设并用 [假设] 标注：{'; '.join(issues)}\n"
    else:
        action = "assume"  # 不阻断，继续生成，但给更强提示
        hint = f"\n[Smart Probe] 清晰度 {score}/25（偏低），关键信息缺失：{'; '.join(issues)}。请在 PRD 中为每个缺失项补充 [假设] 并在末尾列出「待确认事项」。\n"

    return {"score": score, "action": action, "hint": hint, "issues": issues}


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

        # Smart Probe：5 维度需求清晰度评分
        probe_result = _smart_probe(ticket_title, ticket_desc, req_desc, traits)
        clarity_hint = probe_result["hint"]
        logger.info("Smart Probe: %s → 得分 %d/25，操作: %s",
                    ticket_title[:20], probe_result["score"], probe_result["action"])

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
                "smart_probe_score": probe_result["score"],
                "smart_probe_issues": probe_result["issues"],
            },
            files={f"{docs_prefix}PRD.md": prd_md},
            message=f"PRD 已生成：{ticket_title}",
        )
