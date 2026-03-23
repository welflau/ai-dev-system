"""
Agent 单元测试 + 集成测试
"""
import os
import sys
import shutil
import tempfile
import pytest

# 确保能导入项目模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import DevAgent, ArchitectAgent
from orchestrator import Orchestrator


# ============ DevAgent 测试 ============


class TestDevAgent:
    """DevAgent 单元测试"""

    def setup_method(self):
        self.work_dir = tempfile.mkdtemp()
        self.agent = DevAgent(work_dir=self.work_dir)

    def teardown_method(self):
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def test_init(self):
        """测试 DevAgent 初始化"""
        assert self.agent.agent_type.value == "dev"
        assert len(self.agent.get_capabilities()) > 0
        assert "development" in self.agent.get_supported_tasks()

    def test_project_init(self):
        """测试项目初始化"""
        result = self.agent.execute("项目初始化和环境搭建", {
            "project_id": "test-001",
            "requirement": "开发一个用户管理系统",
            "project_name": "user-system",
        })
        assert result["success"] is True
        assert len(result["files_created"]) > 0
        # 检查文件确实被创建
        assert os.path.exists(os.path.join(
            self.work_dir, "test-001", "src", "main.py"
        ))
        assert os.path.exists(os.path.join(
            self.work_dir, "test-001", "requirements.txt"
        ))

    def test_api_code_generation(self):
        """测试 API 代码生成"""
        result = self.agent.execute("实现API端点", {
            "project_id": "test-002",
            "requirement": "用户管理 API，支持登录注册",
        })
        assert result["success"] is True
        assert len(result["files_created"]) > 0

    def test_auth_code_generation(self):
        """测试认证模块生成"""
        result = self.agent.execute("实现用户认证", {
            "project_id": "test-003",
            "requirement": "用户登录注册",
        })
        assert result["success"] is True
        assert os.path.exists(os.path.join(
            self.work_dir, "test-003", "src", "services", "auth.py"
        ))

    def test_login_code_generation(self):
        """测试登录功能代码生成"""
        result = self.agent.execute("实现登录功能", {
            "project_id": "test-004",
            "requirement": "用户登录",
        })
        assert result["success"] is True

    def test_model_code_generation(self):
        """测试数据模型生成"""
        result = self.agent.execute("实现数据模型", {
            "project_id": "test-005",
            "requirement": "用户数据库管理",
        })
        assert result["success"] is True
        assert os.path.exists(os.path.join(
            self.work_dir, "test-005", "src", "models", "database.py"
        ))

    def test_frontend_generation(self):
        """测试前端页面生成"""
        result = self.agent.execute("实现前端页面", {
            "project_id": "test-006",
            "requirement": "前端界面",
            "project_name": "我的应用",
        })
        assert result["success"] is True
        assert os.path.exists(os.path.join(
            self.work_dir, "test-006", "frontend", "index.html"
        ))

    def test_helper_code_generation(self):
        """测试辅助功能代码生成"""
        result = self.agent.execute("辅助功能开发", {
            "project_id": "test-007",
            "requirement": "工具函数",
        })
        assert result["success"] is True

    def test_docs_generation(self):
        """测试文档生成"""
        result = self.agent.execute("编写项目文档", {
            "project_id": "test-008",
            "requirement": "项目文档",
            "project_name": "test-project",
        })
        assert result["success"] is True

    def test_unknown_task_fallback(self):
        """测试未知任务的兜底处理"""
        result = self.agent.execute("执行一个不存在的任务", {
            "project_id": "test-009",
            "requirement": "测试",
        })
        assert result["success"] is True  # 兜底生成通用代码


# ============ ArchitectAgent 测试 ============


