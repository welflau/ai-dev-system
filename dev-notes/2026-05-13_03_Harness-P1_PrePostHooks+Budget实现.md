# [Harness-P1] Pre/Post Tool Hooks + 预算约束 实现记录

> 日期：2026-05-13  
> 系列：Harness 平台升级 / Phase 1  
> 计划来源：`dev-notes/2026-05-13_02_Harness平台升级开发计划.md`  
> 提交：`93e8d23`（Hooks）、`d8f9fbf`（Budget）

---

## 一、Phase 1A — Pre/Post Tool Hooks

### 交付文件

| 文件 | 类型 | 说明 |
|------|------|------|
| `backend/hooks/__init__.py` | 新建 | 模块入口 |
| `backend/hooks/types.py` | 新建 | `HookEvent` 枚举 + `ToolHookContext` 数据类 |
| `backend/hooks/registry.py` | 新建 | `HookRegistry` 单例 |
| `backend/hooks/builtin.py` | 新建 | 3 个内置 Hook |
| `backend/actions/executor.py` | 新建 | `run_action_with_hooks()` 包装器 |
| `backend/agents/base.py` | 修改 | `run_action()` 改调 executor |
| `backend/database.py` | 修改 | 新增 `tool_audit_log` 表 |
| `backend/main.py` | 修改 | lifespan 注册内置 Hooks |

### 设计要点

**HookRegistry.emit(blocking)**

原计划 emit() 是全 fail-open。实现中发现限流 Hook 需要能阻断 Action 执行，
所以加了 `blocking` 参数：

- `blocking=False`（默认）：所有 Hook 失败只记日志，不影响主流程
- `blocking=True`：第一个 Hook 抛出的异常在所有 Hook 执行完后重抛

executor.py 的 `PRE_TOOL_USE` 调用用 `blocking=True`，`POST_TOOL_USE` 和 `TOOL_ERROR` 用默认的 `blocking=False`。

**failure_library_hook 写目标**

计划文档写的是 `failure_library` 表，但实际库里没有这张表（已有 `failure_cases`，字段复杂）。
改为写 `ticket_logs`（level=error），字段简洁，信息完整，且现有前端已能查看。

### 验收结果

```
[1] PRE ShellAction 正常通过（未超限）                ✅
[2] POST_TOOL_USE fail-open 通过（db 未连接不抛错）   ✅
[3] 限流测试通过，count=52 > 50，RuntimeError 正确传播 ✅
```

---

## 二、Phase 1B — 预算/配额约束

### 交付文件

| 文件 | 类型 | 说明 |
|------|------|------|
| `backend/query_engine/__init__.py` | 新建 | 模块入口（为 Phase 2 QueryEngine 预留目录）|
| `backend/query_engine/budget.py` | 新建 | `Budget` 数据类 |
| `backend/config.py` | 修改 | 新增 6 个预算配置项 |
| `backend/llm_client.py` | 修改 | `chat_with_tools_stream` 接受 `budget` 参数 |
| `backend/agents/chat_assistant.py` | 修改 | 两处调用接入 Budget |
| `backend/api/chat.py` | 修改 | 两处 generator 处理 `budget_exceeded` 事件 |

### Budget 配置项（.env 可覆盖）

```python
AGENT_MAX_TOKENS  = 200_000    # 工单 Agent Token 上限
AGENT_MAX_TURNS   = 50         # 工单 Agent 轮次上限
AGENT_MAX_SECONDS = 600        # 工单 Agent 时间上限（秒）
CHAT_MAX_TOKENS   = 100_000    # 聊天会话 Token 上限
CHAT_MAX_TURNS    = 30         # 聊天会话轮次上限
CHAT_MAX_SECONDS  = 180        # 聊天会话时间上限（秒）
```

### 数据流

```
chat_assistant.chat_stream()
  └─► Budget(CHAT_MAX_TURNS=30, ...)
        └─► llm_client.chat_with_tools_stream(budget=chat_budget)
              ├─► 每轮开始：budget.check() → 超限 yield budget_exceeded
              └─► 每轮结束：budget.consume(tokens=..., turns=1)
api/chat.py _chat_stream_generator
  └─► etype == "budget_exceeded" → yield _sse("error", {"message": "已达到对话限制：..."})
```

### 验收结果

```
Budget(max_tokens=1000) consume(500+300+300=1100) → "Token 上限已达到"  ✅
Budget(max_turns=2) consume(turns=2)              → "轮次上限已达到"    ✅
CHAT_MAX_TURNS: 30 / AGENT_MAX_TURNS: 50           配置读取正确         ✅
```

---

## 三、后续计划

- **Phase 2（P1，3-5 天）**：QueryEngine 抽象，统一三条 LLM 调用路径，`api/chat.py` 从 2140 行缩减至 ~900 行
- `query_engine/` 目录已预建，Phase 2 直接在此扩展

---

## 四、Harness 系列文件命名约定

本系列开发记录统一使用前缀 `Harness-Px`：

| 文件 | 内容 |
|------|------|
| `2026-05-13_02_Harness平台升级开发计划.md` | 总体开发计划 |
| `2026-05-13_03_Harness-P1_PrePostHooks+Budget实现.md` | Phase 1 实现记录（本文）|
| `2026-05-xx_xx_Harness-P2_QueryEngine实现.md` | Phase 2 实现记录（待写）|
| `2026-05-xx_xx_Harness-P3_异步权限审批实现.md` | Phase 3 实现记录（待写）|
