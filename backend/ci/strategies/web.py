"""Web 项目 CI 策略——委托现有 `ci_pipeline.py` + `DeployAgent`，**零侵入**

核心原则：不改任何现有代码，只做适配层。Phase A 完成时，Web 项目行为跟 pre-Phase-A
完全一致。v0.19 后期把 Web 逻辑真正"收进" strategy 只是代码归属调整。

匹配条件：platform:web 或 category:app（任一命中）。priority=50（低于 UE 的 100
等专精策略，这样 UE 项目不会被 Web 劫持）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from ci.strategies.base import (
    BuildTypeSpec,
    CIStrategy,
    EnvSpec,
    PipelineStage,
)

logger = logging.getLogger("ci.strategies.web")


class WebCIStrategy(CIStrategy):
    name = "web"
    required_traits = {"any_of": ["platform:web", "category:app"]}
    priority = 50

    # ========== 元数据 ==========

    def pipeline_stages(self) -> List[PipelineStage]:
        return [
            PipelineStage(
                id="syntax_check", name="语法检查", icon="🔍",
                description="Python/JS 语法 compile + 入口文件 smoke",
                blocking=True,
            ),
            PipelineStage(
                id="smoke_test", name="冒烟测试", icon="💨",
                description="src/ 结构完整性 + 关键入口文件存在",
                blocking=True,
            ),
            PipelineStage(
                id="merge_to_main", name="合并主分支", icon="🔀",
                description="通过后自动 develop → main（自动解冲突：报告 theirs + 代码走 LLM）",
                blocking=False,
            ),
            PipelineStage(
                id="deploy_test", name="部署 test", icon="🧪",
                description="起本地 http.server 预览 develop",
                blocking=False,
            ),
            PipelineStage(
                id="deploy_prod", name="部署 prod", icon="🌐",
                description="main 日构建 + 本地 http.server 预览",
                blocking=False,
            ),
        ]

    def environment_specs(self) -> List[EnvSpec]:
        return [
            EnvSpec(
                name="dev", display_name="开发环境", branch_binding="HEAD",
                icon="⚡", description="共享主仓库，跟当前分支实时同步",
            ),
            EnvSpec(
                name="test", display_name="测试环境", branch_binding="develop",
                icon="🧪", description="develop 构建通过后自动部署",
            ),
            EnvSpec(
                name="prod", display_name="生产环境", branch_binding="main",
                icon="🌐", description="main 日构建触发",
            ),
        ]

    def build_types(self) -> List[BuildTypeSpec]:
        return [
            BuildTypeSpec(
                id="develop_build", display_name="构建 Develop", icon="🔨",
                description="语法 + 冒烟 + 合入主分支",
            ),
            BuildTypeSpec(
                id="master_build", display_name="构建 Master", icon="🏗️",
                description="主分支集成测试 + 自动部署 prod",
            ),
            BuildTypeSpec(
                id="deploy", display_name="部署", icon="🚀",
                description="生成 Dockerfile + docker-compose + 模拟部署",
            ),
        ]

    # ========== 运行期（委托给既有实现，零侵入） ==========

    async def trigger_build(
        self, project_id: str, build_type: str, trigger: str = "manual", **kwargs
    ) -> Dict[str, Any]:
        from ci_pipeline import ci_pipeline
        valid = {"develop_build", "master_build", "deploy"}
        if build_type not in valid:
            return {
                "error": f"Web 策略不支持构建类型 {build_type}；可选: {sorted(valid)}",
            }
        return await ci_pipeline.trigger_build(project_id, build_type, trigger=trigger)

    async def deploy_environment(
        self, project_id: str, env_name: str, **kwargs
    ) -> Dict[str, Any]:
        from agents.deploy import DeployAgent
        if env_name not in ("dev", "test", "prod"):
            return {"error": f"Web 策略不支持环境 {env_name}"}
        url = await DeployAgent.deploy_env(project_id, env_name, branch=kwargs.get("branch"))
        if url:
            return {"status": "ok", "url": url, "env_name": env_name}
        return {"status": "error", "message": f"{env_name} 部署失败", "env_name": env_name}

    async def stop_environment(
        self, project_id: str, env_name: str
    ) -> Dict[str, Any]:
        from agents.deploy import DeployAgent
        if env_name not in ("dev", "test", "prod"):
            return {"error": f"Web 策略不支持环境 {env_name}"}
        await DeployAgent.stop_env(project_id, env_name)
        return {"status": "ok", "env_name": env_name}

    async def get_environment_status(
        self, project_id: str, env_name: str
    ) -> Dict[str, Any]:
        # 委托到 get_all_environments 里的 map
        envs = await self.get_all_environments(project_id)
        for e in envs:
            if e.get("name") == env_name or e.get("env_type") == env_name:
                return e
        return {"status": "not_found", "name": env_name}

    async def get_all_environments(self, project_id: str) -> List[Dict[str, Any]]:
        """直接调 api/projects.py 里的 get_project_environments 复用所有一致性逻辑"""
        from api.projects import get_project_environments
        resp = await get_project_environments(project_id)
        envs = resp.get("environments", []) if isinstance(resp, dict) else []
        # 把 spec.name / spec.display_name / icon 附加上（环境卡片前端要）
        spec_map = {s.name: s for s in self.environment_specs()}
        out = []
        for e in envs:
            et = e.get("env_type")
            spec = spec_map.get(et)
            merged = dict(e)
            merged["name"] = et
            if spec:
                merged.setdefault("display_name", spec.display_name)
                merged.setdefault("icon", spec.icon)
                merged.setdefault("description", spec.description)
                merged.setdefault("branch_binding", spec.branch_binding)
                merged.setdefault("can_deploy", spec.can_deploy)
                merged.setdefault("can_stop", spec.can_stop)
            out.append(merged)
        return out
