"""
枚举类型定义
"""
from enum import Enum


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"           # 待处理
    IN_PROGRESS = "in_progress"   # 进行中
    COMPLETED = "completed"        # 已完成
    FAILED = "failed"            # 失败
    CANCELLED = "cancelled"       # 已取消


class TaskType(str, Enum):
    """任务类型"""
    REQUIREMENT = "requirement"   # 需求
    DESIGN = "design"            # 设计
    DEVELOPMENT = "development"  # 开发
    TESTING = "testing"         # 测试
    DEPLOYMENT = "deployment"   # 部署


class AgentType(str, Enum):
    """Agent类型"""
    PRODUCT = "product"          # 产品代理
    ARCHITECT = "architect"      # 架构师代理
    DEV = "dev"                # 开发代理
    TEST = "test"              # 测试代理
    REVIEW = "review"           # 审查代理
    DEPLOY = "deploy"           # 部署代理


class Priority(str, Enum):
    """优先级"""
    HIGH = "high"              # 高
    MEDIUM = "medium"          # 中
    LOW = "low"               # 低


class ProjectPhase(str, Enum):
    """项目阶段"""
    REQUIREMENT_ANALYSIS = "requirement_analysis"  # 需求分析
    DESIGN = "design"                            # 设计
    DEVELOPMENT = "development"                   # 开发
    TESTING = "testing"                         # 测试
    DEPLOYMENT = "deployment"                    # 部署
    COMPLETED = "completed"                      # 已完成


class InterventionType(str, Enum):
    """介入类型"""
    CLARIFICATION = "clarification"  # 澄清需求
    APPROVAL = "approval"            # 审批
    ERROR_REVIEW = "error_review"    # 错误审查
    MANUAL_FIX = "manual_fix"       # 手动修复


class InterventionStatus(str, Enum):
    """介入状态"""
    PENDING = "pending"      # 待处理
    RESPONDED = "responded"  # 已响应
    CLOSED = "closed"        # 已关闭
