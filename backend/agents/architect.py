"""
ArchitectAgent — 架构设计 Agent
职责：接单做架构设计，更新预计完成时间
"""
import json
from typing import Any, Dict
from agents.base import BaseAgent
from llm_client import llm_client


class ArchitectAgent(BaseAgent):

    @property
    def agent_type(self) -> str:
        return "ArchitectAgent"

    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if task_name == "design_architecture":
            return await self.design_architecture(context)
        else:
            return {"status": "error", "message": f"未知任务: {task_name}"}

    async def design_architecture(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """设计架构方案（基于已有代码的增量设计）"""
        ticket_title = context.get("ticket_title", "")
        ticket_description = context.get("ticket_description", "")
        module = context.get("module", "other")
        requirement_description = context.get("requirement_description", "")
        docs_prefix = context.get("docs_prefix", "docs/")
        existing_files = context.get("existing_files", [])
        existing_code = context.get("existing_code", {})
        sibling_tickets = context.get("sibling_tickets", [])
        knowledge_docs = context.get("knowledge_docs", "")

        # 构建已有代码上下文
        existing_section = ""
        if existing_files:
            code_files = [f for f in existing_files if not f.startswith(("docs/", "tests/", ".git", "build/"))]
            if code_files:
                existing_section += f"\n## 项目已有文件\n" + "\n".join(f"  - {f}" for f in code_files[:20]) + "\n"

        if existing_code:
            existing_section += "\n## 现有代码（重要：在此基础上扩展，不要重新设计）\n"
            for fp, code in list(existing_code.items())[:2]:
                existing_section += f"\n### {fp}\n```\n{code[:1500]}\n```\n"

        if sibling_tickets:
            existing_section += "\n## 同需求其他工单\n" + "\n".join(f"  - [{t['status']}] {t['title']}" for t in sibling_tickets) + "\n"

        # 知识库章节
        knowledge_section = f"\n## 项目知识库（请严格遵守以下规范）\n{knowledge_docs}\n" if knowledge_docs else ""

        prompt = f"""你是一位资深软件架构师。请为以下任务设计**增量架构方案**。
{knowledge_section}
## 需求背景
{requirement_description}

## 当前任务
标题: {ticket_title}
描述: {ticket_description}
模块: {module}
{existing_section}
## 请返回 JSON 格式：
{{
  "architecture_type": "架构模式",
  "tech_stack": {{"language": "语言", "framework": "框架"}},
  "module_design": [{{"name": "模块", "responsibility": "职责", "interfaces": ["接口"]}}],
  "data_flow": "数据流描述",
  "estimated_hours": 工时,
  "decisions": ["关键决策"]
}}

关键要求：
1. **增量设计**：如果项目已有代码（index.html/main.py），在现有架构上扩展，不要推翻重来
2. 前端项目如果已有 index.html，新功能应在其中添加，不要设计全新页面结构
3. 技术栈必须与已有代码一致（已用原生 JS 就不要改成 React）
4. module_design 只描述本工单需要新增/修改的部分
"""

        result = await llm_client.chat_json(
            [{"role": "user", "content": prompt}],
            max_tokens=2000,
        )

        if result and isinstance(result, dict):
            arch_md = self._generate_arch_doc(ticket_title, result)
            return {
                "status": "success",
                "architecture": result,
                "estimated_hours": result.get("estimated_hours", 4),
                "files": {
                    f"{docs_prefix}architecture.md": arch_md,
                },
            }

        # 降级
        return self._fallback_design(ticket_title, module, docs_prefix)

    def _generate_arch_doc(self, title: str, arch: dict) -> str:
        """根据架构数据生成 Markdown 文档"""
        lines = [f"# 架构设计 - {title}\n"]
        lines.append(f"## 架构模式\n{arch.get('architecture_type', '未指定')}\n")

        ts = arch.get("tech_stack", {})
        if ts:
            lines.append("## 技术栈\n")
            for k, v in ts.items():
                lines.append(f"- **{k}**: {v if isinstance(v, str) else ', '.join(v)}")
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

        if arch.get("data_flow"):
            lines.append(f"## 数据流\n{arch['data_flow']}\n")

        risks = arch.get("risks", [])
        if risks:
            lines.append("## 风险点\n" + "\n".join(f"- {r}" for r in risks) + "\n")

        decisions = arch.get("decisions", [])
        if decisions:
            lines.append("## 关键决策\n" + "\n".join(f"- {d}" for d in decisions) + "\n")

        return "\n".join(lines)

    def _fallback_design(self, title: str, module: str, docs_prefix: str = "docs/") -> Dict:
        """规则引擎降级架构设计"""
        arch_templates = {
            "frontend": {
                "architecture_type": "组件化架构",
                "tech_stack": {"language": "JavaScript", "framework": "原生 HTML/CSS/JS"},
                "estimated_hours": 3,
            },
            "backend": {
                "architecture_type": "分层架构（Controller-Service-Repository）",
                "tech_stack": {"language": "Python", "framework": "FastAPI"},
                "estimated_hours": 4,
            },
            "database": {
                "architecture_type": "关系型数据库设计",
                "tech_stack": {"language": "SQL", "framework": "SQLite"},
                "estimated_hours": 2,
            },
            "api": {
                "architecture_type": "RESTful API",
                "tech_stack": {"language": "Python", "framework": "FastAPI"},
                "estimated_hours": 3,
            },
        }

        template = arch_templates.get(module, arch_templates["backend"])
        arch_result = {
            **template,
            "module_design": [{"name": title, "responsibility": f"实现 {title} 功能", "interfaces": []}],
            "data_flow": "请求 → Controller → Service → Repository → Database",
            "risks": ["需进一步细化接口设计"],
            "decisions": ["采用分层架构，保持模块解耦"],
        }
        return {
            "status": "success",
            "architecture": arch_result,
            "estimated_hours": template["estimated_hours"],
            "files": {
                f"{docs_prefix}architecture.md": self._generate_arch_doc(title, arch_result),
            },
        }
