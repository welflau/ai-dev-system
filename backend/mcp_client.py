"""
MCPClient — 让 ChatAssistant 接入外部 MCP (Model Context Protocol) server

对标 MagicAI `src/agents/game_agent/utils/mcp_manager.py`（MagicAI 只到配置层，
本实现补全了完整客户端：spawn subprocess / initialize / list_tools / call_tool）。

## 工作原理

启动时（FastAPI lifespan）：
  1. 读 `mcp_servers.json`，按 enabled=true 的条目 spawn stdio subprocess
  2. 每个 server 一个后台 asyncio.Task，持有 ClientSession
  3. 调 session.initialize() + session.list_tools() 缓存工具元数据
  4. 工具名加 `mcp__<server>__` 前缀避免冲突

ChatAssistant 调工具时：
  - 如果 tool_name 以 `mcp__` 开头 → call_tool() 路由到对应 server
  - session 通过 asyncio.Queue 串行化调用，避免并发乱序

关停时：取消后台 task，subprocess 随之清理。

详见 docs/20260421_02_MCP客户端实现方案.md
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("mcp_client")

_CONFIG_PATH = Path(__file__).parent / "mcp_servers.json"
_TOOL_PREFIX = "mcp__"
_CALL_TIMEOUT_SEC = 30.0
_RESPONSE_MAX_CHARS = 10000


def _make_tool_name(server_name: str, raw_name: str) -> str:
    return f"{_TOOL_PREFIX}{server_name}__{raw_name}"


def _parse_tool_name(tool_name: str) -> Optional[Tuple[str, str]]:
    """反向解析 `mcp__<server>__<tool>` → (server_name, raw_tool_name)"""
    if not tool_name.startswith(_TOOL_PREFIX):
        return None
    rest = tool_name[len(_TOOL_PREFIX):]
    if "__" not in rest:
        return None
    server, raw = rest.split("__", 1)
    return server, raw


def _truncate_response(text: str) -> str:
    if not text:
        return ""
    if len(text) <= _RESPONSE_MAX_CHARS:
        return text
    return text[:_RESPONSE_MAX_CHARS] + f"\n... (truncated, 共 {len(text)} 字符)"


class _ServerConnection:
    """单个 MCP server 的会话管理 —— 后台 task + 调用队列"""

    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self.config = config
        self.tools: List[Dict[str, Any]] = []  # 缓存的工具列表（Anthropic schema 格式）
        self.status: str = "pending"            # pending | running | error | stopped
        self.error: Optional[str] = None
        self._task: Optional[asyncio.Task] = None
        self._ready_event = asyncio.Event()
        self._call_queue: "asyncio.Queue[Tuple[str, Dict, asyncio.Future]]" = asyncio.Queue()

    async def start(self, startup_timeout: float = 20.0) -> bool:
        """启动后台 task，等 ready 或 error。返回是否启动成功。"""
        self._task = asyncio.create_task(self._run_loop(), name=f"mcp_server_{self.name}")
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=startup_timeout)
        except asyncio.TimeoutError:
            self.status = "error"
            self.error = f"启动超时 ({startup_timeout}s)"
            logger.warning("MCP server %s 启动超时", self.name)
            return False
        return self.status == "running"

    async def stop(self):
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self.status = "stopped"

    async def call(self, raw_tool_name: str, tool_input: Dict[str, Any]) -> str:
        """队列提交一次调用，由后台 task 消费"""
        if self.status != "running":
            return json.dumps({"error": f"MCP server '{self.name}' 未就绪: {self.status}"}, ensure_ascii=False)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        await self._call_queue.put((raw_tool_name, tool_input, fut))
        try:
            return await asyncio.wait_for(fut, timeout=_CALL_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            return json.dumps({"error": f"MCP 调用超时 ({_CALL_TIMEOUT_SEC}s)"}, ensure_ascii=False)

    async def _run_loop(self):
        """持有 session 生命周期，串行消费调用队列"""
        from mcp.client.stdio import stdio_client, StdioServerParameters
        from mcp import ClientSession

        params = StdioServerParameters(
            command=self.config["command"],
            args=self.config.get("args", []),
            env=self.config.get("env") or None,
        )
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools_resp = await session.list_tools()
                    self.tools = self._format_tools(tools_resp.tools)
                    self.status = "running"
                    self._ready_event.set()
                    logger.info("✅ MCP server %s 启动: %d 个工具", self.name, len(self.tools))

                    # 串行消费调用
                    while True:
                        raw_name, tool_input, fut = await self._call_queue.get()
                        try:
                            result = await session.call_tool(raw_name, tool_input or {})
                            # result.content 是 list[TextContent | ImageContent | ...]
                            text = _extract_text(result.content)
                            fut.set_result(_truncate_response(text))
                        except Exception as e:
                            fut.set_result(json.dumps(
                                {"error": f"MCP 调用失败: {type(e).__name__}: {e}"},
                                ensure_ascii=False,
                            ))
        except asyncio.CancelledError:
            self.status = "stopped"
            raise
        except Exception as e:
            self.status = "error"
            self.error = f"{type(e).__name__}: {e}"
            logger.warning("MCP server %s 启动失败: %s", self.name, self.error)
            self._ready_event.set()  # 解除 start() 的等待

    def _format_tools(self, mcp_tools: List[Any]) -> List[Dict[str, Any]]:
        """MCP Tool → Anthropic tool_schema 格式（加前缀）"""
        formatted = []
        for t in mcp_tools:
            # mcp.types.Tool 有 name / description / inputSchema
            schema = getattr(t, "inputSchema", None) or {}
            formatted.append({
                "name": _make_tool_name(self.name, t.name),
                "description": (getattr(t, "description", "") or "")[:1000],
                "input_schema": schema if isinstance(schema, dict) else {"type": "object", "properties": {}},
            })
        return formatted


def _extract_text(content_blocks: List[Any]) -> str:
    """从 MCP call_tool 返回的 content 里挑 text"""
    parts = []
    for blk in content_blocks or []:
        # TextContent: type=text, text=...
        text = getattr(blk, "text", None)
        if text:
            parts.append(text)
        else:
            # 其他类型（image/resource）打摘要
            parts.append(f"[{type(blk).__name__}]")
    return "\n".join(parts)


class MCPClient:
    """MCPClient 单例：多 server 管理 + 路由"""

    def __init__(self, config_path: Path = _CONFIG_PATH):
        self.config_path = config_path
        self._servers: Dict[str, _ServerConnection] = {}
        self._servers_config: Dict[str, Dict[str, Any]] = {}
        self._started = False
        self._load_config()

    def _load_config(self):
        if not self.config_path.exists():
            logger.info("mcp_servers.json 不存在，MCP 客户端禁用")
            return
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self._servers_config = json.load(f)
        except Exception as e:
            logger.warning("加载 mcp_servers.json 失败: %s", e)
            self._servers_config = {}

    async def start_enabled_servers(self) -> None:
        """启动所有 enabled=true 的 server。逐个启动，失败不阻塞其他。"""
        if self._started:
            return
        self._started = True
        enabled = {n: c for n, c in self._servers_config.items() if c.get("enabled")}
        if not enabled:
            logger.info("MCP 客户端：无启用的 server")
            return
        logger.info("MCP 客户端：启动 %d 个 server...", len(enabled))
        for name, cfg in enabled.items():
            conn = _ServerConnection(name, cfg)
            ok = await conn.start()
            self._servers[name] = conn
            if not ok:
                logger.warning("MCP server %s 启动失败，跳过：%s", name, conn.error)

    async def stop_all_servers(self) -> None:
        for conn in self._servers.values():
            await conn.stop()
        self._servers.clear()
        self._started = False

    def is_mcp_tool(self, tool_name: str) -> bool:
        return tool_name.startswith(_TOOL_PREFIX)

    def list_all_tool_schemas(self) -> List[Dict[str, Any]]:
        """所有 running server 的工具列表（已加 mcp__ 前缀）"""
        schemas = []
        for conn in self._servers.values():
            if conn.status == "running":
                schemas.extend(conn.tools)
        return schemas

    async def call_tool(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        """分发到对应 server；返回 JSON 字符串或纯文本"""
        parsed = _parse_tool_name(tool_name)
        if not parsed:
            return json.dumps({"error": f"非 MCP 工具名: {tool_name}"}, ensure_ascii=False)
        server_name, raw_name = parsed
        conn = self._servers.get(server_name)
        if conn is None:
            return json.dumps(
                {"error": f"MCP server '{server_name}' 未启动（enabled=false 或启动失败）"},
                ensure_ascii=False,
            )
        return await conn.call(raw_name, tool_input or {})

    def get_status(self) -> Dict[str, Any]:
        """状态查询（供 /api/mcp/status + 调试）"""
        result: Dict[str, Any] = {"servers": {}}
        for name, cfg in self._servers_config.items():
            conn = self._servers.get(name)
            if conn is None:
                status = "disabled" if not cfg.get("enabled") else "not_started"
                result["servers"][name] = {
                    "enabled": bool(cfg.get("enabled")),
                    "status": status,
                    "description": cfg.get("description", ""),
                    "tools": [],
                    "error": None,
                }
            else:
                result["servers"][name] = {
                    "enabled": True,
                    "status": conn.status,
                    "description": cfg.get("description", ""),
                    "tools": [t["name"] for t in conn.tools],
                    "error": conn.error,
                }
        return result


# 单例
mcp_client = MCPClient()
