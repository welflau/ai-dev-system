"""
任务分解器（Task Decomposer）
将用户需求分解为可执行的子任务
"""
import uuid
from typing import List, Dict, Any, Optional
from models.schemas import Task, Requirement
from models.enums import TaskType, TaskStatus, AgentType, Priority


class TaskDecomposer:
    """任务分解器"""

    # 关键词到任务模板的映射
    FEATURE_PATTERNS = {
        "api": {
            "tasks": [
                ("设计API接口", TaskType.DESIGN, AgentType.ARCHITECT, Priority.HIGH),
                ("实现API端点", TaskType.DEVELOPMENT, AgentType.DEV, Priority.HIGH),
                ("编写API测试", TaskType.TESTING, AgentType.TEST, Priority.MEDIUM),
                ("编写API文档", TaskType.DEVELOPMENT, AgentType.DEV, Priority.LOW),
            ]
        },
        "数据库": {
            "tasks": [
                ("设计数据库结构", TaskType.DESIGN, AgentType.ARCHITECT, Priority.HIGH),
                ("实现数据模型", TaskType.DEVELOPMENT, AgentType.DEV, Priority.HIGH),
                ("编写数据库迁移脚本", TaskType.DEVELOPMENT, AgentType.DEV, Priority.MEDIUM),
            ]
        },
        "前端": {
            "tasks": [
                ("设计UI界面", TaskType.DESIGN, AgentType.PRODUCT, Priority.HIGH),
                ("实现前端页面", TaskType.DEVELOPMENT, AgentType.DEV, Priority.HIGH),
                ("实现前端交互逻辑", TaskType.DEVELOPMENT, AgentType.DEV, Priority.MEDIUM),
            ]
        },
        "用户": {
            "tasks": [
                ("设计用户系统", TaskType.DESIGN, AgentType.ARCHITECT, Priority.HIGH),
                ("实现用户认证", TaskType.DEVELOPMENT, AgentType.DEV, Priority.HIGH),
                ("实现权限管理", TaskType.DEVELOPMENT, AgentType.DEV, Priority.MEDIUM),
            ]
        },
        "登录": {
            "tasks": [
                ("实现登录功能", TaskType.DEVELOPMENT, AgentType.DEV, Priority.HIGH),
                ("实现注册功能", TaskType.DEVELOPMENT, AgentType.DEV, Priority.HIGH),
            ]
        },
    }

    # 所有项目都需要的基础任务
    BASE_TASKS = [
        ("需求分析", TaskType.REQUIREMENT, AgentType.PRODUCT, Priority.HIGH),
        ("技术架构设计", TaskType.DESIGN, AgentType.ARCHITECT, Priority.HIGH),
        ("项目初始化和环境搭建", TaskType.DEVELOPMENT, AgentType.DEV, Priority.HIGH),
    ]

    # 所有项目都需要的收尾任务
    CLOSING_TASKS = [
        ("编写单元测试", TaskType.TESTING, AgentType.TEST, Priority.MEDIUM),
        ("代码审查", TaskType.TESTING, AgentType.REVIEW, Priority.MEDIUM),
        ("编写项目文档", TaskType.DEVELOPMENT, AgentType.DEV, Priority.LOW),
        ("部署配置", TaskType.DEPLOYMENT, AgentType.DEPLOY, Priority.LOW),
    ]

    def decompose(self, requirement: Requirement) -> List[Task]:
        """
        将需求分解为任务列表

        Args:
            requirement: 用户需求

        Returns:
            任务列表
        """
        tasks = []
        task_order = 0
        description = requirement.description.lower()

        # 1. 添加基础任务
        for name, task_type, agent, priority in self.BASE_TASKS:
            task_order += 1
            tasks.append(self._create_task(
                name=name,
                description=f"{name} - {requirement.description[:100]}",
                task_type=task_type,
                agent=agent,
                priority=priority,
                order=task_order,
            ))

        # 2. 根据需求关键词匹配功能任务
        matched_features = set()
        for keyword, pattern in self.FEATURE_PATTERNS.items():
            if keyword in description:
                matched_features.add(keyword)
                for name, task_type, agent, priority in pattern["tasks"]:
                    task_order += 1
                    tasks.append(self._create_task(
                        name=name,
                        description=f"{name} - 基于需求: {requirement.description[:80]}",
                        task_type=task_type,
                        agent=agent,
                        priority=priority,
                        order=task_order,
                    ))

        # 3. 如果没匹配到任何特征，添加通用开发任务
        if not matched_features:
            generic_tasks = [
                ("功能模块设计", TaskType.DESIGN, AgentType.ARCHITECT, Priority.HIGH),
                ("核心功能开发", TaskType.DEVELOPMENT, AgentType.DEV, Priority.HIGH),
                ("辅助功能开发", TaskType.DEVELOPMENT, AgentType.DEV, Priority.MEDIUM),
            ]
            for name, task_type, agent, priority in generic_tasks:
                task_order += 1
                tasks.append(self._create_task(
                    name=name,
                    description=f"{name} - {requirement.description[:100]}",
                    task_type=task_type,
                    agent=agent,
                    priority=priority,
                    order=task_order,
                ))

        # 4. 添加收尾任务
        for name, task_type, agent, priority in self.CLOSING_TASKS:
            task_order += 1
            tasks.append(self._create_task(
                name=name,
                description=f"{name} - 项目收尾",
                task_type=task_type,
                agent=agent,
                priority=priority,
                order=task_order,
            ))

        # 5. 建立依赖关系
        self._build_dependencies(tasks)

        return tasks

    def _create_task(
        self,
        name: str,
        description: str,
        task_type: TaskType,
        agent: AgentType,
        priority: Priority,
        order: int,
    ) -> Task:
        """创建任务"""
        return Task(
            id=f"task-{uuid.uuid4().hex[:8]}",
            name=name,
            description=description,
            type=task_type,
            status=TaskStatus.PENDING,
            assigned_agent=agent,
            priority=priority,
            estimated_hours=self._estimate_hours(task_type, priority),
        )

    def _estimate_hours(self, task_type: TaskType, priority: Priority) -> float:
        """估算工时"""
        base_hours = {
            TaskType.REQUIREMENT: 2.0,
            TaskType.DESIGN: 4.0,
            TaskType.DEVELOPMENT: 8.0,
            TaskType.TESTING: 4.0,
            TaskType.DEPLOYMENT: 2.0,
        }
        multiplier = {
            Priority.HIGH: 1.5,
            Priority.MEDIUM: 1.0,
            Priority.LOW: 0.5,
        }
        return base_hours.get(task_type, 4.0) * multiplier.get(priority, 1.0)

    def _build_dependencies(self, tasks: List[Task]) -> None:
        """建立任务间的依赖关系（按阶段）"""
        phase_order = [
            TaskType.REQUIREMENT,
            TaskType.DESIGN,
            TaskType.DEVELOPMENT,
            TaskType.TESTING,
            TaskType.DEPLOYMENT,
        ]

        # 按阶段分组
        phases: Dict[TaskType, List[Task]] = {}
        for task in tasks:
            phase = task.type
            if phase not in phases:
                phases[phase] = []
            phases[phase].append(task)

        # 后一阶段依赖前一阶段的所有任务
        prev_phase_ids: List[str] = []
        for phase in phase_order:
            if phase in phases:
                for task in phases[phase]:
                    task.dependencies = prev_phase_ids.copy()
                prev_phase_ids = [t.id for t in phases[phase]]
