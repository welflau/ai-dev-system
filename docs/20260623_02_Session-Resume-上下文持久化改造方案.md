# Session Resume — AI 助手对话上下文持久化改造方案

**日期**：2026-06-23（v2 修订：补充 CLI 模式方案）  
**状态**：部分完成（API 模式已实现，CLI 模式待实施）  
**优先级**：高

---

## 一、问题背景

### 1.1 现象

用户在 AI 助手（ChatAssistant）中进行多轮对话后，遇到以下场景时上下文全部丢失：

- **刷新页面**：`chatHistory[]` 是内存数组，刷新后重置为 `[]`
- **切换项目 / Tab**：`_updateChatPanelForContext()` 显式执行 `chatHistory = []`
- **长时间后重开页面**：localStorage 有 TTL 限制，且仅保存全局聊天

用户不得不在每次新对话开始时重新解释背景，严重影响连续工作效率。

### 1.2 ADS 的两种 LLM 调用模式

ADS 支持两种完全不同的 LLM 调用路径，**Resume 机制也完全不同**：

| 模式 | 触发条件 | history 传递方式 | session 状态存在哪 |
|---|---|---|---|
| **API 模式** | `LLM_API_FORMAT=anthropic/openai` | `messages[]` 数组传给 API | ADS 自己的 DB |
| **CLI 模式** | `LLM_API_FORMAT=cli`（codebuddy/claude 等）| stdin 传 prompt，CLI 自维护 session 文件 | CLI 本地 `~/.claude/` 等 |

截图日志：`cmd /c codebuddy --print --output-format stream-json --include-partial-messages --model deepseek-v4-pro-ioa` — **当前是 CLI 模式**，没有 `--resume` 参数，每次都是全新 session，CLI 无法感知上一轮对话。

### 1.3 与 multica Session Resume 的对应关系

| multica 机制 | ADS CLI 模式对应 | ADS API 模式对应 |
|---|---|---|
| `--resume <session_id>` | 在 `build_cmd` 加 `--resume` | 从 DB 读 history 拼 messages（已实现）|
| `GetLastTaskSession` SQL | 查 `chat_sessions.cli_session_id` | 查 `chat_messages` 表 |
| Mid-flight pin | 从 stream-json 输出捕获 `session_id` 写 DB | 消息落库时更新状态 |
| Poisoned session 过滤 | 异常时不存 `cli_session_id` | 标记 `last_status=poisoned` |
| `force_fresh_session` | 用户点"新对话"时不传 `--resume` | 创建新 `session_id` |

---

## 二、方案思路

### 2.1 CLI 模式（主要问题）

CLI 工具（codebuddy/claude）内部维护对话状态，通过 `--resume <session_id>` 恢复。
`--output-format stream-json` 输出中，第一条消息是：

```json
{"type":"system","subtype":"init","session_id":"<uuid>","..."}
```

**方案：**
1. 从 stream-json 输出中捕获 `session_id`
2. 存入 `chat_sessions.cli_session_id` 字段
3. 下次同一 ADS session 发消息时，`build_cmd` 追加 `--resume <cli_session_id>`

```
首次对话：
  codebuddy --print --output-format stream-json ... → 捕获 session_id → 存 DB

后续对话：
  DB 查 cli_session_id → codebuddy --print ... --resume <id> → CLI 恢复上下文
```

### 2.2 API 模式（已实现，作为兜底）

有 `chat_session_id` 时从 DB 读最近 30 条 `chat_messages` 拼成 `messages[]` 传给 API。
刷新/切换项目后可自动恢复，不依赖前端内存数组。

### 2.3 Poisoned Session 过滤

CLI 异常退出（returncode != 0、超时）时，**不写入** `cli_session_id`（保持 NULL），
下次调用走全新 session，避免损坏的 CLI session 文件污染后续对话。

API 模式：异常时标记 `last_status = 'poisoned'`，`_load_session_history` 返回空列表。

---

## 三、实施步骤

