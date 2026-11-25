"""LLM 配置展示与 Agent 覆盖、CLI 模型刷新及连接测试接口。"""
from fastapi import APIRouter, HTTPException

from services import global_llm_config, llm_config as agent_config

router = APIRouter(prefix="/api/llm")


@router.get("/status")
async def llm_status():
    """LLM 状态。

    display_model = 当前**实际生效**的模型名：CLI 模式用 cli_model，API 模式用 model。
    顶栏徽标、聊天头像等「展示当前模型」的位置一律用它，不要用 model —— CLI 模式下
    model 只是 API 模式遗留的主模型名（例如切到 CLI 前留下的 hy4），并不参与实际调用，
    直接展示会误导用户以为在用 hy4。model 字段保留原语义供 API 模式输入框回填。
    """
    return agent_config.status_view()


@router.get("/agents")
async def llm_agents():
    """枚举所有 Agent + 各自 LLM 生效配置（覆盖 or 继承全局）"""
    return await agent_config.agent_config_view()


@router.post("/cli-models/refresh")
async def llm_cli_models_refresh(body: dict = None):
    """从本地 CLI 实时查询模型列表（刷新下拉）"""
    from llm_client import fetch_cli_models, llm_client

    body = body or {}
    cli_type = body.get("cli_type") or llm_client.cli_type or "claude"
    cli_cmd = body.get("cli_cmd") or llm_client.cli_cmd or ""
    result = await fetch_cli_models(cli_type, cli_cmd)
    return {"cli_type": cli_type, "cli_cmd": cli_cmd, **result}


@router.post("/test")
async def llm_test():
    """测试 LLM 连接"""
    from llm_client import llm_client

    return await llm_client.test_connection()


def _agent_name(agent_type: str) -> str:
    name = (agent_type or "").strip()
    if not name:
        raise HTTPException(400, "agent_type 不能为空")
    return name


@router.post("/agents/{agent_type}/config")
async def llm_agent_config(agent_type: str, body: dict):
    """写/更新某 Agent 的 LLM 覆盖（upsert）。空 body 各字段为空串 = 显式继承全局语义不再适用，
    调用方要"恢复继承"请用 DELETE。"""
    name = _agent_name(agent_type)
    await agent_config.save_agent_override(name, body)
    return {"status": "ok", "agent_type": name}


@router.delete("/agents/{agent_type}/config")
async def llm_agent_config_delete(agent_type: str):
    """删除某 Agent 的覆盖 = 恢复继承全局配置"""
    name = _agent_name(agent_type)
    await agent_config.delete_agent_override(name)
    return {"status": "ok", "agent_type": name}


@router.post("/config")
async def llm_config(body: dict):
    """动态更新 LLM 配置并持久化到 .env"""
    return await global_llm_config.save_global_config(body)
