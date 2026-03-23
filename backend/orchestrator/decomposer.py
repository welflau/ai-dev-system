"""
任务分解器（Task Decomposer）
将用户需求分解为可执行的子任务

LLM 模式：使用大模型智能分解需求
降级模式：使用关键词匹配的规则引擎
"""
import uuid
import json
import logging
from typing import List, Dict, Any, Optional
from models.schemas import Task, Requirement
from models.enums import TaskType, TaskStatus, AgentType, Priority

logger = logging.getLogger(__name__)

# LLM 任务分解的系统提示词
DECOMPOSER_SYSTEM_PROMPT = """你是一个专业的软件项目任务分解专家。
你的职责是将用户的自然语言需求分解为清晰的、可执行的开发任务列表。

规则：
1. 每个任务必须明确、可执行，有清晰的交付物
2. 任务按阶段组织：需求分析 → 架构设计 → 开发实现 → 测试 → 部署
3. 合理分配 Agent 类型：product（产品）、architect（架构）、dev（开发）、test（测试）、deploy（部署）
4. 为每个任务设置优先级：high / medium / low
5. 估算工时（小时）

你必须返回严格的 JSON 格式（不要包含 markdown 代码块标记），结构如下：
[
  {
    "name": "任务名称",
    "description": "任务详细描述",
    "type": "requirement|design|development|testing|deployment",
    "agent": "product|architect|dev|test|deploy",
    "priority": "high|medium|low",
    "estimated_hours": 4.0
  }
]
"""


class TaskDecomposer:
    """任务分解器 - LLM 智能分解 + 规则引擎降级"""

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    # ------------------------------------------------------------------
    #  公开方法
    # ------------------------------------------------------------------

    def decompose(self, requirement: Requirement) -> List[Task]:
        """
        将需求分解为任务列表

        如果 LLM 可用，使用 LLM 智能分解
        否则使用关键词匹配规则引擎

        Args:
            requirement: 用户需求

        Returns:
            任务列表
        """
        # 尝试 LLM 分解
        if self.llm_client and self.llm_client.enabled:
            try:
                tasks = self._llm_decompose(requirement)
                if tasks:
                    logger.info(f"LLM 分解成功：{len(tasks)} 个任务")
                    return tasks
            except Exception as e:
                logger.warning(f"LLM 分解失败，降级到规则引擎: {e}")

        # 降级：规则引擎分解
        logger.info("使用规则引擎分解任务")
        return self._rule_decompose(requirement)

    # ------------------------------------------------------------------
    #  LLM 智能分解
    # ------------------------------------------------------------------

    def _llm_decompose(self, requirement: Requirement) -> List[Task]:
        """使用 LLM 智能分解需求"""
        user_prompt = f"""请分解以下软件开发需求为具体的执行任务：

项目名称：{requirement.project_name}
需求描述：{requirement.description}
技术栈偏好：{json.dumps(requirement.tech_stack, ensure_ascii=False) if requirement.tech_stack else '未指定'}

请返回 JSON 格式的任务列表。"""

        response = self.llm_client.chat(
            messages=[{"role": "user", "content": user_prompt}],
            system=DECOMPOSER_SYSTEM_PROMPT,
            temperature=0.3,
            max_tokens=4096,
        )

        # 检查是否为降级响应
        if response == "[LLM_UNAVAILABLE]":
            return []

        # 解析 LLM 返回的 JSON
        tasks = self._parse_llm_tasks(response, requirement)
        return tasks

    def _parse_llm_tasks(
        self, response: str, requirement: Requirement
    ) -> List[Task]:
        """解析 LLM 返回的任务 JSON"""
        # 尝试提取 JSON（兼容 markdown 代码块）
        text = response.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        try:
            raw_tasks = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"LLM 返回的 JSON 解析失败: {text[:200]}")
            return []

        if not isinstance(raw_tasks, list):
            return []

        tasks = []
        for raw in raw_tasks:
            try:
                task_type = self._map_task_type(raw.get("type", "development"))
                agent_type = self._map_agent_type(raw.get("agent", "dev"))
                priority = self._map_priority(raw.get("priority", "medium"))

                tasks.append(Task(
                    id=f"task-{uuid.uuid4().hex[:8]}",
                    name=raw.get("name", "未命名任务"),
                    description=raw.get("description", raw.get("name", "")),
                    type=task_type,
                    status=TaskStatus.PENDING,
                    assigned_agent=agent_type,
                    priority=priority,
                    estimated_hours=float(raw.get("estimated_hours", 4.0)),
                ))
            except Exception as e:
                logger.warning(f"解析单个任务失败: {e}, raw={raw}")
                continue

        # 建立依赖关系
        if tasks:
            self._build_dependencies(tasks)

        return tasks

    # ------------------------------------------------------------------
    #  类型映射
    # ------------------------------------------------------------------

    TYPE_MAP = {
        "requirement": TaskType.REQUIREMENT,
        "design": TaskType.DESIGN,
        "development": TaskType.DEVELOPMENT,
        "testing": TaskType.TESTING,
        "deployment": TaskType.DEPLOYMENT,
    }

    AGENT_MAP = {
        "product": AgentType.PRODUCT,
        "architect": AgentType.ARCHITECT,
        "dev": AgentType.DEV,
        "test": AgentType.TEST,
        "deploy": AgentType.DEPLOY,
        "review": AgentType.REVIEW,
    }

    PRIORITY_MAP = {
        "high": Priority.HIGH,
        "medium": Priority.MEDIUM,
        "low": Priority.LOW,
    }

    def _map_task_type(self, s: str) -> TaskType:
        return self.TYPE_MAP.get(s.lower(), TaskType.DEVELOPMENT)

    def _map_agent_type(self, s: str) -> AgentType:
        return self.AGENT_MAP.get(s.lower(), AgentType.DEV)

    def _map_priority(self, s: str) -> Priority:
        return self.PRIORITY_MAP.get(s.lower(), Priority.MEDIUM)

    # ------------------------------------------------------------------
    #  规则引擎分解（降级方案）
    # ------------------------------------------------------------------

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

    def _rule_decompose(self, requirement: Requirement) -> List[Task]:
        """规则引擎分解（降级方案）"""
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

    # ------------------------------------------------------------------
    #  工具方法
    # ------------------------------------------------------------------

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
