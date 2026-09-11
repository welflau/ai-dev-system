# DevNote · 2026-08-07（四）

**类型**: 工单 Checkpoint P2 — CLI/API 写工具钩子 + GC  
**状态**: 已落地（需重启后端）  
**方案**: `docs/20260807_01_工单Checkpoint快照与还原方案.md`  
**前置**: P0 `2026-08-07_02`、P1 `2026-08-07_03`

---

## 一、本阶段内容

### 1. QueryEngine 写工具钩子

- **API 路径**：`executor.execute` **之前**调用 `maybe_capture_for_tool`（可靠）
- **CLI 路径**：`cli_tool_start` 时尽力拍快照（原生 Write 可能已落盘，尽力而为）
- 工具名：`Write` / `Edit` / `write_file` / `edit_file` / `create_file` / mcp filesystem 写

### 2. 上下文贯通

- `BaseAgent._react_with_think`：有 `ticket_id` 时 `set_checkpoint_context`
- `ChatAssistant.chat_stream`：若 `project_context` 带 ticket，同样注入

### 3. GC

- `checkpoint_service.gc_expired(ttl_days=14)`
  - 清理 `cancelled`/`deployed` 且超过 TTL 的 checkpoint
  - 进行中 ticket 只保留最近 50 条 `before_write`
  - 删除无引用 orphan blob
- `main.py` lifespan：启动 30s 后跑一次，之后每 6 小时

---

## 二、验收

1. 工单 Agent（API 模式）Write → checkpoints 有对应 before_write  
2. CLI 模式 Write → 尽量有快照（不保证早于写盘）  
3. 日志出现 `Checkpoint GC: {...}`（或无过期数据时静默）  

---

## 三、仍可选（P3）

- 工单对话 API 明确传 `ticket_id` 进 project_context（前端）  
- GC 管理 UI / 手动触发接口  
- before_write 折叠进详细日志  

---

## 四、关键文件

```
backend/checkpoint/service.py
backend/query_engine/engine.py
backend/agents/base.py
backend/agents/chat_assistant.py
backend/main.py
dev-notes/2026-08-07_04_工单Checkpoint_CLI钩子与GC_P2.md
```
