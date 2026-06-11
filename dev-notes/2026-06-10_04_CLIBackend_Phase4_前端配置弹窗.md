# CLIBackend — Phase 4：前端 LLM 配置弹窗

> 日期：2026-06-10  
> 系列：CLIBackend（CLI 基座支持）  
> 参考计划：`docs/20260610_01_CLI基座支持开发计划.md` § Phase 4

---

## 改动文件

- `frontend/index.html`
- `frontend/app.js`

---

## index.html 改动

### 弹窗说明文字

原：「配置 OpenAI 兼容的 LLM API …」  
改：「配置 LLM 接入方式 …」（不再暗示只有 API 模式）

### 新增"接入方式"下拉

```html
<select id="llmApiFormat" onchange="onLLMFormatChange(this.value)">
    <option value="anthropic">API 模式（Anthropic）</option>
    <option value="openai">API 模式（OpenAI 兼容）</option>
    <option value="cli">CLI 模式（本地命令行工具）</option>
</select>
```

### 原有 API 字段用 `<div id="llmApiFields">` 包裹

切换到 CLI 模式时整体 `display:none`，切回 API 模式时恢复。

### 新增 `<div id="llmCliFields">` 默认隐藏

包含：
- CLI 工具类型下拉（claude / codebuddy / custom）
- CLI 可执行路径 input（`id="llmCliCmd"`）
- CLI 超时 number input（`id="llmCliTimeout"`）
- 警示条：Tool Use 降级 + Token 统计不可用

---

## app.js 改动

### 新增 `onLLMFormatChange(format)`

```javascript
function onLLMFormatChange(format) {
    apiFields.style.display = format === 'cli' ? 'none' : 'block';
    cliFields.style.display = format === 'cli' ? 'block' : 'none';
}
```

供 `<select onchange>` 和 `showLLMConfigModal` 回填时调用，保持显隐逻辑统一。

### `showLLMConfigModal` 扩展

从 `/api/llm/status` 读取 `api_format` / `cli_type` / `cli_cmd` / `cli_timeout` 并回填到对应控件，同时调用 `onLLMFormatChange` 触发字段显隐。

### `saveLLMConfig` 扩展

```javascript
const payload = { api_format: format, model, timeout, max_retries, ... };
if (format === 'cli') {
    payload.cli_type    = ...;
    payload.cli_cmd     = ...;
    payload.cli_timeout = ...;
}
```

CLI 专属字段仅在 `format === 'cli'` 时附加，避免无关键污染 API 模式的配置。

---

## 验证

```python
# 直接验证 config 层 CLI 字段加载
os.environ['LLM_API_FORMAT'] = 'cli'
os.environ['LLM_CLI_CMD']    = 'claude'
s = Settings()
assert s.LLM_API_FORMAT == 'cli'
assert s.LLM_CLI_CMD    == 'claude'
assert s.LLM_CLI_TIMEOUT == 120
# → 通过
```

服务热重载后 `/api/llm/status` 将新增返回 `api_format`、`cli_type` 等字段。
