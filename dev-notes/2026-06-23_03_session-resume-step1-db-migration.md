# Session Resume · Step 1 — DB 扩展 chat_sessions 表

**系列**：session-resume  
**日期**：2026-06-23  
**状态**：完成

## 改动

`backend/database.py` — `_auto_migrate()` 的 migrations 列表末尾追加三个字段：

```python
("chat_sessions", "last_status",    "TEXT NOT NULL DEFAULT 'active'"),
("chat_sessions", "last_active_at", "TEXT"),
("chat_sessions", "message_count",  "INTEGER NOT NULL DEFAULT 0"),
```

## 字段说明

| 字段 | 类型 | 用途 |
|---|---|---|
| `last_status` | `TEXT DEFAULT 'active'` | 会话状态：`active` / `completed` / `poisoned` |
| `last_active_at` | `TEXT` | 最后一次 completed/poisoned 的 ISO 时间戳 |
| `message_count` | `INTEGER DEFAULT 0` | 消息总条数，每次 _save_chat_message 时 +1 |

## poisoned 含义

`last_status = 'poisoned'` 时，`_load_session_history()` 返回空列表，避免异常中断后的不完整对话污染下一轮 LLM 上下文。

## 注意

迁移通过 `PRAGMA table_info` 检测列是否存在，重复启动不会报错。旧数据库字段缺失时自动补齐，`last_status` 默认 `'active'`。
