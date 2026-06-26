# Session Resume · Step 6-8 — CLI 模式 --resume 实现

**系列**：session-resume  
**日期**：2026-06-23  
**状态**：完成

## 背景

ADS 以 CLI 模式运行时（`codebuddy --print --output-format stream-json`），每次调用都是全新 session，CLI 工具不知道上一轮对话内容。通过 `--resume <session_id>` 可让 CLI 恢复本地 session 文件，实现上下文持续。

## Step 6：DB 扩展

**文件**：`backend/database.py`

```python
("chat_sessions", "cli_session_id", "TEXT"),
```

存储 CLI 返回的 session_id（如 `abc123-...`），下次调用时传给 `--resume`。

## Step 7：llm_client 层改造

**文件**：`backend/llm_client.py`

### 7.1 `_call_cli_stream` 接受 `resume_session_id` 参数

```python
async def _call_cli_stream(self, messages, temperature, max_tokens,
                            resume_session_id: str = ""):
```

支持 `--resume` 的 CLI 类型（`claude`/`claude-internal`/`codebuddy`）在命令末尾追加：
```python
if resume_session_id and self.cli_type in _RESUME_SUPPORTED:
    cmd += ["--resume", resume_session_id]
```

### 7.2 `_reader` 捕获 `system/init` 事件

stream-json 首条消息格式：
```json
{"type":"system","subtype":"init","session_id":"abc123"}
```

捕获后放入 queue：
```python
elif t == "system" and obj.get("subtype") == "init":
    sid = obj.get("session_id", "")
    if sid:
        await queue.put(("session_id", sid))
```

### 7.3 yield `cli_session_id` 事件

消费 queue 时新增类型：
```python
elif kind == "session_id":
    yield {"type": "cli_session_id", "session_id": chunk}
```

## Step 8：事件链路接通

### 8.1 `query_engine/events.py` 新增事件类型

```python
@dataclass
class CliSessionIdEvent:
    session_id: str
```

加入 `QueryEvent` 联合类型。

### 8.2 `query_engine/engine.py` 传参 + 上抛

- `QueryEngine.__init__` 新增 `resume_session_id: str = ""`
- CLI 分支调用时传入：`_call_cli_stream(..., resume_session_id=self.resume_session_id)`
- 收到 `cli_session_id` 事件时 yield `CliSessionIdEvent`

### 8.3 `chat_assistant.py` 查/存 DB

**调用前**（`chat_stream` 方法）：
```python
if llm_client.api_format == "cli" and session_id:
    _row = await db.fetch_one("SELECT cli_session_id FROM chat_sessions WHERE id=?", (session_id,))
    _cli_resume_id = _row["cli_session_id"] or ""
```
把 `_cli_resume_id` 传给 `QueryEngine(resume_session_id=_cli_resume_id)`。

**收到事件后**（事件循环）：
```python
elif isinstance(event, CliSessionIdEvent):
    await db.execute(
        "UPDATE chat_sessions SET cli_session_id=?, last_active_at=? WHERE id=?",
        (event.session_id, now_iso(), session_id),
    )
```

## 数据流

```
首次对话：
  QueryEngine(resume_session_id="")
  → codebuddy ... (无 --resume)
  → 输出 {"type":"system","subtype":"init","session_id":"abc"}
  → CliSessionIdEvent("abc") → 写 chat_sessions.cli_session_id = "abc"

后续对话：
  DB 查 cli_session_id = "abc"
  → QueryEngine(resume_session_id="abc")
  → codebuddy ... --resume abc
  → CLI 恢复本地 session 文件，AI 记得上文
```

## 修改文件汇总

| 文件 | 改动 |
|---|---|
| `database.py` | migrations 追加 `cli_session_id` |
| `llm_client.py` | `_call_cli_stream` 接受 resume 参数，reader 捕获 session_id，yield cli_session_id 事件 |
| `query_engine/events.py` | 新增 `CliSessionIdEvent` |
| `query_engine/engine.py` | `__init__` 加 `resume_session_id`，CLI 分支传参+上抛事件 |
| `agents/chat_assistant.py` | 调前查 DB，收事件后写 DB（project + global 两处） |
