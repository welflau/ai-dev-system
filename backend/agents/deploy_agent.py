"""
部署代理（DeployAgent）
负责生成部署配置文件：Dockerfile、docker-compose、CI/CD、Nginx 等

LLM 模式：根据项目实际代码生成定制化部署方案
降级模式：基于模板生成通用部署配置
"""
import os
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from models.enums import AgentType

logger = logging.getLogger(__name__)

# LLM 部署配置系统提示词
DEPLOY_SYSTEM_PROMPT = """你是一位资深 DevOps 工程师。
你的职责是根据项目代码和架构，生成完整的部署配置文件。

生成要求：
1. Dockerfile（多阶段构建，生产级优化）
2. docker-compose.yml（完整的服务编排）
3. .dockerignore
4. CI/CD 配置（GitHub Actions）
5. Nginx 配置（如果有前端）
6. 部署文档（deploy.md）

配置规范：
- 使用 Docker 最佳实践（非 root 用户、健康检查、多阶段构建）
- 环境变量通过 .env 文件管理
- 日志输出到 stdout/stderr
- 支持开发和生产两种模式

你必须返回严格的 JSON 格式（不要包含 markdown 代码块标记），结构如下：
{
  "files": [
    {
      "path": "文件相对路径",
      "content": "完整的文件内容"
    }
  ],
  "summary": "一句话描述部署方案"
}"""


class DeployAgent:
    """部署代理 - LLM 智能部署 + 模板降级"""

    def __init__(self, work_dir: str = "projects", llm_client=None):
        self.agent_type = AgentType.DEPLOY
        self.work_dir = work_dir
        self.llm_client = llm_client

    def get_capabilities(self) -> List[str]:
        return [
            "Dockerfile 生成",
            "docker-compose 编排",
            "CI/CD 配置生成",
            "Nginx 反向代理配置",
            "部署文档生成",
        ]

    def get_supported_tasks(self) -> List[str]:
        return ["deployment"]

    @property
    def _llm_available(self) -> bool:
        return self.llm_client is not None and self.llm_client.enabled

    def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行部署配置生成任务

        Args:
            task_name: 任务名称
            context: 包含 project_id, requirement, existing_files 等

        Returns:
            包含 success, files_created, output 的结果
        """
        project_id = context.get("project_id", "unknown")
        project_dir = os.path.join(self.work_dir, project_id)

        try:
            # 分析项目结构以决定技术栈
            project_info = self._analyze_project(project_dir, context)

            # 尝试 LLM 模式
            llm_result = self._llm_deploy(task_name, project_dir, project_info, context)
            if llm_result:
                return {
                    "success": True,
                    "agent": self.agent_type.value,
                    "task": task_name,
                    **llm_result,
                }

            # 降级：模板模式
            result = self._template_deploy(project_dir, project_info, context)
            return {
                "success": True,
                "agent": self.agent_type.value,
                "task": task_name,
                **result,
            }
        except Exception as e:
            logger.error(f"DeployAgent 执行异常: {e}")
            return {
                "success": False,
                "agent": self.agent_type.value,
                "task": task_name,
                "error": str(e),
            }

    def _analyze_project(
        self, project_dir: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """分析项目结构，推断技术栈和部署需求"""
        info = {
            "has_python": False,
            "has_frontend": False,
            "has_requirements": False,
            "has_package_json": False,
            "has_database": False,
            "python_files": [],
            "frontend_files": [],
            "main_entry": "main.py",
            "project_name": context.get("project_name", "app"),
            "port": 8000,
        }

        if not os.path.exists(project_dir):
            return info

        for root, dirs, files in os.walk(project_dir):
            dirs[:] = [d for d in dirs if d not in {
                "__pycache__", ".git", "node_modules", ".venv", "venv"
            }]
            for fname in files:
                rel_path = os.path.relpath(
                    os.path.join(root, fname), project_dir
                ).replace("\\", "/")

                if fname.endswith(".py"):
                    info["has_python"] = True
                    info["python_files"].append(rel_path)
                    if fname in ("main.py", "app.py", "server.py"):
                        info["main_entry"] = rel_path
                elif fname in ("requirements.txt", "pyproject.toml"):
                    info["has_requirements"] = True
                elif fname == "package.json":
                    info["has_package_json"] = True
                elif fname.endswith((".html", ".css", ".js")):
                    info["has_frontend"] = True
                    info["frontend_files"].append(rel_path)

                # 检测数据库使用
                if fname.endswith(".py"):
                    try:
                        full_path = os.path.join(root, fname)
                        with open(full_path, "r", encoding="utf-8") as f:
                            content = f.read(5000)
                        if any(kw in content for kw in ["sqlite", "SQLAlchemy", "database", "psycopg"]):
                            info["has_database"] = True
                    except (UnicodeDecodeError, PermissionError):
                        pass

        return info

    def _llm_deploy(
        self,
        task_name: str,
        project_dir: str,
        project_info: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """LLM 模式：智能生成部署配置"""
        if not self._llm_available:
            return None

        requirement = context.get("requirement", "")
        project_name = context.get("project_name", "项目")

        # 构建项目概况
        tech_desc = []
        if project_info["has_python"]:
            tech_desc.append(f"Python 后端 ({len(project_info['python_files'])} 个文件)")
        if project_info["has_frontend"]:
            tech_desc.append(f"前端 ({len(project_info['frontend_files'])} 个文件)")
        if project_info["has_database"]:
            tech_desc.append("数据库")

        prompt = f"""请为以下项目生成完整的部署配置：

