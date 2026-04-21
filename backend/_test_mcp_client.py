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


def main():
    test_config_loads_and_filters_disabled()
    test_tool_name_namespacing()
    test_is_mcp_tool_routing()
    test_empty_config_no_crash()
    test_missing_config_file()
    print("\n🎉 MCPClient 单测全部通过（5/5）")


if __name__ == "__main__":
    main()
