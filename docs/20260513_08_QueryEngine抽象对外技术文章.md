# 从三条分叉路到一个统一引擎：AI 开发系统的 QueryEngine 重构之路

> 作者：AI Dev System 团队  
> 发布日期：2026-05-13  
> 标签：架构设计 · LLM 工程 · 重构实践

---

## 引言

当你把 AI 能力嵌入一个复杂业务系统，总有那么一天，你会发现同一件事被写了三遍。

这是我们在构建 AI 自动化开发系统（ADS）时遇到的真实困境。系统运行了将近一年，积累了超过 10 个 AI Agent，支撑着从需求拆解到代码部署的完整工作流。然而随着功能增长，我们越来越清晰地看到一个隐患：**每当 AI 需要调用工具，系统里有三条完全独立的路径在做同一件事——而且做法各不相同。**

这篇文章记录了我们识别这一问题、设计解决方案的全过程，以及背后的架构思考。

---

## 一、问题是怎么发生的？

### 从一个功能，到三套实现

最初，系统只有一条路径：用户在聊天面板发送消息，AI 响应。随着需求增长，新的调用场景不断加入：

- **需要流式输出**，于是写了一个生成器函数，专门处理 SSE 流
- **需要在后台执行工单**，于是 Orchestrator 有了自己的 Agent 调度循环
- **需要降级处理**，于是又保留了一条同步的非流式路径作为兜底

每一次扩展都很合理，每一次都是当时的最优解。但积累到今天，就变成了这样：

```
用户发消息 (流式)        用户发消息 (降级)       后台工单执行
      │                       │                      │
      ▼                       ▼                      ▼
_chat_stream_generator    _chat_via_agent       _react_with_think
      │                       │                      │
      ▼                       ▼                      ▼
chat_with_tools_stream    chat_with_tools        llm_client.chat
  （流式工具循环）          （同步工具循环）      （文本选择 Action）
      │                       │                      │
      ▼                       ▼                      ▼
   保存消息               保存消息               执行 Action
  （各自实现）            （各自实现）            （无保存逻辑）
```

三条路径，三套循环逻辑，三种消息格式处理方式。更关键的是：**任何横切关注点——预算限制、审计日志、限流控制——都需要在三个地方各自实现一遍，或者干脆就没有。**

### 一个文件承担了太多

查看核心文件的行数，数字说明了一切：

```
api/chat.py          2140 行
agents/base.py        280 行（REACT 循环与 Agent 基类混杂）
agents/chat_assistant.py  800+ 行（流式循环内嵌于 Agent 方法）
```

`api/chat.py` 这个文件负责了几乎所有事情：HTTP 请求解析、LLM 调用、工具循环、消息持久化、SSE 格式化，还要同时处理项目内和全局两套场景。它是系统中最难修改的文件，因为任何改动都可能牵一发而动全身。

### 代价在哪里？

这个架构问题不是纸面上的，它直接影响了系统能力：

**1. 无法统一执行预算约束**  
流式聊天通过 `max_react_loop=6` 限制轮数，工单 Agent 通过另一个 `max_react_loop` 参数控制，两者的逻辑无法共享，更没有统一的 Token 消耗上限。在工具调用密集的场景下，一次任务可能消耗大量 API 调用，系统对此没有任何防控。

**2. 没有工具调用的拦截点**  
如果想在每次工具调用前记录审计日志、在 Shell 工具调用过多时触发限流、在工具报错时自动写入失败案例库——这些需求在当前架构下要么改遍所有路径，要么完全无法实现。工具执行就像一个黑盒：进去，出来，没有钩子。

**3. Orchestrator Agent 被 LLM 能力隔离**  
工单 Agent 的工具调用使用的是 `llm_client.chat()` + 文本解析的老方式——LLM 输出 `"write_code"` 这样的文本，代码解析后调用对应的 Action。这套"文本协议"无法享受 Anthropic 原生工具调用（`tool_use`）带来的精确性和可靠性，也无法向前端推送实时进度。

---

## 二、解法：让所有路径汇聚到一个引擎

### 找到问题的本质

三条路径之所以能独立存在，是因为它们各自把"调用 LLM"和"执行工具"的逻辑内嵌在了自己里面。解法是把这个共同逻辑提取出来，变成一个独立的、可复用的模块。

我们把它叫做 **QueryEngine**。

类比来说，如果说 LLM 是发动机，工具是变速箱，那么 QueryEngine 就是整个传动系统——它知道发动机什么时候该输出、变速箱什么时候该换挡，以及整套系统的运转要保持在哪个功率范围内。