项目名称：{project_name}
任务：{task_name}
需求描述：{requirement}
技术栈：{', '.join(tech_desc) if tech_desc else '未知'}
主入口文件：{project_info['main_entry']}
端口：{project_info['port']}

文件列表：
{chr(10).join('- ' + f for f in project_info['python_files'][:20])}
{chr(10).join('- ' + f for f in project_info['frontend_files'][:10])}

请生成 Dockerfile、docker-compose.yml、.dockerignore、GitHub Actions CI/CD 配置和部署文档。"""

        try:
            response = self.llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                system=DEPLOY_SYSTEM_PROMPT,
                temperature=0.3,
                max_tokens=8192,
            )
            if not response or response == "[LLM_UNAVAILABLE]":
                return None
            return self._parse_llm_response(response, project_dir)
        except Exception as e:
            logger.warning(f"DeployAgent LLM 生成失败: {e}")
            return None

    def _parse_llm_response(
        self, response: str, project_dir: str
    ) -> Optional[Dict[str, Any]]:
        """解析 LLM JSON 响应并写入文件"""
        text = response.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"DeployAgent LLM 响应 JSON 解析失败: {text[:200]}")
            return None

        files = data.get("files", [])
        if not files:
            return None

        files_created = []
        for f in files:
            path = f.get("path", "")
            content = f.get("content", "")
            if path and content:
                full_path = os.path.join(project_dir, path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "w", encoding="utf-8") as fp:
                    fp.write(content)
                files_created.append(full_path)

        if not files_created:
            return None

        return {
            "files_created": files_created,
            "output": data.get("summary", f"部署配置生成完成，共 {len(files_created)} 个文件"),
            "mode": "llm",
        }

    def _template_deploy(
        self,
        project_dir: str,
        project_info: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """模板模式：生成通用部署配置"""
        project_name = project_info["project_name"]
        main_entry = project_info["main_entry"]
        port = project_info["port"]
        files_created = []

        os.makedirs(project_dir, exist_ok=True)

        # ========== 1. Dockerfile ==========
        dockerfile_content = f"""# ============================================
# {project_name} - Dockerfile
# 多阶段构建 · 生产级优化
# ============================================

# --- Stage 1: Builder ---
FROM python:3.11-slim AS builder

WORKDIR /build

# 安装依赖（利用 Docker 缓存层）
COPY requirements.txt ./
RUN pip install --no-cache-dir --target=/install -r requirements.txt

# --- Stage 2: Runtime ---
FROM python:3.11-slim

# 安全：创建非 root 用户
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

# 复制安装好的依赖
COPY --from=builder /install /usr/local/lib/python3.11/site-packages/

# 复制项目代码
COPY . .

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \\
    PYTHONDONTWRITEBYTECODE=1 \\
    PORT={port}

# 切换到非 root 用户
RUN chown -R appuser:appuser /app
USER appuser

# 暴露端口
EXPOSE {port}

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \\
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:{port}/health')" || exit 1

