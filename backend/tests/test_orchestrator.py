"""
协调器模块测试（Orchestrator + TaskDecomposer + StateManager）
"""
import pytest
from orchestrator import Orchestrator, TaskDecomposer, StateManager
from models.schemas import Requirement
from models.enums import TaskStatus, TaskType, ProjectPhase


class TestTaskDecomposer:
    """任务分解器测试"""

    def setup_method(self):
        self.decomposer = TaskDecomposer()

    def _make_req(self, desc):
        return Requirement(
            id="req-test",
            description=desc,
            project_name="test-project",
        )

    def test_basic_decomposition(self):
        """测试基础分解（总是有 base + closing 任务）"""
        req = self._make_req("开发一个简单的工具")
        tasks = self.decomposer.decompose(req)

        assert len(tasks) >= 7  # 3 base + generic + 4 closing
        # 第一个任务应该是需求分析
        assert tasks[0].name == "需求分析"
        assert tasks[0].type == TaskType.REQUIREMENT.value
        # 最后一个应该是部署配置
        assert tasks[-1].name == "部署配置"

    def test_api_keyword_matching(self):
        """测试 API 关键词匹配"""
        req = self._make_req("开发一个 API 接口系统")
        tasks = self.decomposer.decompose(req)

        task_names = [t.name for t in tasks]
        assert "设计API接口" in task_names
        assert "实现API端点" in task_names
        assert "编写API测试" in task_names

    def test_database_keyword_matching(self):
        """测试数据库关键词匹配"""
        req = self._make_req("需要数据库设计和存储")
        tasks = self.decomposer.decompose(req)

        task_names = [t.name for t in tasks]
        assert "设计数据库结构" in task_names
        assert "实现数据模型" in task_names

    def test_multiple_keywords(self):
        """测试多关键词匹配"""
        req = self._make_req("开发一个用户管理API系统，包含登录注册和数据库")
        tasks = self.decomposer.decompose(req)

        task_names = [t.name for t in tasks]
        # 应该同时匹配 api、数据库、用户、登录
        assert "设计API接口" in task_names
        assert "设计数据库结构" in task_names
        assert "设计用户系统" in task_names
        assert "实现登录功能" in task_names

    def test_no_keyword_uses_generic(self):
        """测试无关键词时使用通用任务"""
        req = self._make_req("做一个简单的东西")
        tasks = self.decomposer.decompose(req)

        task_names = [t.name for t in tasks]
        assert "功能模块设计" in task_names
        assert "核心功能开发" in task_names

    def test_dependencies_built(self):
        """测试依赖关系自动建立"""
        req = self._make_req("开发一个API")
        tasks = self.decomposer.decompose(req)

        # 需求分析阶段的任务应该没有依赖
        req_tasks = [t for t in tasks if t.type == TaskType.REQUIREMENT.value]
        for t in req_tasks:
            assert t.dependencies == []

        # 设计阶段的任务应该依赖需求分析阶段
        design_tasks = [t for t in tasks if t.type == TaskType.DESIGN.value]
        for t in design_tasks:
            assert len(t.dependencies) > 0

    def test_estimated_hours(self):
        """测试工时估算"""
        req = self._make_req("开发一个系统")
        tasks = self.decomposer.decompose(req)

        for task in tasks:
            assert task.estimated_hours is not None
            assert task.estimated_hours > 0


