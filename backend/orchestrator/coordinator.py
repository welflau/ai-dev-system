"""
协调器（Orchestrator）
核心调度中心，接收需求 -> 分解任务 -> 分配Agent -> 管理执行

v0.5.0: Agent 间上下文传递 + TestAgent + ProductAgent 接入
"""
import uuid
import os
import json
import logging
from typing import Dict, Any, Optional, List
from models.schemas import Requirement, Task, ProjectPlan
from models.enums import ProjectPhase, TaskStatus, AgentType
from agents import DevAgent, ArchitectAgent, TestAgent
from .decomposer import TaskDecomposer
from .state_manager import StateManager

logger = logging.getLogger(__name__)


class ProductAgentAdapter:
    """
    ProductAgent 适配器

    原始 ProductAgent 使用 async + Pydantic 模型接口，
    此适配器将其包装为同步的 execute(task_name, context) 接口，
    与 DevAgent / ArchitectAgent / TestAgent 保持统一。

    功能：根据需求生成 PRD 文档和项目分析
    """

    def __init__(self, work_dir: str = "projects", llm_client=None):
        self.agent_type = AgentType.PRODUCT
        self.work_dir = work_dir
        self.llm_client = llm_client

    @property
    def _llm_available(self) -> bool:
        return self.llm_client is not None and self.llm_client.enabled

    def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行需求分析任务

        Args:
            task_name: 任务名称
            context: 包含 project_id, requirement, project_name 等

        Returns:
            包含 success, files_created, output 的结果
        """
        project_id = context.get("project_id", "unknown")
        requirement = context.get("requirement", "")
        project_name = context.get("project_name", "项目")
        project_dir = os.path.join(self.work_dir, project_id)

        try:
            # 尝试 LLM 模式生成 PRD
            llm_result = self._llm_analyze(task_name, project_dir, requirement, project_name)
            if llm_result:
                return {
                    "success": True,
                    "agent": self.agent_type.value,
                    "task": task_name,
                    **llm_result,
                }

            # 降级：模板模式生成基础 PRD
            result = self._template_analyze(project_dir, requirement, project_name)
            return {
                "success": True,
                "agent": self.agent_type.value,
                "task": task_name,
                **result,
            }
        except Exception as e:
            return {
                "success": False,
                "agent": self.agent_type.value,
                "task": task_name,
                "error": str(e),
            }

    def _llm_analyze(
        self, task_name: str, project_dir: str, requirement: str, project_name: str
    ) -> Optional[Dict[str, Any]]:
        """LLM 模式：智能需求分析和 PRD 生成"""
        if not self._llm_available:
            return None

        prompt = f"""请作为产品经理，分析以下需求并生成产品需求文档（PRD）：

项目名称：{project_name}
任务：{task_name}
需求描述：{requirement}

请返回严格的 JSON 格式：
{{
  "files": [
    {{
      "path": "docs/PRD.md",
      "content": "完整的 PRD Markdown 内容"
    }}
  ],
  "summary": "一句话描述需求分析结果",
  "features": ["核心功能1", "核心功能2"]
}}"""

        system = """你是一位资深产品经理。
你的职责是分析用户需求，生成清晰完整的 PRD 文档。

PRD 文档应包含：
1. 项目概述
2. 目标用户
3. 核心功能列表
4. 用户故事（至少 3 个）
5. 非功能性需求（性能、安全、可用性）
6. 技术架构建议
7. 里程碑规划

使用中文撰写，Markdown 格式。
你必须返回严格的 JSON 格式（不要包含 markdown 代码块标记）。"""

        try:
            response = self.llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                system=system,
                temperature=0.3,
                max_tokens=8192,
            )
            if not response or response == "[LLM_UNAVAILABLE]":
                return None
            return self._parse_llm_response(response, project_dir)
        except Exception as e:
            logger.warning(f"ProductAgent LLM 分析失败: {e}")
            return None

    def _parse_llm_response(
        self, response: str, project_dir: str
    ) -> Optional[Dict[str, Any]]:
        """解析 LLM JSON 响应并写入文件"""
        text = response.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"ProductAgent LLM 响应 JSON 解析失败: {text[:200]}")
            return None

        files = data.get("files", [])
        if not files:
            return None

        files_created = []
        for f in files:
            path = f.get("path", "")
            content = f.get("content", "")
            if path and content:
                full_path = os.path.join(project_dir, path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "w", encoding="utf-8") as fp:
                    fp.write(content)
                files_created.append(full_path)

        if not files_created:
            return None

        return {
            "files_created": files_created,
            "output": data.get("summary", f"需求分析完成，生成了 {len(files_created)} 个文档"),
            "features": data.get("features", []),
            "mode": "llm",
        }

    def _template_analyze(
        self, project_dir: str, requirement: str, project_name: str
    ) -> Dict[str, Any]:
        """模板模式：生成基础 PRD 文档"""
        files_created = []

        # 简单关键词提取功能点
        features = []
        kw_map = {
            "登录": "用户登录认证",
            "注册": "用户注册",
            "用户": "用户管理模块",
            "API": "RESTful API 接口",
            "数据库": "数据库设计与存储",
            "前端": "前端界面开发",
            "商品": "商品管理模块",
            "订单": "订单处理模块",
            "支付": "支付集成",
            "搜索": "搜索功能",
            "权限": "权限控制系统",
            "通知": "消息通知系统",
        }
        req_lower = requirement.lower()
        for kw, feat in kw_map.items():
            if kw in req_lower:
                features.append(feat)
        if not features:
            features = ["核心业务逻辑", "数据存储", "API 接口"]

        # 生成 PRD.md
        prd_content = f"""# {project_name} - 产品需求文档 (PRD)

