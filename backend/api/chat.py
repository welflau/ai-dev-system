"""
AI 自动开发系统 - 聊天 API
支持三种模式：
1. 全局聊天（项目内）：用户与 AI 自由对话，支持通过对话发起需求等操作
2. 全局聊天（无项目）：项目列表页的 AI 对话，支持创建项目
3. Job 聊天历史：加载某个工单的 AI 对话记录
"""
import base64
import json
import logging
import uuid
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from database import db
from utils import generate_id, now_iso
from events import event_manager

logger = logging.getLogger("chat")

router = APIRouter(prefix="/api/projects/{project_id}/chat", tags=["chat"])

# 全局聊天路由（不需要 project_id）
global_chat_router = APIRouter(prefix="/api/chat", tags=["global-chat"])


# ==================== 请求/响应模型 ====================

class ChatMessage(BaseModel):
    role: str = Field(..., description="消息角色: user / assistant / system")
    content: str = Field(..., description="消息内容")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户消息")
    history: Optional[List[ChatMessage]] = Field(default=None, description="历史消息（可选）")
    images: Optional[List[str]] = Field(default=None, description="图片列表，base64 data URL，如 data:image/png;base64,...")


class ChatResponse(BaseModel):
    reply: str = Field(..., description="AI 回复")
    action: Optional[Dict[str, Any]] = Field(default=None, description="执行的操作信息")
    actions: Optional[List[Dict[str, Any]]] = Field(default=None, description="批量操作卡片（文档分析等场景）")


class GroupChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户消息")
    agent: Optional[str] = Field(default=None, description="目标 Agent: DevAgent / TestAgent / OrchestratorAgent / ChatAssistant")
    history: Optional[List[ChatMessage]] = Field(default=None, description="历史消息（可选）")
    images: Optional[List[str]] = Field(default=None, description="图片 base64 列表")


class GroupChatResponse(BaseModel):
    agent: str = Field(..., description="响应的 Agent 名称")
    reply: str = Field(..., description="AI 回复")
    emoji: str = Field(..., description="Agent 头像 emoji")
    color: str = Field(..., description="Agent 主题色")


class GroupChatAllResponse(BaseModel):
    replies: List[GroupChatResponse] = Field(..., description="所有 Agent 的回复列表")


# Agent 配置
_AGENT_CONFIG = {
    "DevAgent": {
        "emoji": "👨‍💻",
        "color": "#58a6ff",
        "persona": """你是 DevAgent（开发 Agent），AI 自动开发系统中负责编写代码、实现功能的 Agent。
你的专长是代码设计、架构分析、技术方案、具体实现细节。
回复风格：专业、简洁，偏向技术角度，给出具体可行的建议或代码片段。
你在群聊中与用户和其他 Agent 协作，你清楚地知道自己是 DevAgent，不是普通助手。""",
    },
    "TestAgent": {
        "emoji": "🧪",
        "color": "#3fb950",
        "persona": """你是 TestAgent（测试 Agent），AI 自动开发系统中负责质量保障、测试用例设计、Bug 发现的 Agent。
你的专长是测试策略、边界条件分析、回归测试、自动化测试。
回复风格：严谨、细致，关注质量和可靠性，善于发现潜在问题。
你在群聊中与用户和其他 Agent 协作，你清楚地知道自己是 TestAgent，不是普通助手。""",
    },
    "OrchestratorAgent": {
        "emoji": "🎯",
        "color": "#d2a8ff",
        "persona": """你是 OrchestratorAgent（编排 Agent），AI 自动开发系统的核心调度 Agent，负责需求分析、工单拆分、任务协调。
你的专长是项目管理、需求拆解、任务优先级、跨 Agent 协调。
回复风格：宏观视角、条理清晰，善于把复杂需求分解为可执行步骤。
你在群聊中与用户和其他 Agent 协作，你清楚地知道自己是 OrchestratorAgent，不是普通助手。""",
    },
    "ChatAssistant": {
        "emoji": "🤖",
        "color": "#e6a817",
        "persona": """你是 AI 自动开发系统的智能助手，在群聊中帮助用户与各 Agent 协作。
你负责解答通用问题、协调讨论、提供综合建议。""",
    },
}

_DEFAULT_AGENT = "ChatAssistant"

# 关键词 -> Agent 映射（无 @ 时的自动路由）
_KEYWORD_ROUTES = {
    "代码": "DevAgent", "实现": "DevAgent", "开发": "DevAgent", "编写": "DevAgent",
    "架构": "DevAgent", "设计": "DevAgent", "函数": "DevAgent", "接口": "DevAgent",
    "bug": "TestAgent", "BUG": "TestAgent", "测试": "TestAgent", "用例": "TestAgent",
    "质量": "TestAgent", "验证": "TestAgent", "自动化": "TestAgent",
    "需求": "OrchestratorAgent", "工单": "OrchestratorAgent", "拆分": "OrchestratorAgent",
    "任务": "OrchestratorAgent", "计划": "OrchestratorAgent", "流程": "OrchestratorAgent",
}


# ==================== 聊天端点 ====================


@router.post("/group", response_model=GroupChatResponse)
async def group_chat(project_id: str, req: GroupChatRequest):
    """群聊 — 消息路由到对应 Agent 人格回复"""
    from llm_client import llm_client, set_llm_context, clear_llm_context

    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    # 确定响应 Agent
    agent_name = req.agent
    if not agent_name or agent_name not in _AGENT_CONFIG:
        # 无指定 Agent，根据关键词自动路由
        agent_name = _DEFAULT_AGENT
        msg_lower = req.message.lower()
        for kw, target in _KEYWORD_ROUTES.items():
            if kw.lower() in msg_lower:
                agent_name = target
                break

    agent_cfg = _AGENT_CONFIG[agent_name]

    # 获取项目上下文
    project_context = await _build_project_context(project_id, project)
    req_list = project_context.get("recent_requirements", [])
    req_summary = "\n".join(
        f"  - [{r['status']}] {r['title']} (ID: {r['id']})" for r in req_list[:5]
    ) or "  暂无需求"
    ticket_summary = project_context.get("ticket_summary", "暂无工单")

    system_prompt = f"""{agent_cfg['persona']}

## 当前项目：{project['name']}
- 描述：{project.get('description') or '无'}
- 技术栈：{project.get('tech_stack') or '未指定'}

## 需求概况
{req_summary}

## 工单概况
{ticket_summary}

请以 {agent_name} 的身份简洁地回复用户，不超过 300 字。"""

    messages = [{"role": "system", "content": system_prompt}]

    # 历史消息（过滤掉同 Agent 的连续上下文）
    if req.history:
        for msg in req.history[-10:]:
            messages.append({"role": msg.role, "content": msg.content})

    messages.append({"role": "user", "content": _build_user_content(req.message, req.images)})

    set_llm_context(project_id=project_id, agent_type=agent_name, action="group_chat")
    try:
        reply = await llm_client.chat(messages, temperature=0.75, max_tokens=1000)
        return GroupChatResponse(
            agent=agent_name,
            reply=reply.strip(),
            emoji=agent_cfg["emoji"],
            color=agent_cfg["color"],
        )
    finally:
        clear_llm_context()