class TestStateManager:
    """状态管理器测试"""

    def setup_method(self):
        self.sm = StateManager()
        self.decomposer = TaskDecomposer()

    def _create_test_project(self):
        req = Requirement(
            id="req-1",
            description="测试项目",
            project_name="test",
        )
        tasks = self.decomposer.decompose(req)
        return self.sm.create_project("proj-1", req, tasks), tasks

    def test_create_project(self):
        """测试创建项目"""
        state, tasks = self._create_test_project()

        assert state.project_id == "proj-1"
        assert len(state.tasks) == len(tasks)
        assert state.current_phase == ProjectPhase.REQUIREMENT_ANALYSIS

    def test_get_project(self):
        """测试获取项目"""
        self._create_test_project()

        state = self.sm.get_project("proj-1")
        assert state is not None
        assert state.project_id == "proj-1"

        assert self.sm.get_project("nonexistent") is None

    def test_get_all_projects(self):
        """测试获取所有项目"""
        self._create_test_project()

        projects = self.sm.get_all_projects()
        assert len(projects) == 1
        assert projects[0]["project_id"] == "proj-1"
        assert projects[0]["name"] == "test"

    def test_update_task_status(self):
        """测试更新任务状态"""
        state, tasks = self._create_test_project()

        task_id = tasks[0].id
        updated = self.sm.update_task_status("proj-1", task_id, TaskStatus.COMPLETED)

        assert updated is not None
        assert updated.status == TaskStatus.COMPLETED.value

    def test_update_nonexistent_task(self):
        """测试更新不存在的任务"""
        self._create_test_project()

        result = self.sm.update_task_status("proj-1", "fake-id", TaskStatus.COMPLETED)
        assert result is None

    def test_task_summary(self):
        """测试任务摘要"""
        state, tasks = self._create_test_project()

        summary = self.sm.get_task_summary("proj-1")
        assert summary["total"] == len(tasks)
        assert summary["pending"] == len(tasks)
        assert summary["completed"] == 0

        # 完成一个任务
        self.sm.update_task_status("proj-1", tasks[0].id, TaskStatus.COMPLETED)
        summary = self.sm.get_task_summary("proj-1")
        assert summary["completed"] == 1
        assert summary["pending"] == len(tasks) - 1

    def test_tasks_by_phase(self):
        """测试按阶段分组"""
        self._create_test_project()

        phases = self.sm.get_tasks_by_phase("proj-1")
        assert isinstance(phases, dict)
        # 至少有需求、设计、开发、测试、部署这几个阶段
        assert "requirement" in phases
        assert "development" in phases

    def test_project_logs(self):
        """测试项目日志"""
        self._create_test_project()

        logs = self.sm.get_project_logs("proj-1")
        assert len(logs) >= 1
        assert logs[0]["event"] == "project_created"


class TestOrchestrator:
    """协调器集成测试"""

    def setup_method(self):
        self.orchestrator = Orchestrator()

    def test_process_request(self):
        """测试处理请求"""
        result = self.orchestrator.process_request(
            description="开发一个待办事项应用",
            preferences={"project_name": "todo-app"},
        )

        assert "project_id" in result
        assert result["status"] == "analyzing"
        assert result["task_count"] > 0
        assert len(result["tasks"]) == result["task_count"]

    def test_get_project_state(self):
        """测试获取项目状态"""
        result = self.orchestrator.process_request(
            description="开发一个博客系统",
        )
        pid = result["project_id"]

        state = self.orchestrator.get_project_state(pid)
        assert state is not None
        assert state["project_id"] == pid
        assert "task_summary" in state
        assert "tasks_by_phase" in state
        assert "logs" in state

    def test_get_nonexistent_project(self):
        """测试获取不存在的项目"""
        state = self.orchestrator.get_project_state("fake-project")
        assert state is None

    def test_update_task(self):
        """测试更新任务"""
        result = self.orchestrator.process_request(
            description="开发一个系统",
        )
        pid = result["project_id"]
        task_id = result["tasks"][0]["id"]

        update_result = self.orchestrator.update_task(
            pid, task_id, TaskStatus.IN_PROGRESS
        )
        assert update_result is not None
        assert update_result["status"] == "in_progress"

    def test_get_all_projects(self):
        """测试获取所有项目"""
        self.orchestrator.process_request(description="项目A")
        self.orchestrator.process_request(description="项目B")

        projects = self.orchestrator.get_all_projects()
        assert len(projects) == 2

    def test_full_workflow(self):
        """测试完整工作流"""
        # 1. 创建项目
        result = self.orchestrator.process_request(
            description="开发一个用户管理API",
            preferences={"project_name": "user-api"},
        )
        pid = result["project_id"]

        # 2. 获取状态
        state = self.orchestrator.get_project_state(pid)
        assert state["task_summary"]["total"] > 0
        assert state["task_summary"]["pending"] == state["task_summary"]["total"]

        # 3. 逐个完成需求分析阶段的任务
        for phase, tasks in state["tasks_by_phase"].items():
            if phase == "requirement":
                for task in tasks:
                    self.orchestrator.update_task(
                        pid, task["id"], TaskStatus.COMPLETED
                    )

        # 4. 验证状态推进
        state2 = self.orchestrator.get_project_state(pid)
        assert state2["task_summary"]["completed"] > 0
