"""CIStrategy 抽象——项目类型感知 pipeline 接口

每个策略声明 `required_traits` + `priority`，CI loader 按 traits 匹配挑第一个
命中的（priority 降序）。策略负责：

  1. pipeline_stages()      ——  前端渲染 pipeline 进度条用
  2. environment_specs()    ——  前端渲染环境卡片用
  3. build_types()          ——  可触发的构建类型（给 trigger 按钮下拉）
  4. trigger_build()        ——  触发一次构建
  5. deploy_environment()   ——  部署到指定环境
  6. get_environment_status ——  某环境当前状态

v0.17 SOP fragment 的 trait 匹配语义直接复用。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


# ==================== 数据类 ====================


@dataclass
class PipelineStage:
    """pipeline 阶段定义（给前端进度条渲染用）"""
    id: str                # 稳定机读 id，如 "syntax_check" / "ubt_compile"
    name: str              # 显示名，如 "语法检查" / "UBT 编译"
    icon: str = "●"        # emoji
    description: str = ""
    blocking: bool = True  # 失败是否阻塞后续阶段

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EnvSpec:
    """环境定义（给前端环境卡片渲染用）"""
    name: str                          # "dev" / "test" / "prod" / "packaged_win64"
    display_name: str                  # 显示名
    branch_binding: Optional[str] = None  # 绑定分支名（HEAD / develop / main / None）
    icon: str = "📦"
    description: str = ""
    can_deploy: bool = True            # 是否支持 "部署" 操作
    can_stop: bool = True              # 是否支持 "停止" 操作

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BuildTypeSpec:
    """构建类型定义（给前端"手动触发"下拉用）"""
    id: str                # 稳定机读 id，如 "develop_build" / "full"
    display_name: str      # 显示名
    description: str = ""
    icon: str = "▶"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ==================== 策略接口 ====================


class CIStrategy(ABC):
    """项目类型感知的 CI pipeline 策略接口

    子类必须设置 `name` + `required_traits` + `priority`，实现 5 个核心方法。
    """

    name: str = ""
    required_traits: Dict[str, List[str]] = {}  # {any_of: [...], all_of: [...]}
    priority: int = 0                            # 多个命中时越大越优先

    # ========== 元数据（给前端渲染 & SOP 用） ==========

    @abstractmethod
    def pipeline_stages(self) -> List[PipelineStage]:
        """本策略的 pipeline 阶段定义——前端进度条渲染用"""

    @abstractmethod
    def environment_specs(self) -> List[EnvSpec]:
        """本策略支持的环境列表——前端环境卡片渲染用"""

    def build_types(self) -> List[BuildTypeSpec]:
        """可触发的构建类型列表（默认空，子类可以覆盖加"手动触发"下拉）"""
        return []

    # ========== 运行期行为（给 api/ci.py 调用） ==========

    @abstractmethod
    async def trigger_build(
        self, project_id: str, build_type: str, trigger: str = "manual", **kwargs
    ) -> Dict[str, Any]:
        """触发一次构建，返回 {build_id, status, ...}"""

    @abstractmethod
    async def deploy_environment(
        self, project_id: str, env_name: str, **kwargs
    ) -> Dict[str, Any]:
        """部署到指定环境，返回 {url, port, branch, deployed_at, ...}"""

    async def stop_environment(
        self, project_id: str, env_name: str
    ) -> Dict[str, Any]:
        """停止指定环境（默认无操作，子类需要则覆盖）"""
        return {"status": "not_supported", "env": env_name}

    @abstractmethod
    async def get_environment_status(
        self, project_id: str, env_name: str
    ) -> Dict[str, Any]:
        """取某环境当前状态——给 /environments API 用"""

    async def get_all_environments(self, project_id: str) -> List[Dict[str, Any]]:
        """取所有环境的状态列表。默认按 environment_specs 逐个调 get_environment_status"""
        out = []
        for spec in self.environment_specs():
            status = await self.get_environment_status(project_id, spec.name)
            out.append({**spec.to_dict(), **status})
        return out

    # ========== 声明 ==========

    def to_definition(self) -> Dict[str, Any]:
        """序列化成前端消费的 pipeline-definition 对象"""
        return {
            "strategy": self.name,
            "priority": self.priority,
            "required_traits": self.required_traits,
            "stages": [s.to_dict() for s in self.pipeline_stages()],
            "environments": [e.to_dict() for e in self.environment_specs()],
            "build_types": [b.to_dict() for b in self.build_types()],
        }