### ✅ 已完成（API 模式，Step 1-5）

| Step | 内容 | 文件 |
|---|---|---|
| 1 | DB 追加 `last_status` / `last_active_at` / `message_count` | `database.py` |
| 2 | 新增 `_load_session_history()` | `api/chat.py` |
| 3 | 改造两处 `history_list` 赋值，有 session_id 时从 DB 读 | `api/chat.py` |
| 4 | 流式完成标记 `completed`，异常标记 `poisoned` | `api/chat.py` |
| 5 | 项目内聊天前端移除 `history` 传参 | `app.js` |

---

### 待实施（CLI 模式，Step 6-8）

#### Step 6：DB 扩展 `cli_session_id` 字段

**文件**：`backend/database.py`

在 migrations 列表末尾追加：

```python
("chat_sessions", "cli_session_id", "TEXT"),
# CLI 工具返回的 session_id，用于 --resume 恢复上下文
```

---

#### Step 7：`_call_cli_stream` 捕获并回传 `cli_session_id`

**文件**：`backend/llm_client.py`

**7.1 `_reader` 内捕获 init 事件**

在 `_call_cli_stream` 的流式 `_reader` 函数中，加入对 `type=system, subtype=init` 的解析：

```python
# 现有代码结构（约 802 行）
t = obj.get("type", "")
if t == "stream_event":
    ...
elif t == "result" and obj.get("is_error"):
    ...
# 新增：捕获 CLI session_id
elif t == "system" and obj.get("subtype") == "init":
    sid = obj.get("session_id", "")
    if sid:
        await queue.put(("session_id", sid))
```

**7.2 `_call_cli_stream` 消费 `session_id` 并 yield**

在 queue 消费循环中处理新事件类型：

```python
if kind == "text":
    yield {"type": "text_delta", "delta": chunk}
elif kind == "thinking":
    yield {"type": "thinking_delta", "delta": chunk}
elif kind == "session_id":          # 新增
    yield {"type": "cli_session_id", "session_id": chunk}
```

**7.3 `_call_cli_stream` 接受 `resume_session_id` 参数**

函数签名改为：

```python
async def _call_cli_stream(
    self,
    messages: List[Dict],
    temperature: float,
    max_tokens: int,
    resume_session_id: str = "",    # 新增
) -> AsyncGenerator[Dict[str, Any], None]:
```

`build_cmd` 调用后追加 `--resume`：

```python
raw_args = adapter["build_cmd"](self.cli_cmd, self.cli_model, prompt)
cmd = cmd_prefix + raw_args[1:]
if resume_session_id and self.cli_type in ("claude", "claude-internal", "codebuddy"):
    cmd += ["--resume", resume_session_id]
    logger.info("🖥️  CLI Resume: session_id=%s", resume_session_id)
```

**同样处理非流式 `_call_cli` 和 `stream_chat`**（调用链向上传参）。

---

#### Step 8：`chat_assistant.py` 传入/存储 `cli_session_id`

**文件**：`backend/agents/chat_assistant.py`（或调用 `llm_client` 的最近层）

**8.1 调用前查 DB 取 `cli_session_id`**

在 `chat_stream` 方法调用 llm_client 之前：

```python
cli_resume_id = ""
if llm_client.api_format == "cli" and session_id:
    row = await db.fetch_one(
        "SELECT cli_session_id FROM chat_sessions WHERE id = ?", (session_id,)
    )
    if row and row.get("cli_session_id"):
        cli_resume_id = row["cli_session_id"]
        logger.info("CLI Resume: session=%s cli_sid=%s", session_id, cli_resume_id)
```

**8.2 把 `cli_resume_id` 传给 llm_client**

```python
async for ev in llm_client.stream_chat(
    messages=messages,
    ...,
    resume_session_id=cli_resume_id,   # 新增
):
```

**8.3 收到 `cli_session_id` 事件时写 DB**

在流式事件处理循环中：

