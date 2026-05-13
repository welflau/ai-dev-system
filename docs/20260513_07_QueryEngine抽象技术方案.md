# QueryEngine 抽象技术方案

> 日期：2026-05-13  
> 状态：方案设计（待实现）  
> 优先级：P1  
> 预计工时：3-5 天

---

## 一、背景与问题

### 1.1 现状

ADS 的 LLM 调用分散在三条相互独立的路径上：

```
路径 A：ChatAssistant 流式聊天
  api/chat.py → _chat_stream_generator()
    → agent.chat_stream()
      → llm_client.chat_with_tools_stream()
        → 工具调用循环（内嵌在 chat_assistant.py）

路径 B：ChatAssistant 非流式聊天
  api/chat.py → _chat_via_agent()
    → agent.chat()
      → llm_client.chat_with_tools()

路径 C：Orchestrator 工单 Agent（REACT 模式）
  orchestrator.py → agent.execute()
    → base.py → _react_with_think_inner()
      → _think() → llm_client.chat()   ← 只调一次 LLM，文本协议
      → _actions[next].run()           ← 纯程序式，无流式
```

三条路径**没有共同抽象**，各自实现了自己的：
- 工具调用循环逻辑
- 消息历史管理
- 错误处理方式
- 思考步骤收集

### 1.2 量化问题

| 文件 | 行数 | 职责膨胀原因 |
|------|------|------------|
| `api/chat.py` | **2140 行** | 承载了 HTTP 层、LLM 循环、消息持久化、SSE 格式化、全局/项目两套逻辑 |
| `agents/base.py` | **280 行** | REACT 模式工具循环与 Agent 基类混在一起 |
| `agents/chat_assistant.py` | **800+ 行** | 流式循环逻辑内嵌在 Agent 方法里 |

### 1.3 具体痛点

**痛点 1：预算约束无法统一执行**

```python
# 三条路径各自设置了不同的 max_tokens/max_rounds，
# 但没有统一的"超限中断"机制。
# 路径 A 由 max_react_loop=6 控制（轮数），
# 路径 C 由 max_react_loop（Agent 级）控制，
# 路径 B 没有轮次上限。
```

**痛点 2：Pre/Post Hooks 无插入点**

每条路径的工具执行是裸调用：
```python
# 路径 A（chat_with_tools_stream 内部）
result = await tool_executor.execute(tool_name, tool_input)
# 前后没有 Hook 插入点，无法做审计/限流/追踪

# 路径 C（base.py）
action_result = await self._actions[next_action].run(context)
# 同上，无法拦截
```

**痛点 3：消息格式规范化重复**

三条路径各自处理 Anthropic message 格式转换、thinking_steps 收集、最终保存逻辑，代码严重重复：
```python
# api/chat.py _chat_stream_generator
thinking_steps = ev.get("thinking_steps") or thinking_steps
await _save_chat_message(project_id, "assistant", full_text, ...)

# api/chat.py _global_chat_stream_generator
thinking_steps = ev.get("thinking_steps") or thinking_steps
await _save_chat_message("__global__", "assistant", full_text, ...)
```

**痛点 4：Orchestrator 无法使用流式**

Orchestrator 的工单 Agent 使用 `llm_client.chat()`（单次调用），不支持：
- 流式输出进度反馈
- Anthropic tool_use 格式（只能文本协议 REACT）
- 统一的思考步骤追踪

---

## 二、目标

提取独立的 `QueryEngine` 模块，统一三条 LLM 调用路径：

```
QueryEngine（统一入口）
  ├─► Budget 预算检查
  ├─► PreToolUse Hook 注入
  ├─► LLM 流式调用（llm_client.chat_with_tools_stream）
  ├─► 工具调用循环（tool_use → 执行 → 回填）
  ├─► PostToolUse / ToolError Hook 注入
  ├─► 消息规范化与持久化
  └─► 思考步骤收集
```

**效果**：
- `api/chat.py` 从 2140 行缩减至 ~800 行（纯 HTTP 层）
- Orchestrator Agent 获得流式能力和统一的预算/Hook 支持
- 新增一条执行路径只需配置 QueryEngine，不需要重写循环逻辑

---

## 三、现有调用链分析

