"""
Agent API — 返回 Agent 实时信息（从注册中心和 Action 池动态读取）
"""
import re
import inspect
from fastapi import APIRouter

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _extract_prompt_preview(action_inst) -> str:
    """
    从 Action.run() 源码里提取 instruction= 字符串（静态文字部分）。
    返回最多 300 字符的预览；找不到则返回 action.description。
    """
    try:
        source = inspect.getsource(action_inst.run)
        # 提取所有 instruction= "..." 或 instruction= f"..." 的静态文字
        matches = re.findall(
            r'instruction\s*=\s*(?:f?)(?:"""(.*?)"""|\'\'\'(.*?)\'\'\'|"(.*?)"|\'(.*?)\')',
            source, re.DOTALL,
        )
        parts = []
        for m in matches:
            text = next((t for t in m if t), "").strip()
            if text and len(text) > 4:
                # 去掉 f-string 中的变量插值部分，保留文字骨架
                text = re.sub(r'\{[^}]+\}', '{…}', text)
                parts.append(text)
        if parts:
            combined = "\n---\n".join(parts)
            return combined[:400]
    except Exception:
        pass
    return action_inst.description or ""


# ChatAssistant 系统提示词的结构摘要（静态）
_CHAT_ASSISTANT_PROMPT_SUMMARY = """## 身份
AI 自动开发系统的智能助手，服务于当前项目的全流程开发。

## 核心能力
- **需求管理**：confirm_requirement / confirm_requirements_batch（识别单条/多条需求）
- **BUG 管理**：confirm_bug（识别缺陷，不自动创建）
- **需求状态**：pause / resume / close / pause_requirements_batch
- **仓库操作**：git_log / git_list_branches / git_switch_branch / git_merge / git_read_file
- **进度诊断**：get_requirement_pipeline / get_ticket_status / get_requirement_logs
- **文件操作**：glob（通配搜索）/ grep（内容搜索）/ list_directory / read_files / shell
- **知识检索**：search_knowledge（知识库）/ search_ticket_history（历史工单）/ web_search（联网）
- **文档生成**：generate_document / confirm_save_doc
- **Skill 管理**：load_skill / browse_marketplace / install_project_skill
- **子任务派发**：dispatch_subtask（创建子 Ticket）

## 搜索优先级
问系统/文档 → search_knowledge；问代码 → grep/glob；问外部 → web_search（明确说联网时立即执行）

## 判断准则
- 用户询问 ≠ 要求执行；只有明确说"帮我创建/上报/关闭"才调用行动工具
- 多步操作可在同一轮连续调用多个工具（ReAct 循环）
- 信息已在上下文中 → 直接回答，不重复调工具""".strip()


@router.get("")
async def list_agents():
    """获取所有 Agent 详情（含 Actions、Mode、Watch、Schema）"""
    from orchestrator import orchestrator
    from actions import ACTION_REGISTRY

    agents = []
    icons = {
        "ProductAgent": "📝", "ArchitectAgent": "🏗️", "DevAgent": "💻",
        "TestAgent": "🧪", "ReviewAgent": "🔍", "DeployAgent": "🚀",
    }
    roles = {
        "ProductAgent": "产品经理 — 需求拆单 + 产品验收",
        "ArchitectAgent": "架构师 — 增量架构设计",
        "DevAgent": "开发工程师 — 代码开发 + 自测",
        "TestAgent": "测试工程师 — 5层质量测试",
        "ReviewAgent": "代码审查 — 读取实际代码审查",
        "DeployAgent": "运维工程师 — 三环境部署",
    }

    for name, agent in orchestrator.agents.items():
        action_details = []
        for action_name in agent.list_actions():
            action_cls = ACTION_REGISTRY.get(action_name)
            if action_cls:
                action_inst = action_cls()
                # 获取 Schema 信息
                schema_info = None
                # 检查 Action 是否有对应的 ActionNode Schema
                import inspect
                source = inspect.getsource(action_inst.run)
                if "ActionNode" in source and "expected_type" in source:
                    # 提取 expected_type
                    for line in source.split("\n"):
                        if "expected_type=" in line:
                            type_name = line.split("expected_type=")[1].split(",")[0].split(")")[0].strip()
                            schema_info = {"type": type_name, "mode": "ActionNode"}
                            break
                if not schema_info:
                    schema_info = {"type": "legacy", "mode": "legacy"}

                action_details.append({
                    "name": action_name,
                    "description": action_inst.description,
                    "schema": schema_info,
                    "prompt_preview": _extract_prompt_preview(action_inst),
                })
            else:
                action_details.append({"name": action_name, "description": "", "schema": {"mode": "unknown"}})

        # 状态信息
        status_info = orchestrator._agent_status.get(name, {})

        agents.append({
            "name": name,
            "icon": icons.get(name, "🤖"),
            "role": roles.get(name, name),
            "enabled": True,
            "react_mode": agent.react_mode.value if hasattr(agent.react_mode, 'value') else "single",
            "watch_actions": list(agent.watch_actions) if agent.watch_actions else [],
            "actions": action_details,
            "status": status_info.get("status", "idle"),
            "completed_count": status_info.get("completed_count", 0),
            "error_count": status_info.get("error_count", 0),
        })

    # ChatAssistant：补充 agent_prompt 和正确的 Actions 信息
    # （ChatAssistant 可能已在 orchestrator.agents 里，也可能不在——统一处理）
    chat_entry = next((a for a in agents if a["name"] == "ChatAssistant"), None)
    if chat_entry:
        # 已在列表里，补充 agent_prompt 和图标
        chat_entry["icon"] = "💬"
        chat_entry["role"] = "AI 助手 — 聊天 + 工具调用"
        chat_entry["agent_prompt"] = _CHAT_ASSISTANT_PROMPT_SUMMARY
        # 用 ChatAssistantAgent 的真实 Actions 补全描述
        try:
            from agents.chat_assistant import ChatAssistantAgent
            _ca = ChatAssistantAgent()
            chat_entry["actions"] = [
                {
                    "name": act_name,
                    "description": act_inst.description,
                    "schema": {"mode": "chat"},
                    "prompt_preview": "",
                }
                for act_name, act_inst in _ca._actions.items()
            ]
        except Exception:
            pass
    else:
        agents.append({
            "name": "ChatAssistant",
            "icon": "💬",
            "role": "AI 助手 — 聊天 + 工具调用",
            "enabled": True,
            "react_mode": "react",
            "watch_actions": [],
            "actions": [],
            "status": "idle",
            "completed_count": 0,
            "error_count": 0,
            "agent_prompt": _CHAT_ASSISTANT_PROMPT_SUMMARY,
        })

    return {"agents": agents}


