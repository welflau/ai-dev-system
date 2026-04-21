"""
MCP 状态 API —— 只读查询当前启用了哪些 MCP server + 暴露了哪些工具

供：
- 前端未来的 /mcp 管理页
- ChatAssistant 自己回答"你现在接了哪些 MCP"类问题
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get("/status")
async def mcp_status():
    """返回所有配置的 MCP server 状态 + 每个 server 暴露的工具名"""
    from mcp_client import mcp_client
    return mcp_client.get_status()