### 3.1 路径 A：ChatAssistant 流式（主路径）

```
HTTP POST /projects/{id}/chat/stream
  └─► api/chat.py: chat_stream()
        └─► _chat_stream_generator(project, req)
              ├─► agent.chat_stream()          ← ChatAssistantAgent.chat_stream()
              │     └─► llm_client.chat_with_tools_stream()
              │           └─► 工具调用循环
              │                 ├─► executor.execute(tool_name, input)
              │                 └─► yield tool_start/tool_done/text_delta
              ├─► 转发 SSE 事件
              └─► _save_chat_message()         ← 消息持久化
```

**关键问题**：工具调用循环在 `llm_client.py` 内部，消息持久化在 `api/chat.py`，两层之间没有统一接口。

### 3.2 路径 B：ChatAssistant 非流式（降级路径）

```
HTTP POST /projects/{id}/chat
  └─► api/chat.py: _chat_via_agent()
        └─► agent.chat()
              └─► llm_client.chat_with_tools()   ← 完整返回，非流式
                    └─► 工具调用循环（同步）
```

**关键问题**：与路径 A 是两套完全独立的实现，无法共享限流/审计逻辑。

### 3.3 路径 C：Orchestrator REACT（工单 Agent）

```
TicketOrchestrator._dispatch_ticket()
  └─► agent.execute(action, context)
        └─► base._react_with_think_inner()
              └─► for round in max_react_loop:
                    ├─► _think() → llm_client.chat()    ← 文本协议选 Action
                    └─► _actions[name].run(context)     ← 执行 Action
```

**关键问题**：
1. 只用 `llm_client.chat()`，不用 `tool_use` 格式，无法享受 Anthropic 的原生工具调用能力
2. 完全没有流式，无法向前端推送实时进度
3. 无法插入 Pre/Post Hooks

---

## 四、设计方案

### 4.1 核心抽象

```python
# backend/query_engine/engine.py

class QueryEngine:
    """
    统一的 LLM 查询引擎。
    
    职责：
    - 管理工具调用循环（LLM → tool_use → 执行 → 回填）
    - 执行预算约束（Token / 轮次 / 时间）
    - 发射 Pre/Post Hooks
    - 规范化消息格式
    - 透传流式事件
    
    不负责：
    - HTTP 层（由 api/chat.py 处理）
    - 消息持久化（由调用方决定是否保存）
    - Agent 系统提示（由 Agent 自己构建）
    """
    
    def __init__(
        self,
        llm_client: LLMClient,
        tool_executor: ToolExecutorProtocol,   # 执行工具的接口
        budget: Budget | None = None,
        hooks: HookRegistry | None = None,
    ):
        self.llm = llm_client
        self.executor = tool_executor
        self.budget = budget or Budget()
        self.hooks = hooks or HookRegistry()
    
    async def run(
        self,
        messages: list[dict],
        system: str,
        tools: list[dict],
        context: dict,
    ) -> AsyncIterator[QueryEvent]:
        """
        主循环。yield QueryEvent 供调用方处理（SSE 转发 / 收集 / 忽略）。
        """
```

### 4.2 事件模型

QueryEngine 产出标准化的事件流，调用方按需消费：

```python
# backend/query_engine/events.py

@dataclass
class TextDeltaEvent:
    delta: str

@dataclass
class ToolStartEvent:
    tool: str
    input: dict
    tool_use_id: str

@dataclass
class ToolDoneEvent:
    tool: str
    summary: str
    duration_ms: float

@dataclass
class ToolErrorEvent:
    tool: str
    error: str
    duration_ms: float

@dataclass
class ActionEvent:
    action_data: dict          # confirm_requirement 等卡片数据

@dataclass
class MessageDoneEvent:
    full_text: str
    thinking_steps: list[dict]
    final_action: dict | None
    rounds: int
    total_tokens: int

@dataclass
class BudgetExceededEvent:
    reason: str                # "Token limit reached" / "Turn limit reached"

@dataclass
class ErrorEvent:
    message: str

QueryEvent = Union[
    TextDeltaEvent, ToolStartEvent, ToolDoneEvent, ToolErrorEvent,
    ActionEvent, MessageDoneEvent, BudgetExceededEvent, ErrorEvent,
]
```

