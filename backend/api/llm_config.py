"""LLM 配置展示、CLI 模型刷新与连接测试接口。"""
from fastapi import APIRouter

from services import llm_config

router = APIRouter(prefix="/api/llm")


@router.get("/status")
async def llm_status():
    """LLM 状态。

    display_model = 当前**实际生效**的模型名：CLI 模式用 cli_model，API 模式用 model。
    顶栏徽标、聊天头像等「展示当前模型」的位置一律用它，不要用 model —— CLI 模式下
    model 只是 API 模式遗留的主模型名（例如切到 CLI 前留下的 hy4），并不参与实际调用，
    直接展示会误导用户以为在用 hy4。model 字段保留原语义供 API 模式输入框回填。
    """
    return llm_config.status_view()


@router.get("/agents")
async def llm_agents():
    """枚举所有 Agent + 各自 LLM 生效配置（覆盖 or 继承全局）"""
    return await llm_config.agent_config_view()


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
