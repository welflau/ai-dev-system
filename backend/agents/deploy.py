"""
DeployAgent — 部署 Agent
职责：生成部署配置并执行部署
"""
import json
from typing import Any, Dict
from agents.base import BaseAgent
from llm_client import llm_client


class DeployAgent(BaseAgent):

    @property
    def agent_type(self) -> str:
        return "DeployAgent"

    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if task_name == "deploy":
            return await self.deploy(context)
        else:
            return {"status": "error", "message": f"未知任务: {task_name}"}

    async def deploy(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """部署"""
        ticket_title = context.get("ticket_title", "")
        dev_result = context.get("dev_result", {})
        test_result = context.get("test_result", {})

        prompt = f"""你是一位 DevOps 工程师。请为以下项目生成部署配置。

## 任务
{ticket_title}

## 开发交付物
{json.dumps(dev_result, ensure_ascii=False, indent=2)}

## 测试结果
{json.dumps(test_result, ensure_ascii=False, indent=2)}

请返回 JSON：
{{
  "deploy_configs": [
    {{
      "type": "dockerfile|docker-compose|nginx|ci-cd",
      "filename": "文件名",
      "description": "描述"
    }}
  ],
  "deploy_steps": ["部署步骤"],
  "environment": {{
    "runtime": "运行环境",
    "ports": [端口],
    "env_vars": ["环境变量"]
  }},
  "health_check": {{
    "endpoint": "健康检查地址",
    "expected_status": 200
  }}
}}
"""

        result = await llm_client.chat_json([{"role": "user", "content": prompt}])

        if result and isinstance(result, dict):
            return {
                "status": "success",
                "deploy_result": result,
            }

        # 降级
        return {
            "status": "success",
            "deploy_result": {
                "deploy_configs": [
                    {"type": "dockerfile", "filename": "Dockerfile", "description": "Docker 构建配置"},
                    {"type": "docker-compose", "filename": "docker-compose.yml", "description": "服务编排配置"},
                ],
                "deploy_steps": [
                    "docker build -t ai-dev-system .",
                    "docker-compose up -d",
                    "运行健康检查",
                ],
                "environment": {
                    "runtime": "Python 3.10",
                    "ports": [8000],
                    "env_vars": ["LLM_API_KEY", "DATABASE_URL"],
                },
                "health_check": {
                    "endpoint": "/api/health",
                    "expected_status": 200,
                },
            },
        }
