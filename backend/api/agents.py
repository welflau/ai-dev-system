"""
Agent API — 返回 Agent 实时信息（从注册中心和 Action 池动态读取）
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/agents", tags=["agents"])


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
