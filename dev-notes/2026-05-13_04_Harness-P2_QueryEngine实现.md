# [Harness-P2] QueryEngine 统一 LLM 调用循环 实现记录

> 日期：2026-05-13  
> 系列：Harness 平台升级 / Phase 2  
> 提交：`a2d78e7`

---

## 一、交付文件

| 文件 | 类型 | 说明 |
|------|------|------|
| `backend/query_engine/events.py` | 新建 | 8 种 QueryEvent 类型 |
| `backend/query_engine/executor.py` | 新建 | ToolExecutorProtocol + 两个适配器 |
| `backend/query_engine/engine.py` | 新建 | QueryEngine 主类 |
| `backend/query_engine/__init__.py` | 更新 | 导出全量符号 |
| `backend/agents/chat_assistant.py` | 修改 | 两个流式方法改走 QueryEngine |
| `backend/agents/base.py` | 修改 | get_tool_schemas() + _react_with_think_inner 改走 QueryEngine |

---

## 二、架构说明

### QueryEngine 职责

```
QueryEngine.run(messages, system, tools, context)
  ├─ 每轮前：budget.check()
  ├─ 流式 LLM：llm_client._call_anthropic_tools_stream()
  ├─ 每轮后：budget.consume()
  ├─ 无工具 → yield MessageDoneEvent（同步 executor.thinking_steps）
  └─ 有工具 →
       ├─ hook_registry.emit(PRE_TOOL_USE, blocking=True)
       ├─ executor.execute(tool_name, tool_input, context)
       ├─ hook_registry.emit(POST_TOOL_USE / TOOL_ERROR)
       ├─ yield ToolDoneEvent / ToolErrorEvent
       └─ 回填 tool_results → 下一轮
```

### 适配器模式

```
chat_stream / chat_global_stream
  └─ ChatToolExecutorAdapter(wraps _ChatToolExecutor)
       └─ 复用已有的：thinking_steps 收集、SSE 推送、action 优先级
           primary_action_result、all_confirm_results

_react_with_think_inner（REACT 模式）
  └─ OrchestratorToolExecutorAdapter(wraps agent._actions)
       └─ 自动合并 base_context + context + tool_input 调用 action.run()
```

### 事件映射（chat_stream → SSE dict）

| QueryEvent | SSE dict type |
|------------|--------------|
| TextDeltaEvent | text_delta |
| ToolStartEvent | tool_start |
| ToolDoneEvent / ToolErrorEvent | tool_done |
| ActionEvent | action |
| MessageDoneEvent | message_done（含 thinking_steps / action / actions）|
| BudgetExceededEvent | budget_exceeded |
| ErrorEvent | error |

---

## 三、设计决策

### thinking_steps 同步策略

QueryEngine 内部也会从 `result_text[:120]` 构建 thinking_steps，  
但 `ChatToolExecutorAdapter` 的内部 `_ChatToolExecutor` 有更优质的 summary  
（来自 `result.message` 而非截断文本）。

MessageDoneEvent 生成时，引擎优先同步 `executor.thinking_steps`（若存在），  
这样 `_ChatToolExecutor` 的语义 summary 会覆盖引擎的截断版本。

### Orchestrator get_tool_schemas()

Orchestrator Agent 的 Action 没有 `tool_schema()` 方法。  
`BaseAgent.get_tool_schemas()` 自动为每个 Action 生成简化 schema：
```json
{
  "name": "write_code",
  "description": "写代码",
  "input_schema": {"type": "object", "properties": {}, "required": []}
}
```
并追加 `done` 工具让 LLM 可以主动结束循环。

### api/chat.py 无需修改

两个 stream generator（`_chat_stream_generator` / `_global_chat_stream_generator`）  
依然调用 `agent.chat_stream()` / `agent.chat_global_stream()`，  
而这两个方法内部已改走 QueryEngine，对外 dict 事件格式完全不变。  
**零前端改动，零 API 层改动。**

---

## 四、验收状态

| 验收项 | 状态 |
|--------|------|
| 模块导入无错 | ✅ |
| ChatToolExecutorAdapter 接口正确 | ✅ |
| OrchestratorToolExecutorAdapter 接口正确 | ✅ |
| engine.run() 异步生成器 | ✅ |
| budget.check() 集成在循环中 | ✅ |
| Pre/Post Hooks 集成在循环中 | ✅ |
| _react_with_think_inner 改用 QueryEngine | ✅ |
| api/chat.py 无需修改（向后兼容）| ✅ |

> api/chat.py 行数缩减（目标 ≤900 行）因本次走适配器路线，暂未缩减。  
> 若后续需要可直接在 api/chat.py 中用 QueryEngine 替换 generator 逻辑。
