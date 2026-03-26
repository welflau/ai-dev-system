"""
AI 自动开发系统 - 聊天 API
支持三种模式：
1. 全局聊天（项目内）：用户与 AI 自由对话，支持通过对话发起需求等操作
2. 全局聊天（无项目）：项目列表页的 AI 对话，支持创建项目
3. Job 聊天历史：加载某个工单的 AI 对话记录
"""
import json
import logging
from fastapi import APIRouter, HTTPException
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


class ChatResponse(BaseModel):
    reply: str = Field(..., description="AI 回复")
    action: Optional[Dict[str, Any]] = Field(default=None, description="执行的操作信息")


# ==================== 聊天端点 ====================

@router.post("", response_model=ChatResponse)
async def chat_with_ai(project_id: str, req: ChatRequest):
    """全局聊天 — 用户与 AI 自由对话 + 指令操作"""
    from llm_client import llm_client, set_llm_context, clear_llm_context

    # 校验项目存在
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    # 获取项目上下文
    project_context = await _build_project_context(project_id, project)

    # 构建消息
    system_prompt = _build_system_prompt(project, project_context)
    messages = [{"role": "system", "content": system_prompt}]

    # 添加历史消息
    if req.history:
        for msg in req.history[-20:]:  # 最多保留最近 20 条
            messages.append({"role": msg.role, "content": msg.content})

    # 添加用户当前消息
    messages.append({"role": "user", "content": req.message})

    # 设置 LLM 上下文
    set_llm_context(
        project_id=project_id,
        agent_type="ChatAssistant",
        action="global_chat",
    )

    try:
        # 调用 LLM
        response = await llm_client.chat(messages, temperature=0.7, max_tokens=4096)

        # 解析是否包含操作指令
        action_result = await _parse_and_execute_action(project_id, project, response)

        # 保存聊天记录到数据库
        await _save_chat_message(project_id, "user", req.message)
        await _save_chat_message(project_id, "assistant", response, action=action_result)

        # 清理回复中的指令标记
        clean_reply = _clean_action_tags(response)

        return ChatResponse(reply=clean_reply, action=action_result)

    finally:
        clear_llm_context()


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
    return {"messages": rows, "total": len(rows)}


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
        user_msg = ""
        for m in msgs:
            if m.get("role") == "user":
                user_msg = m.get("content", "")

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

    return f"""你是 AI 自动开发系统的智能助手，当前正在为项目「{project['name']}」提供服务。

## 项目信息
- 名称：{project['name']}
- 描述：{project.get('description') or '无描述'}
- 技术栈：{project.get('tech_stack') or '未指定'}

## 当前需求状态
{req_summary}

## 工单概况
{ticket_summary}

## 你的能力
1. **回答问题**：关于项目状态、需求进展、技术方案的任何问题
2. **创建需求**：当用户描述一个新功能需求时，你可以帮助创建
3. **管理需求状态**：暂停、恢复、关闭需求的执行
4. **查看状态**：汇报当前项目进展、工单状态
5. **技术建议**：基于项目技术栈给出建议

## 操作指令格式
当你判断用户想要执行操作时，在回复末尾附加以下格式的指令标记（必须是独立一行）：

### 创建需求
当用户想要创建新需求时使用：
[ACTION:CREATE_REQUIREMENT]
{{"title": "需求标题", "description": "详细描述", "priority": "medium"}}
[/ACTION]

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

priority 可选值：critical, high, medium, low

## 注意事项
- 用中文回复
- 回答简洁但有信息量
- 如果用户的描述不够清晰，先询问细节再执行操作
- 如果不确定用户想操作哪个需求，列出当前需求让用户选择
- 如果需求 ID 不明确，用标题关键词匹配当前需求列表中的需求
- 暂停/恢复/关闭操作必须确认需求存在且状态允许该操作
"""


