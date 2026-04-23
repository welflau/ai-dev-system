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
        """执行指定 Action（含 v0.17 动态 Skills 注入）

        通过 ContextVar 在 action.run() 期间提供 skills_prompt，
        ActionNode._compile() 读取后自动 prepend 到 LLM prompt 开头。
        ChatAssistant 不走 ActionNode，自己在 _build_system_prompt() 里直接读 self._skills_prompt。
        """
        action = self._actions.get(action_name)
        if not action:
            return {"status": "error", "message": f"Agent {self.agent_type} 没有 Action: {action_name}"}

        from skills import _current_skills
        skills_prompt = await self._resolve_skills_prompt(context)
        token = _current_skills.set(skills_prompt)
        try:
            result = await action.run(context)
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

    async def _react_with_think(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """REACT 模式：LLM 动态选择下一步 Action"""
        from skills import _current_skills
        skills_prompt = await self._resolve_skills_prompt(context)
        token = _current_skills.set(skills_prompt)
        try:
            return await self._react_with_think_inner(task_name, context)
        finally:
            _current_skills.reset(token)

    async def _react_with_think_inner(self, task_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        from llm_client import llm_client

        result = {}
        action_names = list(self._actions.keys())

        for i in range(self.max_react_loop):
            # Think: LLM 决定下一步
            next_action = await self._think(context, action_names, result)
            if not next_action or next_action == "done":
                logger.info("🧠 %s REACT: 第 %d 轮结束 (action=%s)", self.agent_type, i + 1, next_action)
                break

            if next_action not in self._actions:
                logger.warning("🧠 %s REACT: 无效 Action '%s'，跳过", self.agent_type, next_action)
                continue

            # Act: 执行选中的 Action
            logger.info("🧠 %s REACT [%d/%d]: %s", self.agent_type, i + 1, self.max_react_loop, next_action)
            action_result = await self._actions[next_action].run(context)
            step_dict = action_result.to_dict()

            # 合并
            if action_result.files:
                result.setdefault("files", {}).update(action_result.files)
            step_files = step_dict.pop("files", None)
            result.update(step_dict)
            if "files" not in result and step_files:
                result["files"] = step_files

            context.update(action_result.data)
            if action_result.files:
                context["_files"] = {**context.get("_files", {}), **action_result.files}

        result["status"] = result.get("status", "success")
        return result

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
