# Session Transcript — 实现方案（P2）

> 日期: 2026-04-20 | 对标: MagicAI `src/agents/game_agent/utils/transcript.py` + `subagent_tracker.py`

---

## 一、背景

### 1.1 当前调试痛点

系统跑完一个需求，事后要定位"DevAgent 为什么打回了 5 次"、"第 3 次 reflection 的 strategy 是什么"、"哪次 LLM 调用超时了"——得在三处拼凑：

| 源 | 内容 | 问题 |
|---|---|---|
| `server.log`（repo 根） | 所有 Python logging 输出 | 混杂所有项目、所有请求，噪音大 |
| `ticket_logs` 表 | 状态流转事件 | 需 SQL 查询 + JSON detail 手动解析 |
| `llm_conversations` 表 | 每次 LLM 调用 | 同上 |

没有一个统一的、按**需求**为单位的完整执行轨迹。

### 1.2 MagicAI 对标

MagicAI 在 `src/agents/game_agent/utils/` 下有 `transcript.py`（人读）+ `subagent_tracker.py`（结构化）。靠 CodeBuddy SDK 的 `PreToolUse` / `PostToolUse` hook 机制自动捕获。

本项目没有 SDK hook，但刚好有两个**天然 chokepoint**：

| 点 | 覆盖范围 | 调用次数 |
|---|---|---|
| `orchestrator._log()`（orchestrator.py:2119） | 所有 Agent/Action/状态流转事件 | 26 处 |
| `llm_client._save_conversation()`（llm_client.py:305） | 所有 LLM 调用 | 单一入口 |

在这两处各加一行"镜像写入文件"即可获得与 MagicAI 等价的 transcript 能力。

### 1.3 目标

**零改动业务代码**，新增 `SessionLogger` 镜像现有数据流，按需求输出：
- `backend/logs/session_<req_id>/transcript.txt` — 人读事件流
- `backend/logs/session_<req_id>/tool_calls.jsonl` — 结构化 JSON 行

---

## 二、核心设计

### 2.1 目录结构

```
backend/logs/
├── session_REQ-20260420-abc123/
│   ├── transcript.txt
│   └── tool_calls.jsonl
├── session_REQ-20260420-def456/
│   ├── transcript.txt
│   └── tool_calls.jsonl
└── ...
```

**按需求分目录**：一个需求是用户视角的原子单位，同一 requirement 下的多个 ticket 共享 session 目录。

### 2.2 `transcript.txt` 格式

追加模式文本文件，首次写入时写 banner，之后每事件一行：

```
================================================================================
Session: requirement REQ-20260420-abc123
Started: 2026-04-20T20:53:28+00:00
================================================================================

[20:53:28] 🤖 orchestrator · ticket T-xyz1234567 · pending → development · 工单开始开发
[20:53:30] 🧠 DevAgent.write_code → LLM call (1234/567 tokens, 2.0s)
[20:53:45] ℹ️ DevAgent.complete · ticket T-xyz1234567 · development → development_done · 开发完成 2 个文件
[20:54:02] 🧠 ProductAgent.acceptance_review → LLM call (890/120 tokens, 1.5s)
[20:54:04] ❌ ProductAgent.reject · ticket T-xyz1234567 · acceptance_pending → acceptance_rejected · 验收不通过，页面上看不到计数器
[20:54:06] 🔍 DevAgent.reflection · ticket T-xyz1234567 · [反思 #2] 根因: 没在 index.html 加 DOM | 策略: 改 body 插 div
[20:54:20] 🧠 DevAgent.write_code → LLM call (1500/680 tokens, 2.3s)
[20:54:35] ✅ ProductAgent.accept · ticket T-xyz1234567 · acceptance_pending → acceptance_passed · 验收通过，转测试
```

emoji 映射（按 `action` 优先，`kind` 兜底）：
- `reject` → ❌，`accept` → ✅，`complete` → 🎉，`reflection` → 🔍
- `kind=llm` → 🧠，`kind=log` → ℹ️，`kind=start` → 🤖

### 2.3 `tool_calls.jsonl` 格式

