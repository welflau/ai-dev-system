# 从三条分叉路到一个统一引擎：AI 开发系统的 QueryEngine 重构之路

> 作者：AI Dev System 团队  
> 发布日期：2026-05-13  
> 标签：架构设计 · LLM 工程 · 重构实践

---

## 引言

想象一家餐厅，厨房里有三个炉灶，每个炉灶都有自己的火候控制方式、自己的计时器、自己的收尾流程。每次出新菜品，三个炉灶都得各自改造一遍。

这大概是我们在构建 AI 自动化开发系统（ADS）时某个阶段的真实写照。系统运行了将近一年，积累了超过 10 个 AI Agent，支撑着从需求拆解到代码部署的完整工作流。然而随着功能增长，我们越来越清晰地看到一个隐患：**每当 AI 需要调用工具，系统里有三条完全独立的路径在做同一件事——而且做法各不相同。**

这篇文章记录了我们识别这一问题、设计解决方案的全过程，以及背后的架构思考。

---

## 一、问题是怎么发生的？

### 像城市道路一样蔓延的代码

最初，系统只有一条路径：用户在聊天面板发送消息，AI 响应。就像一座小城，最开始只有一条主干道，足够了。

然后需求增长了：
- **需要流式输出**，于是修了一条快速路，专门处理 SSE 流
- **需要在后台执行工单**，于是 Orchestrator 有了自己的内部环路
- **需要降级处理**，于是又保留了原来那条老路作为备用

每一条新路的修建都很合理，每一次都是当时的最优解。但当你俯瞰整张地图，就变成了这样：

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

三条互不相交的路，三套循环逻辑，三种消息格式处理方式。

更麻烦的是：如果你想在**每条路上都装一个红绿灯**——比如限速（预算约束）、监控摄像头（审计日志）、超载预警（限流控制）——你得在三个地方分别施工。漏装一处，就是盲区。

### 一栋楼里住了三家人

查看核心文件的行数，数字说明了一切：

```
api/chat.py          2140 行
agents/base.py        280 行（REACT 循环与 Agent 基类混杂）
agents/chat_assistant.py  800+ 行（流式循环内嵌于 Agent 方法）
```

`api/chat.py` 就像一栋被改造过太多次的老楼——最初只有两室一厅，后来加建了卧室、改造了走廊、隔出了仓库。现在想在这栋楼里换一根水管，你得担心会不会震动到隔壁刚砌好的墙。

它现在负责的事情有：HTTP 请求解析、LLM 调用、工具循环、消息持久化、SSE 格式化，同时还要处理项目内和全局两套场景。任何改动都可能牵一发而动全身。

### 代价是什么？

这些架构问题不是纸面上的警告，它们实实在在地限制了系统能力：

**1. 预算约束：三条路，三把尺**

流式聊天用 `max_react_loop=6` 限制轮数，工单 Agent 用另一个同名参数，两者像是用不同刻度的尺子量同一件事——表面上都有约束，但无法形成统一的防护网。更严重的是，没有任何路径有 Token 消耗上限。在工具调用密集的场景下，一次任务可能像开着水龙头忘了关——直到账单来了才知道流了多少。

**2. 没有拦截点：工具是个黑盒**

想象邮差送信：信件进门、出门，中间发生了什么无从得知。我们的工具调用也是这样——`action.run(context)` 进去，结果出来，中间没有任何地方可以插入逻辑。

想在每次文件写入前记录操作日志？想在 Shell 工具被调用 50 次后触发告警？想在工具报错时自动归档到失败案例库？——当前架构的答案只有两个：改遍三条路，或者放弃。

**3. 工单 Agent 被锁在过去**

工单 Agent 至今还在用一种上古方式和 LLM 沟通——让 LLM 输出纯文本 `"write_code"`，再用代码解析这个字符串来决定调用哪个 Action。

这就像用信鸽传递命令，然后人工翻译信件。Anthropic 早就提供了更可靠的结构化工具调用（`tool_use`），但工单 Agent 因为架构原因，一直没能用上这条高速公路。结果是：解析容易出错，无法推送实时进度，和 Chat 助手的能力差距越来越大。

---

## 二、解法：让所有路径汇聚到一个引擎

### 找到共同的核心

三条路虽然外表不同，但它们做的核心事情是一样的：

> **1.** 把消息发给 LLM  
> **2.** LLM 说"我需要调用某个工具"  
> **3.** 执行那个工具  
> **4.** 把结果告诉 LLM  
> **5.** LLM 继续生成，直到它说"我说完了"  

这是一个循环。三条路都在做这个循环，只是包装方式不同。

解法是：把这个循环提取出来，做成一个独立的模块，让三条路都来用它——就像三条公路共用一套交通管理系统，而不是各自发明信号灯。

我们把它叫做 **QueryEngine**。

