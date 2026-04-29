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
from actions.chat.confirm_requirement import ConfirmRequirementAction
from actions.chat.confirm_bug import ConfirmBugAction
from actions.chat.confirm_project import ConfirmProjectAction
from actions.chat.create_requirement import CreateRequirementAction
from actions.chat.pause_requirement import PauseRequirementAction
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

logger = logging.getLogger("agent.chat_assistant")


# 不对 LLM 暴露为 tool 的 Action 名（只能由后端内部调用）
_INTERNAL_ONLY_ACTIONS = {"create_requirement"}

# 全局聊天（项目列表页，无 project_id）下可用的工具白名单。
# confirm_project：识别新建项目意图
# search_knowledge / search_ticket_history：全局模式下搜全库（无 project_id 过滤）
_GLOBAL_CHAT_TOOLS = {"confirm_project", "search_knowledge", "search_ticket_history"}


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
    _COLLECT_ALL_TYPES = {"confirm_requirement", "confirm_bug"}

    def __init__(self, agent: "ChatAssistantAgent", project_id: Optional[str] = None):
        """project_id=None 表示全局聊天场景（项目列表页），此时 ctx 里不注入 project_id"""
        self.agent = agent
        self.project_id = project_id
        self.primary_action_result: Optional[Dict[str, Any]] = None
        self._primary_tier: int = 99  # 越小越优先
        # 批量收集：confirm_requirement / confirm_bug 每次调用都保留，供前端渲染多张卡片
        self.all_confirm_results: List[Dict[str, Any]] = []

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
        result = await action.run(ctx)
        data = result.data or {}

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