### 4.3 预算模型

```python
# backend/query_engine/budget.py

@dataclass
class Budget:
    max_tokens:  int   = 200_000     # 总 Token 上限
    max_turns:   int   = 50          # 工具调用轮次上限
    max_seconds: float = 600.0       # 执行时间上限（秒）

    _used_tokens: int   = field(default=0, init=False)
    _used_turns:  int   = field(default=0, init=False)
    _start_time:  float = field(default_factory=time.monotonic, init=False)

    def check(self) -> str | None:
        """返回超限原因，或 None（未超限）"""
        if self._used_tokens  >= self.max_tokens:
            return f"Token limit ({self.max_tokens:,}) reached"
        if self._used_turns   >= self.max_turns:
            return f"Turn limit ({self.max_turns}) reached"
        elapsed = time.monotonic() - self._start_time
        if elapsed >= self.max_seconds:
            return f"Time limit ({self.max_seconds:.0f}s) reached"
        return None

    def consume(self, tokens: int = 0, turns: int = 0) -> None:
        self._used_tokens += tokens
        self._used_turns  += turns
```

### 4.4 ToolExecutorProtocol

QueryEngine 不直接依赖 Action 类，而是通过协议接口解耦：

```python
# backend/query_engine/executor.py

class ToolExecutorProtocol(Protocol):
    async def execute(
        self,
        tool_name: str,
        tool_input: dict,
        context: dict,
    ) -> tuple[str, dict | None]:
        """
        执行工具。
        返回 (result_text, action_data)
        action_data 非 None 时表示需要前端渲染卡片（confirm_requirement 等）
        """
        ...
```

**ChatAssistant 的适配器**（已有 `_ChatToolExecutor`，小改即可）：

```python
class ChatToolExecutorAdapter:
    def __init__(self, agent: ChatAssistantAgent, project_id: str):
        self._inner = _ChatToolExecutor(agent, project_id)

    async def execute(self, tool_name, tool_input, context):
        result_json = await self._inner.execute(tool_name, tool_input)
        data = json.loads(result_json)
        action_data = self._inner.primary_action_result
        return result_json, action_data
```

**Orchestrator Agent 的适配器**（新建）：

```python
class OrchestratorToolExecutorAdapter:
    def __init__(self, agent_actions: dict, context: dict):
        self._actions = agent_actions
        self._base_context = context

    async def execute(self, tool_name, tool_input, context):
        action = self._actions.get(tool_name)
        if not action:
            return f"Unknown tool: {tool_name}", None
        ctx = {**self._base_context, **context, "params": tool_input}
        result = await action.run(ctx)
        return result.message or str(result.data), None
```

### 4.5 QueryEngine 主循环实现

