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

    # 添加用户当前消息（含图片时构建 vision content）
    messages.append({"role": "user", "content": _build_user_content(req.message, req.images)})

    # 设置 LLM 上下文
    set_llm_context(
        project_id=project_id,
        agent_type="ChatAssistant",
        action="global_chat",
    )

    try:
        # 调用 LLM
        response = await llm_client.chat(messages, temperature=0.7, max_tokens=8192)

        # 解析是否包含操作指令
        action_result = await _parse_and_execute_action(project_id, project, response)

        # 清理回复中的指令标记（存库和返回都用 clean 版本）
        clean_reply = _clean_action_tags(response)
        # 若清理后为空（整个回复都是 ACTION 块），给一条兜底提示
        if not clean_reply:
            if action_result and action_result.get("type") == "document_generated":
                clean_reply = f"文档「{action_result.get('title', action_result.get('path', '文档'))}」已生成。"
            elif action_result and action_result.get("message"):
                clean_reply = action_result["message"]
            else:
                clean_reply = "操作已完成。"

        # 保存聊天记录到数据库
        await _save_chat_message(project_id, "user", req.message, images=req.images)
        await _save_chat_message(project_id, "assistant", clean_reply, action=action_result)

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
    # 解析 images_json 为列表
    messages = []
    for row in rows:
        msg = dict(row)
        msg["images"] = json.loads(msg.pop("images_json", None) or "[]")
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
                user_msg = m.get("content", "")

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
    file_tree = context.get("file_tree", "")
    key_files_content = context.get("key_files_content", "")
    artifacts_summary = context.get("artifacts_summary", "暂无产物")

    return f"""你是 AI 自动开发系统的智能助手，当前正在为项目「{project['name']}」提供服务。

## 项目信息
- 名称：{project['name']}
- 描述：{project.get('description') or '无描述'}
- 技术栈：{project.get('tech_stack') or '未指定'}
- Git 仓库：{project.get('git_repo_path') or '未配置'}

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
2. **创建需求**：当用户描述一个新功能需求时，你可以帮助创建
3. **管理需求状态**：暂停、恢复、关闭需求的执行
4. **查看状态**：汇报当前项目进展、工单状态
5. **技术建议**：基于项目技术栈和已有代码给出建议
6. **生成文档**：可以基于项目内容生成设计文档、分析报告等
7. **Git 操作**：切换分支、查看分支列表、查看提交日志、查看文件内容、合并分支

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
"""


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
    }


async def _parse_and_execute_action(project_id: str, project: dict, response: str) -> Optional[Dict]:
    """解析 AI 回复中的操作指令并执行"""
    import re

    # 特殊处理 GENERATE_DOCUMENT（非 JSON 格式，用 --- 分隔）
    doc_pattern = r'\[ACTION:GENERATE_DOCUMENT\]\s*(.*?)\s*\[/ACTION\]'
    doc_match = re.search(doc_pattern, response, re.DOTALL)
    if doc_match:
        raw = doc_match.group(1)
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
                return await _execute_generate_document(project_id, {
                    "filename": filename, "title": title, "content": content
                })
        else:
            # 回退：尝试 JSON 解析
            try:
                data = json.loads(raw)
                return await _execute_generate_document(project_id, data)
            except json.JSONDecodeError:
                logger.warning("GENERATE_DOCUMENT 解析失败")
                return None

    # 通用 JSON 指令匹配 [ACTION:XXX] {...} [/ACTION]
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
    elif action_type == "GENERATE_DOCUMENT":
        return await _execute_generate_document(project_id, action_data)
    elif action_type.startswith("GIT_"):
        return await _execute_git_action(project_id, action_type, action_data)

    logger.warning("未知操作类型: %s", action_type)
    return None


async def _execute_generate_document(project_id: str, data: dict) -> Dict:
    """执行生成文档操作：直接写入 Git 仓库"""
    filename = data.get("filename", "").strip()
    title = data.get("title", "").strip()
    content = data.get("content", "").strip()

    if not filename or not content:
        return {"type": "error", "message": "文档文件名和内容不能为空"}

    # 确保文件名安全（英文，.md 结尾）
    import re
    filename = re.sub(r'[^\w\-.]', '', filename)
    if not filename.endswith(".md"):
        filename += ".md"

    file_path = f"docs/{filename}"

    try:
        from git_manager import git_manager

        # 确保仓库存在
        if not git_manager.repo_exists(project_id):
            project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
            if project:
                await git_manager.init_repo(project_id, project["name"])

        # 写入文件
        await git_manager.write_file(project_id, file_path, content)

        # commit + push
        commit_hash = await git_manager.commit(
            project_id,
            f"[Doc] {title or filename}",
            author="ChatAssistant",
        )
        await git_manager.push(project_id)

        # 保存到 artifacts 表
        await db.insert("artifacts", {
            "id": generate_id("ART"),
            "project_id": project_id,
            "requirement_id": None,
            "ticket_id": None,
            "type": "document",
            "name": title or filename,
            "path": file_path,
            "content": content,
            "metadata": json.dumps({"source": "chat_assistant", "commit": commit_hash}),
            "created_at": now_iso(),
        })

        # 发 SSE 事件
        await event_manager.publish_to_project(
            project_id,
            "document_generated",
            {"filename": filename, "path": file_path, "title": title},
        )

        logger.info("📄 文档已生成: %s (commit: %s)", file_path, commit_hash)

        return {
            "type": "document_generated",
            "title": title or filename,
            "path": file_path,
            "commit": commit_hash,
            "message": f"文档「{title or filename}」已生成并保存到 {file_path}",
        }
    except Exception as e:
        logger.error("生成文档失败: %s", e)
        return {"type": "error", "message": f"生成文档失败: {str(e)}"}


