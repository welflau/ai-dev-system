# CLIBackend — Phase 6：多工具流式输出 + 斜杠命令补全

> 日期：2026-06-11
> 系列：CLIBackend（CLI 基座支持）
> 参考计划：`docs/20260610_01_CLI基座支持开发计划.md`（后续迭代）

---

## 一、AI 配置弹窗重构为侧栏 Tab 页

**改动文件**：`frontend/index.html`、`frontend/app.js`、`frontend/styles.css`

弹窗从单页平铺改为三 Tab 侧栏布局：
- 🤖 **LLM** — 接入方式（API/CLI）+ 模型 + 超时
- 🖼️ **图片生成** — LightAI 配置 + 测试
- 🔍 **资产搜索** — Pexels Key + 免费来源说明

新增 `.ai-cfg-tab` / `.ai-cfg-tab.active` CSS 类，`switchAICfgTab(tab)` 函数控制切换。

---

## 二、CLI 工具类型选择与模型列表联动修复

**改动文件**：`frontend/index.html`、`frontend/app.js`

- 弹窗加载期间禁用工具类型下拉（避免数据未就绪时的竞态导致 cmd 填成 `custom`）
- `onCLITypeChange` 改用 `Set` 过滤已知默认命令，切换时只在安全条件下覆盖路径字段
- API 专属字段（模型名/超时/重试）用 `id="llmApiOnlyFields"` 包裹，CLI 模式下整体隐藏

---

## 三、codebuddy 流式输出接入

**改动文件**：`backend/llm_client.py`、`backend/query_engine/engine.py`

### 3.1 stream-json 格式适配

codebuddy/claude 支持 `--output-format stream-json --include-partial-messages`，每行输出一个 JSON：
```json
{"type":"stream_event","event":{"type":"content_block_delta",
  "delta":{"type":"text_delta","text":"..."}}}
{"type":"stream_event","event":{"type":"content_block_delta",
  "delta":{"type":"thinking_delta","thinking":"..."}}}
```

所有流式工具适配表更新为加 `--include-partial-messages` 参数。

### 3.2 asyncio.Queue 桥接方案

`asyncio.wait_for` 不支持 async generator，改用 Queue 桥接：
- `_reader()` task 逐行解析 stdout，把 `(type, chunk)` 元组放入 queue
- 主循环 `await queue.get()` 取出后 yield，None 作为结束哨兵
- 超时控制在外层 while 循环，每次 get 最多等 5s，检查进程是否存活

### 3.3 thinking_delta 推送到前端思考面板

QueryEngine CLI 分支新增：
- `thinking_delta` → `yield ThinkingDeltaEvent(delta=chunk)`（前端逐字显示推理）
- `thinking_done` → `yield ThinkingDoneEvent(text="")`（折叠思考面板）
- 流式结束后调 `_save_conversation` 推送日志到全局 Log 面板

### 3.4 CODEBUDDY_API_KEY_DISABLED 处理

系统环境变量 `CODEBUDDY_API_KEY` 失效会导致 401。对 codebuddy/claude/claude-internal 子进程注入 `CODEBUDDY_API_KEY_DISABLED=1`，让其走本地登录态。

---

## 四、斜杠命令补全（/help /model /clear /status /tasks /agents）

**改动文件**：`backend/api/commands.py`、`frontend/app.js`

### 新增命令

| 命令 | 实现 |
|------|------|
| `/help` | 静态命令表，分类展示所有可用命令 |
| `/model [名称]` | 无参数查看当前+可用列表；有参数切换并写入 `.env` |
| `/clear` | SSE 事件 `clear_history`，前端清空 `chatHistory` + DOM |
| `/status` | 显示 LLM 接入方式/endpoint/模型/系统信息 |
| `/tasks` | 查询 `tickets` 表，展示执行中工单 + Agent 状态 |
| `/agents` | 展示所有注册 Agent 的状态、完成数、异常数 |

### 修复 /skills import 路径

`from skills.loader import skill_loader` → `from skills import skill_loader`（单例在 `__init__.py`）

### 斜杠命令结果持久化

`_handleSlashCommand` 执行完毕后调 `_saveGlobalChatToStorage()`，命令结果写入 localStorage，刷新后从 DOM 中恢复，不再消失。

---

## 五、全局日志面板（Log 面板）接入

**改动文件**：`backend/llm_client.py`

`_save_conversation` 原来只在 `project_id` 非空时推送事件，全局 AI 助手（无项目上下文）的调用日志一直是空的。修复：

```python
if _llm_ctx.project_id:
    # 写 DB + 推 project:{id} 频道（原有）
else:
    # 推 global 频道（新增）
    await event_manager.publish("global", "log_added", log_payload)
```

日志格式升级：CLI 模式显示 `deepseek-v4-pro-ioa via codebuddy`（正确模型名）而非 API 模型名。

---

## 六、uvicorn reload 启动问题根因与修复

**改动文件**：`backend/main.py`

**问题**：`uvicorn.run("main:app", reload=True)` 在 Windows + Git Bash 下，reload worker 子进程的 `sys.path` 不含 `backend/`，导致加载到错误的 `main` 模块，代码改动不生效。

**修复**：改为 `uvicorn.run(app, reload=False)`，直接传 app 对象，永远禁用 reload。代码更新后手动 Ctrl+C 重启。

详见 `dev-notes/2026-06-10_06_CLIBackend_启动问题修复_uvicorn_reload路径污染.md`
