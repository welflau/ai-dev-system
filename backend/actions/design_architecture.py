"""Action: 架构设计（使用 ActionNode 结构化输出）"""
import json
import logging
from typing import Any, Dict
from actions.base import ActionBase, ActionResult
from actions.action_node import ActionNode
from actions.schemas import ArchitectureOutput
from llm_client import llm_client

logger = logging.getLogger("action.architecture")


class DesignArchitectureAction(ActionBase):

    @property
    def name(self) -> str:
        return "design_architecture"

    @property
    def description(self) -> str:
        return "分析需求，设计增量技术架构方案"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        ticket_title = context.get("ticket_title", "")
        ticket_description = context.get("ticket_description", "")
        module = context.get("module", "other")
        requirement_description = context.get("requirement_description", "")
        docs_prefix = context.get("docs_prefix", "docs/")
        existing_files = context.get("existing_files", [])
        existing_code = context.get("existing_code", {})
        sibling_tickets = context.get("sibling_tickets", [])

        # 构建上下文
        ctx_parts = [f"## 需求: {requirement_description[:300]}", f"## 任务: {ticket_title}", ticket_description, f"模块: {module}"]
        if existing_files:
            code_files = [f for f in existing_files if not f.startswith(("docs/", "tests/", ".git", "build/"))]
            if code_files:
                ctx_parts.append("## 已有文件\n" + "\n".join(f"  - {f}" for f in code_files[:20]))
        if existing_code:
            ctx_parts.append("## 现有代码（在此基础上扩展）")
            for fp, code in list(existing_code.items())[:2]:
                ctx_parts.append(f"### {fp}\n```\n{code[:1500]}\n```")
        if sibling_tickets:
            ctx_parts.append("## 同需求其他工单\n" + "\n".join(f"  - [{t['status']}] {t['title']}" for t in sibling_tickets))

        req_context = "\n\n".join(ctx_parts)

        # 使用 ActionNode 结构化输出
        node = ActionNode(
            key="design_architecture",
            expected_type=ArchitectureOutput,
            instruction="为以下任务设计增量架构方案。增量设计，已有代码不推翻，技术栈与已有一致。",
        )
        await node.fill(req=req_context, llm=llm_client, max_tokens=2000)

        arch = node.instruct_content
        arch_dict = arch.model_dump() if arch else {}
        arch_md = _generate_arch_doc(ticket_title, arch_dict)

        return ActionResult(
            success=True,
            data={"architecture": arch_dict, "estimated_hours": arch.estimated_hours if arch else 4},
            files={f"{docs_prefix}architecture.md": arch_md},
        )


def _generate_arch_doc(title: str, arch: dict) -> str:
    lines = [f"# 架构设计 - {title}\n"]
    lines.append(f"## 架构模式\n{arch.get('architecture_type', '未指定')}\n")
    ts = arch.get("tech_stack", {})
    if ts:
        lines.append("## 技术栈\n")
        for k, v in ts.items():
            lines.append(f"- **{k}**: {v if isinstance(v, str) else ', '.join(v) if isinstance(v, list) else str(v)}")
        lines.append("")
    modules = arch.get("module_design", [])
    if modules:
        lines.append("## 模块设计\n")
        for m in modules:
            if isinstance(m, dict):
                lines.append(f"### {m.get('name', '')}")
                lines.append(f"职责: {m.get('responsibility', '')}")
                for iface in m.get("interfaces", []):
                    lines.append(f"- {iface}")
                lines.append("")
    decisions = arch.get("decisions", [])
    if decisions:
        lines.append("## 关键决策\n" + "\n".join(f"- {d}" for d in decisions) + "\n")
    return "\n".join(lines)
