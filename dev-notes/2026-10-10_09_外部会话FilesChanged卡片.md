# 外部会话「N Files Changed」卡片：读取 + 渲染

2026-10-10

## 起因

用户对照 Cursor 原生 UI：每轮回复下面有「7 Files Changed」卡片（文件名 + 每文件 +/- 行数 +
新建标记），问我们能不能读到、渲染出来。

## 数据探测（三轮只读探针，直连 state.vscdb）

1. bubble 顶层的 `diffHistories` / `diffsSinceLastApply` / `gitDiffs` 等字段**全是空数组**，此路不通。
2. `toolFormerData`（edit_file_v2）：有 `params.relativeWorkspacePath`（文件路径）和
   `result` = `{beforeContentId, afterContentId}` —— 内容按 sha256 寻址。
3. `cursorDiskKV` 里实测有 12927 条 `composer.content.*` 键，**值就是文件全文**
   （`sha256(值) == 键后缀` 验证通过；空文件键是著名的 e3b0c44... 空 hash）。

结论：文件名 + 前后全文都有，行数自己 diff。

## 实现

**后端** `backend/external_sessions/cursor.py`：

- `_fetch_content_blob`：按 contentId 拉 `composer.content.*` 原文（bytes → utf-8 decode）。
- `_diff_line_counts`：`difflib.unified_diff(n=0)` 数 +/- 行。
- `_attach_files_changed(blob_fetch, messages)`：在 `get_session` 里消息组装完后跑——
  按「两次 user 消息之间」分轮，收集 `edit_file_v2*` 且 status=completed 的调用；
  **同一文件一轮内多次编辑要链式合并**（第一次的 before + 最后一次的 after，净 diff），
  否则中间态重复计算；轮尾插入合成消息 `kind=files_changed`，
  `tool_calls[0].data.files = [{path, file, added, removed, is_new}]`。
- `base.py` 的 `Kind` Literal 加 `"files_changed"`。

**前端** `frontend/app.js` + `styles.css`：

- `_esRenderMessages` 加 `files_changed` 分支（在 thinking/tool_call 分组之前）。
- `_esRenderFilesChanged`：卡片头「N Files Changed · Review」，行 = 徽标（新建蓝色 C /
  其他扩展名缩写）+ 文件名（title 悬浮全路径）+ 右对齐 +绿 -红。
- `.es-files-changed` 系列样式（bordered 卡，与 Cursor 原生观感对齐）。

## 实测

对真实会话（PSD Editor display，2175 消息 / 199 次编辑）跑通：29 轮卡片，新建文件
（SAnimSequenceNotifyTimeline.h +45 -0）正确标记，链式合并正确。

## 追加：文件名点击跳转仓库（2026-10-10 下午）

卡片每行（`.es-fc-row`）加 `onclick="openRepoFileFromChat(path)"`，hover 高亮 + 文件名变主色。
`openRepoFileFromChat → _normalizeChatFilePath` 已支持绝对路径：命中
`currentProject.local_repo_path` 就裁成仓库相对路径，否则按 `/Source/`、`/Plugins/` 等标记裁。
Windows 路径不含单引号，onclick 里 `escHtml(path).replace(/'/g,'&#39;')` 兜底转义。
无行号范围，打开即显示文件顶部（不带行高亮）。

## 追加 2：点击跳转后路径斜杠全丢（2026-10-10 傍晚）

用户截图：点卡片行后文件 Tab 路径变成 `I:A_WorksOG2P4UE5...`（所有 `\` 消失）。根因：
`onclick` 是内联 JS 字符串，`\A`/`\W`/`\O` 不是合法转义序列，JS 解析时反斜杠被吞
（之前只转义了引号，没管 `\`）。修复：`.replace(/\\/g,'\\\\')` 双写 + 单引号改用 `\'`
（原来的 `&#39;` 实体转义会被 HTML 属性解码穿透成 `'`，对 JS 字符串根本挡不住——
`_chatFileAnchor` 早就是正确写法 `\\` + `\'`，这次对齐）。`buildCodeRefCard` 同款隐患一并修。

验证：node 模拟「HTML 属性 → JS 字符串」解析链路，roundtrip 后路径与原值完全一致。

## 验证边界

- `node --check` + `py_compile` 过；真实 DB 实测通过。**后端服务要重启才生效**（cursor.py
  改动），前端刷新页面即可。
- 卡片的文件名暂不可点击跳转（路径是 workspace 绝对路径，`openRepoFileFromChat` 吃的是
  仓库相对路径，要先把 workspace 根归一化掉，后续可加）。
- Review 角标是纯展示（没有 Cursor 的 review 面板可开）。
- before blob 缺失（理论不该发生）时按空串处理，会把该文件误标为新建——极端边界，可接受。
- 行数是「净变化」（链式合并后），和 Cursor 原生卡片可能因 Cursor 统计口径（逐次 vs 净）
  有细微出入，实测方向一致。
