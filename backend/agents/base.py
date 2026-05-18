"""
AI 自动开发系统 - Agent 基类 (Role)
Agent = Role + Actions + State Machine
移植 MetaGPT 的 Role 状态机：支持 SINGLE / BY_ORDER / REACT 三种执行模式
"""
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Type, Set
import logging

logger = logging.getLogger("agent.base")


class ReactMode(str, Enum):
    """Agent 执行模式（移植自 MetaGPT RoleReactMode）"""
    SINGLE = "single"         # 单步执行（orchestrator 指定 action）
    BY_ORDER = "by_order"     # 按顺序执行所有 Action
    REACT = "react"           # LLM 动态选择下一步（未来扩展）


class BaseAgent(ABC):
    """Agent 基类 (Role) — 持有 Action 列表 + 状态机 + Watch 过滤

    三种执行模式:
    - SINGLE: orchestrator 指定执行哪个 action（默认，向后兼容）
    - BY_ORDER: 按 action_classes 顺序依次执行所有 action
    - REACT: LLM 动态决定下一步（预留接口）
    """

    # 子类声明
    action_classes: List[Type] = []
    react_mode: ReactMode = ReactMode.SINGLE
    watch_actions: Set[str] = set()  # 关心的上游 Action（用于消息过滤）
    max_react_loop: int = 5

    # v0.17 trait-first：Agent 可用性按项目 traits 过滤
    # None = 对所有项目可用（现有 6 个 Role Agent 保持不变）
    # 例：ArtistAgent.available_for_traits = {"any_of": ["category:game"]}
    # orchestrator.get_agents_for_project(project_id) 用此字段过滤
    available_for_traits: Dict[str, Any] = None

    def __init__(self):
        self._actions = {}
        for cls in self.action_classes:
            action = cls()
            self._actions[action.name] = action
        self._state: int = -1  # 当前 Action 索引（BY_ORDER 模式用）

        # Skills / Rules 注入：__init__ 时用无 traits 的默认版本（作为兜底）
        # 真正 action 执行时会在 run_action / _react_* 里按 context.project_id
        # 查 project.traits 动态重算（v0.17 Trait-First）。
        # ChatAssistantAgent 仍直接读 self._skills_prompt（无项目上下文）。
        try:
            from skills import skill_loader
            self._skills_prompt = skill_loader.build_prompt_for_agent(self.agent_type)
        except Exception as e:
            logger.warning("Skills 加载失败（Agent=%s）: %s", self.agent_type, e)
            self._skills_prompt = ""

    @property
    @abstractmethod
    def agent_type(self) -> str:
        pass

    @classmethod
    def is_available_for_traits(cls, traits: List[str] = None) -> bool:
        """v0.17: 本 Agent 类是否可用于给定 project traits。
        None / 空 available_for_traits → 永远可用（现有 6 个 Role 保持）。
        """
        from actions.base import _match_traits
        return _match_traits(cls.available_for_traits, set(traits or []))

    async def execute(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """根据 react_mode 分发执行"""
        if self.react_mode == ReactMode.SINGLE:
            # 单步：orchestrator 指定 action
            if self.has_action(task_name):
                return await self.run_action(task_name, context)
            # 兼容旧模式：子类自己实现 execute
            return await self._execute_legacy(task_name, context)

        elif self.react_mode == ReactMode.BY_ORDER:
            return await self._react_by_order(task_name, context)

        elif self.react_mode == ReactMode.REACT:
            return await self._react_with_think(task_name, context)

        return {"status": "error", "message": f"未知 react_mode: {self.react_mode}"}

    async def _execute_legacy(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """旧模式兼容：子类没有用 Action 组合时的 fallback"""
        return {"status": "error", "message": f"Agent {self.agent_type} 没有 Action: {task_name}"}

    async def _resolve_skills_prompt(self, context: Dict[str, Any]) -> str:
        """v0.17: 根据 context.project_id 拉项目 traits，动态计算 skills prompt。
        无 project_id 或查 traits 失败 → 退回 __init__ 时算好的静态版（兜底）。
        """
        project_id = context.get("project_id")
        if not project_id:
            return self._skills_prompt

        try:
            from database import db
            import json as _json
            row = await db.fetch_one("SELECT traits FROM projects WHERE id = ?", (project_id,))
            if not row:
                return self._skills_prompt
            traits_raw = row.get("traits") or "[]"
            traits = _json.loads(traits_raw) if isinstance(traits_raw, str) else traits_raw
            if not isinstance(traits, list):
                traits = []
            from skills import skill_loader
            return skill_loader.build_prompt_for_agent(self.agent_type, traits=traits)
        except Exception as e:
            logger.warning("动态计算 skills 失败（Agent=%s, project=%s）: %s", self.agent_type, project_id, e)
            return self._skills_prompt

    async def run_action(self, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """执行指定 Action（含 v0.17 动态 Skills 注入 + Pre/Post Hooks）

        通过 ContextVar 在 action.run() 期间提供 skills_prompt，
        ActionNode._compile() 读取后自动 prepend 到 LLM prompt 开头。
        ChatAssistant 不走 ActionNode，自己在 _build_system_prompt() 里直接读 self._skills_prompt。
        """
        action = self._actions.get(action_name)
        if not action:
            return {"status": "error", "message": f"Agent {self.agent_type} 没有 Action: {action_name}"}

        from skills import _current_skills
        from actions.executor import run_action_with_hooks
        skills_prompt = await self._resolve_skills_prompt(context)
        token = _current_skills.set(skills_prompt)
        try:
            result = await run_action_with_hooks(
                action,
                context,
                project_id=context.get("project_id"),
                ticket_id=context.get("ticket_id"),
                agent_type=self.agent_type,
            )
        finally:
            _current_skills.reset(token)
        return result.to_dict()

    async def _react_by_order(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """BY_ORDER 模式：按顺序执行所有 Action，前一步输出注入后一步"""
        from skills import _current_skills
        skills_prompt = await self._resolve_skills_prompt(context)
        token = _current_skills.set(skills_prompt)
        try:
            return await self._react_by_order_inner(task_name, context)
        finally:
            _current_skills.reset(token)

    async def _react_by_order_inner(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        result = {}
        action_names = list(self._actions.keys())
        logger.info("🔄 %s BY_ORDER: %s", self.agent_type, " → ".join(action_names))

        for i, action_name in enumerate(action_names):
            action = self._actions[action_name]
            logger.info("  [%d/%d] %s.%s", i + 1, len(action_names), self.agent_type, action_name)

            action_result = await action.run(context)
            step_dict = action_result.to_dict()

            # 合并文件（累积，不覆盖）
            if action_result.files:
                result.setdefault("files", {}).update(action_result.files)

            # 合并其他字段（排除 files，防止覆盖已累积的文件）
            step_files = step_dict.pop("files", None)
            result.update(step_dict)
            # 把累积的 files 放回
            if "files" not in result and step_files:
                result["files"] = step_files

            # 前一步输出注入后一步上下文
            context.update(action_result.data)
            if action_result.files:
                context["_files"] = {**context.get("_files", {}), **action_result.files}

        result["status"] = result.get("status", "success")
        return result

    def get_tool_schemas(self) -> List[Dict]:
        """返回所有 Action 的 Anthropic tool_use schema（供 QueryEngine / REACT 模式使用）。
        优先用 Action 自身的 tool_schema()（如 Chat Action）；
        否则自动生成简化 schema（Orchestrator Action 无需重写）。
        """
        schemas = []
        for name, action in self._actions.items():
            if hasattr(action, "tool_schema"):
                schemas.append(action.tool_schema())
            else:
                # 自动生成简化 schema
                schemas.append({
                    "name": name,
                    "description": action.description or f"执行 {name}",
                    "input_schema": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                })
        # 加一个 done 工具，让 LLM 可以主动结束循环
        schemas.append({
            "name": "done",
            "description": "任务已完成，退出循环",
            "input_schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "完成摘要（可选）"},
                },
                "required": [],
            },
        })
        return schemas

    async def _react_with_think(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """REACT 模式：LLM 动态选择下一步 Action（内部使用 QueryEngine）"""
        from skills import _current_skills
        skills_prompt = await self._resolve_skills_prompt(context)
        token = _current_skills.set(skills_prompt)
        try:
            return await self._react_with_think_inner(task_name, context)
        finally:
            _current_skills.reset(token)

    async def _react_with_think_inner(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """REACT 模式核心循环：使用 QueryEngine + tool_use 格式（替代旧文本协议）。"""
        from llm_client import llm_client
        from query_engine import QueryEngine, Budget
        from query_engine.events import (
            MessageDoneEvent, BudgetExceededEvent, ToolDoneEvent, ErrorEvent,
        )
        from query_engine.executor import OrchestratorToolExecutorAdapter
        from config import settings as _cfg
        from hooks.registry import hook_registry

        tools = self.get_tool_schemas()
        executor = OrchestratorToolExecutorAdapter(self._actions, context)
        budget = Budget(
            max_tokens=_cfg.AGENT_MAX_TOKENS,
            max_turns=_cfg.AGENT_MAX_TURNS,
            max_seconds=_cfg.AGENT_MAX_SECONDS,
        )
        engine = QueryEngine(
            llm_client=llm_client,
            tool_executor=executor,
            budget=budget,
            hooks=hook_registry,
            max_rounds=self.max_react_loop,
        )

        # 构建初始消息
        action_names = list(self._actions.keys())
        system = (
            f"你是 {self.agent_type}，当前任务：{context.get('ticket_title', task_name)}\n"
            f"可用工具：{', '.join(action_names)}，以及 done（完成时调用）\n"
            f"请依次调用合适的工具完成任务，所有步骤完成后调用 done。"
        )
        messages = [{"role": "user", "content": f"请执行任务：{task_name}"}]

        result = {}
        logger.info("🧠 %s REACT（QueryEngine 路径）: task=%s", self.agent_type, task_name)

        async for event in engine.run(messages, system, tools, context):
            if isinstance(event, ToolDoneEvent):
                logger.info("🔧 %s REACT: %s 完成 (%dms)", self.agent_type, event.tool, event.duration_ms)
            elif isinstance(event, MessageDoneEvent):
                result = {
                    "status": "success",
                    "message": event.full_text,
                    "thinking_steps": event.thinking_steps,
                    "rounds": event.rounds,
                }
            elif isinstance(event, BudgetExceededEvent):
                logger.warning("🧠 %s REACT 预算超限: %s", self.agent_type, event.reason)
                result = {"status": "budget_exceeded", "reason": event.reason}
            elif isinstance(event, ErrorEvent):
                result = {"status": "error", "message": event.message}

        return result or {"status": "success"}

    async def _think(self, context: Dict, action_names: list, current_result: Dict) -> str:
        """LLM 决定下一步执行哪个 Action"""
        from llm_client import llm_client

        actions_desc = "\n".join(f"  {i}. {name} — {self._actions[name].description}" for i, name in enumerate(action_names))
        done_actions = [k for k in current_result.keys() if k in action_names]

        prompt = f"""你是 {self.agent_type}，当前任务: {context.get('ticket_title', '')}

可用 Actions:
{actions_desc}
  {len(action_names)}. done — 任务完成，不再执行

已完成的步骤: {done_actions or '无'}
当前产出: {list(current_result.get('files', {}).keys()) or '无文件'}

请选择下一步要执行的 Action（只输出名称，如 "write_code" 或 "done"）:"""

        try:
            resp = await llm_client.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.1, max_tokens=50,
            )
            choice = resp.strip().lower().strip('"').strip("'")
            # 清理 LLM 输出
            for name in action_names + ["done"]:
                if name in choice:
                    return name
            return "done"
        except Exception:
            return "done"

    # ==================== 查询接口 ====================

    def list_actions(self) -> List[str]:
        return list(self._actions.keys())

    def has_action(self, name: str) -> bool:
        return name in self._actions

    def is_watch(self, cause_by: str) -> bool:
        """检查是否关心某个 Action 的输出"""
        if not self.watch_actions:
            return True  # 未声明 watch = 关心所有
        return cause_by in self.watch_actions

    @property
    def important_memory(self):
        """获取自己关心的记忆（需要外部设置 _memory）"""
        mem = getattr(self, "_memory", None)
        if mem and self.watch_actions:
            return mem.get_by_actions(self.watch_actions)
        return []

    # ========== A-2: 下沉到 BaseAgent 的公共能力 ==========

    async def compact_history(self, messages: list) -> str:
        """A-2: LLM 对话历史压缩（原 ChatAssistantAgent._compact_history_with_llm）
        所有 Agent 均可调用，将旧消息压缩为一条摘要。
        """
        if not messages:
            return ""
        try:
            from llm_client import llm_client
            lines = []
            for m in messages[-30:]:
                role = m.get("role", "?")
                content = m.get("content", "")
                if isinstance(content, list):
                    content = " ".join(
                        b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                if isinstance(content, str) and content.strip():
                    prefix = "用户" if role == "user" else "AI助手"
                    lines.append(f"{prefix}：{content[:300]}")
            if not lines:
                return ""
            conv_text = "\n".join(lines)
            summary_prompt = (
                "请将以下对话历史压缩为简洁摘要，保留关键信息：\n"
                "- 用户提出的需求和问题\n- AI 做出的重要决策和操作\n"
                "- 创建/修改的需求、工单、文档等\n- 重要的技术方案和结论\n\n"
                f"对话历史：\n{conv_text}\n\n请用中文，200字以内。"
            )
            summary = await llm_client.chat(
                [{"role": "user", "content": summary_prompt}],
                max_tokens=300, temperature=0.1,
            )
            if summary and isinstance(summary, str) and len(summary) > 10:
                return f"[之前对话历史摘要]\n{summary.strip()}"
        except Exception as e:
            logger.warning("BaseAgent.compact_history 失败: %s", e)
        return ""

    # A-3: 4 類型標籤映射（對標 Claude Code）
    _MEMORY_TYPE_LABELS = {
        "user_profile":      "👤 用户",
        "behavior_feedback": "💬 反馈",
        "project_context":   "📁 项目",
        "external_ref":      "🔗 外部",
        # 向後兼容舊類型
        "user":      "👤 用户",
        "project":   "📁 项目",
        "technical": "📁 项目",
        "decision":  "📁 项目",
        "handoff":   "📁 项目",
        "insight":   "💬 反馈",
        "project_status": "📁 项目",
    }

    async def get_memory_prompt(self, project_id: str, limit: int = 5) -> str:
        """A-3: 查询 agent_memory，以 MEMORY.md 索引樣式返回注入文本。
        支持 4 類型（user_profile/behavior_feedback/project_context/external_ref）。
        所有 Agent 均可調用。
        """
        if not project_id:
            return ""
        try:
            from database import db
            rows = await db.fetch_all(
                """SELECT type, title, content, created_at FROM agent_memory
                   WHERE project_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (project_id, limit),
            )
            if not rows:
                return ""
            lines = ["## 项目记忆（MEMORY）\n"]
            for r in rows:
                label = self._MEMORY_TYPE_LABELS.get(r["type"], "📝")
                lines.append(f"- [{label}] **{r['title']}**（{r['created_at'][:10]}）")
                if r["content"] and r["content"].strip():
                    lines.append(f"  {r['content'][:120].strip()}")
            lines.append("\n如需完整记忆请调用 get_memory 工具。")
            return "\n".join(lines)
        except Exception as e:
            logger.debug("BaseAgent.get_memory_prompt 失败: %s", e)
            return ""
