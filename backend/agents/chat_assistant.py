"""
ChatAssistantAgent — AI 助手对话 Agent（P2 引入，双轨运行阶段）

继承 BaseAgent，但不走标准 execute(task_name, context) 入口，
新增 chat() 作为对话专用入口，返回 {"reply": ..., "action": ...} 对齐 ChatResponse。

与旧 chat.py 路径的区别：
- 用 llm_client.chat_with_tools（Anthropic 原生 tool_use）替代 [ACTION:XXX] 文本协议
- 能力来源：self._actions + 每个 Action 的 tool_schema（LLM 看得到的工具集）
- create_requirement 不暴露给 LLM —— LLM 只能调 confirm_requirement 产草稿

feature flag: settings.CHAT_USE_AGENT 控制双轨
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent, ReactMode
from actions.chat.confirm_requirement import ConfirmRequirementAction, ConfirmRequirementsBatchAction
from actions.chat.confirm_bug import ConfirmBugAction
from actions.chat.confirm_project import ConfirmProjectAction
from actions.chat.create_requirement import CreateRequirementAction
from actions.chat.pause_requirement import PauseRequirementAction, PauseRequirementsBatchAction
from actions.chat.resume_requirement import ResumeRequirementAction
from actions.chat.close_requirement import CloseRequirementAction
from actions.chat.generate_document import GenerateDocumentAction
from actions.chat.git_log import GitLogAction
from actions.chat.git_list_branches import GitListBranchesAction
from actions.chat.git_switch_branch import GitSwitchBranchAction
from actions.chat.git_read_file import GitReadFileAction
from actions.chat.git_merge import GitMergeAction
from actions.chat.get_requirement_pipeline import GetRequirementPipelineAction
from actions.chat.get_ticket_status import GetTicketStatusAction
from actions.chat.get_requirement_logs import GetRequirementLogsAction
from actions.chat.propose_ue_framework import ProposeUEFrameworkAction
from actions.chat.get_build_logs import GetBuildLogsAction     # v0.19.x 构建日志查询
from actions.chat.search_knowledge import SearchKnowledgeAction        # 知识库全文搜索
from actions.chat.search_ticket_history import SearchTicketHistoryAction  # 历史工单检索
from actions.chat.fetch_url import FetchUrlAction                         # 访问外部 URL
from actions.chat.confirm_save_doc import ConfirmSaveDocAction            # 保存对话内容为项目文档
from actions.chat.load_skill import LoadSkillAction                        # v0.20 主动触发 Skill
from actions.chat.get_memory import GetMemoryAction                       # 查询 Agent Memory
from actions.chat.competitor_analysis import CompetitorAnalysisAction     # 竞品反拆
from actions.chat.read_local_file import ReadLocalFileAction               # 读本地文件（Skill 文档等）
from actions.chat.ue_call import UECallAction                              # UE Editor UCP 控制
from actions.ue_run_python import UERunPythonAction                        # B-0 UE Python 橋接
from actions.ue_blueprint_gen import BlueprintGenAction                    # B-1 Blueprint 生成
from actions.ue_level_gen import LevelGenAction                            # B-2 關卡生成
from actions.chat.install_project_skill import InstallProjectSkillAction   # 项目 Skill 安装/卸载
from actions.chat.browse_marketplace import BrowseMarketplaceAction        # 浏览/安装/卸载市场 Skill
from actions.chat.glob_search import GlobAction, GrepAction, ListDirectoryAction  # 文件系统搜索
from actions.chat.web_search import WebSearchAction                        # 联网搜索
from actions.chat.shell_exec import ShellAction                            # Shell 执行
from actions.chat.memory_write import MemoryWriteAction                    # 写入记忆
from actions.chat.read_many_files import ReadManyFilesAction               # 批量读文件
from actions.chat.dispatch_subtask import DispatchSubtaskAction, DispatchParallelSubtasksAction  # 子任务派发（L8）
from actions.chat.manage_skill import ManageSkillAction                    # Skill 开关管理
from actions.chat.set_session_flag import SetSessionFlagAction, get_session_flag  # L9 Feature Flags
from actions.chat.create_github_repo import CreateGithubRepoAction         # GitHub 建仓库

logger = logging.getLogger("agent.chat_assistant")


def _resolve_thinking_enabled(session_id: str, model_id: str) -> bool:
    """A-2: 三態 thinking 解析
    - thinking_mode=adaptive → 模型支持才開啟（默認）
    - thinking_mode=on       → 強制開啟（模型不支持時降級）
    - thinking_mode=off      → 強制關閉
    """
    from llm_client import _model_supports_thinking
    mode = (get_session_flag(session_id, "thinking_mode") or "adaptive").lower()
    if mode == "off":
        return False
    if mode == "on":
        return True   # 強制開啟，不判斷模型支持
    # adaptive（默認）
    return _model_supports_thinking(model_id)


# 不对 LLM 暴露为 tool 的 Action 名（只能由后端内部调用）
_INTERNAL_ONLY_ACTIONS = {"create_requirement"}

# 工具显示名（流式端点用，与前端 _TOOL_LABELS 保持一致）
_TOOL_LABELS_PY: dict = {
    "search_knowledge": "🔍 搜索知识库",
    "search_ticket_history": "🗂 检索历史工单",
    "fetch_url": "🌐 访问链接",
    "git_log": "📜 查提交历史",
    "git_read_file": "📄 读取文件",
    "git_list_branches": "🌿 列出分支",
    "git_switch_branch": "🔀 切换分支",
    "git_merge": "🔀 合并分支",
    "generate_document": "📝 生成文档",
    "confirm_save_doc": "💾 准备保存文档",
    "confirm_requirement": "📋 识别需求",
    "confirm_requirements_batch": "📋 识别多个需求",
    "confirm_bug": "🐛 识别 BUG",
    "confirm_project": "🏗 识别新建项目",
    "close_requirement": "🚫 关闭需求",
    "pause_requirement": "⏸ 暂停需求",
    "resume_requirement": "▶ 恢复需求",
    "get_requirement_pipeline": "🔍 查需求进度",
    "get_ticket_status": "📊 查工单状态",
    "get_requirement_logs": "📋 查工单日志",
    "get_build_logs": "🔧 查构建日志",
    "get_memory": "🧠 查 Agent 记忆",
    "competitor_analysis": "🔎 竞品分析",
    "load_skill": "📚 加载 Skill",
    "read_local_file": "📂 读取本地文件",
    "ue_call": "🎮 UE Editor 操作",
    "ue_run_python": "🐍 UE Python 執行",
    "ue_blueprint_gen": "🔷 生成 Blueprint",
    "ue_level_gen":     "🗺 生成關卡布局",
    # 新增工具（对标 Gemini CLI）
    "glob": "🔍 查找文件",
    "grep": "🔎 搜索文件内容",
    "list_directory": "📁 列出目录",
    "shell": "⚡ 执行命令",
    "web_search": "🌐 联网搜索",
    "save_memory": "💡 保存记忆",
    "read_files": "📄 批量读文件",
    "browse_marketplace": "🛒 浏览技能市场",
    "install_project_skill": "📦 安装 Skill",
    "manage_skill": "🔧 管理 Skill",
    "create_github_repo": "🐙 创建 GitHub 仓库",
    "set_session_flag": "🎛 调整 AI 行为设置",
    "dispatch_subtask": "📦 派发子任务",
    "dispatch_parallel_subtasks": "⚡ 并行派发子任务",
}

# 全局聊天下额外可用（仅在全局模式有意义）
_GLOBAL_ONLY_TOOLS = {"confirm_project"}

# 需要 project_id 才能运行、全局模式下无意义的工具（即使暴露也会报错，直接隐藏）
_PROJECT_ONLY_TOOLS = {
    "confirm_requirement", "confirm_requirements_batch", "confirm_bug",
    "close_requirement", "pause_requirement", "resume_requirement",
    "get_requirement_pipeline", "get_ticket_status", "get_requirement_logs",
    "get_build_logs", "generate_document", "confirm_save_doc",
    "git_log", "git_read_file", "git_list_branches",
    "git_switch_branch", "git_merge",
    "dispatch_subtask", "dispatch_parallel_subtasks",
    "competitor_analysis",
}

# _CROSS_SCOPE_TOOLS 保留用于向后兼容，全局模式现在直接用"全量 - PROJECT_ONLY"
_CROSS_SCOPE_TOOLS = set()  # 不再需要，逻辑移入 _exposed_tool_schemas


class _ChatToolExecutor:
    """
    chat_with_tools 协议要求的 tool_executor：async execute(name, input) -> str
    负责：
    1. 往 Action 的 context 里注入 project_id（LLM 看不到的环境变量）
    2. 跟踪"最值得展示"的 Action 执行结果 → 用于填充 ChatResponse.action

    关于 primary_action_result 的优先级：
    当 LLM 在一轮里链式调多个工具时（如 close + confirm_requirement），
    前端只能展示一个 action 卡片。需要把最重要的那个留下：
      Tier 1（需用户交互）: confirm_requirement / confirm_bug
      Tier 2（产出物展示）: document_generated / requirement_pipeline / ticket_status / requirement_logs
      Tier 3（状态变更回执）: requirement_closed / requirement_paused / requirement_resumed / requirement_created
      Tier 4（查询结果）: git_result / error
    数字越小优先级越高；同级取最后一次调用（因为更接近"最终状态"）。
    """

    _TYPE_PRIORITY = {
        # Tier 1 — 需要用户点击确认，必须让前端渲染
        "confirm_requirement": 1,
        "confirm_requirements_batch": 1,
        "confirm_bug": 1,
        "confirm_project": 1,
        "propose_ue_framework": 1,   # v0.18 A.6
        # Tier 2 — 重要产出物 / 诊断视图
        "document_generated": 2,
        "requirement_pipeline": 2,
        "ticket_status": 2,
        "requirement_logs": 2,
        "build_logs": 2,               # v0.19.x — 构建/编译日志诊断
        # Tier 3 — 状态变更的回执
        "requirement_closed": 3,
        "requirement_paused": 3,
        "requirement_resumed": 3,
        "requirement_created": 3,
        "project_created": 3,
        # Tier 4 — 普通查询结果
        "git_result": 4,
        "error": 5,
    }

    # 需要收集全量结果的类型（用户需要逐条确认）
    _COLLECT_ALL_TYPES = {"confirm_requirement", "confirm_requirements_batch", "confirm_bug"}

    def __init__(self, agent: "ChatAssistantAgent", project_id: Optional[str] = None, session_id: Optional[str] = None):
        """project_id=None 表示全局聊天场景（项目列表页），此时 ctx 里不注入 project_id"""
        self.agent = agent
        self.project_id = project_id
        self.session_id = session_id   # 全局聊天思考日志 SSE session
        self.primary_action_result: Optional[Dict[str, Any]] = None
        self._primary_tier: int = 99  # 越小越优先
        # 批量收集：confirm_requirement / confirm_bug 每次调用都保留，供前端渲染多张卡片
        self.all_confirm_results: List[Dict[str, Any]] = []
        # 思考步骤：done 阶段的步骤列表，保存到 DB 后刷新可恢复
        self.thinking_steps: List[Dict[str, Any]] = []

    # 向后兼容：保留 first_action_result 的读属性
    @property
    def first_action_result(self) -> Optional[Dict[str, Any]]:
        return self.primary_action_result

    async def execute(self, tool_name: str, tool_input: Any) -> str:
        # MCP 外部工具（以 "mcp__<server>__" 开头）：分发给 MCP 客户端
        if tool_name.startswith("mcp__"):
            try:
                from mcp_client import mcp_client
                return await mcp_client.call_tool(tool_name, tool_input if isinstance(tool_input, dict) else {})
            except Exception as e:
                logger.warning("MCP 工具调用异常 (%s): %s", tool_name, e)
                return json.dumps({"error": f"MCP 调用失败: {e}"}, ensure_ascii=False)

        action = self.agent._actions.get(tool_name)
        if not action:
            return f"未知工具: {tool_name}"
        if tool_name in _INTERNAL_ONLY_ACTIONS:
            return f"工具 {tool_name} 不允许直接调用"

        # Anthropic 对 required=[] 的无参工具偶尔返回 tool_input=[] 而非 {}，兼容一下
        if not isinstance(tool_input, dict):
            logger.warning(
                "tool_input 非 dict（LLM 返回 %s），自动转为 {}。tool=%s",
                type(tool_input).__name__, tool_name,
            )
            tool_input = {}

        # 全局聊天时 project_id=None：不注入到 ctx（confirm_project 等全局工具用不到）
        ctx = dict(tool_input)
        if self.project_id is not None:
            ctx["project_id"] = self.project_id
        # 注入 session_id（供 SetSessionFlagAction 等工具读取）
        if self.session_id is not None:
            ctx["session_id"] = self.session_id

        # 推 SSE 思考日志（start 阶段：有 project_id 或 session_id 才发，否则只记录）
        await self._emit_thinking(tool_name, tool_input, step="start")

        result = await action.run(ctx)
        data = result.data or {}

        # 優先 message，web_search_result 有 0 結果時顯示 query
        if data.get("type") == "web_search_result":
            results = data.get("results") or []
            query   = data.get("query", "")
            if results:
                first = (results[0].get("title") or "")[:30]
                summary = f"{len(results)} 条结果 · {first}" if first else f"{len(results)} 条结果"
            else:
                summary = f"未找到结果 · {query[:40]}"
        else:
            summary = result.message or data.get("message") or ("成功" if result.success else result.error or "失败")
        await self._emit_thinking(tool_name, tool_input, step="done", summary=summary)

        # 按优先级更新 primary_action_result
        current_type = data.get("type", "")
        current_tier = self._TYPE_PRIORITY.get(current_type, 50)
        if current_tier <= self._primary_tier:
            self.primary_action_result = data
            self._primary_tier = current_tier

        # 批量收集：confirm_requirement / confirm_bug 每次调用都追加
        if current_type in self._COLLECT_ALL_TYPES:
            self.all_confirm_results.append(data)

        # 返回给 LLM 的是 JSON 字符串（chat_with_tools 规范）
        return json.dumps(data, ensure_ascii=False)

    async def _emit_thinking(self, tool_name: str, tool_input: dict, step: str, summary: str = "") -> None:
        """推送/记录思考日志。
        - thinking_steps 收集：始终执行（所有聊天模式，用于持久化）
        - SSE 推送：仅在有 project_id 或 session_id 时执行
        """
        try:
            _KEY = {
                "search_knowledge": "query", "search_ticket_history": "query",
                "fetch_url": "url", "git_read_file": "path",
                "get_requirement_pipeline": "requirement_id",
                "get_ticket_status": "ticket_id", "get_requirement_logs": "requirement_id",
                "git_log": "branch", "git_switch_branch": "branch",
                "generate_document": "filename", "confirm_save_doc": "filename",
                "confirm_requirement": "title", "confirm_bug": "title",
                "load_skill": "skill_id", "read_local_file": "path", "ue_call": "command",
                "glob": "pattern", "grep": "pattern", "list_directory": "path",
                "shell": "command", "web_search": "query",
                "save_memory": "title", "read_files": "paths",
                "browse_marketplace": "dir_name", "install_project_skill": "dir_name",
                "manage_skill": "action",
                "set_session_flag": "flag",
                "dispatch_subtask": "title",
                "dispatch_parallel_subtasks": "subtasks",
            }
            key = _KEY.get(tool_name)
            arg_val = str(tool_input.get(key, ""))[:60] if key else ""
            args_hint = f"({key}: {arg_val})" if arg_val else ""
            payload = {"step": step, "tool": tool_name, "args_hint": args_hint, "summary": summary[:120]}

            # 持久化收集：始终执行（done 阶段），不依赖 project_id/session_id
            if step == "done":
                self.thinking_steps.append({
                    "tool": tool_name,
                    "args_hint": args_hint,
                    "summary": summary[:120],
                })

            # SSE 推送：仅在有上下文时执行
            if self.project_id or self.session_id:
                from events import event_manager
                if self.project_id:
                    await event_manager.publish_to_project(self.project_id, "chat_thinking_log", payload)
                elif self.session_id:
                    from api.chat import get_thinking_queue
                    await get_thinking_queue(self.session_id).put(payload)
        except Exception as e:
            logger.warning("_emit_thinking failed: %s", e)


class ChatAssistantAgent(BaseAgent):

    action_classes = [
        ConfirmRequirementAction,
        ConfirmRequirementsBatchAction,
        ConfirmBugAction,
        ConfirmProjectAction,          # 全局聊天用，暴露给 LLM
        CreateRequirementAction,       # 内部用，不暴露给 LLM
        PauseRequirementAction,
        PauseRequirementsBatchAction,
        ResumeRequirementAction,
        CloseRequirementAction,
        GenerateDocumentAction,
        GitLogAction,
        GitListBranchesAction,
        GitSwitchBranchAction,
        GitReadFileAction,
        GitMergeAction,
        GetRequirementPipelineAction,
        GetTicketStatusAction,
        GetRequirementLogsAction,
        ProposeUEFrameworkAction,      # v0.18 Phase A.6 — UE 框架方案卡片
        GetBuildLogsAction,            # v0.19.x — 查构建/编译日志让 AI 自动诊断
        SearchKnowledgeAction,         # 知识库全文搜索（FTS5）
        SearchTicketHistoryAction,     # 历史工单解决方案检索（FTS5）
        FetchUrlAction,                # 访问外部 URL
        ConfirmSaveDocAction,          # 保存对话内容为项目文档
        GetMemoryAction,               # 查询 Agent Memory
        CompetitorAnalysisAction,      # 竞品反拆分析
        ReadLocalFileAction,           # 读本地文件（动态加载 Skill 文档）
        UECallAction,                  # UE Editor UCP 控制（仅 engine:ue5/ue4）
        UERunPythonAction,             # B-0 UE Python 橋接
        BlueprintGenAction,            # B-1 Blueprint 生成
        LevelGenAction,                # B-2 關卡生成
        InstallProjectSkillAction,     # 对话中为项目安装/卸载 Marketplace Skill
        BrowseMarketplaceAction,       # 浏览/安装/卸载市场 Skill（系统级+项目级）
        LoadSkillAction,               # v0.20 主动触发：按需加载 Skill 全文
        # ── 新增工具（对标 Gemini CLI）──
        GlobAction,                    # glob 通配搜索文件（仅项目）
        GrepAction,                    # 正则搜索文件内容（仅项目）
        ListDirectoryAction,           # 列目录树（仅项目）
        ShellAction,                   # 执行 Shell 命令（仅项目）
        WebSearchAction,               # 联网搜索（全局+项目）
        MemoryWriteAction,             # 写入记忆（全局+项目）
        ReadManyFilesAction,           # 批量读文件（全局+项目）
        DispatchSubtaskAction,              # Phase 4 子任务派发
        DispatchParallelSubtasksAction,    # L8 批量并行派发
        ManageSkillAction,             # Skill 启用/禁用管理
        SetSessionFlagAction,          # L9 运行时行为开关
        CreateGithubRepoAction,        # GitHub 建仓库（AiDS-Projects 组织）
    ]
    react_mode = ReactMode.REACT
    max_react_loop = 6   # 工具调用可能多轮（搜索+fetch），留足余量输出最终回答

    @property
    def agent_type(self) -> str:
        return "ChatAssistant"

    # ==================== Tool schemas ====================

    def _exposed_tool_schemas(
        self,
        scope: str = "project",
        traits: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """返回可暴露给 LLM 的 tool schema 列表。

        scope="project"（默认）：项目内聊天，暴露所有非 INTERNAL 工具 + MCP 工具。
        scope="global"：项目列表页的全局聊天，只暴露 _GLOBAL_CHAT_TOOLS 白名单（confirm_project），
          不带 MCP（外部 MCP 工具大多也需要 project 上下文）。

        v0.17 Phase F：项目内聊天把 project.traits 传给 mcp_client，让 MCP server
        的 `enabled_for_traits` 过滤生效（例如 git MCP 只对 vcs:git 项目暴露）。
        """
        schemas = []
        for action in self._actions.values():
            if action.name in _INTERNAL_ONLY_ACTIONS:
                continue
            if scope == "global":
                # 全局模式：暴露所有工具，排除需要 project_id 才能运行的
                if action.name in _PROJECT_ONLY_TOOLS:
                    continue
            elif scope == "project":
                # 项目模式：排除仅全局有意义的（confirm_project）
                if action.name in _GLOBAL_ONLY_TOOLS:
                    continue
            # traits 过滤：action 声明了 available_for_traits 时，按项目 traits 决定是否暴露
            action_traits_cfg = getattr(action, "available_for_traits", None)
            if action_traits_cfg and traits is not None:
                from actions.base import _match_traits
                if not _match_traits(action_traits_cfg, set(traits)):
                    continue
            schema = getattr(action, "tool_schema", None)
            if schema:
                schemas.append(schema)

        if scope == "project":
            # 追加外部 MCP 工具（name 已带 mcp__ 前缀，防冲突），按 project traits 过滤
            try:
                from mcp_client import mcp_client
                schemas.extend(mcp_client.list_all_tool_schemas(traits=traits))
            except Exception as e:
                logger.warning("合并 MCP 工具列表失败: %s", e)

        return schemas

    # ==================== Chat 入口 ====================

    async def chat(
        self,
        user_message: str,
        images: Optional[List[str]],
        history: Optional[List[Dict[str, str]]],
        project: Dict[str, Any],
        project_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        单次对话：user_message → (可能经过若干轮 tool_use) → {reply, action}
        """
        from llm_client import llm_client, set_llm_context, clear_llm_context

        system_prompt = await self._build_system_prompt(project, project_context)
        messages = await self._assemble_messages(history, user_message, images)

        # v0.17 Phase F：把项目 traits 传给 _exposed_tool_schemas，按 traits 过滤 MCP
        project_traits = []
        try:
            import json as _json
            traits_raw = project.get("traits") or "[]"
            if isinstance(traits_raw, str):
                project_traits = _json.loads(traits_raw) or []
            elif isinstance(traits_raw, list):
                project_traits = list(traits_raw)
        except Exception:
            project_traits = []

        tools = self._exposed_tool_schemas(scope="project", traits=project_traits)

        executor = _ChatToolExecutor(self, project["id"])

        set_llm_context(
            project_id=project["id"],
            agent_type=self.agent_type,
            action="global_chat_v2",
        )
        try:
            result = await llm_client.chat_with_tools(
                messages=messages,
                tools=tools,
                tool_executor=executor,
                max_rounds=self.max_react_loop,
                temperature=0.7,
                max_tokens=4000,
                system=system_prompt,
            )
        finally:
            clear_llm_context()

        reply = self._extract_final_text(result.get("messages", []))
        action = executor.first_action_result
        # 多张确认卡片（文档分析批量提取需求场景）
        actions = executor.all_confirm_results if len(executor.all_confirm_results) > 1 else None

        # 兜底：LLM 啥也没说但工具执行了，用 action.message 或固定文案
        if not reply:
            if action:
                reply = action.get("message") or "操作已完成。"
            else:
                reply = "操作已完成。"

        return {
            "reply": reply,
            "action": action,
            "actions": actions,
            "thinking_steps": executor.thinking_steps or None,
        }

    async def chat_stream(
        self,
        user_message: str,
        images: Optional[List[str]],
        history: Optional[List[Dict[str, str]]],
        project: Dict[str, Any],
        project_context: Dict[str, Any],
        session_id: Optional[str] = None,
    ):
        """
        流式对话：逐步 yield SSE 事件 dict，由上层端点包装为 text/event-stream。
        事件类型：text_delta / tool_start / tool_done / action / error / message_done

        内部使用 QueryEngine 统一循环（Phase 2）。
        """
        from llm_client import llm_client, set_llm_context, clear_llm_context
        from query_engine import QueryEngine, Budget
        from query_engine.events import (
            TextDeltaEvent, ToolStartEvent, ToolDoneEvent, ToolErrorEvent,
            ActionEvent, MessageDoneEvent, BudgetExceededEvent, ErrorEvent,
            ThinkingDeltaEvent, ThinkingDoneEvent, RoundStartEvent,
        )
        from query_engine.executor import ChatToolExecutorAdapter
        from config import settings as _cfg
        from hooks.registry import hook_registry
        from llm_client import _model_supports_thinking

        system_prompt = await self._build_system_prompt(project, project_context)
        messages = await self._assemble_messages(history, user_message, images, session_id=session_id)

        project_traits = []
        try:
            import json as _json
            traits_raw = project.get("traits") or "[]"
            project_traits = _json.loads(traits_raw) if isinstance(traits_raw, str) else list(traits_raw)
            if not isinstance(project_traits, list):
                project_traits = []
        except Exception:
            project_traits = []

        tools = self._exposed_tool_schemas(scope="project", traits=project_traits)
        inner_executor = _ChatToolExecutor(self, project["id"], session_id=session_id)
        executor = ChatToolExecutorAdapter(inner_executor)

        # L9 Feature Flags：運行時 budget 覆蓋
        _sid = session_id or "default"
        budget = Budget(
            max_tokens=get_session_flag(_sid, "budget_tokens") or _cfg.CHAT_MAX_TOKENS,
            max_turns=get_session_flag(_sid, "max_turns") or _cfg.CHAT_MAX_TURNS,
            max_seconds=_cfg.CHAT_MAX_SECONDS,
        )
        context = {"project_id": project["id"], "agent_type": self.agent_type}
        engine = QueryEngine(
            llm_client=llm_client,
            tool_executor=executor,
            budget=budget,
            hooks=hook_registry,
            max_rounds=self.max_react_loop,
            enable_thinking=_resolve_thinking_enabled(_sid, llm_client.model),
            thinking_budget=max(1024, get_session_flag(_sid, "thinking_budget") or 8000),
        )

        set_llm_context(project_id=project["id"], agent_type=self.agent_type, action="chat_stream")
        try:
            async for event in engine.run(messages, system_prompt, tools, context):
                if isinstance(event, TextDeltaEvent):
                    yield {"type": "text_delta", "delta": event.delta}
                elif isinstance(event, RoundStartEvent):
                    yield {"type": "round_start", "round": event.round}
                elif isinstance(event, ThinkingDeltaEvent):
                    yield {"type": "thinking_delta", "delta": event.delta}
                elif isinstance(event, ThinkingDoneEvent):
                    yield {"type": "thinking_done", "text": event.text}
                elif isinstance(event, ToolStartEvent):
                    yield {"type": "tool_start", "tool": event.tool,
                           "tool_use_id": event.tool_use_id, "input": event.input}
                elif isinstance(event, ToolDoneEvent):
                    yield {"type": "tool_done", "tool": event.tool,
                           "summary": event.summary, "args_hint": event.args_hint,
                           "duration_ms": round(event.duration_ms),
                           "result": event.result}
                elif isinstance(event, ToolErrorEvent):
                    yield {"type": "tool_done", "tool": event.tool,
                           "summary": f"错误: {event.error}",
                           "args_hint": "", "duration_ms": round(event.duration_ms),
                           "result": ""}
                elif isinstance(event, ActionEvent):
                    yield {"type": "action", "payload": event.action_data}
                elif isinstance(event, MessageDoneEvent):
                    yield {
                        "type": "message_done",
                        "rounds": event.rounds,
                        "thinking_steps": event.thinking_steps or [],
                        "action": event.final_action,
                        "actions": event.all_confirm_results if len(event.all_confirm_results) > 1 else None,
                    }
                elif isinstance(event, BudgetExceededEvent):
                    yield {"type": "budget_exceeded", "reason": event.reason}
                elif isinstance(event, ErrorEvent):
                    yield {"type": "error", "message": event.message}
        finally:
            clear_llm_context()

    # ==================== 全局聊天入口（项目列表页，无 project_id） ====================

    async def chat_global(
        self,
        user_message: str,
        images: Optional[List[str]],
        history: Optional[List[Dict[str, str]]],
        projects_brief: List[Dict[str, Any]],
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        全局聊天：用户在项目列表页使用 AI 助手，可能要求新建项目或单纯聊天。
        只暴露 confirm_project 一个工具；用户确认后由 /api/chat/confirm-create-project 端点落库。
        """
        from llm_client import llm_client, set_llm_context, clear_llm_context

        # v0.17: 用 user_message 预计算 preset 推荐，注入到 system prompt
        preset_suggestions = self._match_preset_suggestions(user_message)

        system_prompt = self._build_global_system_prompt(projects_brief, preset_suggestions)
        messages = await self._assemble_messages(history, user_message, images)
        tools = self._exposed_tool_schemas(scope="global")

        executor = _ChatToolExecutor(self, project_id=None, session_id=session_id)

        set_llm_context(
            agent_type=self.agent_type,
            action="global_chat_v2_no_project",
        )
        try:
            result = await llm_client.chat_with_tools(
                messages=messages,
                tools=tools,
                tool_executor=executor,
                max_rounds=self.max_react_loop,
                temperature=0.7,
                max_tokens=4000,
                system=system_prompt,
            )
        finally:
            clear_llm_context()

        reply = self._extract_final_text(result.get("messages", []))
        action = executor.primary_action_result
        actions = executor.all_confirm_results if len(executor.all_confirm_results) > 1 else None

        if not reply:
            if action:
                reply = action.get("message") or "操作已完成。"
            else:
                reply = "有什么可以帮你的？"

        return {
            "reply": reply,
            "action": action,
            "actions": actions,
            "thinking_steps": executor.thinking_steps or None,
        }

    async def chat_global_stream(
        self,
        user_message: str,
        images: Optional[List[str]],
        history: Optional[List[Dict[str, str]]],
        projects_brief: List[Dict[str, Any]],
        session_id: Optional[str] = None,
    ):
        """全局聊天流式版：逐步 yield SSE 事件，与 chat_stream 同格式。内部使用 QueryEngine（Phase 2）。"""
        from llm_client import llm_client, set_llm_context, clear_llm_context
        from query_engine import QueryEngine, Budget
        from query_engine.events import (
            TextDeltaEvent, ToolStartEvent, ToolDoneEvent, ToolErrorEvent,
            ActionEvent, MessageDoneEvent, BudgetExceededEvent, ErrorEvent,
            ThinkingDeltaEvent, ThinkingDoneEvent, RoundStartEvent,
        )
        from query_engine.executor import ChatToolExecutorAdapter
        from config import settings as _cfg
        from hooks.registry import hook_registry
        from llm_client import _model_supports_thinking

        preset_suggestions = self._match_preset_suggestions(user_message)
        system_prompt = self._build_global_system_prompt(projects_brief, preset_suggestions)
        messages = await self._assemble_messages(history, user_message, images, session_id=session_id)
        tools = self._exposed_tool_schemas(scope="global")
        inner_executor = _ChatToolExecutor(self, project_id=None, session_id=session_id)
        executor = ChatToolExecutorAdapter(inner_executor)

        _sid = session_id or "default"
        budget = Budget(
            max_tokens=get_session_flag(_sid, "budget_tokens") or _cfg.CHAT_MAX_TOKENS,
            max_turns=get_session_flag(_sid, "max_turns") or _cfg.CHAT_MAX_TURNS,
            max_seconds=_cfg.CHAT_MAX_SECONDS,
        )
        context = {"agent_type": self.agent_type}
        engine = QueryEngine(
            llm_client=llm_client,
            tool_executor=executor,
            budget=budget,
            hooks=hook_registry,
            max_rounds=self.max_react_loop,
            enable_thinking=_resolve_thinking_enabled(_sid, llm_client.model),
            thinking_budget=max(1024, get_session_flag(_sid, "thinking_budget") or 8000),
        )

        set_llm_context(agent_type=self.agent_type, action="global_chat_stream")
        try:
            async for event in engine.run(messages, system_prompt, tools, context):
                if isinstance(event, TextDeltaEvent):
                    yield {"type": "text_delta", "delta": event.delta}
                elif isinstance(event, RoundStartEvent):
                    yield {"type": "round_start", "round": event.round}
                elif isinstance(event, ThinkingDeltaEvent):
                    yield {"type": "thinking_delta", "delta": event.delta}
                elif isinstance(event, ThinkingDoneEvent):
                    yield {"type": "thinking_done", "text": event.text}
                elif isinstance(event, ToolStartEvent):
                    yield {"type": "tool_start", "tool": event.tool,
                           "tool_use_id": event.tool_use_id, "input": event.input}
                elif isinstance(event, ToolDoneEvent):
                    yield {"type": "tool_done", "tool": event.tool,
                           "summary": event.summary, "args_hint": event.args_hint,
                           "duration_ms": round(event.duration_ms),
                           "result": event.result}
                elif isinstance(event, ToolErrorEvent):
                    yield {"type": "tool_done", "tool": event.tool,
                           "summary": f"错误: {event.error}",
                           "args_hint": "", "duration_ms": round(event.duration_ms),
                           "result": ""}
                elif isinstance(event, ActionEvent):
                    yield {"type": "action", "payload": event.action_data}
                elif isinstance(event, MessageDoneEvent):
                    yield {
                        "type": "message_done",
                        "rounds": event.rounds,
                        "thinking_steps": event.thinking_steps or [],
                        "action": event.final_action,
                        "actions": event.all_confirm_results if len(event.all_confirm_results) > 1 else None,
                    }
                elif isinstance(event, BudgetExceededEvent):
                    yield {"type": "budget_exceeded", "reason": event.reason}
                elif isinstance(event, ErrorEvent):
                    yield {"type": "error", "message": event.message}
        finally:
            clear_llm_context()

    # ==================== 内部工具 ====================

    # ==================== 对话历史压缩（借鉴 MagicAI §6.4）====================
    # 参数默认值跟 MagicAI 一致，实测对主观任务效果好

    HISTORY_KEEP_RECENT_N = 10        # 最近 N 条全文保留（原 6）
    HISTORY_MAX_RECENT_CHARS = 8000   # 最近 N 条每条上限（原 4000）
    HISTORY_OLDER_CHARS = 1200        # 更早的每条压缩后上限（原 800）
    HISTORY_MAX_TOTAL_CHARS = 30000   # 历史段总硬上限（原 8000，约 7500 tokens）
    HISTORY_COMPACTION_THRESHOLD = 20 # 超过 N 条时触发 LLM 摘要 Compaction

    async def _assemble_messages(
        self,
        history: Optional[List[Dict[str, str]]],
        user_message: str,
        images: Optional[List[str]],
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """组装消息 + 压缩对话历史。

        策略（MagicAI 两级）：
          最近 N 条：全文保留（每条最多 HISTORY_MAX_RECENT_CHARS）
          更早的：压缩到 HISTORY_OLDER_CHARS / 条
          整段历史：总量超 HISTORY_MAX_TOTAL_CHARS 时从最老的开始删
        """
        messages: List[Dict[str, Any]] = []

        if history:
            # L9 Feature Flag：compaction 可运行时关闭
            compaction_enabled = get_session_flag(session_id or "default", "compaction")
            # Compaction：历史条数超过阈值时，用 LLM 把旧消息摘要为单条上下文
            if compaction_enabled and len(history) > self.HISTORY_COMPACTION_THRESHOLD:
                keep_recent = self.HISTORY_KEEP_RECENT_N
                to_compact = history[:-keep_recent]
                recent = history[-keep_recent:]
                summary = await self._compact_history_with_llm(to_compact)
                if summary:
                    history = [{"role": "assistant", "content": summary}] + recent
                    logger.info("历史 Compaction：%d 条 → 摘要 + %d 条", len(to_compact), len(recent))

            compressed = self._compress_history(
                history,
                keep_recent_n=self.HISTORY_KEEP_RECENT_N,
                max_recent_chars=self.HISTORY_MAX_RECENT_CHARS,
                older_msg_chars=self.HISTORY_OLDER_CHARS,
                max_total_chars=self.HISTORY_MAX_TOTAL_CHARS,
            )
            messages.extend(compressed)

        messages.append({"role": "user", "content": self._build_user_content(user_message, images)})
        return messages

    async def _compact_history_with_llm(
        self,
        messages: List[Dict],
    ) -> str:
        """委托到 BaseAgent.compact_history（A-2 下沉）"""
        return await self.compact_history(messages)

    async def _compact_history_with_llm_legacy(
        self,
        messages: List[Dict],
    ) -> str:
        """原实现保留（备用）"""
        if not messages:
            return ""
        try:
            from llm_client import llm_client
            # 把消息整理成文本
            lines = []
            for m in messages[-30:]:  # 最多压缩 30 条，避免摘要请求本身也太大
                role = m.get("role", "?")
                content = m.get("content", "")
                if isinstance(content, list):  # multi-block
                    content = " ".join(
                        b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
                    )
                if isinstance(content, str) and content.strip():
                    prefix = "用户" if role == "user" else "AI助手"
                    lines.append(f"{prefix}：{content[:300]}")

            if not lines:
                return ""

            conv_text = "\n".join(lines)
            summary_prompt = f"""请将以下对话历史压缩为简洁摘要，保留关键信息：
- 用户提出的需求和问题
- AI 做出的重要决策和操作
- 创建/修改的需求、工单、文档等
- 重要的技术方案和结论

对话历史：
{conv_text}

请用中文，200字以内。"""

            summary = await llm_client.chat(
                [{"role": "user", "content": summary_prompt}],
                max_tokens=300,
                temperature=0.1,
            )
            if summary and isinstance(summary, str) and len(summary) > 10:
                return f"[之前对话历史摘要]\n{summary.strip()}"
        except Exception as e:
            logger.warning("历史 Compaction LLM 调用失败（降级为截断）: %s", e)
        return ""

    @classmethod
    def _compress_history(
        cls,
        history: List[Any],
        keep_recent_n: int = 6,
        max_recent_chars: int = 4000,
        older_msg_chars: int = 800,
        max_total_chars: int = 8000,
    ) -> List[Dict[str, Any]]:
        """把历史消息按两级策略压缩，保证总字符数不超标。"""
        if not history:
            return []

        # 归一化：兼容 dict / pydantic model
        normalized: List[Dict[str, Any]] = []
        for msg in history:
            role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
            content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
            if role and content is not None:
                normalized.append({"role": role, "content": content})

        if not normalized:
            return []

        # 分两段
        recent = normalized[-keep_recent_n:]
        older = normalized[:-keep_recent_n] if len(normalized) > keep_recent_n else []

        # 分别按对应字符上限截断
        result = [
            {"role": m["role"], "content": cls._truncate_content(m["content"], older_msg_chars, compress=True)}
            for m in older
        ] + [
            {"role": m["role"], "content": cls._truncate_content(m["content"], max_recent_chars, compress=False)}
            for m in recent
        ]

        # 再做总量硬上限
        result = cls._trim_to_budget(result, max_total_chars)
        return result

    @staticmethod
    def _truncate_content(content: Any, max_chars: int, compress: bool) -> Any:
        """把单条消息 content 截到 max_chars。
        compress=True 对更早的消息：去代码块、去多余空白再截（保语义丢细节）。
        compress=False 对最近消息：只在超长时直接截断加省略。
        content 可能是 str（常规）或 list[block]（Anthropic tool_use 多段格式）。
        """
        if isinstance(content, str):
            if len(content) <= max_chars:
                return content
            if compress:
                # 去代码块（保留占位）+ 压缩空白
                stripped = re.sub(r"```[\s\S]*?```", "[...code...]", content)
                stripped = re.sub(r"\n\s*\n+", "\n", stripped)
                if len(stripped) <= max_chars:
                    return stripped
                return stripped[:max_chars - 3].rstrip() + "..."
            return content[:max_chars - 3].rstrip() + "..."

        if isinstance(content, list):
            # Anthropic 多段 content：text / tool_use / tool_result blocks
            parts: List[str] = []
            for b in content:
                if not isinstance(b, dict):
                    parts.append(str(b)[:200])
                    continue
                btype = b.get("type")
                if btype == "text":
                    parts.append(b.get("text", "")[:max_chars // 2])
                elif btype == "tool_use":
                    parts.append(f"[tool: {b.get('name', '?')}(...)]")
                elif btype == "tool_result":
                    inner = b.get("content", "")
                    inner_s = inner if isinstance(inner, str) else str(inner)[:400]
                    parts.append(f"[tool_result] {inner_s[:300]}")
                else:
                    parts.append(f"[{btype}]")
            joined = "\n".join(p for p in parts if p)
            if len(joined) <= max_chars:
                return joined
            return joined[:max_chars - 3].rstrip() + "..."

        # 未知类型 → repr
        s = str(content)
        return s[:max_chars - 3] + "..." if len(s) > max_chars else s

    @staticmethod
    def _trim_to_budget(messages: List[Dict[str, Any]], max_total_chars: int) -> List[Dict[str, Any]]:
        """总量超预算时从最老的开始删，保证至少留 1 条。"""
        def _len(m):
            c = m.get("content", "")
            return len(c) if isinstance(c, str) else len(str(c))

        total = sum(_len(m) for m in messages)
        if total <= max_total_chars:
            return messages

        # 从头删直到达标（至少留 1 条）
        result = list(messages)
        while total > max_total_chars and len(result) > 1:
            dropped = result.pop(0)
            total -= _len(dropped)
        return result

    @staticmethod
    def _build_user_content(text: str, images: Optional[List[str]]):
        """无图片时返回字符串；有图片时返回 Anthropic vision content blocks 列表。"""
        if not images:
            return text

        content: List[Dict[str, Any]] = []
        for data_url in images:
            try:
                header, b64data = data_url.split(",", 1)
                media_type = header.split(";")[0].split(":")[1]
                if media_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
                    media_type = "image/jpeg"
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": b64data,
                    },
                })
            except Exception as e:
                logger.warning("图片解析失败: %s", e)
        content.append({"type": "text", "text": text})
        return content

    @staticmethod
    def _extract_final_text(messages: List[Dict[str, Any]]) -> str:
        """从 chat_with_tools 结果里拿最后一条 assistant 的纯文本（拼接所有 text block）"""
        for msg in reversed(messages):
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                texts = [b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text"]
                text = "\n".join(t for t in texts if t).strip()
                if text:
                    return text
        return ""

    # ==================== System prompt ====================

    async def _build_system_prompt(self, project: dict, context: dict) -> str:
        """
        精简版系统提示词 —— 不再列 [ACTION:XXX] 格式，
        因为能力通过 Anthropic 原生 tools 字段提供给 LLM，与 prompt 正交。
        """
        req_list = context.get("recent_requirements", [])
        if req_list:
            req_summary = "\n".join(
                f"  - [{r['status']}] {r['title']} (ID: {r['id']})" for r in req_list[:10]
            )
        else:
            req_summary = "  暂无需求"

        ticket_summary = context.get("ticket_summary", "暂无工单")
        file_tree = context.get("file_tree", "")
        key_files_content = context.get("key_files_content", "")
        artifacts_summary = context.get("artifacts_summary", "暂无产物")
        knowledge_content = context.get("knowledge_content", "")

        knowledge_section = (
            "\n## 项目知识库\n" + knowledge_content
            if knowledge_content else ""
        )

        # P2 Memory 主动召回：从 agent_memory 检索最近 3 条相关记忆注入动态上下文
        # 只在有项目且有记忆时注入，不增加 cache 部分的 token
        memory_section = ""
        project_id = project.get("id", "")
        if project_id:
            try:
                mem_rows = await db.fetch_all(
                    """SELECT type, title, content, created_at FROM agent_memory
                       WHERE project_id = ?
                       ORDER BY created_at DESC LIMIT 3""",
                    (project_id,),
                )
                if mem_rows:
                    mem_lines = []
                    for r in mem_rows:
                        date = r["created_at"][:10] if r["created_at"] else ""
                        mem_lines.append(f"  [{r['type']}] {r['title']} ({date})")
                    memory_section = "\n## 项目历史记忆（最近 3 条）\n" + "\n".join(mem_lines) + "\n如需详情请调用 get_memory 工具。\n"
            except Exception:
                pass

        # v0.18：解析项目 traits，若是 UE 项目则加 UE 专属意图路由
        import json as _json
        try:
            _raw = project.get("traits") or "[]"
            project_traits = _json.loads(_raw) if isinstance(_raw, str) else list(_raw)
            if not isinstance(project_traits, list):
                project_traits = []
        except Exception:
            project_traits = []
        project_traits = [str(t) for t in project_traits]

        # Rules 层：全局编码准则（alwaysApply=true）放在 system prompt 最前面
        # rules/global.md 包含语言一致性 / 命名 / 安全红线等，对所有项目生效
        rules_content = ""
        try:
            from skills import skill_loader as _sl
            rule_ids = _sl.get_rules_for_context(traits=project_traits)
            rules_parts = []
            for rid in rule_ids:
                content = _sl.rules.get(rid, {}).get("content", "")
                if content:
                    rules_parts.append(f"<!-- Rule: {rid} -->\n{content}")
            rules_content = "\n\n".join(rules_parts)
        except Exception:
            pass
        rules_section = f"{rules_content}\n\n---\n\n" if rules_content else ""

        # v0.20 主动触发：只注入 Skill 索引（名称+描述），不注入全文。
        # AI 按需调用 load_skill 工具加载具体内容。
        try:
            from skills import skill_loader as _sl
            _skills_index = _sl.build_index_for_agent(self.agent_type, traits=project_traits)
        except Exception:
            _skills_index = ""
        # 追加项目自定义 Skill（custom.* 系列）
        try:
            from database import db as _db
            _custom_rows = await _db.fetch_all(
                "SELECT skill_id, custom_name FROM project_skills WHERE project_id=? AND source='custom' AND enabled=1",
                (project.get("id"),),
            )
            for _r in _custom_rows:
                _skills_index += f"\n| `{_r['skill_id']}` | {_r['custom_name'] or _r['skill_id']} | 项目自定义 Skill |"
        except Exception:
            pass
        # 追加项目 .Agent/skills/ 目录下的 Skill（agent.* 系列）
        try:
            from actions.chat.load_skill import _get_project_agent_skills_dir, _load_agent_skill
            _agent_dir = await _get_project_agent_skills_dir(project.get("id", ""))
            if _agent_dir.exists():
                for _skill_dir in sorted(_agent_dir.iterdir()):
                    if _skill_dir.is_dir() and (_skill_dir / "SKILL.md").exists():
                        _, _skill_name = await _load_agent_skill(
                            f"agent.{_skill_dir.name}", project.get("id", "")
                        )
                        _skills_index += f"\n| `agent.{_skill_dir.name}` | {_skill_name} | 项目本地 Skill |"
        except Exception:
            pass
        skills_section = f"""
## 可用 Skills（按需加载）

{_skills_index}

如当前问题需要以上领域的深度规范知识，请先调用 load_skill 加载对应文档，再回答用户。不确定是否需要时可直接回答。
""" if _skills_index else ""
        is_ue_project = any(t.startswith("engine:ue") for t in project_traits)

        traits_line = (
            f"- 项目特征：{', '.join(project_traits)}"
            if project_traits else "- 项目特征：（未设置）"
        )

        ue_routing = ""
        if is_ue_project:
            ue_routing = """

## 🎮 UE 项目意图路由（优先级最高，在 confirm_requirement 之前判断）
- "生成框架 / 创建骨架 / 初始化工程 / 基于 TP_* 模板 / 做个 FPS / TPS / TopDown 游戏 / 从模板开始" 等
  → **优先调 propose_ue_framework**（产出方案卡片让用户选引擎/模板/项目名后点确认才真落地）
  → ⚠️ 不要调 confirm_requirement 把这个当成"新需求"处理 —— 这是工程骨架生成，不是加功能需求
- 用户在 UE 项目里提"加个武器系统 / 做个 AI / 实现倒计时"这种**具体功能** → 调 confirm_requirement（走需求流）
- 简单说：**动"整个工程骨架"用 propose_ue_framework；动"某个功能模块"用 confirm_requirement**"""

        # <!--CACHE_BOUNDARY--> 之前为稳定内容（Prompt Cache 命中），之后为动态内容（每次不同）
        # 稳定：Rules + 项目基本信息 + Skills + 能力描述
        # 动态：知识库 / 需求状态 / 工单 / 文件树 / 产出物
        return f"""{rules_section}你是 AI 自动开发系统的智能助手，当前正在为项目「{project['name']}」提供服务。

## 项目信息
- 名称：{project['name']}
- 描述：{project.get('description') or '无描述'}
- 技术栈：{project.get('tech_stack') or '未指定'}
- Git 仓库：{project.get('git_repo_path') or '未配置'}
{traits_line}
{ue_routing}
{skills_section}
## 你的能力
你配有一组工具（见 tools 参数），用于：
- 识别单条新需求 → confirm_requirement；识别多条需求（≥2）→ confirm_requirements_batch（一张勾选卡）
- 识别 BUG → confirm_bug 产草稿让用户确认（不要直接创建）
- 管理需求状态 → pause / resume / close
- **批量暂停所有/多条需求** → pause_requirements_batch（用户说"暂停所有工单/需求""先全部停下"时）
- **竞品分析** → competitor_analysis（用户说"分析 XXX 游戏/产品""竞品调研""看看 XXX 怎么做的"时）
- 查看项目 → git_log / git_list_branches / git_read_file
- 切换/合并分支 → git_switch_branch / git_merge
- 生成文档 → generate_document（直接写入 docs/ 并 commit+push）
- 保存本次回复为文档 → generate_document（content 填当前回复内容，让用户确认文件名）
- **诊断需求进度** → get_requirement_pipeline（"XX 卡在哪"）/
  get_ticket_status（工单详细状态）/ get_requirement_logs（最近活动 + 错误）

## 搜索工具使用规则（重要）

**search_knowledge** — 搜索系统知识库（包含 docs/ dev-notes/ 文档）
- 触发：用户询问「系统功能 / 某特性怎么实现的 / 最近做了什么 / 有没有 XX 相关文档」
- 示例：「能搜索到 harness 相关信息吗」「QueryEngine 是怎么做的」「有 Skill 相关文档吗」
- **先用 search_knowledge，找不到才考虑 grep 搜代码**；不要第一步就 grep

**web_search** — 联网搜索
- 触发：用户说「搜一下 XX」「网络搜索 XX」「联网查查」「网上找找」「搜索官方文档」
- **⚠️ 用户明确说"联网/网络搜索"时，立即调用 web_search，不要询问搜什么**
  直接用用户提到的关键词搜索，有了结果再跟用户确认是否需要深入

**搜索优先级**：问系统/文档 → search_knowledge；问项目代码 → grep/glob；问外部知识 → web_search

## 读取用户上传的文件
当消息中包含 `【附件：xxx.md】` 或其他文件内容时：
- 仔细阅读文件内容，结合项目上下文给出具体分析
- 需求文档 / PRD → **从文档中提取所有独立需求点，调用一次 `confirm_requirements_batch`**
  （把所有需求打包进一个数组，前端渲染带勾选框的单张卡片，用户勾选后批量创建）
- 设计文档 / 技术方案 → 讨论实现思路，指出潜在风险
- 代码文件 → 审查逻辑，结合已有代码给出修改建议
- **不要只复述文件内容**，要给出有价值的分析和下一步行动建议

## 判断准则
- 用户**明确要求**新增/开发**单个**功能 → 调 confirm_requirement
- 用户上传文档/让 AI 规划需求列表 → 提取所有独立需求点，调 **confirm_requirements_batch**（≥2 条时），不要逐条调 confirm_requirement
- 用户描述已有功能的缺陷/报错/崩溃/白屏 → 调 confirm_bug（不是需求）
- 用户单纯提问、描述现象、讨论方案 → 直接回答，不要调工具
- 用户说"把这个/刚才的内容/总结保存成文档/存档/记录" → 调 generate_document，content 填本次回复的完整内容，filename 自动生成或询问用户
- 信息已经在上面的上下文里可直接回答 → 不要调 git_* 工具，直接引用上下文作答
- **"仓库里有什么文件" / "能看到哪些文档"** → 直接列举上面「项目文件树」里的内容，**不要调 git_read_file**
- `git_read_file` 只在用户**明确要求查看某文件的具体内容**时才调用（如"帮我看看 README 写了什么"）

## 多步操作（重要）
- 你可以在**同一轮回复里连续调多个工具**（Anthropic tool_use 原生支持 ReAct 循环）
- 典型的合理链式调用：
  - **"重跑/重新做/重来 XX 需求"** → 在同一轮里依次调 `close_requirement`（关闭旧的）
    + `confirm_requirement`（生成同标题新草稿）。**不要先调 get_requirement_pipeline 诊断**，
    用户已经明确说"重跑"就是要重来，诊断是多余步骤。新需求的 title 用老需求的 title，
    description 从上下文里的"## 当前需求状态"推测，或用老需求的文本作为基础。
  - **"把 XX 合并到 YY"** → `git_list_branches`（确认分支存在）+ `git_merge`
  - **"查看 XX 卡在哪"** → `get_requirement_pipeline` + `get_requirement_logs`（两边数据一起看更全面）
- 只在意图真的含糊时才停下来追问，不要把明确意图当含糊意图处理
- 链式调用时**工具顺序要对**：状态变更（close）在前，产生用户需要确认的草稿（confirm_*）在后，
  因为前端会优先显示需要用户交互的草稿卡片

## ⛔ 「问原因/问状态」≠「要求执行动作」

这是最常见的误判，必须严格遵守：

**只询问，不行动的场景**（先查询诊断，回答问题）：
- 「这个 BUG 为啥卡住？」「为什么一直在 XX 状态？」「XX 是什么原因？」
- 「现在什么进度？」「有什么问题？」「为何没有推进？」
- 「能不能帮我看看 XX？」

**明确要求执行的场景**（才可以调用 confirm_bug / close_requirement 等）：
- 「帮我上报这个 BUG」「创建一个 BUG」「提交 bug：XXX」
- 「关掉这个需求」「重跑 XX」「暂停 XX」

**判断规则**：
- 「X 了吗？」「为什么 X？」「现在是 X？」「X 怎么了？」→ 用户在**询问**，先用查询工具诊断，**回答后再问用户是否需要采取行动**
- 「帮我做 X」「创建/上报/关闭/重跑 X」→ 用户在**发出指令**，可以执行
- **模糊情况**（如「X 怎么卡住了」）→ 先诊断说明原因，最后可以**建议**操作，但不能直接调用行动工具

## ⛔ 破坏性操作和创建操作的额外约束

以下操作即使用户明确要求，也要**先展示计划再等确认**：

- `close_requirement` / 关闭需求
- `pause_requirement` / 暂停需求
- `confirm_bug` 生成的草稿卡片，回复文字应说「我建议上报以下 BUG，请确认」，**不要说「已创建」**（卡片未被用户确认前什么都没创建）
- 批量状态变更

## 注意事项
- 用中文回复
- 回答简洁但有信息量
- 如果用户描述**真的**不清晰才追问；"重跑/重来/改颜色/加功能"这类指令是明确的，直接执行
- 需求 ID 不明确时用标题关键词模糊匹配（工具本身支持）
- 需求状态不允许当前操作时，工具会返回错误，据实告知用户

<!--CACHE_BOUNDARY-->
## 当前项目状态（实时）
{memory_section}
{knowledge_section}
## 当前需求状态
{req_summary}

## 工单概况
{ticket_summary}

## 项目文件树
{file_tree}

## 项目关键文档内容
{key_files_content}

## 产出物列表
{artifacts_summary}"""

    def _match_preset_suggestions(self, user_message: str) -> List[Any]:
        """预计算 preset 推荐，注入到 system prompt 给 LLM 参考。"""
        if not user_message or not user_message.strip():
            return []
        try:
            from skills import preset_matcher
            return preset_matcher.match(user_message, top_n=3)
        except Exception as e:
            logger.warning("PresetMatcher 调用异常（忽略）: %s", e)
            return []

    def _build_global_system_prompt(
        self,
        projects_brief: List[Dict[str, Any]],
        preset_suggestions: Optional[List[Any]] = None,
    ) -> str:
        """全局聊天（项目列表页）的系统提示词——不挂在任何具体项目上。
        唯一暴露的工具是 confirm_project，用来产草稿让用户确认后再落库。"""
        if projects_brief:
            proj_lines = "\n".join(
                f"  - [{p.get('status', '?')}] {p.get('name', '')} (id: {p.get('id', '')})"
                for p in projects_brief[:10]
            )
        else:
            proj_lines = "  （尚无项目）"

        # Rules 层：全局聊天同样注入全局编码准则
        global_rules_content = ""
        try:
            from skills import skill_loader as _sl
            rule_ids = _sl.get_rules_for_context(traits=[])
            rules_parts = []
            for rid in rule_ids:
                content = _sl.rules.get(rid, {}).get("content", "")
                if content:
                    rules_parts.append(f"<!-- Rule: {rid} -->\n{content}")
            global_rules_content = "\n\n".join(rules_parts)
        except Exception:
            pass
        global_rules_section = f"{global_rules_content}\n\n---\n\n" if global_rules_content else ""

        # v0.20 主动触发：全局聊天同样只注入索引
        try:
            from skills import skill_loader as _sl
            _skills_index = _sl.build_index_for_agent(self.agent_type)
        except Exception:
            _skills_index = ""
        skills_section = f"""
## 可用 Skills（按需加载）

{_skills_index}

如当前问题需要以上领域的深度规范知识，请先调用 load_skill 加载对应文档，再回答用户。不确定是否需要时可直接回答。
""" if _skills_index else ""

        # v0.17: preset 推荐（从 PresetMatcher 得到）
        preset_section = ""
        if preset_suggestions:
            preset_lines = ["\n## 💡 Preset 匹配推荐（基于用户本次消息预计算）"]
            preset_lines.append("用户消息命中以下 preset（分数 >= 5 才列出）。若高分 preset 的 traits")
            preset_lines.append("明显符合用户意图，可以在反问补齐必填维度时**建议使用这个 preset**；")
            preset_lines.append("用户若采纳，调 confirm_project 时填对应 preset_id 字段。\n")
            for m in preset_suggestions:
                preset_lines.append(f"- **{m.preset_id}**（{m.label}，分数 {m.score}）traits: {m.traits}")
            preset_section = "\n".join(preset_lines) + "\n"

        return f"""{global_rules_section}你是 AI 自动开发系统的全局助手，当前用户在**项目列表页**，**还没有进入任何具体项目**。

## 已有项目（最多展示 10 个）
{proj_lines}
{skills_section}{preset_section}
## 你的能力（当前语境下）

你有以下工具：

**1. confirm_project** — 新建项目草稿
- 当用户**明确表示想新建项目**时调用，产出草稿让用户确认。**不会直接建项目**。

**2. search_knowledge** — 搜索知识库文档
- 当用户询问**系统功能、版本更新、技术方案、开发日志、架构设计**等内容时，
  **主动调用**搜索知识库，包括系统的 docs/ 和 dev-notes/ 文档。
- 示例触发：「v0.19 做了什么」「知识库怎么实现的」「UBT 编译是什么原理」「最近有什么更新」
- **追问优先用对话历史**：如果用户的问题包含"这里面"、"这个功能"、"刚才说的"、"解释一下"等
  指代词，且上一轮回复里已提到相关内容，**直接从对话历史中提取细节作答，不要重新调 search_knowledge**。
  只有历史信息不足以回答时，才用精准关键词（如 `UEPlaytestAction`、`Automation Framework headless`）
  做二次搜索，**不要重复使用上一次已经搜过的宽泛词**（如版本号）。
- **搜索后务必直接回答用户的具体问题**，不要只转述文档标题或版本概览。
  若搜索结果里没有具体答案，如实说明并建议用户进入项目内查看。

**3. search_ticket_history** — 搜索历史工单
- 当用户询问某类问题**历史上有没有解决过**、或**查某个 bug 怎么处理的**时调用。

**4. fetch_url** — 访问外部链接
- 当用户粘贴了一个 URL（http/https）并想让你读取内容时调用。

**5. confirm_save_doc** — 保存 AI 内容为项目文档
- 当用户说"把这个总结/分析/方案保存到项目""存成文档""记录下来"时调用。
- ⚠️ **必须在拿到文档内容的同一轮立即调用**，不要先问用户选哪个项目再分第二轮调用。
  原因：对话历史会压缩，第二轮时 content 会被截断丢失。
- 正确流程：拿到内容 → 从项目列表中挑最合适的 → 立即调用 confirm_save_doc（content 填完整内容）
  → 产出确认卡片，用户在卡片上确认或取消即可，无需提前询问。
- 若实在无法判断目标项目，选第一个项目作为默认值，卡片上会显示项目名让用户确认。

**6. 读取用户上传的文件内容**
- 当消息中包含 `【附件：xxx.md】` 时，文件内容已内联在消息里，直接阅读分析。
- 典型用途：
  - 用户上传需求文档 → 帮助分析需求、识别项目类型和技术栈、推荐 traits / preset
  - 用户上传设计文档 → 讨论技术方案、提出改进建议
  - 信息足够时主动询问是否基于文档内容创建项目（调 confirm_project）
- **不要只复述文件内容**，要结合内容给出具体的分析和建议。

**对于查项目状态、涉及具体项目操作**：提示用户先点击进入那个项目再继续对话。

## 调 confirm_project 必填字段（**全齐了才能调**）

- **name**（必填）：项目名称。用户未指定时**自动生成**一个简短有辨识度的名字（2-4词，如 JumpGame / TaskBoard），用户可在卡片里修改
- **git_remote_url**（必填）：Git 远程仓库 URL
- **traits**（必填）：项目特征标签数组，至少包含：
  - `platform:*` —— `web` / `wechat` / `desktop` / `mobile` / `server` / `cli` 任选
  - `category:*` —— `app` / `game` / `service` / `library` 任选
  - 如果 `category:game`，还必须加 `engine:*`（`ue5` / `godot4` / `unity` / `cocos` / `none`）

可选但推荐：
  - `lang:*`（python/javascript/cpp/gdscript/csharp/...）
  - `framework:*`（react/vue/fastapi/...）
  - 功能性 trait：`multiplayer` / `realtime` / `i18n` / `offline-first` 等
  - **preset_id**：如果 traits 跟某个 preset 完全匹配，填 preset_id 标记来源

## 头脑风暴策略（当用户表达模糊想法时）

当用户说出一个模糊的想法（"想做个游戏""有个点子""做个 app"）时，进入**渐进式脑暴模式**，
而不是立刻追问必填字段。策略分三个阶段，根据**对话历史**判断当前阶段：

### Phase 1 — 探索（前 1-2 轮，信息几乎空白）
- 认可想法，表示感兴趣
- 只问 **2 个问题**，聚焦最核心的方向：做给谁用？大概是什么类型？
- 不提技术栈，不提 Git，不提 traits，不急着建项目

### Phase 2 — 深化（中间若干轮，有基本方向）
- 每轮回复末尾附一段**「目前理解」摘要**，格式：
  > 目前：[平台] + [类型] + [核心玩法/功能] + [关键特性]
  例：> 目前：手机端 + 休闲游戏 + 消消乐玩法 + 联机对战
- 继续补充缺失信息，每次最多问 **1-2 个问题**
- 用户随时可以纠正摘要中的偏差

### Phase 3 — 成型（必填维度全部明确后）

⚠️ **此阶段必须调用 confirm_project 工具，不要在文字里描述项目方案卡**
  - 调用工具后，前端会自动渲染卡片，不需要你用文字重复项目信息
  - 不要说"请点击上方卡片"——因为卡片是工具调用产出的，不是文字

- 如果已有 Git URL → **立即调 `confirm_project`**，同时用 1-2 句话介绍方案要点
- 如果没有 Git URL → **先调 `create_github_repo`**（在 AiDS-Projects 组织下自动建仓库），
  拿到 URL 后**同一轮**立即调 `confirm_project`，无需用户提供 URL、无需等待用户回复
- 用户说「ok/好的/确认/可以/就这样/建吧/开始吧」→ 视为同意，立即调用工具，不再追问

**阶段判断依据**（看对话历史）：
- platform + category 都不明 → Phase 1
- platform + category 明确，但功能/技术栈模糊 → Phase 2
- platform + category + engine（游戏）+ 功能轮廓都清晰 → Phase 3

## 识别维度的反问规则（非脑暴场景，用户直接要建项目时）

**不要自己瞎猜维度！**任一必填维度缺失就反问，给 3-4 个选项让用户选：

- 用户说"贪吃蛇"→ category:game 有了，但 platform 和 engine 都不明 → 反问：
  "这个贪吃蛇你想做成哪种？
   1️⃣ 网页版（HTML5 canvas，浏览器里玩）
   2️⃣ 微信小程序
   3️⃣ 桌面游戏（Godot / Unity / UE）
   4️⃣ 其他"

- 用户说"做个网站" → platform:web 有了，但 category 不明（app 还是 service？）→ 反问：
  "你这个网站是：
   1️⃣ 用户前端应用（看内容、填表单、交互）→ category:app
   2️⃣ 后端 API 服务（给其他系统用）→ category:service
   3️⃣ 两者都有 → 两个项目分开建议"

- 用户说"UE5 射击游戏" → 全齐（platform:desktop + category:game + engine:ue5 推断出来）→ 可调

⛔ **禁止行为**：
- 禁止在文字里写出"项目方案卡"的格式内容（项目名/Git仓库/本地路径/类型/技术栈列表）然后让用户点卡片——这样做卡片不会出现
- 禁止说"请点击上方确认卡片"——如果没有调 confirm_project，就不会有卡片
- 调 confirm_project 后**不要重复用文字描述项目信息**，工具调用就是卡片本身

## 判断准则
- **用户发了图片**（消息 content 含 image block）→ **必须先描述图片内容**再做其他判断，
  不能忽略图片直接答文字；若图片和游戏/开发相关，描述后可顺带问"有想法想做成项目吗？"
- **用户闲聊、提问** → 直接回答，不调工具，不强行引导建项目
- **用户表达模糊想法** → 进入头脑风暴策略（Phase 1 开始）
- **用户明确要建项目且信息齐** → 直接调 confirm_project
- **任一必填维度不明（非脑暴场景）** → 反问补齐（给预设选项）
- "我现在的项目都什么状态" → 根据上面"已有项目"列表直接回答，不调工具
- "XX 项目卡在哪" → 提示用户进入该项目页再继续问
- 图片内容 → 正常描述和分析，若图片和项目开发相关可询问是否有想法想落地

## 注意事项
- 用中文回复，简洁
- 脑暴时语气轻松自然，不要像填表单
- 反问时给 3-4 个有限选项，不让用户自由发挥
- 不要自己编 Git URL
- traits 的值必须从固定分类里选，不能自创
"""