class ChatAssistantAgent(BaseAgent):

    action_classes = [
        ConfirmRequirementAction,
        ConfirmBugAction,
        ConfirmProjectAction,          # 全局聊天用，暴露给 LLM
        CreateRequirementAction,       # 内部用，不暴露给 LLM
        PauseRequirementAction,
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
    ]
    react_mode = ReactMode.REACT
    max_react_loop = 3   # 聊天场景不需要太多轮

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
            if scope == "global" and action.name not in _GLOBAL_CHAT_TOOLS:
                continue
            if scope == "project" and action.name in _GLOBAL_CHAT_TOOLS:
                # confirm_project 不在项目内聊天里暴露——项目里不能再创项目
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

        system_prompt = self._build_system_prompt(project, project_context)
        messages = self._assemble_messages(history, user_message, images)

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
        }

    # ==================== 全局聊天入口（项目列表页，无 project_id） ====================

    async def chat_global(
        self,
        user_message: str,
        images: Optional[List[str]],
        history: Optional[List[Dict[str, str]]],
        projects_brief: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        全局聊天：用户在项目列表页使用 AI 助手，可能要求新建项目或单纯聊天。
        只暴露 confirm_project 一个工具；用户确认后由 /api/chat/confirm-create-project 端点落库。
        """
        from llm_client import llm_client, set_llm_context, clear_llm_context

        # v0.17: 用 user_message 预计算 preset 推荐，注入到 system prompt
        preset_suggestions = self._match_preset_suggestions(user_message)

        system_prompt = self._build_global_system_prompt(projects_brief, preset_suggestions)
        messages = self._assemble_messages(history, user_message, images)
        tools = self._exposed_tool_schemas(scope="global")

        executor = _ChatToolExecutor(self, project_id=None)

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

        return {"reply": reply, "action": action, "actions": actions}

    # ==================== 内部工具 ====================

    # ==================== 对话历史压缩（借鉴 MagicAI §6.4）====================
    # 参数默认值跟 MagicAI 一致，实测对主观任务效果好

    HISTORY_KEEP_RECENT_N = 6         # 最近 N 条全文保留
    HISTORY_MAX_RECENT_CHARS = 4000   # 最近 N 条每条上限
    HISTORY_OLDER_CHARS = 800         # 更早的每条压缩后上限
    HISTORY_MAX_TOTAL_CHARS = 8000    # 历史段总硬上限

    def _assemble_messages(
        self,
        history: Optional[List[Dict[str, str]]],
        user_message: str,
        images: Optional[List[str]],
    ) -> List[Dict[str, Any]]:
        """组装消息 + 压缩对话历史。

        策略（MagicAI 两级）：
          最近 N 条：全文保留（每条最多 HISTORY_MAX_RECENT_CHARS）
          更早的：压缩到 HISTORY_OLDER_CHARS / 条
          整段历史：总量超 HISTORY_MAX_TOTAL_CHARS 时从最老的开始删
        """
        messages: List[Dict[str, Any]] = []

        if history:
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

    def _build_system_prompt(self, project: dict, context: dict) -> str:
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

        # Skills 注入：ChatAssistant 不走 ActionNode，需在这里直接拼入 system prompt。
        # self._skills_prompt 由 BaseAgent.__init__() 从 skills.json 里 "inject_to: ChatAssistant" 的条目聚合而来。
        skills_section = (
            f"\n## 专业技能 (Skills)\n{self._skills_prompt}\n"
            if getattr(self, "_skills_prompt", "") else ""
        )

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

        return f"""你是 AI 自动开发系统的智能助手，当前正在为项目「{project['name']}」提供服务。

## 项目信息
- 名称：{project['name']}
- 描述：{project.get('description') or '无描述'}
- 技术栈：{project.get('tech_stack') or '未指定'}
- Git 仓库：{project.get('git_repo_path') or '未配置'}
{traits_line}
{ue_routing}
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
{artifacts_summary}
{skills_section}
## 你的能力
你配有一组工具（见 tools 参数），用于：
- 识别新需求/BUG → 先用 confirm_requirement / confirm_bug 产草稿让用户确认（不要直接创建）
- 管理需求状态 → pause / resume / close
- 查看项目 → git_log / git_list_branches / git_read_file
- 切换/合并分支 → git_switch_branch / git_merge
- 生成文档 → generate_document（直接写入 docs/ 并 commit+push）
- **诊断需求进度** → get_requirement_pipeline（"XX 卡在哪"）/
  get_ticket_status（工单详细状态）/ get_requirement_logs（最近活动 + 错误）

## 读取用户上传的文件
当消息中包含 `【附件：xxx.md】` 或其他文件内容时：
- 仔细阅读文件内容，结合项目上下文给出具体分析
- 需求文档 / PRD → **从文档中提取所有独立需求点，每个需求调用一次 `confirm_requirement`**
  （同一轮回复可连续调多次，前端会为每条需求渲染独立的确认卡片，用户逐条确认）
- 设计文档 / 技术方案 → 讨论实现思路，指出潜在风险
- 代码文件 → 审查逻辑，结合已有代码给出修改建议
- **不要只复述文件内容**，要给出有价值的分析和下一步行动建议

## 判断准则
- 用户**明确要求**新增/开发某功能（"帮我加…""做一个…""实现…功能"）→ 调 confirm_requirement
- 用户描述已有功能的缺陷/报错/崩溃/白屏 → 调 confirm_bug（不是需求）
- 用户单纯提问、描述现象、讨论方案 → 直接回答，不要调工具
- 信息已经在上面的上下文里可直接回答 → 不要调 git_* 工具，直接引用上下文作答

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

## 注意事项
- 用中文回复
- 回答简洁但有信息量
- 如果用户描述**真的**不清晰才追问；"重跑/重来/改颜色/加功能"这类指令是明确的，直接执行
- 需求 ID 不明确时用标题关键词模糊匹配（工具本身支持）
- 需求状态不允许当前操作时，工具会返回错误，据实告知用户
"""

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

        skills_section = (
            f"\n## 专业技能 (Skills)\n{self._skills_prompt}\n"
            if getattr(self, "_skills_prompt", "") else ""
        )

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

        return f"""你是 AI 自动开发系统的全局助手，当前用户在**项目列表页**，**还没有进入任何具体项目**。

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

**4. 读取用户上传的文件内容**
- 当消息中包含 `【附件：xxx.md】` 时，文件内容已内联在消息里，直接阅读分析。
- 典型用途：
  - 用户上传需求文档 → 帮助分析需求、识别项目类型和技术栈、推荐 traits / preset
  - 用户上传设计文档 → 讨论技术方案、提出改进建议
  - 信息足够时主动询问是否基于文档内容创建项目（调 confirm_project）
- **不要只复述文件内容**，要结合内容给出具体的分析和建议。

**对于查项目状态、涉及具体项目操作**：提示用户先点击进入那个项目再继续对话。

## 调 confirm_project 必填字段（**全齐了才能调**）

- **name**（必填）：项目名称
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

## 识别维度的反问规则（信息不全时务必反问）

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

## 判断准则
- **用户闲聊、提问、发图片、讨论技术方案** → 直接回答，不调工具，不强行引导建项目
- **用户明确表达想建项目** → 收集信息，信息齐了调 confirm_project
- **任一必填维度不明** → 反问补齐（给预设选项）
- "我现在的项目都什么状态" → 根据上面"已有项目"列表直接回答，不调工具
- "XX 项目卡在哪" → 提示用户进入该项目页再继续问
- 图片内容 → 正常描述和分析，若图片和项目开发相关可顺带询问是否要建项目

## 注意事项
- 用中文回复，简洁
- 反问时给 3-4 个有限选项，不让用户自由发挥
- 不要自己编 Git URL
- traits 的值必须从固定分类里选，不能自创
"""
