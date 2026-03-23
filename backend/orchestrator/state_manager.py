"""
状态管理器（State Manager）
管理项目全局状态、任务状态、Agent上下文
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
from models.schemas import (
    Task, Requirement, ProjectState, Artifact, ProjectPlan,
    AgentContext, ExecutionResult
)
from models.enums import TaskStatus, ProjectPhase, TaskType


class StateManager:
    """项目状态管理器（内存版，后续可切换到数据库）"""

    def __init__(self):
        self.projects: Dict[str, ProjectState] = {}
        self.logs: Dict[str, List[Dict[str, Any]]] = {}

    def create_project(
        self,
        project_id: str,
        requirement: Requirement,
        tasks: List[Task],
    ) -> ProjectState:
        """创建项目"""
        task_dict = {task.id: task for task in tasks}

        state = ProjectState(
            project_id=project_id,
            requirements=requirement,
            tasks=task_dict,
            current_phase=ProjectPhase.REQUIREMENT_ANALYSIS,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        self.projects[project_id] = state
        self.logs[project_id] = []

        self._log(project_id, "project_created", {
            "task_count": len(tasks),
            "requirement": requirement.description[:200],
        })

        return state

    def get_project(self, project_id: str) -> Optional[ProjectState]:
        """获取项目状态"""
        return self.projects.get(project_id)

    def get_all_projects(self) -> List[Dict[str, Any]]:
        """获取所有项目摘要"""
        summaries = []
        for pid, state in self.projects.items():
            tasks = list(state.tasks.values())
            summaries.append({
                "project_id": pid,
                "description": state.requirements.description[:100] if state.requirements else "",
                "name": state.requirements.project_name if state.requirements else "未命名",
                "phase": state.current_phase.value,
                "task_count": len(tasks),
                "completed_count": sum(1 for t in tasks if t.status == TaskStatus.COMPLETED),
                "in_progress_count": sum(1 for t in tasks if t.status == TaskStatus.IN_PROGRESS),
                "failed_count": sum(1 for t in tasks if t.status == TaskStatus.FAILED),
                "created_at": state.created_at.isoformat(),
                "updated_at": state.updated_at.isoformat(),
            })
        return summaries

    def update_task_status(
        self,
        project_id: str,
        task_id: str,
        status: TaskStatus,
        result: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> Optional[Task]:
        """更新任务状态"""
        state = self.projects.get(project_id)
        if not state or task_id not in state.tasks:
            return None

        task = state.tasks[task_id]
        old_status = task.status
        task.status = status

        if result:
            task.result = result
        if error_message:
            task.error_message = error_message

        state.updated_at = datetime.now()

        # 自动推进项目阶段
        self._advance_phase(project_id)

        self._log(project_id, "task_status_changed", {
            "task_id": task_id,
            "task_name": task.name,
            "old_status": old_status,
            "new_status": status,
        })

        return task

    def get_task_summary(self, project_id: str) -> Dict[str, Any]:
        """获取任务统计摘要"""
        state = self.projects.get(project_id)
        if not state:
            return {"total": 0, "completed": 0, "in_progress": 0, "pending": 0, "failed": 0}

        tasks = list(state.tasks.values())
        return {
            "total": len(tasks),
            "completed": sum(1 for t in tasks if t.status == TaskStatus.COMPLETED),
            "in_progress": sum(1 for t in tasks if t.status == TaskStatus.IN_PROGRESS),
            "pending": sum(1 for t in tasks if t.status == TaskStatus.PENDING),
            "failed": sum(1 for t in tasks if t.status == TaskStatus.FAILED),
        }

    def get_tasks_by_phase(self, project_id: str) -> Dict[str, List[Dict[str, Any]]]:
        """按阶段分组获取任务"""
        state = self.projects.get(project_id)
        if not state:
            return {}

        phases: Dict[str, List[Dict[str, Any]]] = {}
        for task in state.tasks.values():
            phase = task.type if isinstance(task.type, str) else task.type.value
            if phase not in phases:
                phases[phase] = []
            phases[phase].append({
                "id": task.id,
                "name": task.name,
                "description": task.description,
                "status": task.status if isinstance(task.status, str) else task.status.value,
                "assigned_agent": task.assigned_agent if isinstance(task.assigned_agent, str) else (task.assigned_agent.value if task.assigned_agent else None),
                "priority": task.priority if isinstance(task.priority, str) else task.priority.value,
                "estimated_hours": task.estimated_hours,
                "dependencies": task.dependencies,
            })

        return phases

    def get_project_logs(self, project_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """获取项目日志"""
        logs = self.logs.get(project_id, [])
        return logs[-limit:]

    def _advance_phase(self, project_id: str) -> None:
        """根据任务完成情况自动推进项目阶段"""
        state = self.projects.get(project_id)
        if not state:
            return

        tasks = list(state.tasks.values())
        phase_order = [
            (TaskType.REQUIREMENT, ProjectPhase.REQUIREMENT_ANALYSIS),
            (TaskType.DESIGN, ProjectPhase.DESIGN),
            (TaskType.DEVELOPMENT, ProjectPhase.DEVELOPMENT),
            (TaskType.TESTING, ProjectPhase.TESTING),
            (TaskType.DEPLOYMENT, ProjectPhase.DEPLOYMENT),
        ]

        # 找到最新的已完成阶段
        for task_type, phase in phase_order:
            phase_tasks = [t for t in tasks if t.type == task_type or t.type == task_type.value]
            if phase_tasks:
                all_completed = all(
                    t.status in (TaskStatus.COMPLETED, TaskStatus.COMPLETED.value, "completed")
                    for t in phase_tasks
                )
                if all_completed:
                    state.current_phase = phase
                else:
                    break

        # 所有任务完成 -> 项目完成
        all_done = all(
            t.status in (TaskStatus.COMPLETED, TaskStatus.COMPLETED.value, "completed")
            for t in tasks
        )
        if all_done and tasks:
            state.current_phase = ProjectPhase.COMPLETED

    def _log(self, project_id: str, event: str, data: Dict[str, Any]) -> None:
        """记录项目日志"""
        if project_id not in self.logs:
            self.logs[project_id] = []

        self.logs[project_id].append({
            "timestamp": datetime.now().isoformat(),
            "event": event,
            "data": data,
        })
