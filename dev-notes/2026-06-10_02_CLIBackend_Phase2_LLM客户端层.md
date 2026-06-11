# CLIBackend — Phase 2：LLM 客户端层

> 日期：2026-06-10  
> 系列：CLIBackend（CLI 基座支持）  
> 参考计划：`docs/20260610_01_CLI基座支持开发计划.md` § Phase 2

---

## 改动文件

`backend/llm_client.py`

---

## 新增内容

### 1. `_CLI_ADAPTERS` 适配表（模块级常量）

注册三种 CLI 工具的参数构造方式，放在 `LLMClient` 类定义之前：

```python
_CLI_ADAPTERS = {
    "claude":    { "build_cmd": lambda cli, model, prompt: [cli, "--print", "--model", model, "-p", prompt], "stdin": False },
    "codebuddy": { "build_cmd": lambda cli, model, prompt: [cli, "ask", "--model", model, prompt], "stdin": False },
    "custom":    { "build_cmd": lambda cli, model, prompt: [cli], "stdin": True },
}
```

- `claude` / `codebuddy`：prompt 作为命令行参数传入，`model` 为空时自动省略 `--model` 参数
- `custom`：prompt 通过 stdin 传入，便于接入任意接受 stdin 输入的 LLM 工具

### 2. `LLMClient.__init__` 新增 CLI 属性

```python
self.cli_type    = settings.LLM_CLI_TYPE
self.cli_cmd     = settings.LLM_CLI_CMD
self.cli_model   = settings.LLM_CLI_MODEL or settings.LLM_MODEL
self.cli_timeout = settings.LLM_CLI_TIMEOUT
```

`cli_model` 优先用 `LLM_CLI_MODEL`，为空则复用顶层 `LLM_MODEL`，不强制重复配置。

### 3. `is_configured` 属性扩展

CLI 模式只校验 `cli_cmd` 非空，不要求 `base_url` 和 `api_key`。

### 4. `_messages_to_prompt()`

将 `List[Dict]` 格式的 messages 拼成带 `[System]` / `[User]` / `[Assistant]` 标签的纯文本，
供 CLI 子进程调用时使用。`content` 为 list（vision block）时自动提取文本部分。

### 5. `_call_cli()`

核心子进程调用逻辑：
- `asyncio.create_subprocess_exec` 启动 CLI 进程
- `asyncio.wait_for(..., timeout=cli_timeout)` 超时保护，超时后 `proc.kill()`
- 覆盖三类异常：超时 / 非零退出码 / `FileNotFoundError`（工具不存在）
- 返回 `(response_text, {"input_tokens": None, "output_tokens": None})`，CLI 无精确统计

### 6. `chat()` 分发逻辑

原来：
```python
if self.api_format == "anthropic": ...
else: ...   # 兜底走 openai
```

改为：
```python
if self.api_format == "anthropic": ...
elif self.api_format == "cli": ...   # ← 新增
else: ...   # openai
```

### 7. `chat_with_tools` / `chat_with_tools_stream` CLI 降级

两个方法在 `is_configured` 检查之后立即插入 CLI 模式判断：
- `chat_with_tools`：降级为 `await self.chat()`，返回 `{"cli_fallback": True, ...}`
- `chat_with_tools_stream`：降级后整体 `yield text_delta + message_done`，前端无感知

### 8. `test_connection()` CLI 分支

CLI 模式下跳过 HTTP 请求，改为：
1. `shutil.which(cli_cmd)` 检查工具是否在 PATH
2. 执行 `cli_cmd --version` 获取版本字符串
3. 超时 10s，失败返回 `{"status": "error"}`

---

## 关键设计决策

| 决策 | 理由 |
|------|------|
| `_CLI_ADAPTERS` 用 lambda 而非子类 | 差异只在参数构造，无需引入类层次 |
| `stdin=True` 仅 custom 使用 | claude/codebuddy 有明确的 `-p` / positional 参数，stdin 反而可能不被支持 |
| tool_use 降级而非报错 | 现有文本协议 `[ACTION:xxx]` 已有解析路径，Agent 可继续工作 |
| token 统计返回 None | `_calc_cost_usd(model, 0, 0)` 返回 0.0，数据库字段允许 null，前端 `?` 已兜底 |