# 启动命令
CMD ["python", "{main_entry}"]
"""
        dockerfile_path = os.path.join(project_dir, "Dockerfile")
        with open(dockerfile_path, "w", encoding="utf-8") as f:
            f.write(dockerfile_content)
        files_created.append(dockerfile_path)

        # ========== 2. docker-compose.yml ==========
        compose_services = f"""  app:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: {project_name.lower().replace(' ', '-')}-app
    ports:
      - "{port}:{port}"
    environment:
      - PORT={port}
      - DEBUG=False
    env_file:
      - .env
    restart: unless-stopped
    networks:
      - app-network"""

        if project_info["has_database"]:
            compose_services += f"""

  db:
    image: postgres:15-alpine
    container_name: {project_name.lower().replace(' ', '-')}-db
    environment:
      POSTGRES_DB: ${{DB_NAME:-app_db}}
      POSTGRES_USER: ${{DB_USER:-app_user}}
      POSTGRES_PASSWORD: ${{DB_PASSWORD:-changeme}}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    restart: unless-stopped
    networks:
      - app-network
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${{DB_USER:-app_user}}"]
      interval: 10s
      timeout: 5s
      retries: 5"""

        if project_info["has_frontend"]:
            compose_services += f"""

  nginx:
    image: nginx:alpine
    container_name: {project_name.lower().replace(' ', '-')}-nginx
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on:
      - app
    restart: unless-stopped
    networks:
      - app-network"""

        volumes_section = ""
        if project_info["has_database"]:
            volumes_section = "\nvolumes:\n  postgres_data:\n"

        compose_content = f"""# {project_name} - Docker Compose 配置
# 启动命令：docker compose up -d

version: "3.9"

services:
{compose_services}

networks:
  app-network:
    driver: bridge
{volumes_section}"""

        compose_path = os.path.join(project_dir, "docker-compose.yml")
        with open(compose_path, "w", encoding="utf-8") as f:
            f.write(compose_content)
        files_created.append(compose_path)

        # ========== 3. .dockerignore ==========
        dockerignore_content = """# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/
.venv/
*.egg-info/
dist/
build/

# IDE
.idea/
.vscode/
*.swp
*.swo

# Git
.git/
.gitignore

# Docker
Dockerfile
docker-compose.yml
.dockerignore

# Env
.env
.env.local
.env.*.local

# Tests
tests/
*.test.*
pytest.ini
.pytest_cache/
.coverage
htmlcov/

# Docs
docs/
*.md
LICENSE

# OS
.DS_Store
Thumbs.db
"""
        dockerignore_path = os.path.join(project_dir, ".dockerignore")
        with open(dockerignore_path, "w", encoding="utf-8") as f:
            f.write(dockerignore_content)
        files_created.append(dockerignore_path)

        # ========== 4. GitHub Actions CI/CD ==========
        ci_dir = os.path.join(project_dir, ".github", "workflows")
        os.makedirs(ci_dir, exist_ok=True)

        ci_content = f"""# {project_name} - CI/CD Pipeline
name: CI/CD

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11"]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{{{ matrix.python-version }}}}
        uses: actions/setup-python@v5
        with:
          python-version: ${{{{ matrix.python-version }}}}

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pytest flake8

      - name: Lint with flake8
        run: flake8 . --count --max-line-length=120 --statistics --exclude=venv,.venv,__pycache__

      - name: Run tests
        run: pytest tests/ -v --tb=short

  build:
    needs: test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'

    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Build Docker image
        run: |
          docker build -t {project_name.lower().replace(' ', '-')}:${{{{ github.sha }}}} .
          docker build -t {project_name.lower().replace(' ', '-')}:latest .

      - name: Test Docker image
        run: |
          docker run -d --name test-app -p {port}:{port} {project_name.lower().replace(' ', '-')}:latest
          sleep 5
          curl -f http://localhost:{port}/health || exit 1
          docker stop test-app
"""
        ci_path = os.path.join(ci_dir, "ci.yml")
        with open(ci_path, "w", encoding="utf-8") as f:
            f.write(ci_content)
        files_created.append(ci_path)

        # ========== 5. Nginx 配置（如果有前端） ==========
        if project_info["has_frontend"]:
            nginx_content = f"""# {project_name} - Nginx 反向代理配置

upstream backend {{
    server app:{port};
}}

