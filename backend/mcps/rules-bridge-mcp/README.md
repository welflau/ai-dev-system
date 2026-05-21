# rules-bridge-mcp

为外部 IDE（Claude Code、Cursor、CodeBuddy 等）提供 ADS 规则查询接口。

实现规则**单一真源、多工具共享**：ADS 的规则文件只维护一份，所有 AI 工具通过 MCP 调用获取适用规则。

## 工具

### `get_coding_rules`

返回适用于当前编辑文件的规则文本（系统规则 + 项目规则合并）。

**参数**：
- `file_path`：当前编辑文件路径（用于 `paths:` glob 匹配）
- `project_path`：项目仓库根路径（加载 `.ads/rules/`，可选）
- `traits`：项目 trait 列表，如 `["ue5", "game"]`（可选）
- `scene`：触发场景，`"autoaicr"` / `"precommit"` / 空（可选）

### `list_rules`

列出所有可用规则的元信息（id/paths/scene/alwaysApply）。

## 启动

### stdio 模式（Claude Code MCP）

```bash
python -m mcps.rules-bridge-mcp.server
```

### HTTP 模式

```bash
python -m mcps.rules-bridge-mcp.server --http 3100
```

## Claude Code 配置

在 `.claude/settings.json` 或 `~/.claude/settings.json` 中添加：

```json
{
  "mcpServers": {
    "ads-rules": {
      "command": "python",
      "args": ["-m", "mcps.rules-bridge-mcp.server"],
      "cwd": "/path/to/ai-dev-system/backend"
    }
  }
}
```

配置后，Claude Code 会在每次工具调用时自动提供 `get_coding_rules` 工具。

## 与 IDE 插件集成

在 IDE 的 AI 插件配置中，设置每次编辑文件时调用：

```
get_coding_rules(file_path=<当前文件>, project_path=<项目根目录>, traits=[...])
```

将返回的规则文本注入 system prompt 或附加为用户消息。

## 规则文件格式

每个规则文件（`backend/skills/rules/**/*.md` 或 `.ads/rules/**/*.md`）的 frontmatter：

```yaml
---
alwaysApply: false        # true = 所有场景注入
paths:                    # 按文件类型按需注入
  - "**/*.cpp"
  - "**/*.h"
scene: ""                 # 场景过滤：autoaicr / precommit / 空
traits_match:             # 项目 traits 过滤
  any_of: [ue5]
priority: high            # high / medium / low
description: "规则说明"
---

# 规则内容...
```
