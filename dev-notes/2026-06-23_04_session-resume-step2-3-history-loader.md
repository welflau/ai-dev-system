# Session Resume · Step 2+3 — 服务端 history 加载与端点改造

**系列**：session-resume  
**日期**：2026-06-23  
**状态**：完成

## 背景

原来 history 完全由前端 `chatHistory[]` 内存数组维护，刷新/切换项目即丢失。改造后服务端从 DB 主动加载，实现真正的上下文持久化。

## Step 2：新增 `_load_session_history()`

**文件**：`backend/api/chat.py`（插入在 `_update_session_title_if_needed` 之后）

```python
async def _load_session_history(session_id, project_id, limit=30) -> list:
```

**逻辑**：
1. 查 `chat_sessions.last_status`，若为 `poisoned` 直接返回 `[]`
2. 查 `chat_messages` 按 `session_id + project_id`，正序取最近 30 条（role = user/assistant）
3. 每条 content 超过 8000 字时截断，防止历史占用过多 token

## Step 3：改造两处 history_list 赋值

### 非流式端点 `_chat_via_agent`（约 419 行）

```python
# 改造前
history_list = [{"role": m.role, "content": m.content} for m in (req.history or [])]

# 改造后
if req.chat_session_id:
    history_list = await _load_session_history(req.chat_session_id, project_id)
else:
    history_list = [{"role": m.role, "content": m.content} for m in (req.history or [])]
```

### 流式端点 `_chat_stream_generator`（约 508 行）

同上逻辑，`_sid` 赋值移到 history 加载之前，确保 session_id 一致。

## 兼容策略

- 有 `chat_session_id` → **从 DB 读**（新路径，刷新/重开浏览器可恢复）
- 无 `chat_session_id` 但有 `req.history` → **用前端传的**（全局聊天兜底）
- 两者都无 → 空历史（全新对话）

## 数据时序

```
前端发消息
  → 服务端 _load_session_history()  ← DB（不含本轮 user 消息，时序正确）
  → 追加 user_message
  → 调 LLM
  → 收到 assistant reply
  → _save_chat_message() 写入 DB
```

本轮 user 消息**先调 LLM、后写 DB**，所以 `_load_session_history` 不会读到"未完成的本轮"，不存在重复历史。
