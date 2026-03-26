"""
AI 自动开发系统 - 数据模型与枚举定义
"""
from enum import Enum
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


# ==================== 状态枚举 ====================


class ProjectStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class MilestoneStatus(str, Enum):
    PLANNED = "planned"              # 计划中
    IN_PROGRESS = "in_progress"      # 进行中
    COMPLETED = "completed"          # 已完成
    DELAYED = "delayed"              # 已延期
    CANCELLED = "cancelled"          # 已取消


class RequirementStatus(str, Enum):
    SUBMITTED = "submitted"          # 已提交
    ANALYZING = "analyzing"          # 分析中（ProductAgent）
    DECOMPOSED = "decomposed"        # 已拆单
    IN_PROGRESS = "in_progress"      # 进行中（有工单在执行）
    PAUSED = "paused"                # 已暂停（用户手动暂停）
    COMPLETED = "completed"          # 已完成（所有工单完成）
    CANCELLED = "cancelled"          # 已取消


class TicketStatus(str, Enum):
    # 初始
    PENDING = "pending"                                    # 待启动
    # 架构阶段
    ARCHITECTURE_IN_PROGRESS = "architecture_in_progress"  # 架构中
    ARCHITECTURE_DONE = "architecture_done"                # 架构完成
    # 开发阶段
    DEVELOPMENT_IN_PROGRESS = "development_in_progress"    # 开发中
    DEVELOPMENT_DONE = "development_done"                  # 开发完成
    # 验收阶段
    ACCEPTANCE_PASSED = "acceptance_passed"                 # 验收通过
    ACCEPTANCE_REJECTED = "acceptance_rejected"             # 验收不通过
    # 测试阶段
    TESTING_IN_PROGRESS = "testing_in_progress"            # 测试中
    TESTING_DONE = "testing_done"                          # 测试通过
    TESTING_FAILED = "testing_failed"                      # 测试不通过
    # 部署阶段
    DEPLOYING = "deploying"                                # 部署中
    DEPLOYED = "deployed"                                  # 已部署
    # 终态
    CANCELLED = "cancelled"                                # 已取消


class SubtaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TicketType(str, Enum):
    FEATURE = "feature"
    BUGFIX = "bugfix"
    REFACTOR = "refactor"
    TEST = "test"
    DEPLOY = "deploy"
    DOC = "doc"


class TicketModule(str, Enum):
    FRONTEND = "frontend"
    BACKEND = "backend"
    DATABASE = "database"
    API = "api"
    TESTING = "testing"
    DEPLOY = "deploy"
    DESIGN = "design"
    OTHER = "other"