async def _execute_git_action(project_id: str, action_type: str, data: dict) -> Dict:
    """执行 Git 操作"""
    from git_manager import git_manager

    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        return {"type": "error", "message": "项目不存在"}

    # 恢复自定义仓库路径
    repo_path = project.get("git_repo_path")
    if repo_path and project_id not in git_manager._custom_paths:
        from git_manager import PROJECTS_DIR
        if repo_path != str(PROJECTS_DIR / project_id):
            git_manager.set_project_path(project_id, repo_path)

    if not git_manager.repo_exists(project_id):
        return {"type": "error", "message": "仓库不存在"}

    try:
        if action_type == "GIT_SWITCH_BRANCH":
            branch = data.get("branch", "").strip()
            if not branch:
                return {"type": "error", "message": "分支名不能为空"}
            ok = await git_manager.switch_branch(project_id, branch)
            if ok:
                return {"type": "git_result", "action": "switch_branch", "message": f"已切换到分支: {branch}"}
            return {"type": "error", "message": f"切换分支失败: {branch}"}

        elif action_type == "GIT_LIST_BRANCHES":
            branches = await git_manager.list_branches(project_id)
            current = await git_manager.get_current_branch(project_id)
            branch_list = "\n".join(f"  {'* ' if b == current else '  '}{b}" for b in branches)
            return {
                "type": "git_result", "action": "list_branches",
                "message": f"当前分支: **{current}**\n\n所有分支:\n{branch_list}",
                "data": {"current": current, "branches": branches},
            }

        elif action_type == "GIT_LOG":
            limit = min(data.get("limit", 10), 20)
            logs = await git_manager.get_log(project_id, limit)
            if not logs:
                return {"type": "git_result", "action": "log", "message": "暂无提交记录"}
            log_lines = []
            for c in logs:
                log_lines.append(f"- `{c.get('short_hash', '?')}` {c.get('message', '')} — {c.get('author', '')} ({c.get('date', '')})")
            return {
                "type": "git_result", "action": "log",
                "message": f"最近 {len(logs)} 条提交:\n\n" + "\n".join(log_lines),
            }

        elif action_type == "GIT_READ_FILE":
            path = data.get("path", "").strip()
            if not path:
                return {"type": "error", "message": "文件路径不能为空"}
            content = await git_manager.get_file_content(project_id, path)
            if content is None:
                return {"type": "error", "message": f"文件不存在: {path}"}
            # 截断超长内容
            if len(content) > 5000:
                content = content[:5000] + f"\n\n... (文件过长，已截断，共 {len(content)} 字符)"
            return {
                "type": "git_result", "action": "read_file",
                "message": f"**{path}** 内容:\n\n```\n{content}\n```",
            }

        elif action_type == "GIT_MERGE":
            source = data.get("source", "").strip()
            target = data.get("target", "").strip()
            if not source or not target:
                return {"type": "error", "message": "源分支和目标分支不能为空"}
            result = await git_manager.merge_branch(project_id, source, target)
            if result.get("success"):
                return {
                    "type": "git_result", "action": "merge",
                    "message": f"合并成功: {source} → {target} (commit: {result.get('commit', '?')})",
                }
            return {"type": "error", "message": f"合并失败: {result.get('error', '未知错误')}"}

        return {"type": "error", "message": f"未知 Git 操作: {action_type}"}

    except Exception as e:
        logger.error("Git 操作失败: %s", e)
        return {"type": "error", "message": f"Git 操作失败: {str(e)}"}


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
    """清除回复中的操作指令标记（包括未闭合的块）"""
    import re
    # 先清除完整的 [ACTION:...]...[/ACTION]
    cleaned = re.sub(r'\[ACTION:\w+\].*?\[/ACTION\]', '', response, flags=re.DOTALL)
    # 再清除未闭合的 [ACTION:...] 到字符串结尾（token 截断导致）
    cleaned = re.sub(r'\[ACTION:\w+\].*$', '', cleaned, flags=re.DOTALL)
    return cleaned.strip()