### 一个恰当的类比

如果把整个 AI 系统比作一辆汽车：

- **LLM** 是发动机——提供原始的思考能力和驱动力
- **工具（Actions）** 是各种功能部件——转向、刹车、车窗
- **QueryEngine** 是传动系统和仪表盘的结合体——它决定发动机的输出什么时候该传递给哪个部件、整个系统的运行是否在安全参数范围内，以及当某个部件出问题时如何响应

以前，三条路各自有一套简陋的传动装置，彼此不兼容。现在，统一换成一套标准件。

### QueryEngine 的职责边界

好的设计首先要知道"不做什么"。

**QueryEngine 负责**：
- 管理"LLM → 工具调用 → 结果回填 → 继续生成"这个循环
- 在循环中执行预算检查（Token / 轮次 / 时间）
- 在每次工具执行前后触发 Pre/Post Hooks
- 将来自 LLM 的原始事件规范化为统一格式输出

**QueryEngine 不负责**：
- HTTP 层（那是路由层的事）
- 消息要不要持久化、存到哪里（调用方决定）
- Agent 的系统提示词（Agent 自己知道该说什么）
- 工具内部怎么执行（通过接口注入，不绑定具体实现）

这种设计让 QueryEngine 像一个标准化的插座——它不关心你接的是手机充电器还是台灯，只要符合接口规格，都能工作。

### 统一的事件语言

QueryEngine 对外"说话"的方式是一个异步事件流，就像广播电台——它持续播报正在发生的事情，收听方各取所需：

```python
async for event in engine.run(messages, system, tools, context):
    if isinstance(event, TextDeltaEvent):
        # "AI 正在说话，这是第 N 个字"→ 转发给前端显示
    elif isinstance(event, ToolStartEvent):
        # "AI 刚刚拿起了某个工具"→ 推送进度面板
    elif isinstance(event, ToolDoneEvent):
        # "工具用完了，结果是这样的"→ 收集思考步骤
    elif isinstance(event, MessageDoneEvent):
        # "这轮对话结束了"→ 保存到数据库
    elif isinstance(event, BudgetExceededEvent):
        # "超支了，停下来"→ 安全中断，通知用户
```

HTTP 流式接口听到 `TextDeltaEvent` 就往前端转发；Orchestrator 听到 `ToolDoneEvent` 就更新工单进度；单测环境收集所有事件做断言。**同一台广播机，不同的收听者，各取所需。**

---

## 三、解耦工具执行：插座与插头

QueryEngine 不直接调用具体的 Action 类，而是通过一个"插头规格"（协议接口）来交互：

```python
class ToolExecutorProtocol(Protocol):
    async def execute(tool_name, tool_input, context) -> (result_text, action_data):
        """
        只要符合这个接口，QueryEngine 不关心工具是 Python Action、
        外部 API 调用还是 MCP 服务。
        """
```

这就像家里的插座——它不关心你接的是国产品牌还是进口品牌，只要插头形状符合规格就能用。QueryEngine 定义了"插座形状"，现有的工具通过适配器转换成对应的"插头"：

```
ChatToolExecutorAdapter       ← 聊天助手的 38+ 个工具适配成统一插头
OrchestratorToolExecutorAdapter  ← 工单 Agent 的工具适配成统一插头
（未来）SandboxToolExecutorAdapter  ← 沙箱执行环境只需新写一个适配器
```

---

## 四、预算机制：给 AI 装一块油表

没有预算约束的 AI 调用循环，就像一辆没有油表的车——你知道它会跑，但不知道什么时候会在高速公路上抛锚。

工具调用循环理论上可以无限进行：LLM 请求工具，工具返回结果，LLM 继续请求工具……直到 API 配额耗尽或程序崩溃。我们见过开发者调试时忘了中断，一个任务跑了 200 轮工具调用，账单让人心跳加速。

Budget 类就是那块油表，同时监控三个指标：

```
Token 预算：总燃油量（API 调用的核心成本）
轮次预算：换挡次数上限（防止无意义的反复调用）
时间预算：行驶时间上限（防止某个工具阻塞整个循环）
```

任意一个指标触线，QueryEngine 产出 `BudgetExceededEvent`，优雅停车。不同场景的"油箱容量"不同：

| 场景 | 类比 | Token 上限 | 轮次上限 | 时间上限 |
|------|------|-----------|---------|---------|
| 用户聊天 | 城市代驾 | 100,000 | 30 | 180s |
| 工单 Agent | 长途货运 | 200,000 | 50 | 600s |
| 快速工具调用 | 附近取件 | 20,000 | 5 | 30s |

---

## 五、Hooks：给每个路口装上摄像头

统一了道路，现在终于可以统一安装交通设施了。

每次工具调用，QueryEngine 都会在两个时间点发出信号：

