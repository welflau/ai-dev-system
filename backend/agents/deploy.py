"""
DeployAgent — 部署 Agent
职责：启动本地预览服务 + 生成部署配置
"""
import json
import asyncio
import subprocess
from typing import Any, Dict
from agents.base import BaseAgent
from llm_client import llm_client
import logging

logger = logging.getLogger("deploy_agent")


class DeployAgent(BaseAgent):

    @property
    def agent_type(self) -> str:
        return "DeployAgent"

    # 记录已启动的预览服务 {project_id: {"port": int, "process": Popen}}
    _preview_servers: Dict[str, Dict] = {}

    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if task_name == "deploy":
            return await self.deploy(context)
        else:
            return {"status": "error", "message": f"未知任务: {task_name}"}

    async def deploy(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """部署：启动本地预览服务 + 生成部署配置"""
        ticket_title = context.get("ticket_title", "")
        dev_result = context.get("dev_result", {})
        test_result = context.get("test_result", {})
        docs_prefix = context.get("docs_prefix", "docs/")
        project_id = context.get("project_id", "")

        # Step 1: 尝试启动本地预览服务
        preview_url = None
        if project_id:
            preview_url = await self._start_preview_server(project_id)

        # Step 2: 生成部署配置文件
        files = self._generate_deploy_files(ticket_title, docs_prefix, preview_url)

        return {
            "status": "success",
            "deploy_result": {
                "preview_url": preview_url,
                "deploy_steps": [
                    "docker build -t app .",
                    "docker-compose up -d",
                ],
                "environment": {
                    "runtime": "Python 3.10 / Node.js",
                    "ports": [8000],
                },
            },
            "files": files,
        }

    async def _start_preview_server(self, project_id: str) -> str:
        """在项目仓库目录启动一个简单的 HTTP 服务器用于预览"""
        from git_manager import git_manager

        repo_dir = str(git_manager._repo_path(project_id))

        # 如果已有该项目的预览服务，先停掉
        if project_id in self._preview_servers:
            old = self._preview_servers[project_id]
            try:
                old["process"].terminate()
            except Exception:
                pass
            del self._preview_servers[project_id]

        # 分配端口：9000 + hash
        port = 9000 + (abs(hash(project_id)) % 1000)

        try:
            # 启动 Python HTTP 服务器
            proc = subprocess.Popen(
                ["python", "-m", "http.server", str(port)],
                cwd=repo_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            await asyncio.sleep(1)  # 等服务启动

            if proc.poll() is None:  # 进程还活着
                self._preview_servers[project_id] = {
                    "port": port,
                    "process": proc,
                    "repo_dir": repo_dir,
                }
                url = f"http://localhost:{port}"
                logger.info("🌐 预览服务已启动: %s (pid=%d, dir=%s)", url, proc.pid, repo_dir)
                return url
            else:
                logger.warning("预览服务启动失败: 进程退出")
                return None
        except Exception as e:
            logger.warning("启动预览服务失败: %s", e)
            return None

    def _generate_deploy_files(self, title: str, docs_prefix: str, preview_url: str = None) -> Dict:
        """生成部署配置文件"""
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
    restart: unless-stopped
"""

        preview_section = ""
        if preview_url:
            preview_section = f"\n## 本地预览\n\n- 预览地址: {preview_url}\n- 直接在浏览器中打开即可查看效果\n"

        files[f"{docs_prefix}deploy.md"] = f"""# 部署文档 - {title}
{preview_section}
## 部署步骤

1. 构建镜像: `docker build -t app .`
2. 启动服务: `docker-compose up -d`
3. 健康检查: `curl http://localhost:8000/api/health`
"""

        return files
