"""
协调器（Orchestrator）
核心调度中心，接收需求 -> 分解任务 -> 管理执行
"""
import uuid
from typing import Dict, Any, Optional
from models.schemas import Requirement, Task, ProjectPlan
from models.enums import ProjectPhase, TaskStatus
from .decomposer import TaskDecomposer
from .state_manager import StateManager


class Orchestrator:
    """AI项目协调器"""

    def __init__(self, state_manager: Optional[StateManager] = None):
        self.decomposer = TaskDecomposer()
        self.state_manager = state_manager or StateManager()

    def process_request(
        self,
        description: str,
        tech_stack: Optional[Dict[str, str]] = None,
        preferences: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        处理用户请求：分析需求 -> 分解任务 -> 创建项目

        Args:
            description: 需求描述
            tech_stack: 技术栈偏好
            preferences: 其他偏好

        Returns:
            包含 project_id、tasks、status 的字典
        """
        # 1. 生成项目ID
        project_id = str(uuid.uuid4())

        # 2. 构建需求对象
        project_name = (preferences or {}).get("project_name", "")
        if not project_name:
            # 从描述中提取项目名
            project_name = description.strip().split("\n")[0][:50]

        requirement = Requirement(
            id=f"req-{uuid.uuid4().hex[:8]}",
            description=description,
            project_name=project_name,
            tech_stack=tech_stack,
        )

        # 3. 任务分解
        tasks = self.decomposer.decompose(requirement)

        # 4. 创建项目状态
        project_state = self.state_manager.create_project(
            project_id=project_id,
            requirement=requirement,
            tasks=tasks,
        )

        # 5. 返回结果
        return {
            "project_id": project_id,
            "status": "analyzing",
            "message": f"项目已创建，共分解为 {len(tasks)} 个任务",
            "task_count": len(tasks),
            "tasks": [
                {
                    "id": t.id,
                    "name": t.name,
                    "type": t.type if isinstance(t.type, str) else t.type.value,
                    "status": t.status if isinstance(t.status, str) else t.status.value,
                    "assigned_agent": t.assigned_agent if isinstance(t.assigned_agent, str) else (t.assigned_agent.value if t.assigned_agent else None),
                    "priority": t.priority if isinstance(t.priority, str) else t.priority.value,
                    "estimated_hours": t.estimated_hours,
                    "dependencies": t.dependencies,
                }
                for t in tasks
            ],
        }

    def get_project_state(self, project_id: str) -> Optional[Dict[str, Any]]:
        """获取项目完整状态"""
        state = self.state_manager.get_project(project_id)
        if not state:
            return None

        summary = self.state_manager.get_task_summary(project_id)
        tasks_by_phase = self.state_manager.get_tasks_by_phase(project_id)
        logs = self.state_manager.get_project_logs(project_id)

        return {
            "project_id": project_id,
            "name": state.requirements.project_name if state.requirements else "未命名",
            "description": state.requirements.description if state.requirements else "",
            "phase": state.current_phase.value if hasattr(state.current_phase, 'value') else state.current_phase,
            "task_summary": summary,
            "tasks_by_phase": tasks_by_phase,
            "logs": logs,
            "created_at": state.created_at.isoformat(),
            "updated_at": state.updated_at.isoformat(),
        }

    def get_all_projects(self):
        """获取所有项目摘要"""
        return self.state_manager.get_all_projects()

    def update_task(
        self,
        project_id: str,
        task_id: str,
        status: TaskStatus,
        result: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """更新任务状态"""
        task = self.state_manager.update_task_status(
            project_id, task_id, status, result, error_message
        )
        if not task:
            return None

        return {
            "task_id": task_id,
            "name": task.name,
            "status": task.status if isinstance(task.status, str) else task.status.value,
            "message": f"任务 '{task.name}' 状态已更新为 {task.status if isinstance(task.status, str) else task.status.value}",
        }