### QueryEngine 的职责边界

**它负责**：
- 管理"LLM → 工具调用 → 结果回填 → 继续生成"这个循环
- 在循环中执行预算检查（Token / 轮次 / 时间）
- 在每次工具执行前后触发 Pre/Post Hooks
- 将来自 LLM 的原始事件规范化为统一的事件类型

**它不负责**：
- HTTP 层（那是 `api/chat.py` 的事）
- 消息该不该持久化、怎么持久化（调用方决定）
- Agent 的系统提示词怎么写（Agent 自己构建）
- 工具怎么执行（通过协议接口注入，不绑定具体实现）

这种"只做好一件事"的设计，让 QueryEngine 可以被任何场景复用。

### 统一的事件模型

QueryEngine 的对外接口是一个异步生成器，产出规范化的事件：

```python
async for event in engine.run(messages, system, tools, context):
    if isinstance(event, TextDeltaEvent):
        # 文本流 delta，转发给前端
    elif isinstance(event, ToolStartEvent):
        # 工具开始执行，记录或推送进度
    elif isinstance(event, ToolDoneEvent):
        # 工具执行完成，收集思考步骤
    elif isinstance(event, MessageDoneEvent):
        # 本轮对话结束，保存消息到数据库
    elif isinstance(event, BudgetExceededEvent):
        # 预算超限，安全中断
```

调用方不再需要理解循环的内部逻辑，只需要响应感兴趣的事件。对于 HTTP 流式接口，它把 `TextDeltaEvent` 转发给前端；对于 Orchestrator，它把 `ToolDoneEvent` 推送到实时进度面板。**同一个引擎，不同的消费方式。**

---

## 三、解耦工具执行：协议而非实现

QueryEngine 不直接调用 Action 类，而是通过 `ToolExecutorProtocol` 接口交互：

```python
class ToolExecutorProtocol(Protocol):
    async def execute(
        self,
        tool_name: str,
        tool_input: dict,
        context: dict,
    ) -> tuple[str, dict | None]:
        """
        返回 (result_text, action_data)
        action_data 非空时表示需要前端渲染交互卡片
        """
```

这样设计的好处是：QueryEngine 本身不知道工具是 Python Action、外部 API 还是 MCP 服务，它只知道调用协议。

两个适配器桥接了现有代码：

```
ChatToolExecutorAdapter
  └─► 包装现有的 _ChatToolExecutor（已有 38+ 个 Chat Action）

OrchestratorToolExecutorAdapter
  └─► 包装 Agent._actions（工单 Agent 的 Action 集合）
```

这种分层使得未来接入新的执行环境（比如沙箱执行、远程工具调用）时，只需要写一个新的适配器，不需要改动 QueryEngine 核心。

---

## 四、预算机制：防止失控的安全阀

没有预算约束的 AI 系统，是在悬崖边行走。工具调用循环理论上可以无限执行——LLM 不断请求工具，工具返回结果，LLM 继续请求——直到 API 配额耗尽或程序崩溃。

Budget 类为这个循环设置了三重上限：

```
Token 预算：本次交互消耗的总 Token 数
轮次预算：工具调用的最大轮数
时间预算：整个执行过程的最长时间
```

当任意一个上限触发，QueryEngine 产出 `BudgetExceededEvent` 并安全终止。调用方可以选择将超限信息告知用户，或者静默记录日志。

不同场景使用不同预算配置，通过环境变量暴露：

| 场景 | Token 上限 | 轮次上限 | 时间上限 |
|------|-----------|---------|---------|
| 用户聊天 | 100,000 | 30 | 180s |
| 工单 Agent | 200,000 | 50 | 600s |
| 快速工具调用 | 20,000 | 5 | 30s |

---

## 五、Hooks：横切关注点的统一入口

有了 QueryEngine 作为统一路径，我们终于有了一个地方来放横切关注点。

每次工具调用前后，QueryEngine 都会触发 Hook 事件：

```
PreToolUse  →  工具执行  →  PostToolUse
                  │
                  └─► 异常时触发 ToolError
```

注册一个审计日志 Hook：

```python
async def audit_log_hook(ctx: ToolHookContext):
    if ctx.event == HookEvent.POST_TOOL_USE:
        await db.execute(
            "INSERT INTO tool_audit_log (tool_name, project_id, duration_ms, success) "
            "VALUES (?, ?, ?, ?)",
            (ctx.tool_name, ctx.project_id, ctx.duration_ms, ctx.error is None)
        )
```