@router.post("/group/all", response_model=GroupChatAllResponse)
async def group_chat_all(project_id: str, req: GroupChatRequest):
    """群聊 — 所有 Agent 并发回复，每人从自己视角发言"""
    import asyncio
    from llm_client import llm_client, set_llm_context, clear_llm_context

    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    # 获取项目上下文（只查一次）
    project_context = await _build_project_context(project_id, project)
    req_list = project_context.get("recent_requirements", [])
    req_summary = "\n".join(
        f"  - [{r['status']}] {r['title']} (ID: {r['id']})" for r in req_list[:5]
    ) or "  暂无需求"
    ticket_summary = project_context.get("ticket_summary", "暂无工单")

    history_msgs = []
    if req.history:
        for msg in req.history[-8:]:
            history_msgs.append({"role": msg.role, "content": msg.content})

    user_content = _build_user_content(req.message, req.images)

    # 三个主要 Agent 的顺序：先 Orchestrator 总览，再 Dev 出方案，最后 Test 把关
    participating_agents = ["OrchestratorAgent", "DevAgent", "TestAgent"]

    async def _call_agent(agent_name: str) -> GroupChatResponse:
        cfg = _AGENT_CONFIG[agent_name]
        system_prompt = f"""{cfg['persona']}

## 当前项目：{project['name']}
- 描述：{project.get('description') or '无'}
- 技术栈：{project.get('tech_stack') or '未指定'}

## 需求概况
{req_summary}

## 工单概况
{ticket_summary}

## 群聊规则
- 你正在参加一个多 Agent 群聊，其他 Agent（DevAgent、TestAgent、OrchestratorAgent）也会同时发言
- 请只从 **你自己的专业视角** 简短地回应用户，不要重复其他 Agent 会说的内容
- 回复控制在 150 字以内，简洁有力
- 不要说"我来补充一下"或"如 DevAgent 所说"之类的话，直接说你的观点"""

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history_msgs)
        messages.append({"role": "user", "content": user_content})

        set_llm_context(project_id=project_id, agent_type=agent_name, action="group_chat_all")
        try:
            reply = await llm_client.chat(messages, temperature=0.8, max_tokens=600)
            return GroupChatResponse(
                agent=agent_name,
                reply=reply.strip(),
                emoji=cfg["emoji"],
                color=cfg["color"],
            )
        finally:
            clear_llm_context()

    # 并发调用所有 Agent
    results = await asyncio.gather(*[_call_agent(a) for a in participating_agents], return_exceptions=True)

    replies = []
    for agent_name, result in zip(participating_agents, results):
        if isinstance(result, Exception):
            cfg = _AGENT_CONFIG[agent_name]
            replies.append(GroupChatResponse(
                agent=agent_name,
                reply="（暂时无法回复）",
                emoji=cfg["emoji"],
                color=cfg["color"],
            ))
        else:
            replies.append(result)

    return GroupChatAllResponse(replies=replies)


@router.post("", response_model=ChatResponse)
async def chat_with_ai(project_id: str, req: ChatRequest):
    """全局聊天 — 用户与 AI 自由对话 + 指令操作

    双轨：
    - CHAT_USE_AGENT=true（P3 起默认）→ 走 ChatAssistantAgent + tool_use；
      任何异常自动降级到旧 [ACTION:XXX] 文本协议路径，保证 SLA
    - CHAT_USE_AGENT=false → 直接走旧路径
    """
    from config import settings

    # 校验项目存在
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    # 获取项目上下文
    project_context = await _build_project_context(project_id, project)

    if settings.CHAT_USE_AGENT:
        try:
            return await _chat_via_agent(project_id, project, project_context, req)
        except HTTPException:
            # 业务级错误（404 等）不降级，直接抛
            raise
        except Exception as e:
            logger.warning(
                "新路径失败，降级到旧 [ACTION:XXX] 文本协议路径: %s: %s",
                type(e).__name__, e,
            )
            # 落地一条 fallback 事件，方便统计 new-path 失败率
            try:
                await db.insert("ticket_logs", {
                    "id": generate_id("LOG"),
                    "ticket_id": None,
                    "subtask_id": None,
                    "requirement_id": None,
                    "project_id": project_id,
                    "agent_type": "ChatAssistant",
                    "action": "chat_fallback",
                    "from_status": None,
                    "to_status": None,
                    "detail": json.dumps(
                        {"reason": f"{type(e).__name__}: {e}"[:500]},
                        ensure_ascii=False,
                    ),
                    "level": "warning",
                    "created_at": now_iso(),
                })
            except Exception:
                pass  # 日志写失败不阻断主流程

    return await _chat_via_legacy(project_id, project, project_context, req)


async def _chat_via_legacy(
    project_id: str,
    project: dict,
    project_context: dict,
    req: ChatRequest,
) -> ChatResponse:
    """旧路径：LLM + [ACTION:XXX] 文本协议 + _parse_and_execute_action 分发
    保留为新路径的降级兜底；P4 会随 _execute_* 一起清理
    """
    from llm_client import llm_client, set_llm_context, clear_llm_context

    # 构建消息
    system_prompt = _build_system_prompt(project, project_context)
    messages = [{"role": "system", "content": system_prompt}]

    if req.history:
        for msg in req.history[-20:]:
            messages.append({"role": msg.role, "content": msg.content})

    messages.append({"role": "user", "content": _build_user_content(req.message, req.images)})

    set_llm_context(
        project_id=project_id,
        agent_type="ChatAssistant",
        action="global_chat",
    )

    try:
        response = await llm_client.chat(messages, temperature=0.7, max_tokens=16000)

        has_action_tag = "[ACTION:" in response
        action_result = await _parse_and_execute_action(project_id, project, response)
        logger.info("聊天指令解析: has_tag=%s, result_type=%s", has_action_tag, action_result.get("type") if action_result else "None")

        saved_image_urls = None
        if action_result and action_result.get("type") in ("confirm_requirement", "confirm_bug") and req.images:
            saved_image_urls = await _save_images(project_id, req.images)
            if saved_image_urls:
                action_result["images"] = saved_image_urls

        clean_reply = _clean_action_tags(response)
        if not clean_reply:
            if action_result and action_result.get("type") == "document_generated":
                clean_reply = f"文档「{action_result.get('title', action_result.get('path', '文档'))}」已生成。"
            elif action_result and action_result.get("message"):
                clean_reply = action_result["message"]
            else:
                clean_reply = "操作已完成。"

        if saved_image_urls is not None:
            await _save_chat_message(project_id, "user", req.message, saved_urls=saved_image_urls)
        else:
            await _save_chat_message(project_id, "user", req.message, images=req.images)
        await _save_chat_message(project_id, "assistant", clean_reply, action=action_result)

        return ChatResponse(reply=clean_reply, action=action_result)

    finally:
        clear_llm_context()


