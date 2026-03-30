"""
DeployAgent — 部署 Agent
职责：按环境（dev/test/prod）启动隔离预览服务 + 生成部署配置
"""
import json
import asyncio
import subprocess
import shutil
from pathlib import Path
from typing import Any, Dict, Optional
from agents.base import BaseAgent
from llm_client import llm_client
import logging

logger = logging.getLogger("deploy_agent")

# 环境配置
ENV_CONFIG = {
    "dev":  {"port_offset": 0,   "label": "开发环境", "branch_pattern": "feat/"},
    "test": {"port_offset": 100, "label": "测试环境", "branch": "develop"},
    "prod": {"port_offset": 200, "label": "生产环境", "branch": "main"},
}


class DeployAgent(BaseAgent):

    @property
    def agent_type(self) -> str:
        return "DeployAgent"

    # 已启动的预览服务 {(project_id, env_type): {"port", "process", "deploy_path"}}
    _preview_servers: Dict[tuple, Dict] = {}

    # 兼容旧 API：通过 project_id 获取 preview（取 dev 环境）
    @classmethod
    def get_preview(cls, project_id: str) -> Optional[Dict]:
        """获取项目的预览信息（优先 dev → test → prod）"""
        for env in ("dev", "test", "prod"):
            key = (project_id, env)
            if key in cls._preview_servers:
                return {**cls._preview_servers[key], "env": env}
        return None

    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if task_name == "deploy":
            return await self.deploy(context)
        else:
            return {"status": "error", "message": f"未知任务: {task_name}"}

    async def deploy(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """部署：启动本地预览服务 + 生成部署配置"""
        ticket_title = context.get("ticket_title", "")
        docs_prefix = context.get("docs_prefix", "docs/")
        project_id = context.get("project_id", "")

        preview_url = None
        if project_id:
            preview_url = await self.deploy_env(project_id, "dev")

        files = self._generate_deploy_files(ticket_title, docs_prefix, preview_url)

        return {
            "status": "success",
            "deploy_result": {
                "preview_url": preview_url,
                "environment": "dev",
            },
            "files": files,
        }

    @classmethod
    async def deploy_env(cls, project_id: str, env_type: str, branch: str = None) -> Optional[str]:
        """按环境部署预览服务

        Args:
            project_id: 项目 ID
            env_type: 'dev' | 'test' | 'prod'
            branch: 指定分支（可选，默认按环境规则）
        Returns:
            预览 URL 或 None
        """
        from git_manager import git_manager
        from database import db
        from utils import generate_id, now_iso

        if env_type not in ENV_CONFIG:
            logger.error("未知环境类型: %s", env_type)
            return None

        config = ENV_CONFIG[env_type]
        repo_path = str(git_manager._repo_path(project_id))
        base_port = 9000 + (abs(hash(project_id)) % 100)
        port = base_port + config["port_offset"]

        # 确定部署目录
        if env_type == "dev":
            deploy_path = repo_path  # dev 直接用仓库目录
        else:
            deploy_path = f"{repo_path}_{env_type}"

        # 确定分支
        if not branch:
            if env_type == "dev":
                branch = await git_manager.get_current_branch(project_id)
            else:
                branch = config.get("branch", "main")

        try:
            # 对 test/prod 环境：从仓库 checkout 到隔离目录
            if env_type != "dev":
                deploy_dir = Path(deploy_path)
                deploy_dir.mkdir(parents=True, exist_ok=True)

                # 如果隔离目录没有 .git，用 git worktree 或 copy
                git_dir = deploy_dir / ".git"
                if not git_dir.exists():
                    # 使用 git clone --branch 从本地仓库 clone
                    rc, _, err = await git_manager._run_git(
                        str(deploy_dir.parent),
                        "clone", "--branch", branch, "--single-branch",
                        repo_path, str(deploy_dir),
                    )
                    if rc != 0:
                        # clone 失败则直接复制文件
                        logger.warning("git clone 到 %s 失败: %s, 使用文件复制", env_type, err)
                        if deploy_dir.exists():
                            shutil.rmtree(deploy_dir, ignore_errors=True)
                        shutil.copytree(repo_path, str(deploy_dir),
                                       ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc'))
                else:
                    # 已有 .git，fetch + checkout
                    await git_manager._run_git(str(deploy_dir), "fetch", "origin")
                    await git_manager._run_git(str(deploy_dir), "clean", "-fd")
                    await git_manager._run_git(str(deploy_dir), "checkout", branch)
                    await git_manager._run_git(str(deploy_dir), "pull", "origin", branch)

            # 停掉旧的预览服务
            key = (project_id, env_type)
            if key in cls._preview_servers:
                old = cls._preview_servers[key]
                try:
                    old["process"].terminate()
                    await asyncio.sleep(0.5)
                except Exception:
                    pass
                del cls._preview_servers[key]

            # 启动 HTTP 预览服务
            proc = subprocess.Popen(
                ["python", "-m", "http.server", str(port)],
                cwd=deploy_path,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            await asyncio.sleep(1)

            if proc.poll() is not None:
                logger.warning("[%s] 预览服务启动失败: 端口 %d 可能被占用", env_type, port)
                return None

            url = f"http://localhost:{port}"
            cls._preview_servers[key] = {
                "port": port,
                "process": proc,
                "deploy_path": deploy_path,
            }

            # 获取当前 commit
            rc, commit_hash, _ = await git_manager._run_git(
                deploy_path if env_type != "dev" else repo_path,
                "rev-parse", "--short", "HEAD",
            )

            # 更新数据库环境记录
            existing = await db.fetch_one(
                "SELECT id FROM project_environments WHERE project_id = ? AND env_type = ?",
                (project_id, env_type),
            )
            env_data = {
                "branch": branch,
                "deploy_path": deploy_path,
                "port": port,
                "status": "running",
                "url": url,
                "last_commit": commit_hash if rc == 0 else None,
                "last_deployed_at": now_iso(),
            }
            if existing:
                await db.update("project_environments", env_data,
                                "id = ?", (existing["id"],))
            else:
                env_data.update({
                    "id": generate_id("ENV"),
                    "project_id": project_id,
                    "env_type": env_type,
                    "created_at": now_iso(),
                })
                await db.insert("project_environments", env_data)

            logger.info("🌐 [%s] %s 已部署: %s (port=%d, branch=%s, commit=%s)",
                        env_type, config["label"], url, port, branch,
                        commit_hash if rc == 0 else "?")
            return url

        except Exception as e:
            logger.error("[%s] 部署失败: %s", env_type, e, exc_info=True)
            return None

    @classmethod
    async def stop_env(cls, project_id: str, env_type: str):
        """停止环境预览服务"""
        from database import db
        from utils import now_iso

        key = (project_id, env_type)
        if key in cls._preview_servers:
            try:
                cls._preview_servers[key]["process"].terminate()
            except Exception:
                pass
            del cls._preview_servers[key]

        await db.execute(
            "UPDATE project_environments SET status = 'inactive' WHERE project_id = ? AND env_type = ?",
            (project_id, env_type),
        )
        logger.info("🛑 [%s] 环境已停止: project=%s", env_type, project_id[:12])

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
            preview_section = f"\n## 本地预览\n\n- 预览地址: {preview_url}\n"

        files[f"{docs_prefix}deploy.md"] = f"""# 部署文档 - {title}
{preview_section}
## 部署步骤

1. 构建镜像: `docker build -t app .`
2. 启动服务: `docker-compose up -d`
3. 健康检查: `curl http://localhost:8000/api/health`
"""

        return files