注册一个 Shell 防滥用 Hook：

```python
async def shell_rate_limit_hook(ctx: ToolHookContext):
    if ctx.event == HookEvent.PRE_TOOL_USE and ctx.tool_name == "ShellAction":
        count = _increment_and_get(ctx.ticket_id)
        if count > 50:
            raise RuntimeError(f"Shell call limit exceeded")
```

两个 Hook，一行注册，全局生效。以前需要修改三处代码的事情，现在只需要写一次。

这套 Hook 机制在设计上参考了 Claude Code 的 `settings.json` 配置格式，未来可以做到配置化——用户无需修改代码，直接在配置文件中声明 Hook 脚本。

---

## 六、改造效果：聚焦看 api/chat.py

最直观的变化发生在 `api/chat.py`。

**改造前**，`_chat_stream_generator` 函数承担了一切：它既要管理 Agent 的创建和初始化，又要解析每一种 SSE 事件类型，还要在最后负责把消息写入数据库。这个函数约 100 行，逻辑紧密耦合，很难单独测试。

**改造后**，这个函数变成了一个薄薄的适配层：

```python
async def _chat_stream_generator(project_id, project, project_context, req):
    # 创建引擎
    engine = QueryEngine(llm_client, executor, budget, hooks)

    # 消费事件，各自处理
    async for event in engine.run(messages, system, tools, context):
        match event:
            case TextDeltaEvent(delta=d):
                yield _sse("text_delta", {"delta": d})
            case ToolStartEvent(tool=t, input=inp):
                yield _sse("tool_start", {"tool": t, "input": inp})
            case MessageDoneEvent() as done:
                await _save_chat_message(..., thinking=done.thinking_steps)
                yield _sse("message_done", {"rounds": done.rounds})
                return
```

函数从 100 行缩减到约 30 行，逻辑清晰，每种事件的处理一目了然。

`api/chat.py` 整体从 2140 行缩减到预计 900 行以内，减少了 **57%** 的代码量。

---

## 七、Orchestrator 获得了什么？

对工单执行引擎来说，这次重构带来的不只是代码整洁，而是**能力升级**。

**改造前**，工单 Agent 使用"文本协议"——LLM 输出选择的 Action 名称，代码解析执行。这种方式依赖 LLM 的文本格式服从性，而且无法利用 Anthropic 提供的结构化工具调用能力。

**改造后**，工单 Agent 通过 QueryEngine 使用原生 `tool_use` 格式，LLM 直接输出结构化的工具调用请求，不再依赖文本解析。与此同时：

- 工单执行的每一步工具调用都会触发 Hooks，审计日志自动记录
- 预算约束统一生效，不再担心某个工单无限消耗 API 调用
- 每次工具完成都会推送进度到前端，用户可以实时看到 AI 在做什么

---

## 八、更大的图景

QueryEngine 不是一个孤立的重构，它是我们向"Harness 架构"演进的关键一步。

Harness（执行框架）思想的核心是：**AI 模型不直接拥有能力，它只能"请求"执行工具；是否真正执行，由框架根据声明、规则和策略共同决定。**

Claude Code（Anthropic 官方 CLI）是这一思想的完整实现：QueryEngine 作为唯一入口，三层权限决策系统，Hooks 作为生命周期拦截点，预算约束防止失控。

ADS 目前处于这条路的中途。QueryEngine 的完成，让我们从 58% 向 80% 迈进一步。接下来还有：异步权限审批系统（高风险操作需要人工确认）、子任务派发（Agent 在执行中动态创建子任务）。

---

## 结语

架构问题往往不是在某一刻突然出现的，而是在功能增长中悄悄积累，直到某一天维护成本开始可感知地上升。

回顾这次重构，解法其实并不复杂：找到重复的核心逻辑，为它建立清晰的边界，通过协议而非实现来连接不同的使用方。**复杂性没有消失，只是被放到了最合适的地方。**

QueryEngine 会是我们写的最后一个 LLM 调用包装器。以后再有新的 AI 交互场景，直接实例化一个新的 Engine，告诉它用什么工具、有多少预算、需要哪些 Hooks——剩下的事，它来做。

---

*AI Dev System 是一个持续演进的项目。如果你对 AI 辅助软件开发感兴趣，欢迎参考 [GitHub 仓库](https://github.com/welflau/ai-dev-system)。*
