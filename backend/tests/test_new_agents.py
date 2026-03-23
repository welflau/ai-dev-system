"""
v0.6.0 新增 Agent 单元测试
覆盖：TestAgent, ReviewAgent, DeployAgent, ProductAgentAdapter
"""
import os
import sys
import shutil
import tempfile
import pytest

# 确保能导入项目模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import TestAgent, ReviewAgent, DeployAgent
from orchestrator.coordinator import ProductAgentAdapter


# ============ TestAgent 测试 ============


class TestTestAgent:
    """TestAgent 单元测试"""

    def setup_method(self):
        self.work_dir = tempfile.mkdtemp()
        self.agent = TestAgent(work_dir=self.work_dir)

    def teardown_method(self):
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def test_init(self):
        """测试 TestAgent 初始化"""
        assert self.agent.agent_type.value == "test"
        assert self.agent.work_dir == self.work_dir
        assert self.agent.llm_client is None

    def test_llm_not_available_by_default(self):
        """默认无 LLM 客户端"""
        assert not self.agent._llm_available

    def test_generate_tests_template_mode(self):
        """模板模式生成测试代码"""
        # 先创建一些假的项目代码文件供 TestAgent 读取
        project_id = "test-project-001"
        project_dir = os.path.join(self.work_dir, project_id, "src")
        os.makedirs(project_dir, exist_ok=True)
        with open(os.path.join(project_dir, "app.py"), "w") as f:
            f.write("from fastapi import FastAPI\napp = FastAPI()\n")

        result = self.agent.execute("编写测试用例", {
            "project_id": project_id,
            "requirement": "用户管理系统",
            "project_name": "用户管理系统",
        })
        assert result["success"] is True
        assert result["agent"] == "test"
        assert len(result.get("files_created", [])) > 0
        assert result.get("mode") == "template"

    def test_generate_tests_no_code_files(self):
        """没有代码文件时也能成功"""
        result = self.agent.execute("编写测试用例", {
            "project_id": "empty-project",
            "requirement": "空项目",
            "project_name": "空项目",
        })
        assert result["success"] is True


# ============ ReviewAgent 测试 ============


class TestReviewAgent:
    """ReviewAgent 单元测试"""

    def setup_method(self):
        self.work_dir = tempfile.mkdtemp()
        self.agent = ReviewAgent(work_dir=self.work_dir)

    def teardown_method(self):
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def test_init(self):
        """测试 ReviewAgent 初始化"""
        assert self.agent.agent_type.value == "review"
        assert "代码规范检查" in self.agent.get_capabilities()
        assert "review" in self.agent.get_supported_tasks()

    def test_llm_not_available_by_default(self):
        """默认无 LLM 客户端"""
        assert not self.agent._llm_available

    def test_review_empty_project(self):
        """审查空项目"""
        result = self.agent.execute("代码审查", {
            "project_id": "empty-project",
            "requirement": "空项目",
            "project_name": "空项目",
        })
        assert result["success"] is True
        assert result["score"] == "N/A"
        assert len(result.get("files_created", [])) > 0

    def test_review_python_code(self):
        """审查 Python 代码"""
        project_id = "review-test-001"
        project_dir = os.path.join(self.work_dir, project_id)
        os.makedirs(project_dir, exist_ok=True)

        # 写入有一些问题的 Python 代码
        code = '''
import os
from sys import *

password = "hardcoded123"

def very_long_function():
''' + '    pass\n' * 55 + '''

def another_func():
    try:
        x = 1 / 0
    except:
        pass  # TODO: handle error

f = open("test.txt", "r")
content = f.read()
'''
        with open(os.path.join(project_dir, "main.py"), "w") as f:
            f.write(code)

        result = self.agent.execute("代码审查", {
            "project_id": project_id,
            "requirement": "测试项目",
            "project_name": "测试项目",
        })
        assert result["success"] is True
        assert result.get("mode") == "template"
        assert result.get("score") in ("A", "A-", "B+", "B", "C", "D", "F")

        # 应该发现一些问题
        issues = result.get("issues", {})
        total = issues.get("critical", 0) + issues.get("warning", 0) + issues.get("suggestion", 0)
        assert total > 0, "应该发现代码问题"

        # 检查生成了报告文件
        files = result.get("files_created", [])
        assert len(files) > 0
        report_path = files[0]
        assert os.path.exists(report_path)
        with open(report_path, "r", encoding="utf-8") as f:
            report_content = f.read()
        assert "代码审查报告" in report_content

    def test_review_detects_bare_except(self):
        """检测裸 except"""
        project_id = "review-bare-except"
        project_dir = os.path.join(self.work_dir, project_id)
        os.makedirs(project_dir, exist_ok=True)

        code = '''"""test module"""
try:
    x = 1
except:
    pass
'''
        with open(os.path.join(project_dir, "test.py"), "w") as f:
            f.write(code)

        result = self.agent.execute("代码审查", {
            "project_id": project_id,
            "requirement": "测试",
            "project_name": "测试",
        })
        assert result["success"] is True
        assert result["issues"]["warning"] > 0, "应检测到裸 except"

    def test_review_detects_import_star(self):
        """检测 import *"""
        project_id = "review-import-star"
        project_dir = os.path.join(self.work_dir, project_id)
        os.makedirs(project_dir, exist_ok=True)

        code = '''"""test module"""
from os import *
'''
        with open(os.path.join(project_dir, "test.py"), "w") as f:
            f.write(code)

        result = self.agent.execute("代码审查", {
            "project_id": project_id,
            "requirement": "测试",
            "project_name": "测试",
        })
        assert result["success"] is True
        assert result["issues"]["warning"] > 0, "应检测到 import *"

    def test_collect_code_files(self):
        """测试代码文件收集"""
        project_id = "collect-test"
        project_dir = os.path.join(self.work_dir, project_id)
        os.makedirs(os.path.join(project_dir, "src"), exist_ok=True)
        os.makedirs(os.path.join(project_dir, "__pycache__"), exist_ok=True)

        with open(os.path.join(project_dir, "src", "main.py"), "w") as f:
            f.write("print('hello')")
        with open(os.path.join(project_dir, "__pycache__", "main.cpython-311.pyc"), "w") as f:
            f.write("bytecode")
        with open(os.path.join(project_dir, "readme.txt"), "w") as f:
            f.write("readme")

        files = self.agent._collect_code_files(project_dir)
        paths = [f["path"] for f in files]
        assert "src/main.py" in paths
        # __pycache__ 应被跳过
        assert not any("__pycache__" in p for p in paths)