```python
# backend/query_engine/engine.py（核心部分）

async def run(self, messages, system, tools, context) -> AsyncIterator[QueryEvent]:
    current_messages = list(messages)
    full_text = ""
    thinking_steps = []
    final_action = None
    round_count = 0

    while True:
        # 1. 预算检查
        if reason := self.budget.check():
            yield BudgetExceededEvent(reason=reason)
            return

        # 2. 流式 LLM 调用
        text_chunks = []
        tool_calls = []
        usage = {}

        async for chunk in self.llm.chat_with_tools_stream(
            messages=current_messages,
            system=system,
            tools=tools,
        ):
            ctype = chunk.get("type", "")

            if ctype == "text_delta":
                full_text += chunk["delta"]
                text_chunks.append(chunk)
                yield TextDeltaEvent(delta=chunk["delta"])

            elif ctype == "tool_use":
                tool_calls.append(chunk)

            elif ctype == "usage":
                usage = chunk

        # 消耗 Token/轮次预算
        tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        self.budget.consume(tokens=tokens, turns=1)
        round_count += 1

        # 3. 无工具调用 → 结束
        if not tool_calls:
            yield MessageDoneEvent(
                full_text=full_text,
                thinking_steps=thinking_steps,
                final_action=final_action,
                rounds=round_count,
                total_tokens=self.budget._used_tokens,
            )
            return

        # 4. 执行每个工具调用
        tool_results = []
        for call in tool_calls:
            tool_name = call["name"]
            tool_input = call.get("input", {})
            start_ts = time.monotonic()

            # 4a. PreToolUse Hook
            await self.hooks.emit(ToolHookContext(
                event=HookEvent.PRE_TOOL_USE,
                tool_name=tool_name, input=tool_input,
                **self._extract_context_meta(context),
            ))

            yield ToolStartEvent(
                tool=tool_name, input=tool_input, tool_use_id=call["id"]
            )

            try:
                result_text, action_data = await self.executor.execute(
                    tool_name, tool_input, context
                )
                duration_ms = (time.monotonic() - start_ts) * 1000

                # 4b. PostToolUse Hook
                await self.hooks.emit(ToolHookContext(
                    event=HookEvent.POST_TOOL_USE,
                    tool_name=tool_name, input=tool_input,
                    output=result_text, duration_ms=duration_ms,
                    **self._extract_context_meta(context),
                ))

                thinking_steps.append({
                    "tool": tool_name,
                    "args_hint": self._extract_args_hint(tool_name, tool_input),
                    "summary": result_text[:120] if result_text else "",
                })
                yield ToolDoneEvent(
                    tool=tool_name,
                    summary=thinking_steps[-1]["summary"],
                    duration_ms=duration_ms,
                )
                if action_data:
                    final_action = action_data
                    yield ActionEvent(action_data=action_data)

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": call["id"],
                    "content": result_text,
                })

            except Exception as e:
                duration_ms = (time.monotonic() - start_ts) * 1000
                # 4c. ToolError Hook
                await self.hooks.emit(ToolHookContext(
                    event=HookEvent.TOOL_ERROR,
                    tool_name=tool_name, input=tool_input,
                    error=e, duration_ms=duration_ms,
                    **self._extract_context_meta(context),
                ))
                yield ToolErrorEvent(
                    tool=tool_name,
                    error=str(e),
                    duration_ms=duration_ms,
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": call["id"],
                    "content": f"Error: {e}",
                    "is_error": True,
                })

        # 5. 回填结果，进入下一轮
        current_messages.append({"role": "assistant", "content": text_chunks + tool_calls})
        current_messages.append({"role": "user",      "content": tool_results})
```

---

## 五、调用方改造

### 5.1 api/chat.py：流式端点（路径 A）

**改造前**（约 100 行逻辑散落在 `_chat_stream_generator`）：

```python
async def _chat_stream_generator(project_id, project, project_context, req):
    agent = agent_cls()
    # ... 80+ 行事件处理 + 保存逻辑
    async for ev in agent.chat_stream(...):
        if etype == "text_delta": ...
        elif etype == "tool_start": ...
        ...
        elif etype == "message_done":
            await _save_chat_message(...)
```

**改造后**（委托给 QueryEngine）：

```python
async def _chat_stream_generator(project_id, project, project_context, req):
    agent = agent_cls()
    system = await agent._build_system_prompt(project, project_context)
    tools = agent._exposed_tool_schemas(scope="project", traits=project_traits)
    executor = ChatToolExecutorAdapter(agent, project_id)

    engine = QueryEngine(
        llm_client=llm_client,
        tool_executor=executor,
        budget=Budget(max_turns=settings.CHAT_MAX_TURNS,
                      max_tokens=settings.CHAT_MAX_TOKENS),
        hooks=hook_registry,
    )

    full_text = ""
    async for event in engine.run(messages, system, tools, context):
        if isinstance(event, TextDeltaEvent):
            full_text += event.delta
            yield _sse("text_delta", {"delta": event.delta})

        elif isinstance(event, ToolStartEvent):
            label = _TOOL_LABELS_PY.get(event.tool, f"🔧 {event.tool}")
            yield _sse("tool_start", {"tool": event.tool, "label": label,
                                       "input": event.input})

        elif isinstance(event, ToolDoneEvent):
            yield _sse("tool_done", {"tool": event.tool, "summary": event.summary})

        elif isinstance(event, ActionEvent):
            yield _sse("action", event.action_data)

        elif isinstance(event, MessageDoneEvent):
            await _save_chat_message(project_id, "assistant", event.full_text,
                                     action=event.final_action, session_id=_sid,
                                     thinking=event.thinking_steps or None)
            yield _sse("message_done", {"rounds": event.rounds})
            return

        elif isinstance(event, BudgetExceededEvent):
            yield _sse("error", {"message": f"预算超限: {event.reason}"})
            return

        elif isinstance(event, ErrorEvent):
            yield _sse("error", {"message": event.message})
            return
```