class TestArchitectAgent:
    """ArchitectAgent 单元测试"""

    def setup_method(self):
        self.work_dir = tempfile.mkdtemp()
        self.agent = ArchitectAgent(work_dir=self.work_dir)

    def teardown_method(self):
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def test_init(self):
        """测试 ArchitectAgent 初始化"""
        assert self.agent.agent_type.value == "architect"
        assert len(self.agent.get_capabilities()) > 0
        assert "design" in self.agent.get_supported_tasks()

    def test_architecture_design(self):
        """测试系统架构设计"""
        result = self.agent.execute("技术架构设计", {
            "project_id": "arch-001",
            "requirement": "开发一个用户管理API系统，包含登录注册和数据库",
            "project_name": "user-api",
        })
        assert result["success"] is True
        assert os.path.exists(os.path.join(
            self.work_dir, "arch-001", "docs", "architecture.md"
        ))
        assert len(result.get("features", [])) > 0

    def test_database_design(self):
        """测试数据库设计"""
        result = self.agent.execute("设计数据库结构", {
            "project_id": "arch-002",
            "requirement": "用户数据库管理，包含用户表",
        })
        assert result["success"] is True
        assert os.path.exists(os.path.join(
            self.work_dir, "arch-002", "docs", "database_design.md"
        ))

    def test_api_design(self):
        """测试 API 接口设计"""
        result = self.agent.execute("设计API接口", {
            "project_id": "arch-003",
            "requirement": "用户管理 API 接口",
        })
        assert result["success"] is True

    def test_ui_design(self):
        """测试 UI 设计"""
        result = self.agent.execute("设计UI界面", {
            "project_id": "arch-004",
            "requirement": "前端界面设计",
            "project_name": "test-app",
        })
        assert result["success"] is True

    def test_user_system_design(self):
        """测试用户系统设计"""
        result = self.agent.execute("设计用户系统", {
            "project_id": "arch-005",
            "requirement": "用户认证系统",
        })
        assert result["success"] is True

    def test_unknown_task_fallback(self):
        """测试未知任务的兜底处理"""
        result = self.agent.execute("一个不存在的设计任务", {
            "project_id": "arch-006",
            "requirement": "测试",
        })
        assert result["success"] is True


# ============ 集成测试: Orchestrator + Agent ============


class TestOrchestratorWithAgents:
    """Orchestrator 集成 Agent 测试"""

    def setup_method(self):
        self.work_dir = tempfile.mkdtemp()
        self.orchestrator = Orchestrator(work_dir=self.work_dir)

    def teardown_method(self):
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def test_full_workflow(self):
        """测试完整工作流：提交需求 → 执行任务 → 生成文件"""
        # 1. 提交需求
        result = self.orchestrator.process_request(
            description="开发一个用户管理API系统，包含登录注册和数据库",
            preferences={"project_name": "user-api"},
        )
        project_id = result["project_id"]
        assert result["task_count"] > 0

        # 2. 逐个执行任务
        executed_count = 0
        max_iterations = 30  # 防止无限循环
        for _ in range(max_iterations):
            exec_result = self.orchestrator.execute_next_task(project_id)
            if not exec_result.get("task"):
                break  # 所有任务完成
            executed_count += 1

        # 3. 验证结果
        assert executed_count > 0

        state = self.orchestrator.get_project_state(project_id)
        summary = state["task_summary"]
        assert summary["completed"] == summary["total"]
        assert summary["pending"] == 0

        # 4. 验证文件被生成
        project_dir = os.path.join(self.work_dir, project_id)
        assert os.path.exists(project_dir)

    def test_execute_next_task(self):
        """测试 execute_next_task 方法"""
        result = self.orchestrator.process_request(
            description="做一个简单系统",
        )
        project_id = result["project_id"]

        # 执行第一个任务
        exec_result = self.orchestrator.execute_next_task(project_id)
        assert exec_result["success"] is True

        # 验证该任务状态已改变
        state = self.orchestrator.get_project_state(project_id)
        summary = state["task_summary"]
        # 第一个任务应该已完成
        assert summary["completed"] >= 1

    def test_execute_task_by_id(self):
        """测试按 ID 执行指定任务"""
        result = self.orchestrator.process_request(
            description="开发一个API",
        )
        project_id = result["project_id"]
        task_id = result["tasks"][0]["id"]

        exec_result = self.orchestrator.execute_task(project_id, task_id)
        assert exec_result["success"] is True

    def test_agents_available(self):
        """测试 Agent 已正确注册"""
        assert "dev" in self.orchestrator.agents
        assert "architect" in self.orchestrator.agents

    def test_nonexistent_project(self):
        """测试不存在的项目"""
        result = self.orchestrator.execute_next_task("nonexistent-id")
        assert result["success"] is False
