---
description: 查看或修改项目级 MCP server 配置（.ads/mcp_servers.json）
args_hint: "[enable|disable|add|list] [server名]"
requires_project: true
---

# /mcp-config [操作] [参数]

查看或修改当前项目的 MCP server 配置（存储于 `.ads/mcp_servers.json`）。

## 用法

```
/mcp-config                    列出当前项目生效的所有 MCP server（全局 + 项目层合并）
/mcp-config enable filesystem  在项目层启用 filesystem MCP（覆盖全局 enabled:false）
/mcp-config disable git        在项目层禁用 git MCP
/mcp-config add <名称> <命令>  向项目层添加自定义 MCP server
```

## 配置来源说明

| 来源 | 文件 | 说明 |
|------|------|------|
| 全局层 | `backend/mcp_servers.json` | 所有项目默认可用，管理员维护 |
| 项目层 | `.ads/mcp_servers.json` | 该项目独立配置，优先级高于全局层 |

项目层可以：
- 将全局层 `enabled:false` 的 server 启用（如项目专属的 filesystem 路径）
- 将全局层 `enabled:true` 的 server 禁用
- 添加项目私有的 MCP server（其他项目不可见）
