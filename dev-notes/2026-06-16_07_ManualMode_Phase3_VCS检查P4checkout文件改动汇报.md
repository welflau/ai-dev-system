# ManualMode Phase3 — 手动挡对话执行：VCS检查 + P4 checkout + 文件改动汇报

> 日期：2026-06-16
> 系列：ManualMode
> 关联文档：`docs/20260616_02_手动挡模式与多路径项目设计方案.md`
> 前置：`dev-notes/2026-06-16_06_ManualMode_Phase2_...`

---

## 背景

Phase 1/2 完成了手动挡基础设施和快速打开目录。
Phase 3 让手动挡项目在对话中直接改文件时：
1. 写 P4 文件前自动 `p4 edit` checkout
2. 会话结束后汇报改动了哪些文件

---

## 改动文件

### `backend/agents/chat_assistant.py`

#### 新增模块级辅助函数

**`_session_file_changes`**：`dict[project_id, [file_path]]`  
内存记录本次对话写过的文件，会话结束后汇报并清空。

**`_ensure_writable_for_mcp(tool_name, tool_input, project_id)`**  
MCP 写文件工具（`write_file`/`edit_file`/`create_file`）执行前调用：
- 只在手动挡项目（`mode=manual`）下生效
- 提取文件路径，调用 `vcs_detector.ensure_writable()`
- P4 路径：自动执行 `p4 edit`，日志打印 `🔓 P4 checkout`
- 只读路径：打印警告（Phase 5 再做用户确认交互）

**`_record_file_change(tool_name, tool_input, project_id)`**  
MCP 写文件工具执行后调用，记录文件路径到 `_session_file_changes`。

#### `_ChatToolExecutor.execute()` 修改

MCP 工具调用前后各加一步：
```python
# 执行前
await _ensure_writable_for_mcp(tool_name, tool_input, self.project_id)
# 执行后
_record_file_change(tool_name, tool_input, self.project_id)
```

#### `MessageDoneEvent` 处理增加汇报

`chat_stream` 和 `chat_global_stream` 两处，会话完成后：
```python
changes = _session_file_changes.pop(project_id, [])
if changes and project.get("mode") == "manual":
    yield {"type": "text_delta", "delta": "📝 本次共修改 N 个文件：\n- file1\n- file2\n\n请自行决定提交时机..."}
```

#### `_build_manual_mode_section(project)` 新增

模块级函数，手动挡项目在 system prompt 里注入路径信息：
- 列出所有路径（git 🟢 / P4 🟡 / none ⚪）及只读标注
- 说明写文件规则（git 直接写/P4 自动 checkout/只读需确认）
- 结束时提示用户自行提交

### `backend/actions/chat/generate_document.py`

`generate_document` action 写文件前加 VCS 检查：
- 手动挡项目跳过 commit/push，只写文件
- 写前调用 `ensure_writable()`，P4 文件自动 checkout
- 只读路径返回错误提示

---

## 效果

手动挡项目对话中，AI 修改文件后：

```
📝 本次共修改 3 个文件：
  - `F:/MyGame/Source/LoginModule.cpp`
  - `F:/MyGame/Source/LoginModule.h`
  - `F:/MyGame/Content/UI/LoginWidget.uasset`

请自行决定提交时机（git commit / p4 submit）。
```

P4 管理的文件在写入前，后端日志可见：
```
🔓 P4 checkout: F:/MyGame/Content/UI/LoginWidget.uasset → //depot/...#1 - opened for edit
```

---

## 验证

重启服务后：
1. 打开一个 mode=manual 的项目
2. 让 AI 修改一个文件
3. 会话结束后底部出现文件汇报
4. 如果是 P4 项目，后端日志出现 `🔓 P4 checkout`
