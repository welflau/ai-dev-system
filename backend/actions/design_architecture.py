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

        # Self-Consistency 投票（opt-in via SOP config）：
        # 对"架构设计"这类主观发散任务，生成 N=3 候选 → Critic LLM 选 best。
        # 默认关闭（成本 4×），SOP config.self_consistency=true 时开启。
        sop_cfg = context.get("sop_config") or {}
        use_consistency = bool(sop_cfg.get("self_consistency", False))

        def _new_node():
            return ActionNode(
                key="design_architecture",
                expected_type=ArchitectureOutput,
                instruction="为以下任务设计增量架构方案。增量设计，已有代码不推翻，技术栈与已有一致。",
            )

        vote_info = None
        if use_consistency:
            from actions.voting import fill_with_consistency
            n = int(sop_cfg.get("consistency_n", 3) or 3)
            temp = float(sop_cfg.get("consistency_temperature", 0.8) or 0.8)
            try:
                best_node, all_nodes, judge_info = await fill_with_consistency(
                    _new_node, req=req_context, llm=llm_client,
                    n=n, temperature=temp, max_tokens=2000,
                    task_desc=f"为「{ticket_title}」设计增量架构方案",
                )
                node = best_node
                vote_info = {
                    "stage": "design_architecture",
                    "n_candidates": len(all_nodes),
                    "best_index": judge_info.get("best_index"),
                    "reasoning": judge_info.get("reasoning"),
                    "fallback": judge_info.get("fallback", False),
                    "temperature": temp,
                }
            except Exception as e:
                logger.warning("Self-Consistency 失败，降级到单次调用: %s", e)
                node = _new_node()
                await node.fill(req=req_context, llm=llm_client, max_tokens=2000)
        else:
            node = _new_node()
            await node.fill(req=req_context, llm=llm_client, max_tokens=2000)

        arch = node.instruct_content
        arch_dict = arch.model_dump() if arch else {}
        arch_md = _generate_arch_doc(ticket_title, arch_dict)

        result_data = {"architecture": arch_dict, "estimated_hours": arch.estimated_hours if arch else 4}
        if vote_info:
            result_data["_consistency_vote"] = vote_info

        return ActionResult(
            success=True,
            data=result_data,
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
