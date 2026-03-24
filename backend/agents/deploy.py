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

        prompt = f"""你是一位 DevOps 工程师。请为以下项目生成部署配置文件。

## 任务
{ticket_title}

## 开发交付物
{json.dumps(dev_result, ensure_ascii=False, indent=2)}

## 测试结果
{json.dumps(test_result, ensure_ascii=False, indent=2)}

## 请返回 JSON 格式（files 字段包含真正的文件内容）：
{{
  "files": {{
    "build/Dockerfile": "FROM python:3.10-slim\\n...",
    "build/docker-compose.yml": "version: '3'\\n...",
    "build/.github/workflows/ci.yml": "name: CI\\n...",
    "docs/deploy.md": "# 部署文档\\n..."
  }},
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

关键要求：files 字典的 value 是文件的完整内容
"""

        result = await llm_client.chat_json(
            [{"role": "user", "content": prompt}]
        )

        if result and isinstance(result, dict):
            files = result.get("files", {})
            return {
                "status": "success",
                "deploy_result": result,
                "files": files if isinstance(files, dict) else {},
            }

        # 降级：生成标准部署配置
        return self._fallback_deploy(ticket_title)

    def _fallback_deploy(self, title: str) -> Dict:
        """规则引擎降级：生成标准部署配置"""
        files = {}

        files["build/Dockerfile"] = """FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY config/ ./config/

EXPOSE 8000

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
"""

        files["build/docker-compose.yml"] = f"""version: '3.8'

services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=sqlite:///data/app.db
    volumes:
      - app-data:/app/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  app-data:
"""

        files["build/.github/workflows/ci.yml"] = """name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.10'
      - run: pip install -r requirements.txt
      - run: pytest tests/ -v
"""

        files["docs/deploy.md"] = f"""# 部署文档 - {title}

## 环境要求
- Python 3.10+
- Docker & Docker Compose

## 部署步骤

1. 构建镜像: `docker build -t app .`
2. 启动服务: `docker-compose up -d`
3. 健康检查: `curl http://localhost:8000/api/health`

## 环境变量
- `DATABASE_URL`: 数据库连接地址
- `LLM_API_KEY`: LLM API Key

## 端口
- 8000: HTTP 服务
"""

        return {
            "status": "success",
            "deploy_result": {
                "files": files,
                "deploy_steps": [
                    "docker build -t app .",
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
            "files": files,
        }
