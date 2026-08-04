# DevNote · 2026-08-04（一）

**类型**: 功能迭代 + Bug 修复  
**状态**: 工作区改动（未提交），后端改动需重启服务生效  
**范围**: LLM CLI 接入 / 聊天消息元数据 / AI 配置 UI

---

## 一、接入 Cursor Agent CLI

在现有 `claude` / `codebuddy` / `tclaude` 等之外新增 `cli_type=cursor`。

### 适配要点（`backend/llm_client.py`）

| 项 | 说明 |
|---|---|
| 默认命令 | `agent`（亦可 `cursor-agent`） |
| 调用方式 | `-p --output-format stream-json --stream-partial-output --force --trust [--model …]` |
| Prompt | **不能纯 stdin**；`prompt_as_arg=True`，作为最后一个 CLI 参数 |
| Resume | 支持 `--resume`，插入在 prompt 参数之前 |
| 思考流 | 解析 Cursor 的 `{"type":"thinking","subtype":"delta"}` |
| 文本流 | 兼容累计快照帧（`startswith(full_text)` 只补 delta） |

### 前端 / 配置

- `index.html`：CLI 工具类型增加「Cursor Agent（agent）」
- `app.js`：`_CLI_ICONS.cursor`
- `config.py` / `.env.example` / `README.md`：补充 `LLM_CLI_TYPE=cursor`

精选模型下拉（内置）：`auto`、`composer-2.5`、`cursor-grok-4.5-*`、部分 Claude/GPT/Gemini 等。

---

## 二、根因修复：Cursor 秒退 →「操作已完成」

**现象**：发「你好」约 0.1s 回「操作已完成。」，头像显示 `auto`。

**根因**：Cursor 把整段 system+history 塞进命令行；Windows 上 `agent` 是 `agent.cmd`，经 `cmd /c` 启动，触发 **「命令行太长」**（约 8191 限制）。进程秒退、无 `text_delta`，流式落库兜底成「操作已完成。」。

**修复**：

1. **直调 `node.exe + index.js`**（`_resolve_cursor_agent_bin`），绕开 `cmd /c`
2. **超长 prompt**（估命令行 ≥ 28000）写临时文件，短引导语让 Agent 读文件执行
3. **stderr 曝光**：空正文时把 CLI stderr（GBK 解码）推成 `[CLI错误] …`，不再静默兜底

---

## 三、聊天消息快照 LLM 配置（历史头像不再漂移）

**现象**：历史气泡全部变成当前 Cursor/`auto` 图标——内容未改，是渲染用了全局 `_llmConfig`。

**此前**：`chat_messages` 不存 `cli_type` / `model`。

**本次**：

| 层 | 改动 |
|---|---|
| DB | `chat_messages` 增列 `api_format` / `cli_type` / `llm_model`（migration） |
| 保存 | `_snapshot_llm_meta`：assistant 落库时快照当前 `llm_client` |
| 前端 | `_buildAssistantAvatar(meta)` / `_msgLlmMeta(msg)`；历史 `appendChatBubble` 传入快照 |

**注意**：旧消息无快照，仍回退当前全局配置；仅**新消息**可稳定保留当时 CLI/模型图标。

---

## 四、AI 配置：模型列表「↻ 刷新」

内置 `CLI_MODEL_OPTIONS` 会过期；增加手动从本地 CLI 查询。

- **API**：`POST /api/llm/cli-models/refresh` `{cli_type, cli_cmd}`
- **实现**：`fetch_cli_models`
  - Cursor → `agent --list-models`
  - CodeBuddy / Claude 等 → 解析 `--help` 中 `Currently supported: (...)`（CodeBuddy 可能较慢）
- **缓存**：`_CLI_MODEL_RUNTIME` 覆盖进程内列表；`/api/llm/status` 走 `get_cli_model_options()`
- **UI**：模型标签旁「↻ 刷新」，提示查询状态与结果条数

---

## 关键文件

```
backend/llm_client.py          ← cursor adapter、直调 node、prompt 临时文件、thinking/累计帧、
                                  fetch_cli_models / get_cli_model_options
backend/main.py                ← /api/llm/cli-models/refresh；status 用运行时模型列表
backend/api/chat.py            ← _snapshot_llm_meta + 保存 api_format/cli_type/llm_model
backend/api/commands.py        ← 模型列表改 get_cli_model_options()
backend/database.py            ← chat_messages 三列 migration
backend/config.py / .env.example / README.md
frontend/index.html            ← Cursor 选项、刷新按钮、app.js cache bust
frontend/app.js                ← cursor 图标、头像按消息快照、refreshCliModels
```

---

## 验证建议

1. 重启后端；LLM 选 CLI → Cursor Agent → 模型 `auto`，发「你好」应有真实问候（数秒级），非「操作已完成」
2. 日志应出现 `Cursor Agent 直调: …\node.exe …\index.js`，不应再有「命令行太长」
3. 新 assistant 消息刷新后头像/模型名保持发送时配置；换 CLI 后旧无快照消息仍可能跟全局
4. AI 配置点「↻ 刷新」：Cursor 应很快拉全量；CodeBuddy 需等待 help 解析
