# CLIBackend — Phase 5：多工具 + 模型列表联动

> 日期：2026-06-10  
> 系列：CLIBackend（CLI 基座支持）  
> 参考计划：`docs/20260610_01_CLI基座支持开发计划.md`（补充需求）

---

## 背景

Phase 1-4 完成基础 CLI 支持后，需要扩展到四种具体工具，并为每种工具提供独立的模型列表下拉选择。

---

## 改动文件

- `backend/llm_client.py`
- `backend/main.py`
- `frontend/index.html`
- `frontend/app.js`

---

## llm_client.py

### 新增 `CLI_MODEL_OPTIONS`（模块级常量）

```python
CLI_MODEL_OPTIONS = {
    "claude":          ["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5", ...],
    "claude-internal": ["claude-sonnet-4-5", "claude-haiku-4-5", ...],   # 腾讯内网 Claude
    "gemini-internal": ["gemini-2.5-pro", "gemini-2.5-flash", ...],      # 腾讯内网 Gemini
    "codebuddy":       ["skylark2-pro-4k", "skylark2-lite-4k", "deepseek-v3", "deepseek-r1"],
    "custom":          [],
}
```

模型列表仅供前端下拉展示，后端调用时直接透传 `cli_model`，无校验约束。

### `_CLI_ADAPTERS` 新增两个工具

| 工具 | `cli_type` | 默认命令 | 参数格式 |
|------|-----------|---------|---------|
| Claude 内网 | `claude-internal` | `claude` | 与 `claude` 完全相同，靠模型名区分 |
| Gemini 内网 | `gemini-internal` | `gemini` | `gemini --model <m> -p "<prompt>"` |

每个适配器新增 `"default_cmd"` 字段，供前端自动填充默认可执行文件名。

---

## main.py — `/api/llm/status` 新增两个字段

```json
{
  "cli_model_options": { "claude": [...], "codebuddy": [...], ... },
  "cli_default_cmds":  { "claude": "claude", "gemini-internal": "gemini", ... }
}
```

始终返回（不限于 CLI 模式），前端打开弹窗时一次性拿到所有元数据。

---

## index.html — CLI 字段重构

### 工具类型下拉新增选项

```html
<option value="claude-internal">Claude 内网版</option>
<option value="gemini-internal">Gemini 内网版</option>
```

### 模型字段：`<input text>` → `<select>` + 隐藏 `<input>`

- 有预设模型的工具（claude / claude-internal / gemini-internal / codebuddy）：显示 `<select id="llmCliModelSelect">`
- `custom` 或无预设：隐藏 select，显示 `<input id="llmCliModelCustom">`（手动填写）

---

## app.js — 联动逻辑

### 模块级缓存

```javascript
let _cliModelOptions = {};   // 从 /api/llm/status 加载后缓存
let _cliDefaultCmds  = {};
```

### `onCLITypeChange(cliType)`

工具类型下拉 `onchange` 回调：
1. 调用 `_fillCliModelSelect(cliType, '')` 重建模型下拉
2. 若命令路径字段为空或仍是某工具的默认值，自动回填新工具的默认命令名

### `_fillCliModelSelect(cliType, currentModel)`

- 有预设模型：构建 `<option>` 列表，`currentModel` 不在列表时插入"（当前）"项
- 无预设（custom）：切换为 input 手动输入

### `_getCliModelValue()`

读取当前模型值——自动判断当前是 select 模式还是 input 模式：

```javascript
function _getCliModelValue() {
    const customEl = document.getElementById('llmCliModelCustom');
    if (customEl && customEl.style.display !== 'none') return customEl.value.trim();
    return document.getElementById('llmCliModelSelect')?.value || '';
}
```

### `saveLLMConfig` 新增 `cli_model`

```javascript
payload.cli_model = _getCliModelValue();
```

---

## 验证输出

```
CLI 工具类型: ['claude', 'claude-internal', 'gemini-internal', 'codebuddy', 'custom']

claude:          ['claude-opus-4-5', 'claude-sonnet-4-5', 'claude-haiku-4-5', ...]
claude-internal: ['claude-sonnet-4-5', 'claude-haiku-4-5', ...]
gemini-internal: ['gemini-2.5-pro', 'gemini-2.5-flash', ...]
codebuddy:       ['skylark2-pro-4k', 'skylark2-lite-4k', 'deepseek-v3', 'deepseek-r1']
custom:          []

claude cmd:          ['mycli', '--print', '--model', 'mymodel', '-p', 'hello']
claude-internal cmd: ['mycli', '--print', '--model', 'mymodel', '-p', 'hello']
gemini-internal cmd: ['mycli', '--model', 'mymodel', '-p', 'hello']
codebuddy cmd:       ['mycli', 'ask', '--model', 'mymodel', 'hello']
custom cmd:          ['mycli']
```