```
工具调用开始 (PreToolUse) → 工具执行中 → 工具调用完成 (PostToolUse)
                                │
                                └─► 出错时：ToolError
```

任何人都可以"订阅"这些信号，在不改动工具本身的情况下注入逻辑：

**审计摄像头**：记录每次工具调用的时间、成败、耗时，存入数据库——无论哪个 Agent 调用了什么工具，一览无余。

```python
async def audit_log_hook(ctx: ToolHookContext):
    if ctx.event == HookEvent.POST_TOOL_USE:
        await db.execute(
            "INSERT INTO tool_audit_log (tool_name, duration_ms, success) "
            "VALUES (?, ?, ?)",
            (ctx.tool_name, ctx.duration_ms, ctx.error is None)
        )
```

**超载预警**：Shell 工具被某个工单调用超过 50 次，自动触发告警并中断——就像货车轴重超限自动拦截。

```python
async def shell_rate_limit_hook(ctx: ToolHookContext):
    if ctx.event == HookEvent.PRE_TOOL_USE and ctx.tool_name == "ShellAction":
        if _get_call_count(ctx.ticket_id) > 50:
            raise RuntimeError("Shell call limit exceeded")
```

两个 Hook，注册一次，三条路全覆盖。以前要在三个地方各贴一张告示牌，现在一块指示牌立在路口就够了。

---

## 六、改造前后的对比

### api/chat.py：从多功能瑞士军刀到专注的薄层

**改造前**，核心的流式处理函数像一个什么都能做但也什么都不精的瑞士军刀：初始化 Agent、逐个解析 SSE 事件类型、在函数末尾负责数据库写入。约 100 行紧密耦合的逻辑，牵一发而动全身。

**改造后**，同一个函数变成了一个薄薄的翻译层——把 QueryEngine 的标准事件翻译成 HTTP 需要的 SSE 格式：

```python
async def _chat_stream_generator(project_id, project, project_context, req):
    engine = QueryEngine(llm_client, executor, budget, hooks)

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

函数从 100 行缩减到约 30 行。整个 `api/chat.py` 从 2140 行缩减至约 900 行，减少 **57%**——不是删除了功能，而是把功能放回了它该在的地方。

### Orchestrator：从骑马到开汽车

工单 Agent 的变化更本质。

**改造前**，工单 Agent 和 LLM 的沟通方式像用信鸽传命令：让 LLM 写下 `"write_code"` 这几个字，系统读到字符串再去找对应的 Action 执行。这套"鸽信协议"在文字识别上容易出错，也无法把 LLM 最新的 `tool_use` 结构化能力发挥出来。

**改造后**，工单 Agent 通过 QueryEngine 直接使用 Anthropic 原生 `tool_use` 格式——LLM 精确输出结构化的工具调用请求，系统直接执行，不再依赖文字解析。同时：

- 每步工具调用自动触发 Hooks，审计日志无需额外编码
- 预算约束生效，杜绝失控场景
- 每次工具完成都推送进度到前端，用户实时可见 AI 在做什么

---

## 七、更大的图景：向 Harness 架构演进

QueryEngine 不是一次孤立的代码整理，它是我们向更安全、更可控的 AI 执行架构迈出的一步。

一个成熟的 AI 系统，应该像一套驾马用的"挽具"（Harness）——不是限制马的力量，而是让这股力量变得**可驾驭、可引导、可审计**。Anthropic 官方 CLI（Claude Code）把这套思想实现得很完整：QueryEngine 是唯一入口，三层权限决策，Hooks 是生命周期拦截点，预算约束防止失控。

我们的系统目前走了大约 58% 的路。QueryEngine 完成后，这个数字将提升到约 80%。剩下的旅程还包括：为高风险操作（删文件、强制推送）建立异步人工审批通道，以及让 Agent 在执行过程中能动态创建子任务——但那是另外的故事了。

---

## 结语

架构腐化从来不是一夜之间发生的，它是一百次合理决策叠加的结果。每一条新路的修建都有充分的理由，每一个新功能的嵌入都是当时的最优解。直到有一天，你站在整张地图前，发现城市已经堵成了一团。

重构的本质，不是消灭复杂性，而是让复杂性**各归其位**——把循环逻辑放回循环应该在的地方，把横切关注点放进统一的拦截层，把职责边界画得清晰可见。

QueryEngine 会是我们最后一次重写 LLM 调用循环。以后再有新的 AI 交互场景，直接实例化一个 Engine，告诉它用什么工具、有多少预算、需要哪些 Hooks——剩下的事，让引擎来做。

---

*AI Dev System 是一个持续演进的开源项目。如果你对 AI 辅助软件开发的工程实践感兴趣，欢迎参考 [GitHub 仓库](https://github.com/welflau/ai-dev-system)。*