每行一个 JSON 对象。两种 kind：

**kind=log**（ticket_logs 镜像）：
```json
{"ts":"2026-04-20T20:53:45+00:00","kind":"log","agent":"DevAgent","action":"complete","ticket_id":"T-xyz","from":"development","to":"development_done","message":"开发完成 2 个文件","detail":{"files":["index.html","app.js"]}}
```

**kind=llm**（LLM 调用镜像）：
```json
{"ts":"2026-04-20T20:53:30+00:00","kind":"llm","agent":"DevAgent","action":"write_code","ticket_id":"T-xyz","model":"claude-sonnet-4-6","input_tokens":1234,"output_tokens":567,"duration_ms":2000,"status":"success"}
```

**重要**：`kind=llm` 不含 messages / response 内容（太大，且已在 `llm_conversations` 表里）。只记 tokens / duration / status。要看完整对话去查表。

### 2.4 `SessionLogger` 类

`backend/session_logger.py`，单例 `session_logger`。

```python
class SessionLogger:
    async def log_event(*, requirement_id, kind, agent, action, ticket_id,
                       from_status, to_status, message, detail=None) -> None
    async def log_llm(*, requirement_id, agent, action, ticket_id, model,
                     input_tokens, output_tokens, duration_ms, status) -> None
```

**实现要点**：
- 每个 requirement 一个 `asyncio.Lock`，防并发写乱序
- 懒创建：首次 event 触发 `mkdir -p logs/session_<req_id>/` + 写 banner
- requirement_id 经 `_sanitize_req_id()` 去掉非字母数字字符（防路径注入 + Windows 兼容）
- 所有异常被 try/except 吞掉，仅打 warning，绝不阻塞主流程
- requirement_id 为空时直接 return（没有 req 就没有 session）

### 2.5 两个集成点

**集成点 1**：`backend/orchestrator.py::_log()` 末尾

```python
# 原本就有的：
await db.insert("ticket_logs", {...})
await event_manager.publish_to_project(...)

# 新增：
try:
    from session_logger import session_logger
    await session_logger.log_event(
        requirement_id=requirement_id,
        kind="log",
        agent=agent_type,
        action=action,
        ticket_id=ticket_id,
        from_status=from_status,
        to_status=to_status,
        message=message,
        detail=detail_data,
    )
except Exception as e:
    logger.warning("SessionLogger.log_event 失败: %s", e)
```

**集成点 2**：`backend/llm_client.py::_save_conversation()` 末尾

```python
await db.insert("llm_conversations", data)

# 新增：
try:
    from session_logger import session_logger
    await session_logger.log_llm(
        requirement_id=_llm_ctx.requirement_id,
        agent=_llm_ctx.agent_type,
        action=_llm_ctx.action,
        ticket_id=_llm_ctx.ticket_id,
        model=self.model,
        input_tokens=data["input_tokens"],
        output_tokens=data["output_tokens"],
        duration_ms=data["duration_ms"],
        status=data["status"],
    )
except Exception as e:
    logger.error("SessionLogger.log_llm 失败: %s", e)
```

**两点合计改动 ≤ 30 行，其余全自动。**

---

## 三、改动清单

### 3.1 新增

| 文件 | 说明 |
|---|---|
| `backend/session_logger.py` | SessionLogger 类 + 单例（~170 行） |
| `backend/_test_session_logger.py` | 5 用例单测（~150 行） |
| `docs/20260420_03_Session_Transcript实现方案.md` | 本文档 |

### 3.2 修改

| 文件 | 改动行数 |
|---|---|
| `backend/orchestrator.py::_log` | +16 行（try/except 镜像调用） |
| `backend/llm_client.py::_save_conversation` | +15 行（try/except 镜像调用） |

### 3.3 不需要改

- `.gitignore` — 已有 `logs/` 规则，涵盖 `backend/logs/`
- 其他 Agent / Action 代码 — 走既有 chokepoint 自动覆盖
- DB schema — 纯文件系统产物，无表结构变化

---

## 四、测试

### 4.1 单测 `_test_session_logger.py`（5/5 通过）

