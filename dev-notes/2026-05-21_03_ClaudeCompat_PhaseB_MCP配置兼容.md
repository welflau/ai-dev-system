# ClaudeCompat Phase B — MCP 配置兼容

> 日期：2026-05-21
> 提交：`72dbe2b`
> 系列：ClaudeCompat（ADS 兼容 Claude Code 目录结构）

---

## 目标

`_load_project_mcp_config()` 同时读取 `.claude/settings.json["mcpServers"]`（Claude Code 标准格式）和 `.ads/mcp_servers.json`（ADS 格式），`.ads/` 优先级高于 `.claude/`。

---

## 改动文件

`backend/mcp_client.py`

---

## 两路合并逻辑

```
1. .claude/settings.json["mcpServers"]   低优先级（Claude Code 格式）
           ↓
2. .ads/mcp_servers.json                 高优先级（ADS 格式，同名字段覆盖）
```

**格式转换**：Claude Code 的 `mcpServers` 中无 `enabled` 字段，出现即视为 `enabled: true`。

**`_source` 字段**：每个 server 附加 `_source: "claude"` 或 `_source: "ads"`，供 `/mcp-config list` 展示来源。

---

## 测试结果

| 场景 | 验证点 | 结果 |
|------|--------|------|
| `.claude/settings.json` 中的 `filesystem` | enabled:true，source=claude | ✅ |
| `.ads/mcp_servers.json` 覆盖 `filesystem` args | 使用 .ads/ 的自定义路径 | ✅ |
| `.ads/` 禁用 `git`（全局 enabled:true） | enabled:false | ✅ |
| `.ads/` 新增 `project-db` | source=ads，仅该项目可用 | ✅ |

---

## `/mcp-config list` 展示效果

```
MCP Server     来源        状态
filesystem     .ads        启用 ✅
git            .ads        已禁用 ⭕
fetch          全局        已禁用 ⭕
project-db     .ads        启用 ✅
```