```python
elif ev.get("type") == "cli_session_id":
    new_cli_sid = ev.get("session_id", "")
    if new_cli_sid and session_id:
        await db.execute(
            "UPDATE chat_sessions SET cli_session_id = ?, last_active_at = ? WHERE id = ?",
            (new_cli_sid, now_iso(), session_id),
        )
        logger.info("CLI session_id pinned: %s → %s", session_id, new_cli_sid)
```

---

## 四、完整数据流

### CLI 模式（首次对话）

```
用户发消息
  → chat.py: _load_session_history() → DB（API 模式兜底，CLI 模式不依赖此步骤）
  → llm_client._call_cli_stream(resume_session_id="")
  → codebuddy --print --output-format stream-json ...（无 --resume）
  → 输出 {"type":"system","subtype":"init","session_id":"abc123"}
  → yield {"type":"cli_session_id","session_id":"abc123"}
  → chat_assistant: UPDATE chat_sessions SET cli_session_id='abc123'
  → 后续流式文本正常输出
```

### CLI 模式（续上轮对话）

```
用户发消息
  → chat_assistant: SELECT cli_session_id FROM chat_sessions → 'abc123'
  → llm_client._call_cli_stream(resume_session_id="abc123")
  → codebuddy --print --output-format stream-json ... --resume abc123
  → CLI 从本地 session 文件恢复完整对话上下文
  → 正常输出（可能返回新的 session_id，覆盖写入）
```

### CLI 模式（异常情况）

```
codebuddy 异常退出（returncode != 0 / 超时）
  → 不写入 cli_session_id（保持原值或 NULL）
  → 下次发消息时 cli_session_id 为空 → 走全新 session
  → 同时标记 last_status = 'poisoned'（与 API 模式共享）
```

---

## 五、不需要改的部分

| 模块 | 原因 |
|---|---|
| `chat_messages` 表 | 已有完整字段，无需变动 |
| `_assemble_messages` 压缩逻辑 | CLI 模式不走此路径；API 模式已接管 |
| `ChatRequest.history` 字段 | 保留，全局聊天兜底 |
| 前端气泡渲染 | 不变，`chatHistory[]` 仍用于 UI |
| `build_cmd` 其他参数 | 只在末尾追加 `--resume`，不影响现有参数 |

---

## 六、验收标准

| 场景 | 预期结果 |
|---|---|
| CLI 模式：同 session 第二条消息 | 命令带 `--resume <id>`，AI 记得上文 |
| CLI 模式：刷新页面后发消息 | 从 DB 取 `cli_session_id`，仍带 `--resume` |
| CLI 模式：codebuddy 超时 | 不写 `cli_session_id`，下次全新 session |
| API 模式：刷新页面后发消息 | 从 DB 读历史，AI 记得上文 |
| 用户点"新对话" | 创建新 `session_id`，`cli_session_id` 为 NULL，无 `--resume` |
| 切换项目再切回 | `cli_session_id` 已存 DB，恢复正常 |

---

## 七、风险与注意事项

1. **CLI session 文件有效期**：`~/.claude/` 下的 session 文件有 TTL（通常数天到数周）。过期后 `--resume` 会静默失败，CLI 自动开新 session 并返回新 `session_id`，ADS 捕获后覆盖写入，无需额外处理。

2. **多设备 / 多进程**：CLI session 文件是本地文件，只对当前机器有效。若后端迁移到其他机器，历史 `cli_session_id` 失效，行为同"过期"。

3. **非 streaming CLI**（gemini-internal 等）：`streaming=False` 的适配器走 `_call_cli` 而非 `_call_cli_stream`，stdout 是完整文本，没有 stream-json 格式，无法捕获 `session_id`，暂不支持 resume（现状不变）。

4. **`--resume` 参数兼容性**：已确认 claude、codebuddy 均支持 `--resume <id>`。gemini-internal 使用 `-r`，如需支持需在 `_CLI_ADAPTERS` 中单独处理。