async def _chat_via_agent(
    project_id: str,
    project: dict,
    project_context: dict,
    req: ChatRequest,
) -> ChatResponse:
    """新路径：走 ChatAssistantAgent + tool_use（默认路径）"""
    import agent_registry as _ar

    # 懒初始化（首次调用时触发 discover_agents）
    registry = _ar.get_registry()
    if not registry:
        _ar.discover_agents()
        registry = _ar.get_registry()

    agent_cls = registry.get("ChatAssistant")
    if not agent_cls:
        # 注册失败属于可自愈范围，抛一般异常让外层降级接手
        raise RuntimeError("ChatAssistant agent 未注册")
    agent = agent_cls()

    history_list = [{"role": m.role, "content": m.content} for m in (req.history or [])]

    agent_result = await agent.chat(
        user_message=req.message,
        images=req.images,
        history=history_list,
        project=project,
        project_context=project_context,
    )

    reply = agent_result.get("reply") or "操作已完成。"
    action_result = agent_result.get("action")

    logger.info(
        "ChatAssistantAgent 返回: action_type=%s",
        (action_result or {}).get("type") if action_result else "None",
    )

    saved_image_urls = None
    if action_result and action_result.get("type") in ("confirm_requirement", "confirm_bug") and req.images:
        saved_image_urls = await _save_images(project_id, req.images)
        if saved_image_urls:
            action_result["images"] = saved_image_urls

    if saved_image_urls is not None:
        await _save_chat_message(project_id, "user", req.message, saved_urls=saved_image_urls)
    else:
        await _save_chat_message(project_id, "user", req.message, images=req.images)
    await _save_chat_message(project_id, "assistant", reply, action=action_result)

    return ChatResponse(reply=reply, action=action_result)


class SaveToRepoRequest(BaseModel):
    filename: str = Field(..., description="文件路径，如 docs/note.md")
    content: str = Field(..., description="文件内容")


class ConfirmRequirementRequest(BaseModel):
    title: str
    description: str = ""
    priority: str = "medium"
    images: Optional[List[str]] = None  # 已保存的图片 URL 列表，如 ["/chat-images/..."]


class ConfirmBugRequest(BaseModel):
    title: str
    description: str = ""
    priority: str = "high"
    requirement_id: Optional[str] = None
    images: Optional[List[str]] = None  # 已保存的图片 URL 列表


@router.post("/confirm-create-bug")
async def confirm_create_bug(project_id: str, req: ConfirmBugRequest):
    """用户确认后真正创建 BUG 并触发修复工作流"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")
    if req.priority not in ("critical", "high", "medium", "low"):
        raise HTTPException(400, "priority 无效")

    # 将图片 URL 以 Markdown 形式追加到描述末尾
    description = req.description
    if req.images:
        img_md = "\n\n" + "\n\n".join(
            f"![截图 {i+1}]({url})" for i, url in enumerate(req.images)
        )
        description = description + img_md

    from utils import generate_id, now_iso
    bug_id = generate_id("bug")
    now = now_iso()
    await db.insert("bugs", {
        "id": bug_id,
        "project_id": project_id,
        "requirement_id": req.requirement_id,
        "title": req.title,
        "description": description,
        "priority": req.priority,
        "status": "open",
        "version_id": None,
        "fix_notes": None,
        "created_at": now,
        "updated_at": now,
        "fixed_at": None,
    })
    logger.info("🐛 BUG 已创建（来自聊天）: %s [%s]", req.title, bug_id)
    bug = await db.fetch_one("SELECT * FROM bugs WHERE id = ?", (bug_id,))
    return {
        "type": "bug_created",
        "bug_id": bug_id,
        "message": f"BUG「{req.title}」已创建",
        "bug": bug,
    }


@router.post("/confirm-create-requirement")
async def confirm_create_requirement(project_id: str, req: ConfirmRequirementRequest):
    """用户确认后真正创建需求"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    # 将图片 URL 以 Markdown 形式追加到描述末尾
    description = req.description
    if req.images:
        img_md = "\n\n" + "\n\n".join(
            f"![截图 {i+1}]({url})" for i, url in enumerate(req.images)
        )
        description = description + img_md

    from actions.chat.create_requirement import CreateRequirementAction
    action_result = await CreateRequirementAction().run({
        "project_id": project_id,
        "title": req.title,
        "description": description,
        "priority": req.priority,
    })
    result = action_result.data
    if result.get("type") == "error":
        raise HTTPException(400, result["message"])

    # 更新 chat_messages 中的 action_data（confirm → created），刷新后不再显示按钮
    import json as _json
    await db.execute(
        """UPDATE chat_messages SET action_type = 'requirement_created',
           action_data = ? WHERE project_id = ? AND action_type = 'confirm_requirement'
           AND action_data LIKE ?""",
        (_json.dumps(result, ensure_ascii=False), project_id, f'%{req.title[:30]}%'),
    )

    return result