> 由 AI 自动开发系统自动生成

## 1. 项目概述

{requirement}

## 2. 目标用户

- 系统管理员
- 普通用户
- 访客

## 3. 核心功能

{chr(10).join(f"- {f}" for f in features)}

## 4. 用户故事

| 编号 | 角色 | 功能 | 价值 |
|------|------|------|------|
| US-01 | 用户 | {features[0] if features else '使用系统'} | 完成日常操作 |
| US-02 | 管理员 | 管理系统配置 | 确保系统正常运行 |
| US-03 | 用户 | 查看操作记录 | 追踪历史操作 |

## 5. 非功能性需求

- **性能**：API 响应时间 < 500ms
- **安全**：支持认证鉴权，数据加密传输
- **可用性**：系统可用性 > 99%
- **可维护性**：代码覆盖率 > 70%

## 6. 技术架构建议

- 后端：Python / FastAPI
- 数据库：SQLite (开发) / PostgreSQL (生产)
- 前端：HTML / CSS / JavaScript
- 部署：Docker + Nginx

## 7. 里程碑

| 阶段 | 内容 | 预估周期 |
|------|------|----------|
| M1 | 需求分析 + 架构设计 | 1 周 |
| M2 | 核心功能开发 | 2 周 |
| M3 | 测试 + 修复 | 1 周 |
| M4 | 部署上线 | 0.5 周 |
"""
        docs_dir = os.path.join(project_dir, "docs")
        os.makedirs(docs_dir, exist_ok=True)
        prd_path = os.path.join(docs_dir, "PRD.md")
        with open(prd_path, "w", encoding="utf-8") as f:
            f.write(prd_content)
        files_created.append(prd_path)

        return {
            "files_created": files_created,
            "output": f"需求分析完成：识别 {len(features)} 个功能模块，生成 PRD 文档",
            "features": features,
            "mode": "template",
        }


class Orchestrator:
    """AI项目协调器"""

    def __init__(
        self,
        state_manager: Optional[StateManager] = None,
        work_dir: str = "projects",
        llm_client=None,
    ):
        self.llm_client = llm_client
        self.decomposer = TaskDecomposer(llm_client=llm_client)
        self.state_manager = state_manager or StateManager()
        self.work_dir = work_dir

        # 项目上下文缓存：project_id -> {阶段输出汇总}
        self._project_context: Dict[str, Dict[str, Any]] = {}

        # 初始化 Agent 池（全部 4 个 Agent 到位）
        self.agents = {
            AgentType.PRODUCT.value: ProductAgentAdapter(work_dir=work_dir, llm_client=llm_client),
            AgentType.DEV.value: DevAgent(work_dir=work_dir, llm_client=llm_client),
            AgentType.ARCHITECT.value: ArchitectAgent(work_dir=work_dir, llm_client=llm_client),
            AgentType.TEST.value: TestAgent(work_dir=work_dir, llm_client=llm_client),
            # review, deploy 暂用占位
        }

    def update_llm_client(self, llm_client):
        """运行时更新 LLM 客户端"""
        self.llm_client = llm_client
        self.decomposer = TaskDecomposer(llm_client=llm_client)
        self.agents[AgentType.PRODUCT.value] = ProductAgentAdapter(
            work_dir=self.work_dir, llm_client=llm_client
        )
        self.agents[AgentType.DEV.value] = DevAgent(
            work_dir=self.work_dir, llm_client=llm_client
        )
        self.agents[AgentType.ARCHITECT.value] = ArchitectAgent(
            work_dir=self.work_dir, llm_client=llm_client
        )
        self.agents[AgentType.TEST.value] = TestAgent(
            work_dir=self.work_dir, llm_client=llm_client
        )

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

    # ------------------------------------------------------------------
    #  上下文管理
    # ------------------------------------------------------------------

    def _collect_completed_outputs(self, project_id: str) -> Dict[str, Any]:
        """
        收集项目中所有已完成任务的输出，按阶段组织

        Returns:
            {
                "design_outputs": [...],   # 架构设计阶段的输出
                "dev_outputs": [...],      # 开发阶段的输出
                "files_created": [...],    # 所有已生成的文件
            }
        """
        if project_id in self._project_context:
            return self._project_context[project_id]

        # 从磁盘收集已生成的文件列表
        project_dir = os.path.join(self.work_dir, project_id)
        existing_files = []
        if os.path.exists(project_dir):
            for root, dirs, files in os.walk(project_dir):
                for fname in files:
                    full_path = os.path.join(root, fname)
                    rel_path = os.path.relpath(full_path, project_dir).replace("\\", "/")
                    existing_files.append(rel_path)

        ctx = {
            "design_outputs": [],
            "dev_outputs": [],
            "test_outputs": [],
            "files_created": existing_files,
        }
        self._project_context[project_id] = ctx
        return ctx

    def _save_task_output(
        self, project_id: str, agent_key: str, task_name: str, result: Dict[str, Any]
    ):
        """将任务执行结果存入项目上下文"""
        ctx = self._collect_completed_outputs(project_id)

        summary = {
            "task": task_name,
            "agent": agent_key,
            "output": result.get("output", ""),
            "files": result.get("files_created", []),
            "mode": result.get("mode", "template"),
        }

        if agent_key == AgentType.ARCHITECT.value:
            ctx["design_outputs"].append(summary)
        elif agent_key == AgentType.DEV.value:
            ctx["dev_outputs"].append(summary)
        elif agent_key == AgentType.TEST.value:
            ctx["test_outputs"].append(summary)

        # 更新文件列表
        for f in result.get("files_created", []):
            fname = os.path.basename(f) if isinstance(f, str) else str(f)
            if fname not in ctx["files_created"]:
                ctx["files_created"].append(fname)

    # ------------------------------------------------------------------
    #  任务执行
    # ------------------------------------------------------------------

    def execute_task(
        self, project_id: str, task_id: str
    ) -> Dict[str, Any]:
        """
        执行指定任务：调用对应 Agent 真正执行

        上下文传递策略：
        - 每个 Agent 执行时都会收到前序 Agent 的输出摘要
        - ArchitectAgent 的设计文档会传给 DevAgent
        - DevAgent 的代码文件会传给 TestAgent

        Args:
            project_id: 项目 ID
            task_id: 任务 ID

        Returns:
            执行结果
        """
        state = self.state_manager.get_project(project_id)
        if not state:
            return {"success": False, "error": "项目不存在"}

        if task_id not in state.tasks:
            return {"success": False, "error": "任务不存在"}

        task = state.tasks[task_id]
        task_name = task.name
        assigned_agent = task.assigned_agent

        # 收集前序 Agent 的输出
        prior_context = self._collect_completed_outputs(project_id)

        # 构建增强执行上下文（包含前序 Agent 输出）
        context = {
            "project_id": project_id,
            "requirement": state.requirements.description if state.requirements else "",
            "project_name": state.requirements.project_name if state.requirements else "未命名",
            "tech_stack": state.requirements.tech_stack if state.requirements else None,
            # --- 上下文传递 ---
            "design_outputs": prior_context.get("design_outputs", []),
            "dev_outputs": prior_context.get("dev_outputs", []),
            "test_outputs": prior_context.get("test_outputs", []),
            "existing_files": prior_context.get("files_created", []),
        }

        # 标记为进行中
        self.update_task(project_id, task_id, TaskStatus.IN_PROGRESS)

        # 找到对应 Agent
        agent_key = assigned_agent if isinstance(assigned_agent, str) else (
            assigned_agent.value if assigned_agent else None
        )
        agent = self.agents.get(agent_key)

        if agent:
            # 真正执行
            try:
                result = agent.execute(task_name, context)
                if result.get("success"):
                    # 保存输出到上下文（供后续 Agent 使用）
                    self._save_task_output(project_id, agent_key, task_name, result)
                    self.update_task(
                        project_id, task_id, TaskStatus.COMPLETED,
                        result=result,
                    )
                    return result
                else:
                    self.update_task(
                        project_id, task_id, TaskStatus.FAILED,
                        error_message=result.get("error", "未知错误"),
                    )
                    return result
            except Exception as e:
                logger.error(f"Agent {agent_key} 执行异常: {e}")
                self.update_task(
                    project_id, task_id, TaskStatus.FAILED,
                    error_message=str(e),
                )
                return {"success": False, "error": str(e)}
        else:
            # 没有对应 Agent，模拟完成
            self.update_task(project_id, task_id, TaskStatus.COMPLETED)
            return {
                "success": True,
                "agent": agent_key or "auto",
                "task": task_name,
                "output": f"任务 '{task_name}' 已完成（Agent {agent_key} 暂未实现，自动标记完成）",
                "files_created": [],
            }

    def execute_next_task(self, project_id: str) -> Dict[str, Any]:
        """
        执行项目的下一个待处理任务

        Returns:
            执行结果
        """
        state = self.state_manager.get_project(project_id)
        if not state:
            return {"success": False, "error": "项目不存在"}

        # 按阶段顺序找下一个 pending 任务
        phase_order = ["requirement", "design", "development", "testing", "deployment"]
        tasks_by_phase = self.state_manager.get_tasks_by_phase(project_id)

        for phase in phase_order:
            tasks = tasks_by_phase.get(phase, [])
            for task_info in tasks:
                if task_info["status"] == "pending":
                    return self.execute_task(project_id, task_info["id"])

        return {
            "success": True,
            "output": "所有任务已完成！",
            "files_created": [],
        }