# ============ DeployAgent 测试 ============


class TestDeployAgent:
    """DeployAgent 单元测试"""

    def setup_method(self):
        self.work_dir = tempfile.mkdtemp()
        self.agent = DeployAgent(work_dir=self.work_dir)

    def teardown_method(self):
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def test_init(self):
        """测试 DeployAgent 初始化"""
        assert self.agent.agent_type.value == "deploy"
        assert "Dockerfile 生成" in self.agent.get_capabilities()
        assert "deployment" in self.agent.get_supported_tasks()

    def test_llm_not_available_by_default(self):
        """默认无 LLM 客户端"""
        assert not self.agent._llm_available

    def test_deploy_empty_project(self):
        """对空项目生成部署配置"""
        result = self.agent.execute("部署配置生成", {
            "project_id": "deploy-test-empty",
            "requirement": "简单 API",
            "project_name": "TestApp",
        })
        assert result["success"] is True
        assert result["agent"] == "deploy"
        assert len(result.get("files_created", [])) >= 4  # Dockerfile + compose + dockerignore + CI + doc
        assert result.get("mode") == "template"

    def test_deploy_python_project(self):
        """对 Python 项目生成部署配置"""
        project_id = "deploy-python-001"
        project_dir = os.path.join(self.work_dir, project_id)
        os.makedirs(project_dir, exist_ok=True)

        # 模拟一个 Python 后端项目
        with open(os.path.join(project_dir, "main.py"), "w") as f:
            f.write("from fastapi import FastAPI\napp = FastAPI()\n")
        with open(os.path.join(project_dir, "requirements.txt"), "w") as f:
            f.write("fastapi\nuvicorn\n")

        result = self.agent.execute("部署配置生成", {
            "project_id": project_id,
            "requirement": "FastAPI 后端",
            "project_name": "MyAPI",
        })
        assert result["success"] is True
        files = result.get("files_created", [])
        file_names = [os.path.basename(f) for f in files]
        assert "Dockerfile" in file_names
        assert "docker-compose.yml" in file_names
        assert ".dockerignore" in file_names
        assert "ci.yml" in file_names
        assert "deploy.md" in file_names

        # 验证 Dockerfile 内容
        dockerfile = [f for f in files if f.endswith("Dockerfile")][0]
        with open(dockerfile, "r", encoding="utf-8") as f:
            content = f.read()
        assert "FROM python" in content
        assert "HEALTHCHECK" in content
        assert "main.py" in content

    def test_deploy_with_frontend(self):
        """有前端的项目应生成 Nginx 配置"""
        project_id = "deploy-frontend-001"
        project_dir = os.path.join(self.work_dir, project_id)
        os.makedirs(project_dir, exist_ok=True)

        with open(os.path.join(project_dir, "main.py"), "w") as f:
            f.write("from fastapi import FastAPI\napp = FastAPI()\n")
        with open(os.path.join(project_dir, "index.html"), "w") as f:
            f.write("<html></html>")

        result = self.agent.execute("部署配置生成", {
            "project_id": project_id,
            "requirement": "全栈应用",
            "project_name": "FullStack",
        })
        assert result["success"] is True
        files = result.get("files_created", [])
        file_names = [os.path.basename(f) for f in files]
        assert "nginx.conf" in file_names, "有前端应生成 Nginx 配置"

    def test_deploy_with_database(self):
        """使用数据库的项目应在 compose 中包含 db 服务"""
        project_id = "deploy-db-001"
        project_dir = os.path.join(self.work_dir, project_id)
        os.makedirs(project_dir, exist_ok=True)

        with open(os.path.join(project_dir, "app.py"), "w") as f:
            f.write("import sqlite3\nfrom SQLAlchemy import create_engine\n")

        result = self.agent.execute("部署配置生成", {
            "project_id": project_id,
            "requirement": "带数据库的应用",
            "project_name": "DBApp",
        })
        assert result["success"] is True
        compose_file = [f for f in result["files_created"] if "docker-compose" in os.path.basename(f)]
        assert len(compose_file) > 0
        with open(compose_file[0], "r", encoding="utf-8") as f:
            content = f.read()
        assert "postgres" in content.lower(), "应包含数据库服务"

    def test_analyze_project(self):
        """测试项目结构分析"""
        project_id = "analyze-test"
        project_dir = os.path.join(self.work_dir, project_id)
        os.makedirs(project_dir, exist_ok=True)

        with open(os.path.join(project_dir, "main.py"), "w") as f:
            f.write("print('hello')")
        with open(os.path.join(project_dir, "requirements.txt"), "w") as f:
            f.write("fastapi")

        info = self.agent._analyze_project(project_dir, {"project_name": "test"})
        assert info["has_python"] is True
        assert info["has_requirements"] is True
        assert "main.py" in info["python_files"]


