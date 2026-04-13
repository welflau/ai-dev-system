"""Action: 架构设计（从 ArchitectAgent 抽离）"""
import json
from typing import Any, Dict
from actions.base import ActionBase, ActionResult
from llm_client import llm_client


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

        # 构建已有代码上下文
        existing_section = ""
        if existing_files:
            code_files = [f for f in existing_files if not f.startswith(("docs/", "tests/", ".git", "build/"))]
            if code_files:
                existing_section += f"\n## 项目已有文件\n" + "\n".join(f"  - {f}" for f in code_files[:20]) + "\n"
        if existing_code:
            existing_section += "\n## 现有代码（在此基础上扩展）\n"
            for fp, code in list(existing_code.items())[:2]:
                existing_section += f"\n### {fp}\n```\n{code[:1500]}\n```\n"
        if sibling_tickets:
            existing_section += "\n## 同需求其他工单\n" + "\n".join(f"  - [{t['status']}] {t['title']}" for t in sibling_tickets) + "\n"

        prompt = f"""为以下任务设计增量架构方案，返回 JSON。

## 需求: {requirement_description[:300]}
## 任务: {ticket_title}
{ticket_description}
模块: {module}
{existing_section}
返回: {{"architecture_type":"架构模式","tech_stack":{{"language":"","framework":""}},"module_design":[{{"name":"","responsibility":"","interfaces":[]}}],"data_flow":"","estimated_hours":0,"decisions":[]}}

要求：增量设计，已有代码不推翻，技术栈与已有一致。"""

        result = await llm_client.chat_json(
            [{"role": "user", "content": prompt}], max_tokens=2000,
        )

        if result and isinstance(result, dict):
            arch_md = _generate_arch_doc(ticket_title, result)
            return ActionResult(
                success=True,
                data={"architecture": result, "estimated_hours": result.get("estimated_hours", 4)},
                files={f"{docs_prefix}architecture.md": arch_md},
            )

        # 降级
        return _fallback_design(ticket_title, module, docs_prefix)


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
            lines.append(f"### {m.get('name', '')}")
            lines.append(f"职责: {m.get('responsibility', '')}")
            for iface in m.get("interfaces", []):
                lines.append(f"- {iface}")
            lines.append("")
    return "\n".join(lines)


def _fallback_design(title: str, module: str, docs_prefix: str) -> ActionResult:
    templates = {
        "frontend": {"architecture_type": "组件化架构", "tech_stack": {"language": "JavaScript", "framework": "原生 HTML/CSS/JS"}, "estimated_hours": 3},
        "backend": {"architecture_type": "分层架构", "tech_stack": {"language": "Python", "framework": "FastAPI"}, "estimated_hours": 4},
    }
    template = templates.get(module, templates["backend"])
    arch = {**template, "module_design": [{"name": title, "responsibility": f"实现 {title}", "interfaces": []}]}
    return ActionResult(
        success=True,
        data={"architecture": arch, "estimated_hours": template["estimated_hours"]},
        files={f"{docs_prefix}architecture.md": _generate_arch_doc(title, arch)},
    )
