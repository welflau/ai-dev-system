"""
SQLite 持久化状态管理器测试
"""
import os
import json
import pytest
import tempfile
from orchestrator.db_state_manager import DbStateManager
from models.schemas import Requirement, Task
from models.enums import TaskStatus, TaskType, AgentType, Priority, ProjectPhase


@pytest.fixture
def db_path():
    """创建临时数据库文件"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def manager(db_path):
    return DbStateManager(db_path=db_path)


@pytest.fixture
def sample_requirement():
    return Requirement(
        id="req-001",
        description="开发一个用户管理API系统，包含登录注册和数据库",
        project_name="用户管理系统",
        tech_stack={"language": "Python", "framework": "FastAPI"},
    )


@pytest.fixture
def sample_tasks():
    return [
        Task(
            id="task-001",
            name="需求分析",
            description="分析用户管理需求",
            type=TaskType.REQUIREMENT,
            assigned_agent=AgentType.PRODUCT,
            priority=Priority.HIGH,
            estimated_hours=2.0,
        ),
        Task(
            id="task-002",
            name="系统架构设计",
            description="设计系统架构",
            type=TaskType.DESIGN,
            assigned_agent=AgentType.ARCHITECT,
            priority=Priority.HIGH,
            estimated_hours=4.0,
            dependencies=["task-001"],
        ),
        Task(
            id="task-003",
            name="API开发",
            description="实现REST API",
            type=TaskType.DEVELOPMENT,
            assigned_agent=AgentType.DEV,
            priority=Priority.MEDIUM,
            estimated_hours=8.0,
            dependencies=["task-002"],
        ),
    ]


class TestDbStateManager:
    """SQLite 状态管理器测试"""

    def test_init_creates_tables(self, db_path):
        """测试初始化创建数据库表"""
        m = DbStateManager(db_path=db_path)
        import sqlite3
        conn = sqlite3.connect(db_path)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        conn.close()
        assert "projects" in tables
        assert "tasks" in tables
        assert "project_logs" in tables

    def test_create_project(self, manager, sample_requirement, sample_tasks):
        """测试创建项目"""
        state = manager.create_project("proj-001", sample_requirement, sample_tasks)
        assert state is not None
        assert state.project_id == "proj-001"
        assert len(state.tasks) == 3
        assert state.requirements.project_name == "用户管理系统"

    def test_get_project(self, manager, sample_requirement, sample_tasks):
        """测试获取项目"""
        manager.create_project("proj-001", sample_requirement, sample_tasks)
        state = manager.get_project("proj-001")
        assert state is not None
        assert state.project_id == "proj-001"
        assert "task-001" in state.tasks
        assert "task-002" in state.tasks
        assert "task-003" in state.tasks

    def test_get_nonexistent_project(self, manager):
        """测试获取不存在的项目"""
        state = manager.get_project("nonexistent")
        assert state is None

    def test_get_all_projects(self, manager, sample_requirement, sample_tasks):
        """测试获取所有项目"""
        manager.create_project("proj-001", sample_requirement, sample_tasks)
        req2 = Requirement(id="req-002", description="第二个项目", project_name="项目2")
        task2 = Task(
            id="task-201",
            name="需求分析2",
            description="分析第二个项目需求",
            type=TaskType.REQUIREMENT,
            assigned_agent=AgentType.PRODUCT,
        )
        manager.create_project("proj-002", req2, [task2])

        projects = manager.get_all_projects()
        assert len(projects) == 2
        ids = {p["project_id"] for p in projects}
        assert ids == {"proj-001", "proj-002"}

    def test_update_task_status(self, manager, sample_requirement, sample_tasks):
        """测试更新任务状态"""
        manager.create_project("proj-001", sample_requirement, sample_tasks)
        task = manager.update_task_status("proj-001", "task-001", TaskStatus.IN_PROGRESS)
        assert task is not None
        assert task.status == "in_progress"

        task = manager.update_task_status("proj-001", "task-001", TaskStatus.COMPLETED)
        assert task.status == "completed"

    def test_update_task_with_result(self, manager, sample_requirement, sample_tasks):
        """测试更新任务状态带结果"""
        manager.create_project("proj-001", sample_requirement, sample_tasks)
        result = {"output": "代码生成完成", "files": ["main.py"]}
        task = manager.update_task_status(
            "proj-001", "task-001", TaskStatus.COMPLETED, result=result
        )
        assert task is not None

        # 重新获取验证持久化
        state = manager.get_project("proj-001")
        t = state.tasks["task-001"]
        assert t.result is not None
        assert t.result["output"] == "代码生成完成"

    def test_update_task_with_error(self, manager, sample_requirement, sample_tasks):
        """测试更新任务状态带错误信息"""
        manager.create_project("proj-001", sample_requirement, sample_tasks)
        task = manager.update_task_status(
            "proj-001", "task-001", TaskStatus.FAILED,
            error_message="模板生成失败"
        )
        assert task.status == "failed"
        assert task.error_message == "模板生成失败"

    def test_update_nonexistent_task(self, manager, sample_requirement, sample_tasks):
        """测试更新不存在的任务"""
        manager.create_project("proj-001", sample_requirement, sample_tasks)
        task = manager.update_task_status("proj-001", "task-999", TaskStatus.COMPLETED)
        assert task is None

    def test_task_summary(self, manager, sample_requirement, sample_tasks):
        """测试任务统计"""
        manager.create_project("proj-001", sample_requirement, sample_tasks)
        summary = manager.get_task_summary("proj-001")
        assert summary["total"] == 3
        assert summary["pending"] == 3
        assert summary["completed"] == 0

        manager.update_task_status("proj-001", "task-001", TaskStatus.COMPLETED)
        manager.update_task_status("proj-001", "task-002", TaskStatus.IN_PROGRESS)
        summary = manager.get_task_summary("proj-001")
        assert summary["completed"] == 1
        assert summary["in_progress"] == 1
        assert summary["pending"] == 1

    def test_tasks_by_phase(self, manager, sample_requirement, sample_tasks):
        """测试按阶段分组"""
        manager.create_project("proj-001", sample_requirement, sample_tasks)
        phases = manager.get_tasks_by_phase("proj-001")
        assert "requirement" in phases
        assert "design" in phases
        assert "development" in phases
        assert len(phases["requirement"]) == 1
        assert phases["requirement"][0]["name"] == "需求分析"

    def test_project_logs(self, manager, sample_requirement, sample_tasks):
        """测试项目日志"""
        manager.create_project("proj-001", sample_requirement, sample_tasks)
        manager.update_task_status("proj-001", "task-001", TaskStatus.COMPLETED)
        logs = manager.get_project_logs("proj-001")
        assert len(logs) >= 2  # 至少 project_created + task_status_changed
        events = [l["event"] for l in logs]
        assert "project_created" in events
        assert "task_status_changed" in events

    def test_phase_auto_advance(self, manager, sample_requirement, sample_tasks):
        """测试阶段自动推进"""
        manager.create_project("proj-001", sample_requirement, sample_tasks)

        # 完成需求阶段
        manager.update_task_status("proj-001", "task-001", TaskStatus.COMPLETED)
        state = manager.get_project("proj-001")
        assert state.current_phase == "requirement_analysis"

        # 完成设计阶段
        manager.update_task_status("proj-001", "task-002", TaskStatus.COMPLETED)
        state = manager.get_project("proj-001")
        assert state.current_phase == "design"

    def test_all_completed_phase(self, manager, sample_requirement, sample_tasks):
        """测试所有任务完成后项目标记为 completed"""
        manager.create_project("proj-001", sample_requirement, sample_tasks)
        for tid in ["task-001", "task-002", "task-003"]:
            manager.update_task_status("proj-001", tid, TaskStatus.COMPLETED)

        state = manager.get_project("proj-001")
        assert state.current_phase == "completed"

    def test_persistence_across_instances(self, db_path, sample_requirement, sample_tasks):
        """测试数据持久化：关闭重开后数据不丢失"""
        # 第一个实例：创建项目
        m1 = DbStateManager(db_path=db_path)
        m1.create_project("proj-001", sample_requirement, sample_tasks)
        m1.update_task_status("proj-001", "task-001", TaskStatus.COMPLETED)

        # 第二个实例：验证数据还在
        m2 = DbStateManager(db_path=db_path)
        state = m2.get_project("proj-001")
        assert state is not None
        assert state.project_id == "proj-001"
        assert state.tasks["task-001"].status == "completed"
        assert state.tasks["task-002"].status == "pending"
        assert state.requirements.project_name == "用户管理系统"

        projects = m2.get_all_projects()
        assert len(projects) == 1

    def test_persistence_logs(self, db_path, sample_requirement, sample_tasks):
        """测试日志持久化"""
        m1 = DbStateManager(db_path=db_path)
        m1.create_project("proj-001", sample_requirement, sample_tasks)
        m1.update_task_status("proj-001", "task-001", TaskStatus.IN_PROGRESS)
        m1.update_task_status("proj-001", "task-001", TaskStatus.COMPLETED)

        m2 = DbStateManager(db_path=db_path)
        logs = m2.get_project_logs("proj-001")
        assert len(logs) >= 3  # created + in_progress + completed

    def test_concurrent_safe(self, db_path, sample_requirement, sample_tasks):
        """测试多次操作的数据一致性"""
        m = DbStateManager(db_path=db_path)
        m.create_project("proj-001", sample_requirement, sample_tasks)

        # 快速连续更新
        m.update_task_status("proj-001", "task-001", TaskStatus.IN_PROGRESS)
        m.update_task_status("proj-001", "task-001", TaskStatus.COMPLETED)
        m.update_task_status("proj-001", "task-002", TaskStatus.IN_PROGRESS)
        m.update_task_status("proj-001", "task-002", TaskStatus.COMPLETED)
        m.update_task_status("proj-001", "task-003", TaskStatus.IN_PROGRESS)

        summary = m.get_task_summary("proj-001")
        assert summary["completed"] == 2
        assert summary["in_progress"] == 1
        assert summary["pending"] == 0
