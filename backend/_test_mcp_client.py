"""
MCPClient 单元测试（mock 为主，不实际 spawn MCP server）

5 用例：
1. 配置加载：mcp_servers.json 解析正确，disabled 条目不会启动
2. 工具名 namespacing：mcp__<server>__<tool> 前缀 + 反向解析
3. is_mcp_tool 路由判断
4. get_status 对每种状态（disabled / not_started / running）都正确
5. call_tool 在 server 不存在时优雅降级

运行：cd backend && PYTHONIOENCODING=utf-8 python _test_mcp_client.py
"""
import asyncio
import json
import tempfile
from pathlib import Path


def test_config_loads_and_filters_disabled():
    from mcp_client import MCPClient

    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "mcp_servers.json"
        cfg_path.write_text(json.dumps({
            "enabled_server": {
                "command": "echo", "args": ["hi"], "enabled": True, "description": "test on",
            },
            "disabled_server": {
                "command": "echo", "args": ["bye"], "enabled": False, "description": "test off",
            },
        }, ensure_ascii=False), encoding="utf-8")

        client = MCPClient(config_path=cfg_path)
        # 只有 enabled 的 server 会在 start 时被激活；config 保留两条
        assert "enabled_server" in client._servers_config
        assert "disabled_server" in client._servers_config
        assert client._servers_config["disabled_server"]["enabled"] is False

        status = client.get_status()
        assert status["servers"]["enabled_server"]["status"] == "not_started"
        assert status["servers"]["disabled_server"]["status"] == "disabled"
        assert status["servers"]["enabled_server"]["enabled"] is True
        assert status["servers"]["disabled_server"]["enabled"] is False
    print("✅ Test 1 配置加载 + disabled 过滤通过")


def test_tool_name_namespacing():
    from mcp_client import _make_tool_name, _parse_tool_name

    assert _make_tool_name("filesystem", "read_file") == "mcp__filesystem__read_file"
    assert _make_tool_name("fetch", "fetch_url") == "mcp__fetch__fetch_url"

    assert _parse_tool_name("mcp__filesystem__read_file") == ("filesystem", "read_file")
    assert _parse_tool_name("mcp__fetch__fetch_url") == ("fetch", "fetch_url")
    # 工具名里可能有双下划线，只按第一个分
    assert _parse_tool_name("mcp__git__list__branches") == ("git", "list__branches")

    # 非 MCP 工具名
    assert _parse_tool_name("confirm_requirement") is None
    assert _parse_tool_name("mcp_filesystem_read") is None  # 缺一条 _
    assert _parse_tool_name("mcp__") is None  # 没 tool 部分
    print("✅ Test 2 工具名 namespacing 通过")


def test_is_mcp_tool_routing():
    from mcp_client import MCPClient

    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "mcp_servers.json"
        cfg_path.write_text("{}", encoding="utf-8")
        client = MCPClient(config_path=cfg_path)

        assert client.is_mcp_tool("mcp__filesystem__read_file") is True
        assert client.is_mcp_tool("confirm_requirement") is False
        assert client.is_mcp_tool("") is False
        assert client.is_mcp_tool("mcp_singleunderscore__tool") is False  # 前缀错误
    print("✅ Test 3 is_mcp_tool 路由判断通过")


def test_empty_config_no_crash():
    """完全没配置 / 配置里没 enabled 的条目，start_enabled_servers 应优雅返回"""
    from mcp_client import MCPClient

    with tempfile.TemporaryDirectory() as td:
        cfg_path = Path(td) / "mcp_servers.json"
        cfg_path.write_text(json.dumps({
            "only_disabled": {"command": "x", "args": [], "enabled": False},
        }), encoding="utf-8")

        async def run():
            client = MCPClient(config_path=cfg_path)
            await client.start_enabled_servers()
            # 没有任何 server 启动，但 client 可用
            assert client.list_all_tool_schemas() == []
            # 调用不存在的 server 应返回 error JSON，不抛
            result = await client.call_tool("mcp__doesnotexist__tool", {})
            data = json.loads(result)
            assert "error" in data
            await client.stop_all_servers()

        asyncio.run(run())
    print("✅ Test 4 空配置 / 无 enabled server 不崩通过")


