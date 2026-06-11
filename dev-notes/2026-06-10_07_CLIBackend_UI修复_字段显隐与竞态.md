# CLIBackend — UI 修复：字段显隐 + cmd 填充竞态

> 日期：2026-06-10  
> 系列：CLIBackend（CLI 基座支持）

---

## 问题 1：API 专属字段在 CLI 模式下仍显示

**现象**：切换到 CLI 模式后，"模型名称 / 超时时间 / 最大重试次数"三个字段仍然可见。

**原因**：这三个字段在 `index.html` 里位于 `llmCliFields` div 之外，`onLLMFormatChange` 只控制了 `llmApiFields` 和 `llmCliFields` 的显隐，没有覆盖到这三个字段。

**修复**：用 `<div id="llmApiOnlyFields">` 包住这三个字段，在 `onLLMFormatChange` 里同步控制：

```javascript
if (apiOnlyFields) apiOnlyFields.style.display = isCli ? 'none' : 'block';
```

---

## 问题 2：CLI 可执行路径显示 "custom" 而非 "codebuddy"

**现象**：切换 CLI 工具类型到 codebuddy 后，CLI 路径框自动填成了 "custom"。

**根本原因：竞态条件**

弹窗打开时，`showLLMConfigModal` 发起异步请求 `/api/llm/status` 获取 `_cliDefaultCmds`。在请求返回之前，用户已经切换了 CLI 类型下拉，触发 `onCLITypeChange`。此时 `_cliDefaultCmds` 还是空 `{}`：

```
_cliDefaultCmds['codebuddy']  → undefined → fallback '' (空字符串)
_fillCliModelSelect('codebuddy', '') → models 为空 → 走 custom 分支
→ selectEl.style.display = 'none'; customEl.style.display = 'block'
→ cmd 框不更新（空字符串 falsy 跳过赋值）
→ cmd 框保持上一个工具的默认值，UI 显示 custom 输入框
```

**修复**：

1. 弹窗打开时立即 `disabled = true` 禁用 CLI 类型下拉，防止数据未到时操作
2. `finally` 块里恢复 `disabled = false`
3. `onCLITypeChange` 的 cmd 填充改用 `Set` 判断已知默认值，逻辑更清晰

```javascript
const cliTypeEl = document.getElementById('llmCliType');
if (cliTypeEl) cliTypeEl.disabled = true;
try {
    const data = await api('/llm/status');
    _cliModelOptions = data.cli_model_options || {};
    _cliDefaultCmds  = data.cli_default_cmds  || {};
    // ... 回填字段
} finally {
    if (cliTypeEl) cliTypeEl.disabled = false;
}
```

---

## 改动文件

- `frontend/index.html`：新增 `<div id="llmApiOnlyFields">` 包裹
- `frontend/app.js`：`onLLMFormatChange` + `onCLITypeChange` + `showLLMConfigModal`