async def _build_project_context(project_id: str, project: dict) -> dict:
    """构建项目上下文信息"""
    # 获取最近需求
    requirements = await db.fetch_all(
        "SELECT id, title, status, priority, created_at FROM requirements WHERE project_id = ? ORDER BY created_at DESC LIMIT 10",
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

    return {
        "recent_requirements": requirements,
        "ticket_summary": ticket_summary,
    }


async def _parse_and_execute_action(project_id: str, project: dict, response: str) -> Optional[Dict]:
    """解析 AI 回复中的操作指令并执行"""
    import re

    # 匹配 [ACTION:XXX] ... [/ACTION]
    pattern = r'\[ACTION:(\w+)\]\s*(\{.*?\})\s*\[/ACTION\]'
    match = re.search(pattern, response, re.DOTALL)

    if not match:
        return None

    action_type = match.group(1)
    action_data_str = match.group(2)

    try:
        action_data = json.loads(action_data_str)
    except json.JSONDecodeError:
        logger.warning("无法解析操作数据: %s", action_data_str)
        return None

    if action_type == "CREATE_REQUIREMENT":
        return await _execute_create_requirement(project_id, action_data)
    elif action_type == "PAUSE_REQUIREMENT":
        return await _execute_pause_requirement(project_id, action_data)
    elif action_type == "RESUME_REQUIREMENT":
        return await _execute_resume_requirement(project_id, action_data)
    elif action_type == "CLOSE_REQUIREMENT":
        return await _execute_close_requirement(project_id, action_data)

    logger.warning("未知操作类型: %s", action_type)
    return None


async def _execute_create_requirement(project_id: str, data: dict) -> Dict:
    """执行创建需求操作"""
    title = data.get("title", "").strip()
    description = data.get("description", "").strip()
    priority = data.get("priority", "medium")

    if not title or not description:
        return {"type": "error", "message": "需求标题和描述不能为空"}

    if priority not in ("critical", "high", "medium", "low"):
        priority = "medium"

    req_id = generate_id("REQ")
    now = now_iso()
    req_data = {
        "id": req_id,
        "project_id": project_id,
        "title": title,
        "description": description,
        "priority": priority,
        "status": "submitted",
        "submitter": "chat_assistant",
        "prd_content": None,
        "module": None,
        "tags": None,
        "estimated_hours": None,
        "actual_hours": None,
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
    }
    await db.insert("requirements", req_data)

    # 写日志
    log_id = generate_id("LOG")
    detail_json = json.dumps({"message": f"通过聊天助手创建需求「{title}」"}, ensure_ascii=False)
    await db.insert("ticket_logs", {
        "id": log_id,
        "ticket_id": None,
        "subtask_id": None,
        "requirement_id": req_id,
        "project_id": project_id,
        "agent_type": "ChatAssistant",
        "action": "create",
        "from_status": None,
        "to_status": "submitted",
        "detail": detail_json,
        "level": "info",
        "created_at": now,
    })

    # SSE 事件
    await event_manager.publish_to_project(
        project_id, "requirement_created", {"id": req_id, "title": title}
    )

    logger.info("聊天助手创建需求: %s — %s", req_id, title)

    # === 自动触发拆单（创建后直接启动分析） ===
    from models import RequirementStatus
    await db.update(
        "requirements",
        {"status": RequirementStatus.ANALYZING.value, "updated_at": now_iso()},
        "id = ?",
        (req_id,),
    )

    # 写分析启动日志
    start_log_id = generate_id("LOG")
    start_detail = json.dumps({"message": "ProductAgent 开始分析需求"}, ensure_ascii=False)
    await db.insert("ticket_logs", {
        "id": start_log_id,
        "ticket_id": None,
        "subtask_id": None,
        "requirement_id": req_id,
        "project_id": project_id,
        "agent_type": "ProductAgent",
        "action": "start",
        "from_status": "submitted",
        "to_status": "analyzing",
        "detail": start_detail,
        "level": "info",
        "created_at": now_iso(),
    })

    await event_manager.publish_to_project(
        project_id, "requirement_analyzing", {"id": req_id, "title": title}
    )

    # 后台执行拆单（由 Orchestrator 调度）
    import asyncio
    from orchestrator import orchestrator
    asyncio.create_task(orchestrator.handle_requirement(project_id, req_id))
    logger.info("自动触发需求拆单: %s", req_id)

    return {
        "type": "requirement_created",
        "requirement_id": req_id,
        "title": title,
        "description": description,
        "priority": priority,
        "message": f"需求「{title}」已创建，正在自动分析拆单...",
    }


async def _execute_pause_requirement(project_id: str, data: dict) -> Dict:
    """执行暂停需求操作"""
    from models import RequirementStatus, validate_requirement_transition

    requirement_id = data.get("requirement_id", "").strip()
    reason = data.get("reason", "用户通过聊天助手暂停").strip()

    if not requirement_id:
        return {"type": "error", "message": "需求 ID 不能为空"}

    # 支持模糊匹配：如果传入的不是完整 ID，尝试通过标题关键词匹配
    req = await db.fetch_one(
        "SELECT * FROM requirements WHERE id = ? AND project_id = ?",
        (requirement_id, project_id),
    )
    if not req:
        # 尝试通过标题模糊匹配
        req = await db.fetch_one(
            "SELECT * FROM requirements WHERE project_id = ? AND title LIKE ? AND status NOT IN ('completed', 'cancelled')",
            (project_id, f"%{requirement_id}%"),
        )
        if req:
            requirement_id = req["id"]
        else:
            return {"type": "error", "message": f"未找到需求「{requirement_id}」"}

    current_status = req["status"]
    # 验证状态转换是否合法
    if not validate_requirement_transition(current_status, "paused"):
        status_label = {"submitted": "已提交", "analyzing": "分析中", "decomposed": "已拆单",
                       "in_progress": "进行中", "paused": "已暂停", "completed": "已完成",
                       "cancelled": "已取消"}.get(current_status, current_status)
        return {"type": "error", "message": f"需求当前状态为「{status_label}」，无法暂停"}

    now = now_iso()
    await db.update("requirements", {
        "status": RequirementStatus.PAUSED.value,
        "updated_at": now,
    }, "id = ?", (requirement_id,))

    # 写日志
    log_id = generate_id("LOG")
    detail_json = json.dumps({"message": f"通过聊天助手暂停需求，原因: {reason}"}, ensure_ascii=False)
    await db.insert("ticket_logs", {
        "id": log_id,
        "ticket_id": None,
        "subtask_id": None,
        "requirement_id": requirement_id,
        "project_id": project_id,
        "agent_type": "ChatAssistant",
        "action": "update_status",
        "from_status": current_status,
        "to_status": "paused",
        "detail": detail_json,
        "level": "info",
        "created_at": now,
    })

    # SSE 事件
    await event_manager.publish_to_project(
        project_id, "requirement_status_changed",
        {"id": requirement_id, "title": req["title"], "from": current_status, "to": "paused"},
    )

    logger.info("聊天助手暂停需求: %s — %s", requirement_id, req["title"])

    return {
        "type": "requirement_paused",
        "requirement_id": requirement_id,
        "title": req["title"],
        "from_status": current_status,
        "to_status": "paused",
        "reason": reason,
        "message": f"需求「{req['title']}」已暂停",
    }


async def _execute_resume_requirement(project_id: str, data: dict) -> Dict:
    """执行恢复需求操作"""
    from models import RequirementStatus, validate_requirement_transition

    requirement_id = data.get("requirement_id", "").strip()

    if not requirement_id:
        return {"type": "error", "message": "需求 ID 不能为空"}

    req = await db.fetch_one(
        "SELECT * FROM requirements WHERE id = ? AND project_id = ?",
        (requirement_id, project_id),
    )
    if not req:
        # 尝试通过标题模糊匹配
        req = await db.fetch_one(
            "SELECT * FROM requirements WHERE project_id = ? AND title LIKE ? AND status = 'paused'",
            (project_id, f"%{requirement_id}%"),
        )
        if req:
            requirement_id = req["id"]
        else:
            return {"type": "error", "message": f"未找到需求「{requirement_id}」或需求不处于暂停状态"}

    current_status = req["status"]
    if current_status != "paused":
        return {"type": "error", "message": f"需求当前不处于暂停状态（当前: {current_status}），无法恢复"}

    # 恢复到 in_progress 状态
    new_status = RequirementStatus.IN_PROGRESS.value

    now = now_iso()
    await db.update("requirements", {
        "status": new_status,
        "updated_at": now,
    }, "id = ?", (requirement_id,))

    # 写日志
    log_id = generate_id("LOG")
    detail_json = json.dumps({"message": "通过聊天助手恢复需求执行"}, ensure_ascii=False)
    await db.insert("ticket_logs", {
        "id": log_id,
        "ticket_id": None,
        "subtask_id": None,
        "requirement_id": requirement_id,
        "project_id": project_id,
        "agent_type": "ChatAssistant",
        "action": "update_status",
        "from_status": current_status,
        "to_status": new_status,
        "detail": detail_json,
        "level": "info",
        "created_at": now,
    })

    # SSE 事件
    await event_manager.publish_to_project(
        project_id, "requirement_status_changed",
        {"id": requirement_id, "title": req["title"], "from": current_status, "to": new_status},
    )

    logger.info("聊天助手恢复需求: %s — %s", requirement_id, req["title"])

    # 恢复需求后，自动继续处理未完成的工单
    try:
        from orchestrator import orchestrator
        import asyncio
        pending_tickets = await db.fetch_all(
            "SELECT id FROM tickets WHERE requirement_id = ? AND status NOT IN ('deployed', 'cancelled')",
            (requirement_id,),
        )
        for t in pending_tickets:
            # 用后台方式继续流转
            asyncio.create_task(orchestrator.process_ticket(project_id, t["id"]))
        if pending_tickets:
            logger.info("恢复需求后继续处理 %d 个工单", len(pending_tickets))
    except Exception as e:
        logger.warning("恢复工单流转失败: %s", e)

    return {
        "type": "requirement_resumed",
        "requirement_id": requirement_id,
        "title": req["title"],
        "from_status": current_status,
        "to_status": new_status,
        "message": f"需求「{req['title']}」已恢复执行",
    }


async def _execute_close_requirement(project_id: str, data: dict) -> Dict:
    """执行关闭需求操作"""
    from models import RequirementStatus

    requirement_id = data.get("requirement_id", "").strip()
    reason = data.get("reason", "用户通过聊天助手关闭").strip()

    if not requirement_id:
        return {"type": "error", "message": "需求 ID 不能为空"}

    req = await db.fetch_one(
        "SELECT * FROM requirements WHERE id = ? AND project_id = ?",
        (requirement_id, project_id),
    )
    if not req:
        # 尝试通过标题模糊匹配
        req = await db.fetch_one(
            "SELECT * FROM requirements WHERE project_id = ? AND title LIKE ? AND status NOT IN ('completed', 'cancelled')",
            (project_id, f"%{requirement_id}%"),
        )
        if req:
            requirement_id = req["id"]
        else:
            return {"type": "error", "message": f"未找到需求「{requirement_id}」"}

    current_status = req["status"]
    if current_status in ("completed", "cancelled"):
        status_label = "已完成" if current_status == "completed" else "已取消"
        return {"type": "error", "message": f"需求已处于终态「{status_label}」，无需操作"}

    now = now_iso()
    await db.update("requirements", {
        "status": RequirementStatus.CANCELLED.value,
        "updated_at": now,
    }, "id = ?", (requirement_id,))

    # 同时取消该需求下所有未完成的工单
    cancelled_tickets = 0
    tickets = await db.fetch_all(
        "SELECT id, status FROM tickets WHERE requirement_id = ? AND status NOT IN ('deployed', 'cancelled')",
        (requirement_id,),
    )
    for t in tickets:
        await db.update("tickets", {
            "status": "cancelled",
            "updated_at": now,
        }, "id = ?", (t["id"],))
        cancelled_tickets += 1

    # 写日志
    log_id = generate_id("LOG")
    detail_json = json.dumps({
        "message": f"通过聊天助手关闭需求，原因: {reason}",
        "cancelled_tickets": cancelled_tickets,
    }, ensure_ascii=False)
    await db.insert("ticket_logs", {
        "id": log_id,
        "ticket_id": None,
        "subtask_id": None,
        "requirement_id": requirement_id,
        "project_id": project_id,
        "agent_type": "ChatAssistant",
        "action": "update_status",
        "from_status": current_status,
        "to_status": "cancelled",
        "detail": detail_json,
        "level": "info",
        "created_at": now,
    })

    # SSE 事件
    await event_manager.publish_to_project(
        project_id, "requirement_status_changed",
        {"id": requirement_id, "title": req["title"], "from": current_status, "to": "cancelled",
         "cancelled_tickets": cancelled_tickets},
    )

    logger.info("聊天助手关闭需求: %s — %s (同时取消 %d 个工单)", requirement_id, req["title"], cancelled_tickets)

    return {
        "type": "requirement_closed",
        "requirement_id": requirement_id,
        "title": req["title"],
        "from_status": current_status,
        "to_status": "cancelled",
        "reason": reason,
        "cancelled_tickets": cancelled_tickets,
        "message": f"需求「{req['title']}」已关闭" + (f"，同时取消了 {cancelled_tickets} 个工单" if cancelled_tickets > 0 else ""),
    }


def _clean_action_tags(response: str) -> str:
    """清除回复中的操作指令标记"""
    import re
    cleaned = re.sub(r'\[ACTION:\w+\].*?\[/ACTION\]', '', response, flags=re.DOTALL)
    return cleaned.strip()


async def _save_chat_message(
    project_id: str,
    role: str,
    content: str,
    action: dict = None,
):
    """保存聊天消息到数据库"""
    msg_id = generate_id("MSG")
    await db.insert("chat_messages", {
        "id": msg_id,
        "project_id": project_id,
        "role": role,
        "content": content,
        "action_type": action.get("type") if action else None,
        "action_data": json.dumps(action, ensure_ascii=False) if action else None,
        "created_at": now_iso(),
    })


# ==================== 全局聊天 API（无需 project_id）====================


class GlobalChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户消息")
    history: Optional[List[ChatMessage]] = Field(default=None, description="历史消息（可选）")


class GlobalChatResponse(BaseModel):
    reply: str = Field(..., description="AI 回复")
    action: Optional[Dict[str, Any]] = Field(default=None, description="执行的操作信息")


@global_chat_router.post("", response_model=GlobalChatResponse)
async def global_chat_with_ai(req: GlobalChatRequest):
    """全局聊天（项目列表页）— 无需 project_id，支持创建项目"""
    from llm_client import llm_client, set_llm_context, clear_llm_context

    # 获取所有项目列表作为上下文
    projects = await db.fetch_all(
        "SELECT id, name, status, tech_stack, description, created_at FROM projects ORDER BY created_at DESC LIMIT 20"
    )

    system_prompt = _build_global_system_prompt(projects)
    messages = [{"role": "system", "content": system_prompt}]

    if req.history:
        for msg in req.history[-20:]:
            messages.append({"role": msg.role, "content": msg.content})

    messages.append({"role": "user", "content": req.message})

    set_llm_context(agent_type="GlobalChatAssistant", action="global_chat_no_project")

    try:
        response = await llm_client.chat(messages, temperature=0.7, max_tokens=4096)

        # 解析是否包含 CREATE_PROJECT 操作
        action_result = await _parse_global_action(response)

        clean_reply = _clean_action_tags(response)

        return GlobalChatResponse(reply=clean_reply, action=action_result)
    finally:
        clear_llm_context()


@global_chat_router.get("/projects-brief")
async def get_projects_brief():
    """获取项目简要列表（用于 AI 聊天上下文）"""
    projects = await db.fetch_all(
        "SELECT id, name, status, tech_stack, description, created_at FROM projects ORDER BY created_at DESC LIMIT 20"
    )
    return {"projects": projects, "total": len(projects)}


def _build_global_system_prompt(projects: list) -> str:
    """构建全局聊天系统提示词（无项目上下文）"""
    if projects:
        proj_lines = []
        for p in projects[:10]:
            proj_lines.append(f"  - [{p['status']}] {p['name']} (技术栈: {p.get('tech_stack') or '未指定'})")
        proj_summary = "\n".join(proj_lines)
    else:
        proj_summary = "  暂无项目"

    return f"""你是 AI 自动开发系统的智能助手。当前用户尚未进入任何项目，你正在项目列表页提供服务。

## 当前项目列表
{proj_summary}

## 你的能力
1. **回答问题**：关于系统功能、使用方法的任何问题
2. **创建项目**：当用户想创建新项目时，收集必要信息后创建
3. **推荐操作**：引导用户进入已有项目，或创建新项目

## 创建项目的必填信息
创建项目需要以下信息：
- **项目名称**（必填）：项目的名称
- **Git 远程仓库 URL**（必填）：如 https://github.com/username/repo.git
- **项目描述**（可选）：项目的简要说明
- **技术栈**（可选）：如 Python, FastAPI, React 等
- **本地仓库路径**（可选）：留空则自动生成

## 对话式创建项目流程
当用户表达想创建项目的意图时：
1. 先确认用户想创建项目
2. 逐步收集缺少的必填信息（名称、Git URL），可以一次问多个
3. 可选信息可以建议用户填写，但不强制
4. 信息收集完毕后，向用户确认所有信息，等用户确认后再创建
5. 用户确认后，输出创建指令

## 操作指令格式
当信息收集完毕且用户确认后，在回复末尾附加（必须是独立一行）：

### 创建项目
[ACTION:CREATE_PROJECT]
{{"name": "项目名称", "description": "项目描述", "tech_stack": "技术栈", "git_remote_url": "Git远程仓库URL", "local_repo_path": ""}}
[/ACTION]

## 注意事项
- 用中文回复
- 回答简洁但有信息量
- 创建项目前必须确认用户的意图和必填信息
- 如果用户只说了项目名没说 Git URL，要追问 Git URL
- 不要自己编造 Git URL
- 用户说"确认"、"好的"、"创建吧"等表示同意时才执行创建
"""


async def _parse_global_action(response: str) -> Optional[Dict]:
    """解析全局聊天中的操作指令"""
    import re

    pattern = r'\[ACTION:(\w+)\]\s*(\{.*?\})\s*\[/ACTION\]'
    match = re.search(pattern, response, re.DOTALL)

    if not match:
        return None

    action_type = match.group(1)
    action_data_str = match.group(2)

    try:
        action_data = json.loads(action_data_str)
    except json.JSONDecodeError:
        logger.warning("无法解析全局操作数据: %s", action_data_str)
        return None

    if action_type == "CREATE_PROJECT":
        return await _execute_create_project(action_data)

    logger.warning("未知全局操作类型: %s", action_type)
    return None


async def _execute_create_project(data: dict) -> Dict:
    """通过 AI 对话执行创建项目"""
    import os
    from git_manager import git_manager

    name = data.get("name", "").strip()
    description = data.get("description", "").strip()
    tech_stack = data.get("tech_stack", "").strip()
    git_remote_url = data.get("git_remote_url", "").strip()
    local_repo_path = data.get("local_repo_path", "").strip()

    if not name:
        return {"type": "error", "message": "项目名称不能为空"}
    if not git_remote_url:
        return {"type": "error", "message": "Git 远程仓库 URL 不能为空"}

    try:
        project_id = generate_id("PRJ")
        now = now_iso()

        # 确定本地仓库路径
        if local_repo_path:
            repo_path = os.path.abspath(local_repo_path)
            git_manager.set_project_path(project_id, repo_path)
        else:
            repo_path = str(git_manager._repo_path(project_id))

        # 创建目录结构
        logger.info("AI助手创建项目: %s, 仓库路径: %s", name, repo_path)
        os.makedirs(repo_path, exist_ok=True)
        for d in git_manager.REPO_DIRS:
            os.makedirs(os.path.join(repo_path, d), exist_ok=True)

        # 生成 README.md
        readme = f"# {name}\n\n{description or '由 AI 自动开发系统创建的项目'}\n"
        readme_path = os.path.join(repo_path, "README.md")
        if not os.path.exists(readme_path):
            with open(readme_path, "w", encoding="utf-8") as f:
                f.write(readme)

        # 生成 .gitignore
        gitignore = "__pycache__/\n*.py[cod]\n.venv/\nvenv/\n.idea/\n.vscode/\n.DS_Store\nThumbs.db\n.env\n*.log\n"
        gitignore_path = os.path.join(repo_path, ".gitignore")
        if not os.path.exists(gitignore_path):
            with open(gitignore_path, "w", encoding="utf-8") as f:
                f.write(gitignore)

        # git init
        git_dir = os.path.join(repo_path, ".git")
        if not os.path.isdir(git_dir):
            await git_manager._run_git(repo_path, "init")

        # 配置远程仓库
        if git_remote_url:
            await git_manager.set_remote(project_id, git_remote_url)

        # 初始提交
        await git_manager._run_git(repo_path, "add", ".")
        await git_manager._run_git(
            repo_path, "commit", "-m",
            f"init: {name} - project initialized by AI Dev System",
            "--author", "AI Dev System <ai@dev-system.local>",
        )

        # 尝试推送
        push_success = False
        try:
            push_success = await git_manager.push(project_id)
        except Exception as e:
            logger.warning("AI助手创建项目首次推送失败: %s", e)

        # 写入数据库
        proj_data = {
            "id": project_id,
            "name": name,
            "description": description,
            "status": "active",
            "tech_stack": tech_stack,
            "config": "{}",
            "git_repo_path": repo_path,
            "git_remote_url": git_remote_url,
            "created_at": now,
            "updated_at": now,
        }
        await db.insert("projects", proj_data)

        logger.info("AI助手创建项目完成: %s (%s)", name, project_id)

        return {
            "type": "project_created",
            "project_id": project_id,
            "name": name,
            "description": description,
            "tech_stack": tech_stack,
            "git_remote_url": git_remote_url,
            "push_success": push_success,
            "message": f"项目「{name}」已创建成功" + ("，并已推送到远程仓库" if push_success else "（首次推送失败，请检查远程仓库权限）"),
        }

    except Exception as e:
        logger.error("AI助手创建项目失败: %s", e)
        return {"type": "error", "message": f"创建项目失败: {str(e)}"}