### 5.2 Orchestrator：工单 Agent（路径 C）

**改造后**（工单 Agent 也可以用 tool_use 格式）：

```python
# backend/orchestrator.py
async def _run_agent_via_query_engine(self, agent, action_name, context):
    executor = OrchestratorToolExecutorAdapter(
        agent_actions=agent._actions,
        context=context,
    )
    engine = QueryEngine(
        llm_client=llm_client,
        tool_executor=executor,
        budget=Budget(
            max_turns=settings.AGENT_MAX_TURNS,
            max_tokens=settings.AGENT_MAX_TOKENS,
            max_seconds=settings.AGENT_MAX_SECONDS,
        ),
        hooks=hook_registry,
    )

    system = agent._build_agent_system_prompt(action_name, context)
    tools = agent.get_tool_schemas()
    messages = agent.build_messages(action_name, context)

    result = {}
    async for event in engine.run(messages, system, tools, context):
        if isinstance(event, MessageDoneEvent):
            result = {"status": "success", "full_text": event.full_text,
                      "thinking_steps": event.thinking_steps}
        elif isinstance(event, ToolDoneEvent):
            # 实时推送进度到前端（SSE event_manager）
            await event_manager.publish_to_project(
                context["project_id"], "agent_progress",
                {"tool": event.tool, "summary": event.summary}
            )
        elif isinstance(event, BudgetExceededEvent):
            result = {"status": "budget_exceeded", "reason": event.reason}

    return result
```

---

## 六、文件结构

```
backend/
└── query_engine/              ← 新建目录
    ├── __init__.py
    ├── engine.py              ← QueryEngine 主类
    ├── events.py              ← QueryEvent 类型定义
    ├── budget.py              ← Budget 数据类
    ├── executor.py            ← ToolExecutorProtocol + 适配器
    └── README.md              ← 模块说明
```

---

## 七、实施步骤

```
Day 1：搭框架
  ├─► 创建 backend/query_engine/ 目录结构
  ├─► 实现 Budget / QueryEvent / ToolExecutorProtocol
  └─► 实现 QueryEngine.run() 主循环（不带 Hooks）

Day 2：接 ChatAssistant（路径 A）
  ├─► 实现 ChatToolExecutorAdapter
  ├─► 改造 _chat_stream_generator 委托给 QueryEngine
  └─► 运行测试，验证流式输出一致性

Day 3：接 Orchestrator（路径 C）
  ├─► 实现 OrchestratorToolExecutorAdapter
  ├─► 改造 _react_with_think_inner 或增量接入 QueryEngine
  └─► 验证工单执行不回归

Day 4：接 Pre/Post Hooks
  ├─► 引入 HookRegistry（与 Hooks Phase 联动）
  ├─► 内置 audit_log_hook + shell_rate_limit_hook
  └─► 验证 Hook 事件正常触发

Day 5：收尾 + 测试
  ├─► 清理 api/chat.py 冗余代码
  ├─► 补全单测（Budget 超限、工具调用失败等场景）
  └─► 文档更新
```

---

## 八、风险与兜底

| 风险 | 概率 | 缓解方案 |
|------|------|---------|
| Orchestrator Agent 改造引起工单执行回归 | 中 | 增量接入：新路径作为可选，旧路径保留 flag 回退 |
| ChatAssistant 流式输出格式变化 | 低 | 事件字段保持向后兼容，前端不需改动 |
| Hook 执行抛错影响主流程 | 低 | HookRegistry.emit() 内部 try/except，fail-open |
| Budget 参数设置不当导致截断 | 中 | 默认值设为当前实际用量的 2 倍，开放 .env 配置 |

---

## 九、成功指标

- `api/chat.py` 行数从 2140 行减少到 ≤ 900 行
- 三条 LLM 调用路径统一使用 QueryEngine
- 所有工具调用有 PreToolUse + PostToolUse Hook 触发点
- 预算约束在 Chat 和 Orchestrator 两侧均生效
- 现有功能回归测试 100% 通过
