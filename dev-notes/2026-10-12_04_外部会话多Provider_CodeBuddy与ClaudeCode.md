# 外部会话多 Provider：CodeBuddy 与 Claude Code

2026-10-12

## 起因

「外部会话」之前只支持 Cursor。用户想让 ADS 也能读 CodeBuddy、Claude Code 在本项目
的对话数据（评估后决定先做这两个，WorkBuddy 因消息在 Electron IndexedDB 且本项目
0 条会话暂缓）。

## 存储探测结论

| 工具 | 位置 | 格式 | 标题来源 | 本项目数据 |
|---|---|---|---|---|
| CodeBuddy | `~/.codebuddy/projects/<slug>/<sessionId>.jsonl` | JSONL 事件 | `ai-title` 事件 | 35 会话（最全） |
| Claude Code | `~/.claude/projects/<slug>/<sessionId>.jsonl` | JSONL 事件 | `history.jsonl`（sessionId→display） | 0 条（转写被 cleanup 清掉） |

- 两者都是**每会话一个 JSONL 文件**（无锁），比 Cursor 的 sqlite 只读锁那套简单得多。
- slug 都是「盘符 + 路径把 `:`/`\` 换成 `-`」；但**不用反解 slug**——每条事件都带 `cwd`
  字段（项目绝对路径），直接按 `cwd` 匹配候选根（复用 `_norm`/`_path_matches_any`）。

## 事件格式差异（关键）

- **CodeBuddy**：`type: message`（role=user/assistant，content blocks `input_text`/`output_text`）、
  `reasoning`（rawContent.reasoning_text）、`function_call`/`function_call_result`（工具）、
  `ai-title`（标题）、`summary`/`file-history-snapshot`（跳过）。timestamp 是**毫秒**。
- **Claude Code**：`type: user`/`assistant`（`message.content` 是 str 或
  `[{type:text/tool_use/thinking}]`）、`summary`/`attachment`/`queue-operation`/`last-prompt`
  （跳过）。timestamp 是 **ISO 字符串**（含 Z），不是毫秒。

## 实现

**后端**（`backend/external_sessions/`）
- `codebuddy.py`：`CodeBuddyProvider`，扫 `projects/*/*.jsonl`，`_scan_session` 按 `cwd`
  匹配 + 取 `ai-title`；`get_session` 解析 message/reasoning/function_call(±result)。
  标题回退到首条用户消息截 40 字。
- `claude.py`：`ClaudeProvider`，同骨架；标题走 `_load_titles`（读 `history.jsonl` 建
  sessionId→最早 display 映射）；`_to_iso` 兼容 ISO 字符串/毫秒两种 timestamp。
- `__init__.py`：`PROVIDERS` 注册 `codebuddy` / `claude`。

**前端**（`frontend/app.js` / `styles.css`）
- 外部会话面板顶栏加 **Cursor | CodeBuddy | Claude** 分段切换（`_esSwitchProvider`，
  按项目存 localStorage `esProvider:<pid>`）。
- 所有 `external-sessions/cursor/...` 硬编码改为 `_esState.provider`（列表/详情/导入/图片
  端点 + 图片 Tab 的 `tab.provider`）。
- 标题从「外部会话 · Cursor」改为「外部会话」。

## 复用点

- 三 provider 共用同一套 `SessionProvider` 接口 + 前端渲染/导入/diff/图片 Tab 逻辑。
- 导入接口 `POST /external-sessions/{provider}/{session_id}/import` 天然 provider 无关，
  CodeBuddy/Claude 的会话也能一键导入（`kind=text` 过滤，thinking/tool_call 自动跳过）。

## 坑 / 边界

- **CodeBuddy 图片暂不解析**：本项目会话里截图是「文件路径 + Read 工具」读入
  （blob 落 `~/.codebuddy/blobs`），非内联 image block，v1 跳过（导入时文字全量、图片缺省）。
- **Claude 本项目 0 条**：转写被 `.last-cleanup` 清掉（只留 memory/），provider 就绪但暂无可读。
- CodeBuddy 标题可能很长（`ai-title` 或首条用户消息是长 prompt），`_trim_title` 截 60 字。
- 会话匹配靠 `cwd` 前缀，子目录里的 CodeBuddy 会话也能命中项目根（和 Cursor 一致）。

## 验证

- CodeBuddy：`list_sessions` 命中 ai-dev-system 35 会话，`get_session` 解析 571 条消息
  （text/thinking/tool_call 分布正确）。
- Claude：用 ComicAI-backend 验证 4 会话，标题/消息解析正常。
- 三个 provider 均 `available=True`，后端重启 + 前端刷新生效。