@router.post("/save-to-repo")
async def save_chat_to_repo(project_id: str, req: SaveToRepoRequest):
    """将聊天内容保存为文件到项目 Git 仓库"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    import re
    # 安全过滤文件名（允许 docs/ 前缀 + 英文文件名）
    safe_path = re.sub(r'[^\w\-./]', '', req.filename).lstrip('/')
    if not safe_path.endswith('.md'):
        safe_path += '.md'

    from git_manager import git_manager
    try:
        if not git_manager.repo_exists(project_id):
            await git_manager.init_repo(project_id, project["name"])
        await git_manager.write_file(project_id, safe_path, req.content)
        commit_hash = await git_manager.commit(
            project_id,
            f"[Doc] 保存聊天导出: {safe_path}",
            author="ChatAssistant",
        )
        await git_manager.push(project_id)
        logger.info("💾 聊天内容已保存到仓库: %s (commit: %s)", safe_path, commit_hash)
        return {"status": "ok", "path": safe_path, "commit": commit_hash}
    except Exception as e:
        logger.error("保存到仓库失败: %s", e)
        raise HTTPException(500, f"保存失败: {str(e)}")


class ActionStatePatchRequest(BaseModel):
    """v0.19.1 action state 持久化：前端点击卡片按钮成功后上报状态"""
    state: str = Field(..., pattern="^(pending|executed|cancelled)$")
    result: Optional[Dict[str, Any]] = Field(default=None, description="执行产物摘要，可选")


@router.patch("/messages/{message_id}/action-state")
async def patch_message_action_state(
    project_id: str, message_id: str, req: ActionStatePatchRequest,
):
    """更新某条聊天消息的 action_state（pending→executed / cancelled）
    用于卡片点击幂等：刷新后前端看到 state=executed 就渲染历史摘要而非可点按钮。
    """
    msg = await db.fetch_one(
        "SELECT id, project_id, action_type FROM chat_messages WHERE id = ? AND project_id = ?",
        (message_id, project_id),
    )
    if not msg:
        raise HTTPException(404, "消息不存在")

    update: Dict[str, Any] = {"action_state": req.state}
    if req.result is not None:
        update["action_result"] = json.dumps(req.result, ensure_ascii=False)

    await db.update("chat_messages", update, "id = ?", (message_id,))
    return {"ok": True, "message_id": message_id, "state": req.state}


@router.get("/history")
async def get_chat_history(project_id: str, limit: int = 50):
    """获取项目全局聊天历史"""
    # 校验项目存在
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    rows = await db.fetch_all(
        """SELECT * FROM chat_messages
           WHERE project_id = ?
           ORDER BY created_at DESC
           LIMIT ?""",
        (project_id, limit),
    )
    # 倒序返回（最新在底部）
    rows.reverse()
    # 解析 images_json 为列表；修复旧记录中 content 为空的问题
    messages = []
    for row in rows:
        msg = dict(row)
        msg["images"] = json.loads(msg.pop("images_json", None) or "[]")
        # v0.19.1 action_result JSON → dict 给前端直接用
        raw_ar = msg.get("action_result")
        if isinstance(raw_ar, str) and raw_ar:
            try:
                msg["action_result"] = json.loads(raw_ar)
            except Exception:
                pass  # 保持字符串，前端容错
        # 旧记录 assistant content 可能为空（历史 bug），用 action_data 的 message 填充
        if msg["role"] == "assistant" and not (msg.get("content") or "").strip():
            action_data = json.loads(msg.get("action_data") or "{}")
            if action_data.get("type") == "document_generated":
                msg["content"] = f"文档「{action_data.get('title', action_data.get('path', '文档'))}」已生成。"
            elif action_data.get("message"):
                msg["content"] = action_data["message"]
            else:
                msg["content"] = "操作已完成。"
        messages.append(msg)
    return {"messages": messages, "total": len(messages)}


# ==================== 附件上传 ====================

# 支持的文件类型配置
_TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".py", ".js", ".ts", ".jsx", ".tsx",
    ".html", ".css", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".sh", ".bash", ".sql", ".xml", ".csv", ".log", ".rs", ".go",
    ".java", ".cpp", ".c", ".h", ".rb", ".php", ".swift", ".kt",
}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
_PDF_EXT = ".pdf"
_DOCX_EXT = ".docx"
_MAX_FILE_SIZE = 10 * 1024 * 1024   # 10MB
_MAX_TEXT_CHARS = 20000              # 最多提取前 20000 字符


@router.post("/upload-attachment")
async def upload_chat_attachment(
    project_id: str,
    file: UploadFile = File(...),
):
    """
    上传聊天附件。
    - 图片 → 返回 base64 data URL（前端直接用于 vision）
    - 文本/代码 → 提取文本内容返回
    - PDF → 提取文本内容返回
    - Word → 提取文本内容返回
    """
    filename = file.filename or "unknown"
    ext = Path(filename).suffix.lower()

    raw = await file.read()
    if len(raw) > _MAX_FILE_SIZE:
        raise HTTPException(413, f"文件过大（最大 {_MAX_FILE_SIZE // 1024 // 1024}MB）")

    # ---- 图片 ----
    if ext in _IMAGE_EXTS:
        mime = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/jpeg",
        }.get(ext, "image/jpeg")
        data_url = f"data:{mime};base64," + base64.b64encode(raw).decode()
        return {"type": "image", "filename": filename, "data_url": data_url}

    # ---- PDF ----
    if ext == _PDF_EXT:
        text = _extract_pdf(raw, filename)
        return {"type": "document", "filename": filename, "text": text[:_MAX_TEXT_CHARS]}

    # ---- Word ----
    if ext == _DOCX_EXT:
        text = _extract_docx(raw, filename)
        return {"type": "document", "filename": filename, "text": text[:_MAX_TEXT_CHARS]}

    # ---- 纯文本 / 代码 ----
    if ext in _TEXT_EXTS or ext == "":
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            text = raw.decode("latin-1", errors="replace")
        return {"type": "document", "filename": filename, "text": text[:_MAX_TEXT_CHARS]}

    raise HTTPException(415, f"不支持的文件类型: {ext or '(无扩展名)'}，支持：图片、PDF、Word、文本/代码文件")


def _extract_pdf(raw: bytes, filename: str) -> str:
    try:
        import io
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        pages = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():
                pages.append(f"[第{i+1}页]\n{text}")
        return "\n\n".join(pages) if pages else "(PDF 无可提取文本)"
    except Exception as e:
        logger.warning("PDF 解析失败 %s: %s", filename, e)
        return f"(PDF 解析失败: {e})"


def _extract_docx(raw: bytes, filename: str) -> str:
    try:
        import io
        from docx import Document
        doc = Document(io.BytesIO(raw))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs) if paragraphs else "(Word 文档无可提取文本)"
    except Exception as e:
        logger.warning("Word 解析失败 %s: %s", filename, e)
        return f"(Word 解析失败: {e})"


def _content_to_display_text(content: Any) -> str:
    """把 LLM 消息的 content 字段展平成纯文本，供前端对话 feed 展示。

    Anthropic 格式下 content 可能是：
    - str：直接返回
    - list of blocks：每个 block 是 {"type": "text"|"tool_use"|"tool_result", ...}
      - text block → 取 "text"
      - tool_use block → "[tool: xxx(args)]"
      - tool_result block → "[tool_result: ...]"
    其他类型兜底为 repr()，永不返回非字符串。
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict):
                parts.append(str(block))
                continue
            btype = block.get("type")
            if btype == "text":
                parts.append(block.get("text", ""))
            elif btype == "tool_use":
                name = block.get("name", "?")
                parts.append(f"[tool: {name}(…)]")
            elif btype == "tool_result":
                inner = block.get("content", "")
                inner_text = _content_to_display_text(inner) if not isinstance(inner, str) else inner
                parts.append(f"[tool_result] {inner_text}")
            else:
                parts.append(str(block))
        return "\n".join(p for p in parts if p)
    if content is None:
        return ""
    return str(content)


