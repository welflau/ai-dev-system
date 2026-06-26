# Session Resume · Step 4+5 — Session 状态跟踪与前端解耦

**系列**：session-resume  
**日期**：2026-06-23  
**状态**：完成

## Step 4：Session 状态更新

### 4.1 message_count 自增

**文件**：`backend/api/chat.py`，`_save_chat_message()`

将原来的：
```python
await db.update("chat_sessions", {"updated_at": now_iso()}, "id = ?", (eff_session,))
```
改为：
```python
await db.execute(
    "UPDATE chat_sessions SET updated_at=?, message_count=message_count+1 WHERE id=?",
    (now_iso(), eff_session),
)
```

### 4.2 completed 标记

流式端点收到 `message_done` 事件、消息保存成功后：
```python
await db.execute(
    "UPDATE chat_sessions SET last_status='completed', last_active_at=? WHERE id=?",
    (now_iso(), _sid),
)
```
适用范围：项目内聊天流式端点 + 全局聊天流式端点，各改一处。

### 4.3 poisoned 标记

流式端点 `except Exception` 块里：
```python
await db.execute(
    "UPDATE chat_sessions SET last_status='poisoned', last_active_at=? WHERE id=?",
    (now_iso(), _sid),
)
```
标记后，下次该 session 调 `_load_session_history()` 会返回空列表，不带入坏上下文。

若用户在 poisoned session 上继续发消息，新消息存入同一 session，session 状态会被下一次 completed 重置（新消息保存后标记为 completed）。

## Step 5：前端移除 history 传参

**文件**：`frontend/app.js`

**项目内聊天**（有 `chat_session_id`）：删掉 `history: historyToSend`：
```js
resp = await _sendChatStreaming(
    `/projects/${currentProjectId}/chat/stream`,
    { message: fullMessage,
      images: ...,
      chat_session_id: _sid }   // 无 history 字段
);
```

**全局聊天**（无 project_id）：保留 `history: historyToSend` 作兜底：
```js
resp = await _sendChatStreaming(
    `/chat/stream`,
    { message: fullMessage, history: historyToSend,
      images: ...,
      chat_session_id: _sid }   // 有 history 字段（服务端无 session 时用）
);
```

`chatHistory[]` 数组保留，仅用于前端气泡渲染，不再承担"传给 LLM"的职责。

## 验收要点

| 场景 | 结果 |
|---|---|
| 项目内对话后刷新页面 | AI 回忆上轮内容 ✓ |
| 切换项目再切回 | 上下文自动恢复 ✓ |
| API 异常中断 | session 标记 poisoned，下次从空历史开始 ✓ |
| 全局聊天（无项目）| 行为不变（history 兜底）✓ |
