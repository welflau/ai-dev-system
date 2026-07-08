"""
MCP 状态 API —— 只读查询当前启用了哪些 MCP server + 暴露了哪些工具

供：
- 前端未来的 /mcp 管理页
- ChatAssistant 自己回答"你现在接了哪些 MCP"类问题
"""
import asyncio
from fastapi import APIRouter

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get("/status")
async def mcp_status():
    """返回所有配置的 MCP server 状态 + 每个 server 暴露的工具名"""
    from mcp_client import mcp_client
    try:
        # 加 3 秒超时，防止 MCP subprocess 挂起导致 API 无响应
        result = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, mcp_client.get_status),
            timeout=3.0,
        )
        return result
    except asyncio.TimeoutError:
        return {"servers": {}, "error": "MCP 状态查询超时（MCP server 可能挂起）"}
    except Exception as e:
        return {"servers": {}, "error": str(e)}
