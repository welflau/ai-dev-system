---
description: 查看或管理项目 MCP server（/mcp-config 别名）
args_hint: "[enable|disable|add|list] [server名]"
requires_project: true
---

# /mcp [操作] [参数]

等同于 `/mcp-config`，管理当前项目的 MCP server 配置。

## 用法

```
/mcp                      列出所有 MCP server（全局 + 项目层合并状态）
/mcp enable filesystem    在项目层启用 filesystem MCP
/mcp disable git          在项目层禁用 git MCP
/mcp add <名称> <命令>    添加项目私有 MCP server
```