async def _save_chat_message(
    project_id: str,
    role: str,
    content: str,
    action: dict = None,
    images: list = None,       # base64 data URL 列表
):
    """保存聊天消息到数据库，图片保存为文件"""
    from config import BASE_DIR
    msg_id = generate_id("MSG")

    # 保存图片文件，记录相对 URL 路径
    image_urls = []
    if images:
        chat_images_dir = BASE_DIR / "chat_images" / project_id
        chat_images_dir.mkdir(parents=True, exist_ok=True)
        for data_url in images:
            try:
                header, b64data = data_url.split(",", 1)
                ext = header.split(";")[0].split("/")[-1]  # png / jpeg / gif / webp
                ext = ext if ext in ("png", "jpeg", "gif", "webp") else "png"
                filename = f"{uuid.uuid4().hex}.{ext}"
                file_path = chat_images_dir / filename
                file_path.write_bytes(base64.b64decode(b64data))
                image_urls.append(f"/chat-images/{project_id}/{filename}")
            except Exception as e:
                logger.warning("聊天图片保存失败，已跳过: %s", e)

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

    messages.append({"role": "user", "content": _build_user_content(req.message, req.images)})

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

        logger.info("AI助手创建项目: %s, 仓库路径: %s", name, repo_path)

        git_dir = os.path.join(repo_path, ".git")
        cloned = False
        push_success = False

        if git_remote_url and not os.path.isdir(git_dir):
            # 远程仓库 + 本地无 .git：尝试 clone
            if os.path.isdir(repo_path) and os.listdir(repo_path):
                # 目录非空但无 .git，init + fetch + reset
                logger.info("目录非空但无 .git，执行 init + fetch + reset")
                await git_manager._run_git(repo_path, "init", "-b", "main")
                git_manager.set_project_path(project_id, repo_path)
                await git_manager.set_remote(project_id, git_remote_url)
                await git_manager._run_git(repo_path, "fetch", "origin")
                # 检测远程默认分支
                rc, refs, _ = await git_manager._run_git(repo_path, "ls-remote", "--symref", "origin", "HEAD")
                remote_branch = "main"
                if "refs/heads/" in refs:
                    for line in refs.splitlines():
                        if "ref:" in line and "refs/heads/" in line:
                            remote_branch = line.split("refs/heads/")[-1].split()[0]
                            break
                await git_manager._run_git(repo_path, "reset", "--mixed", f"origin/{remote_branch}")
                await git_manager._run_git(repo_path, "checkout", ".")
                cloned = True
            else:
                # 目录为空或不存在：直接 clone
                if os.path.isdir(repo_path):
                    try:
                        os.rmdir(repo_path)
                    except OSError:
                        pass
                cloned = await git_manager.clone(git_remote_url, repo_path)
                if cloned:
                    logger.info("clone 成功，使用远程仓库内容")
                    git_manager.set_project_path(project_id, repo_path)
                else:
                    logger.warning("clone 失败，回退到本地初始化")
                    os.makedirs(repo_path, exist_ok=True)

        if not cloned:
            # 本地初始化流程
            os.makedirs(repo_path, exist_ok=True)
            for d in git_manager.REPO_DIRS:
                os.makedirs(os.path.join(repo_path, d), exist_ok=True)

            readme = f"# {name}\n\n{description or '由 AI 自动开发系统创建的项目'}\n"
            readme_path = os.path.join(repo_path, "README.md")
            if not os.path.exists(readme_path):
                with open(readme_path, "w", encoding="utf-8") as f:
                    f.write(readme)

            gitignore = "__pycache__/\n*.py[cod]\n.venv/\nvenv/\n.idea/\n.vscode/\n.DS_Store\nThumbs.db\n.env\n*.log\n"
            gitignore_path = os.path.join(repo_path, ".gitignore")
            if not os.path.exists(gitignore_path):
                with open(gitignore_path, "w", encoding="utf-8") as f:
                    f.write(gitignore)

            if not os.path.isdir(git_dir):
                await git_manager._run_git(repo_path, "init", "-b", "main")

            if git_remote_url:
                await git_manager.set_remote(project_id, git_remote_url)

            await git_manager._run_git(repo_path, "add", ".")
            await git_manager._run_git(
                repo_path, "commit", "-m",
                f"init: {name} - project initialized by AI Dev System",
                "--author", "AI Dev System <ai@dev-system.local>",
            )

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

        # 异步生成初版 Roadmap
        import asyncio
        from api.milestones import generate_roadmap_for_project
        asyncio.create_task(generate_roadmap_for_project(project_id, name, description))

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