server {{
    listen 80;
    server_name localhost;

    # 前端静态文件
    location /static/ {{
        alias /usr/share/nginx/html/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }}

    # API 反向代理
    location /api/ {{
        proxy_pass http://backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE 支持
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400s;
    }}

    # SSE 事件流
    location /api/projects/ {{
        proxy_pass http://backend;
        proxy_set_header Host $host;
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        proxy_buffering off;
        chunked_transfer_encoding off;
        proxy_cache off;
        proxy_read_timeout 86400s;
    }}

    # 默认代理到后端
    location / {{
        proxy_pass http://backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }}

    # 健康检查
    location /nginx-health {{
        access_log off;
        return 200 "OK";
    }}
}}
"""
            nginx_path = os.path.join(project_dir, "nginx.conf")
            with open(nginx_path, "w", encoding="utf-8") as f:
                f.write(nginx_content)
            files_created.append(nginx_path)

        # ========== 6. 部署文档 ==========
        deploy_doc = self._generate_deploy_doc(
            project_name, project_info, port, files_created
        )
        docs_dir = os.path.join(project_dir, "docs")
        os.makedirs(docs_dir, exist_ok=True)
        doc_path = os.path.join(docs_dir, "deploy.md")
        with open(doc_path, "w", encoding="utf-8") as f:
            f.write(deploy_doc)
        files_created.append(doc_path)

        return {
            "files_created": files_created,
            "output": f"部署配置生成完成：{len(files_created)} 个文件"
                      f"（Dockerfile + docker-compose + CI/CD"
                      f"{' + Nginx' if project_info['has_frontend'] else ''}）",
            "mode": "template",
        }

    def _generate_deploy_doc(
        self,
        project_name: str,
        project_info: Dict[str, Any],
        port: int,
        files: List[str],
    ) -> str:
        """生成部署文档"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        slug = project_name.lower().replace(" ", "-")

        doc = f"""# {project_name} - 部署指南

> 由 AI 自动开发系统自动生成 | {now}

## 📦 部署文件清单

| 文件 | 说明 |
|------|------|
| `Dockerfile` | Docker 多阶段构建配置 |
| `docker-compose.yml` | 服务编排配置 |
| `.dockerignore` | Docker 构建忽略文件 |
| `.github/workflows/ci.yml` | GitHub Actions CI/CD |"""

        if project_info["has_frontend"]:
            doc += "\n| `nginx.conf` | Nginx 反向代理配置 |"

        doc += f"""
| `docs/deploy.md` | 本文档 |

---

## 🚀 快速部署

### 1. 本地 Docker 部署

```bash
# 克隆项目
git clone <仓库地址>
cd {slug}

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入实际配置

# 构建并启动
docker compose up -d

# 检查服务状态
docker compose ps

# 查看日志
docker compose logs -f app
```

### 2. 访问服务

| 服务 | 地址 |
|------|------|
| API | http://localhost:{port} |
| 健康检查 | http://localhost:{port}/health |"""

        if project_info["has_frontend"]:
            doc += "\n| 前端 (Nginx) | http://localhost |"
        if project_info["has_database"]:
            doc += "\n| 数据库 (PostgreSQL) | localhost:5432 |"

        doc += f"""

### 3. 常用命令

```bash
# 停止服务
docker compose down

# 重新构建
docker compose up -d --build

# 查看实时日志
docker compose logs -f

# 进入容器
docker compose exec app /bin/bash

# 清理（包括数据卷）
docker compose down -v
```

---

## 🔧 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `PORT` | 服务端口 | {port} |
| `DEBUG` | 调试模式 | False |"""

        if project_info["has_database"]:
            doc += """
| `DB_NAME` | 数据库名 | app_db |
| `DB_USER` | 数据库用户 | app_user |
| `DB_PASSWORD` | 数据库密码 | (必填) |"""

        doc += """

---

## 📋 CI/CD 流程

GitHub Actions 自动化流程：

1. **Test** (每次 push/PR)
   - Python 3.10 + 3.11 矩阵测试
   - flake8 代码检查
   - pytest 单元测试

2. **Build** (仅 main 分支)
   - Docker 镜像构建
   - 健康检查验证

---

## ⚠️ 生产环境注意事项

1. **修改默认密码**：所有默认密码必须在生产环境中修改
2. **HTTPS**：生产环境务必配置 SSL/TLS 证书
3. **日志**：建议接入日志收集系统（ELK / Loki 等）
4. **监控**：建议接入 Prometheus + Grafana 监控
5. **备份**：定期备份数据库数据
"""
        return doc