class Priority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class LogLevel(str, Enum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class LogAction(str, Enum):
    CREATE = "create"
    ASSIGN = "assign"
    START = "start"
    UPDATE_STATUS = "update_status"
    UPDATE_ESTIMATE = "update_estimate"
    ACCEPT = "accept"
    REJECT = "reject"
    COMPLETE = "complete"
    COMMENT = "comment"
    ERROR = "error"
    DECOMPOSE = "decompose"


class AgentType(str, Enum):
    PRODUCT = "ProductAgent"
    ARCHITECT = "ArchitectAgent"
    DEV = "DevAgent"
    TEST = "TestAgent"
    REVIEW = "ReviewAgent"
    DEPLOY = "DeployAgent"


# ==================== 状态机：合法转换规则 ====================

# 工单状态转换表：{当前状态: [允许转到的状态列表]}
TICKET_TRANSITIONS = {
    TicketStatus.PENDING: [
        TicketStatus.ARCHITECTURE_IN_PROGRESS,
        TicketStatus.CANCELLED,
    ],
    TicketStatus.ARCHITECTURE_IN_PROGRESS: [
        TicketStatus.ARCHITECTURE_DONE,
        TicketStatus.CANCELLED,
    ],
    TicketStatus.ARCHITECTURE_DONE: [
        TicketStatus.DEVELOPMENT_IN_PROGRESS,
    ],
    TicketStatus.DEVELOPMENT_IN_PROGRESS: [
        TicketStatus.DEVELOPMENT_DONE,
        TicketStatus.CANCELLED,
    ],
    TicketStatus.DEVELOPMENT_DONE: [
        TicketStatus.ACCEPTANCE_PASSED,
        TicketStatus.ACCEPTANCE_REJECTED,
    ],
    TicketStatus.ACCEPTANCE_PASSED: [
        TicketStatus.TESTING_IN_PROGRESS,
    ],
    TicketStatus.ACCEPTANCE_REJECTED: [
        TicketStatus.DEVELOPMENT_IN_PROGRESS,  # 打回开发
    ],
    TicketStatus.TESTING_IN_PROGRESS: [
        TicketStatus.TESTING_DONE,
        TicketStatus.TESTING_FAILED,
    ],
    TicketStatus.TESTING_DONE: [
        TicketStatus.DEPLOYING,
    ],
    TicketStatus.TESTING_FAILED: [
        TicketStatus.DEVELOPMENT_IN_PROGRESS,  # 打回开发
    ],
    TicketStatus.DEPLOYING: [
        TicketStatus.DEPLOYED,
    ],
    TicketStatus.DEPLOYED: [],  # 终态
    TicketStatus.CANCELLED: [],  # 终态
}

# 需求状态转换表
REQUIREMENT_TRANSITIONS = {
    RequirementStatus.SUBMITTED: [
        RequirementStatus.ANALYZING,
        RequirementStatus.CANCELLED,
    ],
    RequirementStatus.ANALYZING: [
        RequirementStatus.DECOMPOSED,
        RequirementStatus.PAUSED,
    ],
    RequirementStatus.DECOMPOSED: [
        RequirementStatus.IN_PROGRESS,
        RequirementStatus.PAUSED,
        RequirementStatus.CANCELLED,
    ],
    RequirementStatus.IN_PROGRESS: [
        RequirementStatus.COMPLETED,
        RequirementStatus.PAUSED,
        RequirementStatus.CANCELLED,
    ],
    RequirementStatus.PAUSED: [
        RequirementStatus.IN_PROGRESS,  # 恢复执行
        RequirementStatus.CANCELLED,     # 关闭
    ],
    RequirementStatus.COMPLETED: [],
    RequirementStatus.CANCELLED: [],
}


def validate_ticket_transition(from_status: str, to_status: str) -> bool:
    """验证工单状态转换是否合法"""
    try:
        from_s = TicketStatus(from_status)
        to_s = TicketStatus(to_status)
    except ValueError:
        return False
    allowed = TICKET_TRANSITIONS.get(from_s, [])
    return to_s in allowed


def validate_requirement_transition(from_status: str, to_status: str) -> bool:
    """验证需求状态转换是否合法"""
    try:
        from_s = RequirementStatus(from_status)
        to_s = RequirementStatus(to_status)
    except ValueError:
        return False
    allowed = REQUIREMENT_TRANSITIONS.get(from_s, [])
    return to_s in allowed


# ==================== Pydantic 请求/响应模型 ====================


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    tech_stack: Optional[str] = None
    git_remote_url: str = Field(..., min_length=1, description="Git 远程仓库 URL（必填）")
    local_repo_path: Optional[str] = Field(None, description="本地仓库路径（可选，默认为 backend/projects/{project_id}/）")


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tech_stack: Optional[str] = None
    status: Optional[str] = None
    git_remote_url: Optional[str] = None


class RequirementCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: str = Field(..., min_length=1)
    priority: Priority = Priority.MEDIUM
    module: Optional[str] = None
    tags: Optional[List[str]] = None


class RequirementUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    module: Optional[str] = None
    tags: Optional[List[str]] = None


class TicketUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[int] = None
    module: Optional[str] = None
    estimated_hours: Optional[float] = None
    estimated_completion: Optional[str] = None


class SubtaskCreate(BaseModel):
    title: str
    description: Optional[str] = None


class TicketRejectRequest(BaseModel):
    reason: str = Field(..., min_length=1)


class MilestoneCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    planned_start: Optional[str] = None
    planned_end: Optional[str] = None
    sort_order: int = 0


class MilestoneUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    planned_start: Optional[str] = None
    planned_end: Optional[str] = None
    sort_order: Optional[int] = None
    status: Optional[str] = None


# ==================== 看板状态分组映射 ====================

# 工单看板的 5 列对应的状态
BOARD_COLUMNS = {
    "pending": [TicketStatus.PENDING],
    "architecture": [TicketStatus.ARCHITECTURE_IN_PROGRESS, TicketStatus.ARCHITECTURE_DONE],
    "development": [
        TicketStatus.DEVELOPMENT_IN_PROGRESS,
        TicketStatus.DEVELOPMENT_DONE,
        TicketStatus.ACCEPTANCE_REJECTED,
        TicketStatus.ACCEPTANCE_PASSED,
    ],
    "testing": [
        TicketStatus.TESTING_IN_PROGRESS,
        TicketStatus.TESTING_DONE,
        TicketStatus.TESTING_FAILED,
    ],
    "deployed": [TicketStatus.DEPLOYING, TicketStatus.DEPLOYED],
}

# 状态 → 中文展示名
STATUS_LABELS = {
    # 工单状态
    "pending": "待启动",
    "architecture_in_progress": "架构中",
    "architecture_done": "架构完成",
    "development_in_progress": "开发中",
    "development_done": "开发完成",
    "acceptance_passed": "验收通过",
    "acceptance_rejected": "验收不通过",
    "testing_in_progress": "测试中",
    "testing_done": "测试通过",
    "testing_failed": "测试不通过",
    "deploying": "部署中",
    "deployed": "已部署",
    "cancelled": "已取消",
    # 需求状态
    "submitted": "已提交",
    "analyzing": "分析中",
    "decomposed": "已拆单",
    "in_progress": "进行中",
    "paused": "已暂停",
    "completed": "已完成",
    # 里程碑状态
    "planned": "计划中",
    "delayed": "已延期",
}