def test_missing_config_file():
    """mcp_servers.json 不存在时 client 仍可实例化"""
    from mcp_client import MCPClient

    with tempfile.TemporaryDirectory() as td:
        # 指向一个不存在的文件
        ghost = Path(td) / "not_exist.json"
        client = MCPClient(config_path=ghost)
        assert client._servers_config == {}

        async def run():
            await client.start_enabled_servers()  # 不崩
            assert client.list_all_tool_schemas() == []
            assert client.get_status() == {"servers": {}}
            await client.stop_all_servers()

        asyncio.run(run())
    print("✅ Test 5 配置文件缺失不崩通过")


def test_http_mcp_port_sniffer():
    """方案 1：测试项目候选端口提取与本地 /mcp 协议自动嗅探（含 JSON 与 SSE 两种响应格式 + DELETE 会话清理）"""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading
    from mcp_client import (
        _collect_candidate_mcp_ports,
        probe_http_mcp_endpoint,
        sniff_project_http_mcp_servers,
        _load_project_mcp_config,
        _SNIFFED_MCP_CACHE,
    )

    deleted_sessions = []

    class _MockMcpHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_POST(self):
            if self.path != "/mcp":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if body.get("method") == "initialize":
                resp_payload = {
                    "jsonrpc": "2.0",
                    "id": body.get("id", 1),
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "bagins", "version": "0.1.0"},
                    },
                }
                # 模拟 StreamableHTTPServerTransport 的 text/event-stream 响应
                sse_body = f"event: message\ndata: {json.dumps(resp_payload)}\n\n".encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("mcp-session-id", "mock-session-123")
                self.send_header("Content-Length", str(len(sse_body)))
                self.end_headers()
                self.wfile.write(sse_body)

        def do_DELETE(self):
            sid = self.headers.get("mcp-session-id")
            if sid:
                deleted_sessions.append(sid)
            self.send_response(200)
            self.end_headers()

    httpd = HTTPServer(("127.0.0.1", 0), _MockMcpHandler)
    port = httpd.server_port
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()

    try:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            # 模拟 Vite 项目配置端口为 mock server 端口
            (repo / "package.json").write_text(
                json.dumps({"name": "kinema-mock", "scripts": {"dev": "vite"}, "devDependencies": {"vite": "^8.0.0"}}),
                encoding="utf-8",
            )
            (repo / "vite.config.ts").write_text(
                f"export default {{ server: {{ port: {port} }} }};",
                encoding="utf-8",
            )

            ports = _collect_candidate_mcp_ports(str(repo))
            assert port in ports, f"Expected {port} in {ports}"

            async def run_sniff():
                info = await probe_http_mcp_endpoint(f"http://127.0.0.1:{port}/mcp")
                assert info is not None
                assert info["name"] == "bagins"
                assert info["version"] == "0.1.0"
                assert "mock-session-123" in deleted_sessions

                discovered = await sniff_project_http_mcp_servers(str(repo))
                assert "bagins" in discovered
                assert discovered["bagins"]["url"] == f"http://127.0.0.1:{port}/mcp"
                assert discovered["bagins"]["_source"] == "sniffed"
                assert discovered["bagins"]["enabled"] is True

                merged_cfg = _load_project_mcp_config(str(repo), include_user=False)
                assert "bagins" in merged_cfg
                assert merged_cfg["bagins"]["url"] == f"http://127.0.0.1:{port}/mcp"

                # 显式 .ads/mcp_servers.json 可以覆盖/禁用自动嗅探结果
                ads_dir = repo / ".ads"
                ads_dir.mkdir(exist_ok=True)
                (ads_dir / "mcp_servers.json").write_text(
                    json.dumps({"bagins": {"enabled": False}}),
                    encoding="utf-8",
                )
                merged_override = _load_project_mcp_config(str(repo), include_user=False)
                assert merged_override["bagins"]["enabled"] is False

            asyncio.run(run_sniff())
            _SNIFFED_MCP_CACHE.clear()
    finally:
        httpd.shutdown()
        httpd.server_close()

    print("✅ Test 6 运行时 HTTP MCP 端口自动嗅探 + 会话清理 + 配置覆盖通过")


def main():
    test_config_loads_and_filters_disabled()
    test_tool_name_namespacing()
    test_is_mcp_tool_routing()
    test_empty_config_no_crash()
    test_missing_config_file()
    test_http_mcp_port_sniffer()
    print("\n🎉 MCPClient 单测全部通过（6/6）")


if __name__ == "__main__":
    main()
