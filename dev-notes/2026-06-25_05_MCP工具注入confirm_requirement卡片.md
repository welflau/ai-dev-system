# MCP Tool 方案：confirm_requirement 通过 ads-data MCP server 注入

## 问题
DeepSeek 跑在 codebuddy agent 模式下，只能看到 codebuddy 自己的工具列表（EnterPlanMode、Write 等），无法调用 ADS 的 confirm_requirement。文本协议注入 system prompt 无效。

## 解法：全局注入 ads-data MCP server

### 1. `llm_client.py` — `_build_settings_args` 重构

- **不再依赖 `.ads/mcp_servers.json`** — 始终全局注入 `ads-data` MCP server
- 自动用 `sys.executable` + `ads_data_mcp_server.py` 绝对路径构建启动命令
- `.ads/mcp_servers.json` 存在时追加（项目级扩展，不冲突）
- **codebuddy** 用 `--mcp-config`；**claude/claude-internal/tclaude** 用 `--settings`（之前两者都用 `--settings`，codebuddy 不识别）
- 去掉 `cwd` 强制检查（全局注入不需要 cwd）

### 2. `ads_data_mcp_server.py` — 新增两个 Chat Action tool

新增 `ADS_BASE_URL` 环境变量（默认 `http://localhost:8000`）。

**`confirm_requirement(project_id, title, description, priority)`**
- 触发时机：用户说「帮我做…」「创建一个…」「新增…」
- 行为：POST `/api/projects/{project_id}/chat/mcp-action` → ADS 推 SSE → 前端弹卡片

**`confirm_bug(project_id, title, description, priority, requirement_id)`**
- 触发时机：用户描述 Bug/报错/崩溃
- 行为：同上

### 3. `api/chat.py` — 新增 `/mcp-action` 端点

`POST /api/projects/{project_id}/chat/mcp-action`
- 接收 MCP tool 的 HTTP 回调
- 复用 `_parse_and_execute_action` 解析 action
- 通过 `event_manager.publish_to_project` 推 `chat_mcp_action` SSE 事件

### 4. `frontend/app.js`

- SSE 监听 `chat_mcp_action` 事件 → 调 `appendMcpActionCard(action)`
- `appendMcpActionCard`：在聊天窗口追加 assistant 气泡，复用现有 `renderActionCard` 渲染卡片
- `checkLLMStatus` 时缓存 `window._currentCliType`，供头像图标使用

## 链路
```
用户说「创建一个 NPC 角色」
  → codebuddy agent（DeepSeek）
  → 调用 MCP tool: confirm_requirement(project_id="...", title="NPC角色", ...)
  → ads_data_mcp_server.py handler
  → POST http://localhost:8000/api/projects/{pid}/chat/mcp-action
  → SSE: chat_mcp_action → 前端
  → appendMcpActionCard → 弹出需求确认卡片
  → 用户点「确认创建」→ 正式创建需求
```
