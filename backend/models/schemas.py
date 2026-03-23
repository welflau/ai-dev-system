"""
Pydantic数据模型
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from .enums import TaskStatus, TaskType, AgentType, Priority, ProjectPhase


# ============ 任务相关 ============

class Task(BaseModel):
    """任务模型"""
    id: str
    name: str
    description: str
    type: TaskType
    status: TaskStatus = TaskStatus.PENDING
    assigned_agent: Optional[AgentType] = None
    priority: Priority = Priority.MEDIUM
    estimated_hours: Optional[float] = None
    actual_hours: Optional[float] = None
    dependencies: List[str] = Field(default_factory=list)
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    
    class Config:
        use_enum_values = True


class Requirement(BaseModel):
    """需求模型"""
    id: str
    description: str
    project_name: Optional[str] = None
    core_features: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    tech_stack: Optional[Dict[str, str]] = None


class ProjectPlan(BaseModel):
    """项目计划"""
    project_id: str
    requirements: Requirement
    tasks: List[Task]
    current_phase: ProjectPhase
    created_at: datetime = Field(default_factory=datetime.now)


# ============ 执行结果相关 ============

class Artifact(BaseModel):
    """产物模型"""
    id: str
    type: str
    name: Optional[str] = None
    path: Optional[str] = None
    content: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)


class ExecutionResult(BaseModel):
    """执行结果"""
    success: bool
    output: Optional[Dict[str, Any]] = None
    artifacts: List[Artifact] = Field(default_factory=list)
    error_message: Optional[str] = None
    execution_time: Optional[float] = None


# ============ Agent相关 ============

class AgentContext(BaseModel):
    """Agent上下文"""
    project_id: str
    task_id: Optional[str] = None
    requirements: Optional[Requirement] = None
    previous_tasks: List[Task] = Field(default_factory=list)
    artifacts: Dict[str, Artifact] = Field(default_factory=dict)
    global_context: Dict[str, Any] = Field(default_factory=dict)


class AgentCapabilities(BaseModel):
    """Agent能力描述"""
    agent_type: AgentType
    capabilities: List[str]
    supported_tasks: List[TaskType]


# ============ 项目状态相关 ============

class ProjectState(BaseModel):
    """项目状态"""
    project_id: str
    requirements: Optional[Requirement] = None
    tasks: Dict[str, Task] = Field(default_factory=dict)
    current_phase: ProjectPhase = ProjectPhase.REQUIREMENT_ANALYSIS
    global_context: Dict[str, Any] = Field(default_factory=dict)
    artifacts: Dict[str, Artifact] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


# ============ API请求/响应 ============

class ProcessRequest(BaseModel):
    """处理请求"""
    description: str
    tech_stack: Optional[Dict[str, str]] = None
    preferences: Optional[Dict[str, Any]] = None


class ProcessResponse(BaseModel):
    """处理响应"""
    project_id: str
    status: str
    message: str
    plan: Optional[ProjectPlan] = None


class TaskUpdateRequest(BaseModel):
    """任务更新请求"""
    status: Optional[TaskStatus] = None
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


class GetProjectStateRequest(BaseModel):
    """获取项目状态请求"""
    project_id: str


class GetProjectStateResponse(BaseModel):
    """获取项目状态响应"""
    project_state: ProjectState
    task_summary: Dict[str, Any]
