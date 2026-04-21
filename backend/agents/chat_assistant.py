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
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent, ReactMode
from actions.chat.confirm_requirement import ConfirmRequirementAction
from actions.chat.confirm_bug import ConfirmBugAction
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

logger = logging.getLogger("agent.chat_assistant")


# 不对 LLM 暴露为 tool 的 Action 名（只能由后端内部调用）
_INTERNAL_ONLY_ACTIONS = {"create_requirement"}


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
        # Tier 2 — 重要产出物 / 诊断视图
        "document_generated": 2,
        "requirement_pipeline": 2,
        "ticket_status": 2,
        "requirement_logs": 2,
        # Tier 3 — 状态变更的回执
        "requirement_closed": 3,
        "requirement_paused": 3,
        "requirement_resumed": 3,
        "requirement_created": 3,
        # Tier 4 — 普通查询结果
        "git_result": 4,
        "error": 5,
    }

    def __init__(self, agent: "ChatAssistantAgent", project_id: str):
        self.agent = agent
        self.project_id = project_id
        self.primary_action_result: Optional[Dict[str, Any]] = None
        self._primary_tier: int = 99  # 越小越优先

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

        ctx = {"project_id": self.project_id, **tool_input}
        result = await action.run(ctx)
        data = result.data or {}

        # 按优先级更新 primary_action_result
        current_type = data.get("type", "")
        current_tier = self._TYPE_PRIORITY.get(current_type, 50)
        if current_tier <= self._primary_tier:
            self.primary_action_result = data
            self._primary_tier = current_tier

        # 返回给 LLM 的是 JSON 字符串（chat_with_tools 规范）
        return json.dumps(data, ensure_ascii=False)


class ChatAssistantAgent(BaseAgent):

    action_classes = [
        ConfirmRequirementAction,
        ConfirmBugAction,
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
    ]
    react_mode = ReactMode.REACT
    max_react_loop = 3   # 聊天场景不需要太多轮

    @property
    def agent_type(self) -> str:
        return "ChatAssistant"

    # ==================== Tool schemas ====================

    def _exposed_tool_schemas(self) -> List[Dict[str, Any]]:
        """返回可暴露给 LLM 的 tool schema 列表（内部 Action + MCP 外部工具）"""
        schemas = []
        for action in self._actions.values():
            if action.name in _INTERNAL_ONLY_ACTIONS:
                continue
            schema = getattr(action, "tool_schema", None)
            if schema:
                schemas.append(schema)

        # 追加外部 MCP 工具（name 已带 mcp__ 前缀，防冲突）
        try:
            from mcp_client import mcp_client
            schemas.extend(mcp_client.list_all_tool_schemas())
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
        tools = self._exposed_tool_schemas()

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

        # 兜底：LLM 啥也没说但工具执行了，用 action.message 或固定文案
        if not reply:
            if action:
                reply = action.get("message") or "操作已完成。"
            else:
                reply = "操作已完成。"

        return {
            "reply": reply,
            "action": action,
        }

    # ==================== 内部工具 ====================

    def _assemble_messages(
        self,
        history: Optional[List[Dict[str, str]]],
        user_message: str,
        images: Optional[List[str]],
    ) -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = []

        if history:
            for msg in history[-20:]:
                role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
                content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
                if role and content is not None:
                    messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": self._build_user_content(user_message, images)})
        return messages

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

        return f"""你是 AI 自动开发系统的智能助手，当前正在为项目「{project['name']}」提供服务。

## 项目信息
- 名称：{project['name']}
- 描述：{project.get('description') or '无描述'}
- 技术栈：{project.get('tech_stack') or '未指定'}
- Git 仓库：{project.get('git_repo_path') or '未配置'}
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