# ============ ProductAgentAdapter 测试 ============


class TestProductAgentAdapter:
    """ProductAgentAdapter 单元测试"""

    def setup_method(self):
        self.work_dir = tempfile.mkdtemp()
        self.agent = ProductAgentAdapter(work_dir=self.work_dir)

    def teardown_method(self):
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def test_init(self):
        """测试初始化"""
        assert self.agent.agent_type.value == "product"

    def test_llm_not_available_by_default(self):
        """默认无 LLM 客户端"""
        assert not self.agent._llm_available

    def test_template_analyze_basic(self):
        """模板模式基础需求分析"""
        result = self.agent.execute("需求分析", {
            "project_id": "product-test-001",
            "requirement": "开发一个用户登录注册系统，支持 API 接口",
            "project_name": "用户系统",
        })
        assert result["success"] is True
        assert result["agent"] == "product"
        assert len(result.get("files_created", [])) > 0
        assert result.get("mode") == "template"

        # 检查 PRD 文件
        prd_file = result["files_created"][0]
        assert os.path.exists(prd_file)
        with open(prd_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert "用户系统" in content
        assert "PRD" in content

    def test_template_analyze_keywords(self):
        """模板模式关键词提取"""
        result = self.agent.execute("需求分析", {
            "project_id": "product-test-002",
            "requirement": "开发商品管理系统，支持订单、支付、搜索功能",
            "project_name": "商品管理系统",
        })
        assert result["success"] is True
        features = result.get("features", [])
        # 应该包含商品、订单、支付、搜索相关的功能
        assert len(features) >= 3, f"应识别出至少 3 个功能模块，实际: {features}"

    def test_template_analyze_fallback_features(self):
        """没有匹配关键词时使用默认功能"""
        result = self.agent.execute("需求分析", {
            "project_id": "product-test-003",
            "requirement": "做一个很酷的东西",
            "project_name": "酷东西",
        })
        assert result["success"] is True
        features = result.get("features", [])
        assert len(features) > 0, "应有默认功能列表"

    def test_execute_creates_docs_dir(self):
        """执行后应创建 docs 目录"""
        project_id = "product-test-004"
        result = self.agent.execute("需求分析", {
            "project_id": project_id,
            "requirement": "测试",
            "project_name": "测试",
        })
        assert result["success"] is True
        docs_dir = os.path.join(self.work_dir, project_id, "docs")
        assert os.path.exists(docs_dir)
