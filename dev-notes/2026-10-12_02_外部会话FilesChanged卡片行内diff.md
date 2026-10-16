# 外部会话 Files Changed 卡片行内 diff（Cursor Review 风格）

2026-10-12

## 起因

Files Changed 卡片之前只显示「文件名 + 行数」，点行跳转仓库文件。用户对着 Cursor
原生 Review 视图，要求能直接看到每个文件**改了什么**（行号 + 绿增红删 + 未改动折叠）。

## 数据来源

Cursor 的 `composer.content.*` 存了每个文件编辑前后的**全文**（上一轮 `_attach_files_changed`
已经拿它算 +/- 行数，但算完就丢了）。这次在同一个地方顺手把 unified diff 也生成了。

## 实现

**后端 `backend/external_sessions/cursor.py`**（`_attach_files_changed.flush`）
- 每个文件条目新增 `diff`：`difflib.unified_diff(before, after, n=3)` 文本（超 16KB
  截断），外加 `after_lines`（用于倒推文件末尾未改动行数）。

**前端 `frontend/app.js`**
- `_esRenderFileDiff`：解析 unified diff → Cursor Review 风格：
  - 行号列：删除行显旧行号（红）、新增行显新行号（绿）、上下文行显新行号。
  - 行内容按扩展名走 hljs 语法高亮（20+ 语言）。
  - `@@` 头只用于行号定位；hunk 间/前后的未改动区间渲染成 "N unmodified lines" 折叠条。
- `_esRenderFilesChanged`：文件行点击展开/收起行内 diff（▸/▾），跳转仓库改成行尾 ↗ 图标
  （`event.stopPropagation()` 与展开不冲突）。

**前端 `styles.css`**
- `.es-fc-diff` / `.es-diff-row(.add/.del)` / `.es-diff-gap` 等样式，diff 区最高 460px 内滚动。

## 坑 / 边界

- 折叠条是**静态的**：n=3 的 diff 里没带未改动行内容，条不可展开（要可展开得后端带全量
  上下文，token 不划算）。
- 语法高亮按行做，跨行块注释的高亮会断。
- diff 截断 16KB/文件，超大 diff 显示「（diff 过长已截断）」。
- `get_session` 现在每个文件都带 diff 文本，大会话（上百次编辑）响应会变大，本地工具可接受。

## 验证

- `node --check` + `py_compile` 通过。
- 后端要重启（cursor.py 改动）；前端刷新页面。文件行首出现 ▸ 即代表 diff 字段已生效。