@router.get("/status")
async def get_agents_status():
    """获取所有 Agent 实时运行状态"""
    from orchestrator import orchestrator
    status = orchestrator.get_agent_status()
    agents_dict = status.get("agents", status)

    for name, agent in orchestrator.agents.items():
        if name in agents_dict:
            agents_dict[name]["actions"] = agent.list_actions()
            agents_dict[name]["react_mode"] = agent.react_mode.value if hasattr(agent.react_mode, 'value') else str(agent.react_mode)
            agents_dict[name]["watch_actions"] = list(agent.watch_actions) if agent.watch_actions else []
            agents_dict[name]["is_action_mode"] = len(agent.list_actions()) > 0

    return status


@router.get("/orchestrator")
async def get_orchestrator_status():
    """Orchestrator 调度引擎详细状态：正在处理 + 待处理队列"""
    from orchestrator import orchestrator
    from database import db
    import time

    # ── 正在处理的工单（_agent_status 里 working 的条目）──
    active = []
    for name, info in orchestrator._agent_status.items():
        if info.get("status") == "working":
            started = info.get("started_at")
            elapsed_s = 0
            if started:
                try:
                    from datetime import datetime, timezone
                    t = datetime.fromisoformat(started.replace("Z", "+00:00"))
                    elapsed_s = int((datetime.now(timezone.utc) - t).total_seconds())
                except Exception:
                    pass
            active.append({
                "agent":       name,
                "action":      info.get("action", ""),
                "ticket_id":   info.get("ticket_id", ""),
                "ticket_title": info.get("ticket_title", ""),
                "started_at":  started,
                "elapsed_s":   elapsed_s,
            })

    # ── 待处理队列（actionable 状态的工单，未在 _processing 中）──
    try:
        actionable = await orchestrator._get_all_actionable_statuses()
        if actionable:
            placeholders = ",".join(["?"] * len(actionable))
            pending_rows = await db.fetch_all(
                f"SELECT t.id, t.title, t.status, t.project_id "
                f"FROM tickets t "
                f"WHERE t.status IN ({placeholders}) "
                f"AND t.id NOT IN ({','.join(['?']*len(orchestrator._processing)) or 'NULL'}) "
                f"ORDER BY t.priority ASC, t.sort_order ASC LIMIT 20",
                tuple(actionable) + tuple(orchestrator._processing),
            )
            queue = [{"id": r["id"], "title": r["title"], "status": r["status"]} for r in pending_rows]
        else:
            queue = []
    except Exception as e:
        queue = []

    # 待处理按状态聚合
    from collections import Counter
    queue_summary = dict(Counter(r["status"] for r in queue))

    return {
        "max_concurrent":     orchestrator._MAX_CONCURRENT_PER_PROJECT,
        "processing_count":   len(orchestrator._processing),
        "processing_tickets": list(orchestrator._processing),
        "active_agents":      active,
        "queue_count":        len(queue),
        "queue_summary":      queue_summary,
        "queue_preview":      queue[:5],
    }


@router.get("/actions")
async def list_all_actions():
    """获取 Action 池全览"""
    from actions import list_actions
    from orchestrator import orchestrator
    agent_actions = {}
    for name, agent in orchestrator.agents.items():
        agent_actions[name] = agent.list_actions()
    return {"actions": list_actions(), "agent_actions": agent_actions}


@router.get("/{agent_name}")
async def get_agent(agent_name: str):
    """获取单个 Agent 详情"""
    from orchestrator import orchestrator
    agent = orchestrator.agents.get(agent_name)
    if not agent:
        return {"error": f"Agent '{agent_name}' not found"}

    icons = {"ProductAgent": "📝", "ArchitectAgent": "🏗️", "DevAgent": "💻",
             "TestAgent": "🧪", "ReviewAgent": "🔍", "DeployAgent": "🚀"}

    return {
        "name": agent_name,
        "icon": icons.get(agent_name, "🤖"),
        "agent_type": agent.agent_type,
        "react_mode": agent.react_mode.value if hasattr(agent.react_mode, 'value') else "single",
        "actions": agent.list_actions(),
        "watch_actions": list(agent.watch_actions) if agent.watch_actions else [],
    }