```
✅ Test 1 目录 + banner + 首次写入通过
✅ Test 2 事件顺序追加通过
✅ Test 3 LLM 写入双格式通过
✅ Test 4 jsonl 全合法 + detail 嵌套保留通过
✅ Test 5 并发 100 条无损通过
```

运行：`cd backend && PYTHONIOENCODING=utf-8 python _test_session_logger.py`

### 4.2 回归（全过）

```
_test_skills.py             ✅ 8/8
_test_reflection.py         ✅ 5/5
_test_failure_library.py    ✅ 6/6
_test_vision_action_node.py ✅ 4/4
```

### 4.3 手工端到端

1. 启动服务 → 创建一个需求 → 观察 Agent 跑完
2. 查 `backend/logs/session_<req_id>/` 应生成 transcript.txt + tool_calls.jsonl
3. 肉眼看 transcript.txt 应包含：banner、状态流转、LLM 调用行、emoji 标记
4. `jq` 解析 tool_calls.jsonl，行数应 ≈ `SELECT COUNT(*) FROM ticket_logs WHERE requirement_id=?` + `SELECT COUNT(*) FROM llm_conversations WHERE requirement_id=?`

---

## 五、未来扩展

### 5.1 前端「查看会话日志」按钮

需求详情页加一个按钮，打开 modal 展示 `transcript.txt` 内容（Markdown 渲染 + 高亮 emoji）。

实现：新增 `GET /api/requirements/<req_id>/session_transcript` 返回文本。工作量 0.5 天。

### 5.2 AI 助手引用会话

ChatAssistant 新增 Action `get_session_transcript(req_id)`，能回答"这个需求中间发生了什么"——直接把 transcript 最近 50 行塞给 LLM 做分析。

### 5.3 轮转与清理

当前无清理。未来若磁盘压力：
- 按时间清理：`find backend/logs -type d -mtime +30 -exec rm -rf {} \;`
- 按大小清理：单 session > 10MB 压缩
- 归档到 S3

### 5.4 扩展事件类型

目前两类：`log` + `llm`。未来可加：
- `tool_call`（MCP 工具调用，P3 后）
- `artifact`（产物写入事件）
- `error`（未处理异常）

在 SessionLogger 内加对应 `log_xxx` 方法即可，调用点由各子系统自行接入。

---

## 六、风险与降级

| 风险 | 缓解 |
|---|---|
| 文件写入异常阻塞 orchestrator | 所有 `session_logger.*` 调用都包 try/except，打 warning 不 raise |
| 高并发下多线程写乱序 / 交叉 | 每个 requirement 一个 asyncio.Lock；已 100 条并发测试通过 |
| 磁盘占用增长 | 现阶段不清理；未来加 retention（见 5.3）；单条事件 ≤ 2KB，平均每需求约 50 事件，单 session < 100KB |
| req_id 非法字符（路径注入） | `_sanitize_req_id()` 只保留字母数字 `_-.`，截断 80 字符 |
| 文件编码问题（Windows） | 全程 UTF-8 显式声明，中文直接写入（`ensure_ascii=False`） |

---

## 七、与 MagicAI 的差异

| 特性 | MagicAI | 本方案 |
|---|---|---|
| 触发机制 | SDK hook (`PreToolUse`/`PostToolUse`) | 复用现有 `_log()` + `_save_conversation()` chokepoint |
| 目录粒度 | 一次 session（用户一次对话） | 一个需求（横跨多 ticket） |
| Subagent 追踪 | `parent_tool_use_id` 归因 | 不需要（流程是串行调度，无子 agent 嵌套） |
| 文件数 | `transcript.txt` + `tool_calls.jsonl` | 同 |
| 记录 LLM 内容 | 记 prompt 摘要 | 不记（已在 `llm_conversations` 表） |

---

## 八、一句话总结

> 把现有 DB 里零散的 `ticket_logs` + `llm_conversations` 数据，按需求镜像一份到 `backend/logs/session_<req_id>/`，让调试不再需要 SQL。改动 30 行代码覆盖全部 Agent/Action/LLM 活动，失败降级不影响主流程。