@router.get("/tickets/conversations")
async def get_all_ticket_conversations(project_id: str):
    """获取项目下所有工单的 AI 对话记录（统一 Feed）"""
    # 校验项目存在
    project = await db.fetch_one("SELECT id FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    # 获取所有工单
    tickets = await db.fetch_all(
        "SELECT id, title, status, requirement_id FROM tickets WHERE project_id = ? ORDER BY created_at ASC",
        (project_id,),
    )
    if not tickets:
        return {"tickets": [], "total_tickets": 0, "total_messages": 0}

    # 批量查 LLM 会话记录
    conversations = await db.fetch_all(
        """SELECT id, ticket_id, agent_type, action, model, input_tokens, output_tokens,
                  duration_ms, status, created_at, messages, response
           FROM llm_conversations
           WHERE project_id = ? AND ticket_id IS NOT NULL
           ORDER BY created_at ASC""",
        (project_id,),
    )

    # 批量查重要 ticket_logs（状态变更、分派、完成等）
    logs = await db.fetch_all(
        """SELECT id, ticket_id, agent_type, action, from_status, to_status, detail, level, created_at
           FROM ticket_logs
           WHERE project_id = ? AND ticket_id IS NOT NULL
             AND action IN ('assign', 'complete', 'accept', 'reject', 'error', 'start', 'llm_call')
           ORDER BY created_at ASC""",
        (project_id,),
    )

    # 按 ticket_id 分组
    conv_by_ticket = {}
    for conv in conversations:
        tid = conv["ticket_id"]
        if tid not in conv_by_ticket:
            conv_by_ticket[tid] = []

        # 提取 user prompt
        try:
            msgs = json.loads(conv["messages"]) if conv["messages"] else []
        except (json.JSONDecodeError, TypeError):
            msgs = []
        user_msg = ""
        for m in msgs:
            if m.get("role") == "user":
                user_msg = _content_to_display_text(m.get("content", ""))

        conv_by_ticket[tid].append({
            "type": "conversation",
            "id": conv["id"],
            "role": "user",
            "content": user_msg[:500] if user_msg else f"[{conv['agent_type']} / {conv['action']}]",
            "agent_type": conv["agent_type"],
            "action": conv["action"],
            "created_at": conv["created_at"],
            "is_agent": True,
        })
        conv_by_ticket[tid].append({
            "type": "conversation",
            "id": conv["id"] + "_resp",
            "role": "assistant",
            "content": conv["response"] or "",
            "agent_type": conv["agent_type"],
            "action": conv["action"],
            "model": conv["model"],
            "input_tokens": conv["input_tokens"],
            "output_tokens": conv["output_tokens"],
            "duration_ms": conv["duration_ms"],
            "status": conv["status"],
            "created_at": conv["created_at"],
            "is_agent": True,
        })

    # 合并 logs
    for log in logs:
        tid = log["ticket_id"]
        if tid not in conv_by_ticket:
            conv_by_ticket[tid] = []
        detail_msg = ""
        if log["detail"]:
            try:
                detail_obj = json.loads(log["detail"])
                detail_msg = detail_obj.get("message", "")
            except (json.JSONDecodeError, TypeError):
                detail_msg = log["detail"]
        conv_by_ticket[tid].append({
            "type": "log",
            "id": log["id"],
            "agent_type": log["agent_type"] or "System",
            "action": log["action"],
            "from_status": log["from_status"],
            "to_status": log["to_status"],
            "message": detail_msg,
            "level": log["level"],
            "created_at": log["created_at"],
        })

    # 每个 ticket 内按时间排序
    result_tickets = []
    total_messages = 0
    for t in tickets:
        messages = conv_by_ticket.get(t["id"], [])
        messages.sort(key=lambda m: m.get("created_at", ""))
        total_messages += len(messages)
        result_tickets.append({
            "id": t["id"],
            "title": t["title"],
            "status": t["status"],
            "messages": messages,
        })

    return {
        "tickets": result_tickets,
        "total_tickets": len(tickets),
        "total_messages": total_messages,
    }


@router.get("/ticket/{ticket_id}/conversations")
async def get_ticket_conversations(project_id: str, ticket_id: str):
    """获取工单的 AI 对话记录"""
    # 校验工单存在
    ticket = await db.fetch_one(
        "SELECT * FROM tickets WHERE id = ? AND project_id = ?",
        (ticket_id, project_id),
    )
    if not ticket:
        raise HTTPException(404, "工单不存在")

    # 获取 LLM 会话记录
    conversations = await db.fetch_all(
        """SELECT id, agent_type, action, model, input_tokens, output_tokens,
                  duration_ms, status, created_at, messages, response
           FROM llm_conversations
           WHERE ticket_id = ?
           ORDER BY created_at ASC""",
        (ticket_id,),
    )

    # 转换为聊天消息格式
    chat_messages = []
    for conv in conversations:
        # 提取 prompt 中的 user 消息
        try:
            msgs = json.loads(conv["messages"]) if conv["messages"] else []
        except (json.JSONDecodeError, TypeError):
            msgs = []

        # 取最后一条 user 消息作为用户输入
        # 注意：tool_use 场景下 content 可能是 list of blocks（Anthropic 多段格式），
        # 需展平成纯文本给前端显示
        user_msg = ""
        for m in msgs:
            if m.get("role") == "user":
                user_msg = _content_to_display_text(m.get("content", ""))

        chat_messages.append({
            "id": conv["id"],
            "role": "user",
            "content": user_msg[:500] if user_msg else f"[{conv['agent_type']} / {conv['action']}]",
            "agent_type": conv["agent_type"],
            "action": conv["action"],
            "created_at": conv["created_at"],
            "is_agent": True,
        })

        chat_messages.append({
            "id": conv["id"] + "_resp",
            "role": "assistant",
            "content": conv["response"] or "",
            "agent_type": conv["agent_type"],
            "action": conv["action"],
            "model": conv["model"],
            "input_tokens": conv["input_tokens"],
            "output_tokens": conv["output_tokens"],
            "duration_ms": conv["duration_ms"],
            "status": conv["status"],
            "created_at": conv["created_at"],
            "is_agent": True,
        })

    return {
        "ticket": {
            "id": ticket["id"],
            "title": ticket["title"],
            "status": ticket["status"],
        },
        "messages": chat_messages,
        "total": len(conversations),
    }


# ==================== 内部方法 ====================


def _build_system_prompt(project: dict, context: dict) -> str:
    """构建系统提示词"""
    req_list = context.get("recent_requirements", [])
    req_summary = ""
    if req_list:
        req_lines = []
        for r in req_list[:10]:
            req_lines.append(f"  - [{r['status']}] {r['title']} (ID: {r['id']})")
        req_summary = "\n".join(req_lines)
    else:
        req_summary = "  暂无需求"

    ticket_summary = context.get("ticket_summary", "暂无工单")
    file_tree = context.get("file_tree", "")
    key_files_content = context.get("key_files_content", "")
    artifacts_summary = context.get("artifacts_summary", "暂无产物")
    knowledge_content = context.get("knowledge_content", "")

    return f"""你是 AI 自动开发系统的智能助手，当前正在为项目「{project['name']}」提供服务。

## 项目信息
- 名称：{project['name']}
- 描述：{project.get('description') or '无描述'}
- 技术栈：{project.get('tech_stack') or '未指定'}
- Git 仓库：{project.get('git_repo_path') or '未配置'}
{(chr(10) + '## 项目知识库' + chr(10) + knowledge_content) if knowledge_content else ''}
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

## 你的能力
1. **回答项目问题**：你可以直接访问项目的文件树和文档内容，回答关于项目代码、架构、设计、测试报告等任何问题
2. **创建需求**：当用户**明确要求**新增/开发某个功能时，帮助起草需求让用户确认；单纯提问或描述现有问题时不要主动创建需求
3. **管理需求状态**：暂停、恢复、关闭需求的执行
4. **查看状态**：汇报当前项目进展、工单状态
5. **技术建议**：基于项目技术栈和已有代码给出建议
6. **生成文档**：可以基于项目内容生成设计文档、分析报告等
7. **Git 操作**：切换分支、查看分支列表、查看提交日志、查看文件内容、合并分支
8. **上报 BUG**：当用户描述已有功能出现缺陷、错误、崩溃、白屏、接口异常等问题时，帮助上报 BUG（注意：BUG 是「已有功能出了问题」，而非新功能需求）

## 操作指令格式
当你判断用户想要执行操作时，在回复末尾附加以下格式的指令标记（必须是独立一行）：

### 创建需求
**只有**当用户**明确表达**想要新增/开发某个功能时，才提出需求草稿让用户确认，例如：
- ✅ 「我想要...」「帮我开发...」「新增一个...」「加个功能...」「做一个...」「实现...功能」
- ❌ 用户只是在提问、描述现象、反馈问题、讨论方案、聊天闲谈 → **不要生成此指令**
- ❌ 用户描述的是 BUG / 报错 / 崩溃 / 异常 → **不要用此指令，应使用下面的 CONFIRM_BUG**

满足条件时，先提出草稿，不要直接创建：
[ACTION:CONFIRM_REQUIREMENT]
{{"title": "需求标题", "description": "详细描述", "priority": "medium"}}
[/ACTION]

注意：只有用户在界面上点击「确认创建」后才会真正创建需求，不要使用 CREATE_REQUIREMENT。

### 上报 BUG
**当用户描述的是已有功能出现的问题**（缺陷、报错、崩溃、白屏、接口报错、功能不正常等），**必须使用此指令**，不要创建需求：
[ACTION:CONFIRM_BUG]
{{"title": "BUG 标题", "description": "复现步骤/现象描述", "priority": "high", "requirement_id": null}}
[/ACTION]

注意：
- BUG 与需求的区别：BUG 是「已有功能出了问题」，需求是「希望新增或改变某个功能」
- requirement_id 若能从上下文判断 BUG 属于哪个需求则填写，否则填 null
- 只有用户点击「确认上报」后才会真正创建 BUG

### 暂停需求
当用户想暂停某个需求的执行时使用（需求必须处于 analyzing/decomposed/in_progress 状态）：
[ACTION:PAUSE_REQUIREMENT]
{{"requirement_id": "需求ID", "reason": "暂停原因"}}
[/ACTION]

### 恢复需求
当用户想恢复已暂停的需求时使用（需求必须处于 paused 状态）：
[ACTION:RESUME_REQUIREMENT]
{{"requirement_id": "需求ID"}}
[/ACTION]

### 关闭需求
当用户想关闭/取消某个需求时使用（终态需求不可关闭）：
[ACTION:CLOSE_REQUIREMENT]
{{"requirement_id": "需求ID", "reason": "关闭原因"}}
[/ACTION]

### 生成文档
当用户要求生成设计报告、技术方案、API 文档、分析报告等文档时使用（不需要走开发流程，直接生成）：
[ACTION:GENERATE_DOCUMENT]
filename: english-filename.md
title: 文档标题
---
完整的 Markdown 文档内容放在 --- 分隔线下面...
（可以包含任何 Markdown 格式：标题、表格、代码块等）
[/ACTION]

注意：
- filename 必须是英文，以 .md 结尾
- --- 分隔线上面是元数据（filename 和 title），下面是文档正文
- 文档会自动保存到项目仓库的 docs/ 目录并 commit + push
- 适合：设计报告、技术方案、API 文档、项目总结、竞品分析等
- 直接生成完整内容，不要省略

### Git 操作

切换分支：
[ACTION:GIT_SWITCH_BRANCH]
{{"branch": "分支名"}}
[/ACTION]

查看分支列表（用户问"有哪些分支"、"当前在哪个分支"时使用）：
[ACTION:GIT_LIST_BRANCHES]
{{}}
[/ACTION]

查看提交日志（用户问"最近提交了什么"、"git log"时使用）：
[ACTION:GIT_LOG]
{{"limit": 10}}
[/ACTION]

查看文件内容（用户问"看一下 xxx 文件的内容"时使用）：
[ACTION:GIT_READ_FILE]
{{"path": "文件相对路径"}}
[/ACTION]

合并分支（用户说"合并 develop 到 main"时使用）：
[ACTION:GIT_MERGE]
{{"source": "源分支", "target": "目标分支"}}
[/ACTION]

priority 可选值：critical, high, medium, low

## 注意事项
- 用中文回复
- 回答简洁但有信息量
- 当用户询问项目文件、代码、文档内容时，直接引用上面的文件树和文档内容来回答，不要说"无法访问"
- 如果用户的描述不够清晰，先询问细节再执行操作
- 如果不确定用户想操作哪个需求，列出当前需求让用户选择
- 如果需求 ID 不明确，用标题关键词匹配当前需求列表中的需求
- 暂停/恢复/关闭操作必须确认需求存在且状态允许该操作

## 说到做到（重要）
- **禁止只说不做**：凡回复中出现"让我查看/检查/看看/查一下/确认一下 XX"、"我需要查看 XX"、"让我先 XX" 之类的措辞，**必须**在同一轮回复末尾附上对应的 [ACTION:...] 指令，由系统实际执行。
- **一次回复最多一个 action**：如果需要多步查询（比如既想看提交又想看分支），选最关键的那一个发出；等结果回来后再在下一轮发起下一个。**禁止**在同一条回复里写两个 [ACTION:...] 块。
- 典型对应：
  - "查看提交记录/最近提交/开发进展" → `[ACTION:GIT_LOG]`
  - "查看分支/当前在哪个分支" → `[ACTION:GIT_LIST_BRANCHES]`
  - "看一下 XX 文件内容" → `[ACTION:GIT_READ_FILE]`
  - "切换到 XX 分支" → `[ACTION:GIT_SWITCH_BRANCH]`
- 如果你确认不需要真的调用工具（例如信息已经在上面的上下文里直接可得），**不要**用"让我查看"这类措辞，直接基于上下文作答即可。
- 不要把"查看 XX"留给下一轮——当前轮是你唯一的执行机会。
"""


def _load_knowledge_content(project_id: str, global_limit: int = 2000, project_limit: int = 3000) -> str:
    """读取全局知识库 + 项目知识库，返回拼接文本（带 token 预算控制）"""
    from config import BASE_DIR as _BASE_DIR
    from pathlib import Path as _Path

    parts = []

    def _read_docs(docs_dir: _Path, label: str, char_limit: int):
        if not docs_dir.exists():
            return
        files = sorted(docs_dir.glob("*.md"), key=lambda f: f.name)
        total = 0
        section_parts = []
        for f in files:
            if total >= char_limit:
                break
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                remaining = char_limit - total
                if len(text) > remaining:
                    text = text[:remaining] + "\n...(truncated)"
                section_parts.append(f"#### {f.name}\n{text}")
                total += len(text)
            except Exception:
                pass
        if section_parts:
            parts.append(f"### {label}\n" + "\n\n".join(section_parts))

    _read_docs(_BASE_DIR / "docs", "全局规范", global_limit)
    _read_docs(_BASE_DIR / "projects" / project_id / "docs", "项目文档", project_limit)

    return "\n\n".join(parts)


async def _build_project_context(project_id: str, project: dict) -> dict:
    """构建项目上下文信息（含文件树和关键文档内容）"""
    # 获取最近需求
    requirements = await db.fetch_all(
        "SELECT id, title, status, priority, branch_name, created_at FROM requirements WHERE project_id = ? ORDER BY created_at DESC LIMIT 10",
        (project_id,),
    )

    # 获取工单统计
    ticket_stats = await db.fetch_all(
        "SELECT status, COUNT(*) as count FROM tickets WHERE project_id = ? GROUP BY status",
        (project_id,),
    )

    ticket_summary_parts = []
    total_tickets = 0
    for ts in ticket_stats:
        ticket_summary_parts.append(f"{ts['status']}: {ts['count']}")
        total_tickets += ts["count"]

    if total_tickets > 0:
        ticket_summary = f"共 {total_tickets} 个工单 — " + ", ".join(ticket_summary_parts)
    else:
        ticket_summary = "暂无工单"

    # === 读取项目仓库文件树 ===
    file_tree = ""
    key_files_content = ""
    try:
        from git_manager import git_manager
        repo_dir = git_manager._repo_path(project_id)
        if repo_dir.exists():
            from pathlib import Path
            # 文件树（最多 100 个文件）
            all_files = []
            for f in sorted(repo_dir.rglob("*")):
                if f.is_file() and ".git" not in str(f):
                    rel = f.relative_to(repo_dir)
                    size = f.stat().st_size
                    all_files.append(f"{rel} ({size}B)")
                    if len(all_files) >= 100:
                        break
            file_tree = "\n".join(all_files) if all_files else "（空仓库）"

            # 读取关键文档内容（README, docs/*.md, index.html 等，最多 8000 字符）
            key_file_patterns = ["README.md", "docs/**/REPORT.md", "docs/**/PRD.md",
                                 "docs/**/architecture.md", "docs/**/deploy.md",
                                 "index.html", "docs/**/test-report.md"]
            content_parts = []
            total_chars = 0
            max_chars = 8000

            for pattern in key_file_patterns:
                for fpath in repo_dir.glob(pattern):
                    if fpath.is_file() and total_chars < max_chars:
                        try:
                            text = fpath.read_text(encoding="utf-8", errors="replace")
                            remaining = max_chars - total_chars
                            if len(text) > remaining:
                                text = text[:remaining] + "\n...(truncated)"
                            rel = fpath.relative_to(repo_dir)
                            content_parts.append(f"### {rel}\n```\n{text}\n```")
                            total_chars += len(text)
                        except Exception:
                            pass

            key_files_content = "\n\n".join(content_parts) if content_parts else "（暂无文档）"
    except Exception as e:
        file_tree = f"（读取文件树失败: {e}）"
        key_files_content = ""

    # === 获取最近产物列表 ===
    artifacts = await db.fetch_all(
        "SELECT type, name, path, created_at FROM artifacts WHERE project_id = ? ORDER BY created_at DESC LIMIT 20",
        (project_id,),
    )
    artifacts_summary = "\n".join(
        f"- [{a['type']}] {a['name'] or a['path'] or '未命名'} ({a['created_at'][:16]})"
        for a in artifacts
    ) if artifacts else "暂无产物"

    return {
        "recent_requirements": requirements,
        "ticket_summary": ticket_summary,
        "file_tree": file_tree,
        "key_files_content": key_files_content,
        "artifacts_summary": artifacts_summary,
        "knowledge_content": _load_knowledge_content(project_id),
    }


def _try_fix_json(raw: str) -> Optional[dict]:
    """尝试多种策略修复 LLM 产出的坏 JSON"""
    import re as _re

    # 策略 1: 替换中文引号
    cleaned = raw.replace('\u201c', '\\"').replace('\u201d', '\\"')
    cleaned = cleaned.replace('\u2018', "\\'").replace('\u2019', "\\'")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 策略 2: 提取 key-value 对（正则匹配 "key": "value" 模式）
    try:
        pairs = {}
        for m in _re.finditer(r'"(\w+)"\s*:\s*"((?:[^"\\]|\\.)*)(?:"|$)', raw):
            pairs[m.group(1)] = m.group(2)
        if not pairs:
            # 尝试更宽松的匹配
            for m in _re.finditer(r'"(\w+)"\s*:\s*"([^}]*?)"\s*[,}]', raw):
                pairs[m.group(1)] = m.group(2)
        if pairs and ("title" in pairs or "name" in pairs):
            return pairs
    except Exception:
        pass

    # 策略 3: 把内部未转义的双引号替换掉
    try:
        # 找到所有 "key": "value" 的 value 部分，修复内部双引号
        def fix_value(m):
            val = m.group(1)
            # 保留首尾引号，内部双引号转义
            fixed = val.replace('"', '\\"')
            return f'"{fixed}"'

        # 匹配 : "..." 模式（贪婪到下一个 ", " 或 "} 为止）
        fixed = _re.sub(r':\s*"(.*?)"\s*([,}])', lambda m: f': "{m.group(1).replace(chr(34), "")}" {m.group(2)}', raw)
        return json.loads(fixed)
    except Exception:
        pass

    return None


async def _parse_and_execute_action(project_id: str, project: dict, response: str) -> Optional[Dict]:
    """解析 AI 回复中的操作指令并执行"""
    import re

    # 特殊处理 GENERATE_DOCUMENT（非 JSON 格式，用 --- 分隔）
    doc_pattern = r'\[ACTION:GENERATE_DOCUMENT\]\s*(.*?)\s*\[/ACTION\]'
    doc_match = re.search(doc_pattern, response, re.DOTALL)
    if doc_match:
        from actions.chat.generate_document import GenerateDocumentAction

        raw = doc_match.group(1)
        doc_data = None
        # 解析 filename/title + --- + content
        if '---' in raw:
            header, content = raw.split('---', 1)
            filename = ""
            title = ""
            for line in header.strip().split('\n'):
                line = line.strip()
                if line.lower().startswith('filename:'):
                    filename = line.split(':', 1)[1].strip()
                elif line.lower().startswith('title:'):
                    title = line.split(':', 1)[1].strip()
            content = content.strip()
            if filename and content:
                doc_data = {"filename": filename, "title": title, "content": content}
        else:
            # 回退：尝试 JSON 解析
            try:
                doc_data = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("GENERATE_DOCUMENT 解析失败")
                return None

        if doc_data:
            action_result = await GenerateDocumentAction().run({"project_id": project_id, **doc_data})
            return action_result.data
        return None

    # 通用 JSON 指令匹配 [ACTION:XXX] {...} [/ACTION]
    # 用非贪婪 \{.*?\}：避免一条回复里出现两个 action 时，贪婪匹配跨越多个块
    # 非贪婪 + 必须以 [/ACTION] 结尾的组合会自动回溯扩展，能正确匹配嵌套 JSON
    pattern = r'\[ACTION:(\w+)\]\s*(\{.*?\})\s*\[/ACTION\]'
    match = re.search(pattern, response, re.DOTALL)

    if not match:
        return None

    action_type = match.group(1)
    action_data_str = match.group(2)

    try:
        action_data = json.loads(action_data_str)
    except json.JSONDecodeError:
        # 尝试多种修复策略
        action_data = _try_fix_json(action_data_str)
        if not action_data:
            logger.warning("无法解析操作数据: %s", action_data_str[:200])
            return None
        logger.info("JSON 修复解析成功")

    # ACTION 类型 → Action 实例 的映射（P1 改造后：所有能力走 Action 体系）
    # 对于 GIT_* 一族，原来共享 _execute_git_action 的一个分发器，现在每种子操作一个 Action。
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

    _ACTION_MAP = {
        "CONFIRM_REQUIREMENT": ConfirmRequirementAction,
        "CONFIRM_BUG": ConfirmBugAction,
        "CREATE_REQUIREMENT": CreateRequirementAction,
        "PAUSE_REQUIREMENT": PauseRequirementAction,
        "RESUME_REQUIREMENT": ResumeRequirementAction,
        "CLOSE_REQUIREMENT": CloseRequirementAction,
        "GENERATE_DOCUMENT": GenerateDocumentAction,
        "GIT_LOG": GitLogAction,
        "GIT_LIST_BRANCHES": GitListBranchesAction,
        "GIT_SWITCH_BRANCH": GitSwitchBranchAction,
        "GIT_READ_FILE": GitReadFileAction,
        "GIT_MERGE": GitMergeAction,
    }

    action_cls = _ACTION_MAP.get(action_type)
    if not action_cls:
        logger.warning("未知操作类型: %s", action_type)
        return None

    # 统一用 ActionBase 协议调用：context 里注入 project_id + action_data
    ctx = {"project_id": project_id, **action_data}
    action_result = await action_cls().run(ctx)
    return action_result.data


def _clean_action_tags(response: str) -> str:
    """清除回复中的操作指令标记（包括未闭合的块）"""
    import re
    # 先清除完整的 [ACTION:...]...[/ACTION]
    cleaned = re.sub(r'\[ACTION:\w+\].*?\[/ACTION\]', '', response, flags=re.DOTALL)
    # 再清除未闭合的 [ACTION:...] 到字符串结尾（token 截断导致）
    cleaned = re.sub(r'\[ACTION:\w+\].*$', '', cleaned, flags=re.DOTALL)
    return cleaned.strip()


async def _save_images(project_id: str, images: list) -> list:
    """将 base64 data URL 图片列表保存为文件，返回可访问的 URL 列表"""
    from config import BASE_DIR
    image_urls = []
    chat_images_dir = BASE_DIR / "chat_images" / project_id
    chat_images_dir.mkdir(parents=True, exist_ok=True)
    for data_url in images:
        try:
            header, b64data = data_url.split(",", 1)
            ext = header.split(";")[0].split("/")[-1]
            ext = ext if ext in ("png", "jpeg", "gif", "webp") else "png"
            filename = f"{uuid.uuid4().hex}.{ext}"
            file_path = chat_images_dir / filename
            file_path.write_bytes(base64.b64decode(b64data))
            image_urls.append(f"/chat-images/{project_id}/{filename}")
        except Exception as e:
            logger.warning("图片保存失败，已跳过: %s", e)
    return image_urls


async def _save_chat_message(
    project_id: str,
    role: str,
    content: str,
    action: dict = None,
    images: list = None,       # base64 data URL 列表（原始图片）
    saved_urls: list = None,   # 已保存的图片 URL 列表（优先使用，避免重复保存）
):
    """保存聊天消息到数据库，图片保存为文件"""
    msg_id = generate_id("MSG")

    # 优先使用已保存的 URL，否则从 base64 保存
    if saved_urls is not None:
        image_urls = saved_urls
    else:
        image_urls = await _save_images(project_id, images) if images else []

    await db.insert("chat_messages", {
        "id": msg_id,
        "project_id": project_id,
        "role": role,
        "content": content,
        "action_type": action.get("type") if action else None,
        "action_data": json.dumps(action, ensure_ascii=False) if action else None,
        "images_json": json.dumps(image_urls, ensure_ascii=False) if image_urls else None,
        "created_at": now_iso(),
    })


# ==================== 全局聊天 API（无需 project_id）====================


class GlobalChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户消息")
    history: Optional[List[ChatMessage]] = Field(default=None, description="历史消息（可选）")
    images: Optional[List[str]] = Field(default=None, description="图片列表，base64 data URL")


class GlobalChatResponse(BaseModel):
    reply: str = Field(..., description="AI 回复")
    action: Optional[Dict[str, Any]] = Field(default=None, description="执行的操作信息")
    actions: Optional[List[Dict[str, Any]]] = Field(default=None, description="批量操作卡片（文档分析等场景）")


@global_chat_router.post("", response_model=GlobalChatResponse)
async def global_chat_with_ai(req: GlobalChatRequest):
    """全局聊天（项目列表页）— ChatAssistantAgent + tool_use"""
    return await _global_chat_via_agent(req)


async def _global_chat_via_agent(req: GlobalChatRequest) -> GlobalChatResponse:
    """新路径：ChatAssistantAgent.chat_global() + tool_use。"""
    import agent_registry as _ar

    registry = _ar.get_registry()
    if not registry:
        _ar.discover_agents()
        registry = _ar.get_registry()
    agent_cls = registry.get("ChatAssistant")
    if not agent_cls:
        raise RuntimeError("ChatAssistant agent 未注册")
    agent = agent_cls()

    projects = await db.fetch_all(
        "SELECT id, name, status, tech_stack, description, created_at FROM projects ORDER BY created_at DESC LIMIT 20"
    )

    history = [{"role": m.role, "content": m.content} for m in (req.history or [])]

    result = await agent.chat_global(
        user_message=req.message,
        images=req.images,
        history=history,
        projects_brief=projects,
    )
    return GlobalChatResponse(reply=result["reply"], action=result.get("action"))


# ---- 确认创建项目端点 ----

class ConfirmCreateProjectRequest(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = Field(default="")
    tech_stack: str = Field(default="")
    git_remote_url: str = Field(..., min_length=1)
    local_repo_path: str = Field(default="")
    traits: List[str] = Field(default_factory=list)              # v0.17
    preset_id: Optional[str] = Field(default=None)               # v0.17
    traits_confidence: Dict[str, Any] = Field(default_factory=dict)  # v0.17


@global_chat_router.post("/confirm-create-project")
async def confirm_create_project(req: ConfirmCreateProjectRequest):
    """用户点击"确认创建"按钮后真正落库创建项目。"""
    from actions.chat.create_project import CreateProjectAction
    result = await CreateProjectAction().run(req.model_dump())
    if not result.success:
        raise HTTPException(400, result.data.get("message") or result.error or "创建失败")
    return result.data


@global_chat_router.get("/projects-brief")
async def get_projects_brief():
    """获取项目简要列表（用于 AI 聊天上下文）"""
    projects = await db.fetch_all(
        "SELECT id, name, status, tech_stack, description, created_at FROM projects ORDER BY created_at DESC LIMIT 20"
    )
    return {"projects": projects, "total": len(projects)}



# ==================== 图片消息构建 ====================

def _build_user_content(text: str, images: Optional[List[str]] = None):
    """
    构建用户消息 content。
    无图片时返回字符串；有图片时返回 Anthropic vision content blocks 列表。
    data URL 格式：data:image/png;base64,<base64data>
    """
    if not images:
        return text

    content = []
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
                }
            })
        except Exception as ex:
            logger.warning("图片解析失败，已跳过: %s", ex)

    content.append({"type": "text", "text": text})
    return content
