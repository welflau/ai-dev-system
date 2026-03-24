"""
DevAgent — 开发 Agent
职责：接单开发代码，更新开发时间和状态
"""
import json
from typing import Any, Dict
from agents.base import BaseAgent
from llm_client import llm_client


class DevAgent(BaseAgent):

    @property
    def agent_type(self) -> str:
        return "DevAgent"

    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if task_name == "develop":
            return await self.develop(context)
        elif task_name == "rework":
            return await self.rework(context)
        elif task_name == "fix_issues":
            return await self.fix_issues(context)
        else:
            return {"status": "error", "message": f"未知任务: {task_name}"}

    async def develop(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """开发任务"""
        ticket_title = context.get("ticket_title", "")
        ticket_description = context.get("ticket_description", "")
        architecture = context.get("architecture", {})
        module = context.get("module", "other")

        prompt = f"""你是一位资深软件开发工程师。请根据架构设计实现以下功能。

## 任务
标题: {ticket_title}
描述: {ticket_description}
模块: {module}

## 架构设计
{json.dumps(architecture, ensure_ascii=False, indent=2)}

## 请返回 JSON 格式：
{{
  "files_created": [
    {{
      "path": "文件路径",
      "description": "文件描述",
      "language": "编程语言",
      "lines_of_code": 行数
    }}
  ],
  "key_implementations": ["关键实现点"],
  "api_endpoints": [
    {{"method": "GET/POST/PUT/DELETE", "path": "/api/xxx", "description": "接口描述"}}
  ],
  "dependencies_added": ["新增依赖"],
  "estimated_hours": 实际用时估算,
  "notes": "开发备注"
}}
"""

        result = await llm_client.chat_json(
            [{"role": "user", "content": prompt}]
        )

        if result and isinstance(result, dict):
            return {
                "status": "success",
                "dev_result": result,
                "estimated_hours": result.get("estimated_hours", 4),
            }

        # 降级
        return {
            "status": "success",
            "dev_result": {
                "files_created": [
                    {"path": f"src/{module}/{ticket_title.lower().replace(' ', '_')}.py", "description": ticket_title, "language": "Python", "lines_of_code": 150}
                ],
                "key_implementations": [f"实现了 {ticket_title} 的核心功能"],
                "api_endpoints": [],
                "dependencies_added": [],
                "estimated_hours": 4,
                "notes": "[规则引擎] 代码开发完成",
            },
            "estimated_hours": 4,
        }

    async def rework(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """返工（验收不通过打回）"""
        rejection_reason = context.get("rejection_reason", "")
        return await self.develop({
            **context,
            "ticket_description": f"{context.get('ticket_description', '')} [返工原因] {rejection_reason}",
        })

    async def fix_issues(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """修复问题（测试不通过打回）"""
        test_issues = context.get("test_issues", [])
        return await self.develop({
            **context,
            "ticket_description": f"{context.get('ticket_description', '')} [测试问题] {json.dumps(test_issues, ensure_ascii=False)}",
        })
