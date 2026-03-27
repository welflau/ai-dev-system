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
        """设计架构方案"""
        ticket_title = context.get("ticket_title", "")
        ticket_description = context.get("ticket_description", "")
        module = context.get("module", "other")
        requirement_description = context.get("requirement_description", "")
        docs_prefix = context.get("docs_prefix", "docs/")

        prompt = f"""你是一位资深软件架构师。请为以下任务设计技术架构方案。

## 需求背景
{requirement_description}

## 当前任务
标题: {ticket_title}
描述: {ticket_description}
模块: {module}

## 请返回 JSON 格式：
{{
  "architecture_type": "架构模式（如 MVC、微服务、分层等）",
  "tech_stack": {{
    "language": "编程语言",
    "framework": "框架",
    "database": "数据库",
    "others": ["其他技术"]
  }},
  "module_design": [
    {{
      "name": "模块名",
      "responsibility": "职责描述",
      "interfaces": ["接口描述"]
    }}
  ],
  "data_flow": "数据流描述",
  "estimated_hours": 预估开发工时（小时）,
  "risks": ["风险点"],
  "decisions": ["关键技术决策"]
}}
"""

        result = await llm_client.chat_json(
            [{"role": "user", "content": prompt}]
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
