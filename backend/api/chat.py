"""
AI 自动开发系统 - 聊天 API
支持两种模式：
1. 全局聊天：用户与 AI 自由对话，支持通过对话发起需求等操作
2. Job 聊天历史：加载某个工单的 AI 对话记录
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
        for r in req_list[:5]:
            req_lines.append(f"  - [{r['status']}] {r['title']} (ID: {r['id'][:12]}...)")
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
3. **查看状态**：汇报当前项目进展、工单状态
4. **技术建议**：基于项目技术栈给出建议

## 操作指令格式
当你判断用户想要创建需求时，在回复末尾附加以下格式的指令标记（必须是独立一行）：

[ACTION:CREATE_REQUIREMENT]
{{"title": "需求标题", "description": "详细描述", "priority": "medium"}}
[/ACTION]

priority 可选值：critical, high, medium, low

## 注意事项
- 用中文回复
- 回答简洁但有信息量
- 如果用户的描述不够清晰，先询问细节再创建需求
- 如果不确定用户是否要创建需求，先确认
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

    return {
        "type": "requirement_created",
        "requirement_id": req_id,
        "title": title,
        "description": description,
        "priority": priority,
        "message": f"需求「{title}」已创建成功",
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
