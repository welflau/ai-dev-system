# ChatAssistant 流式输出方案

> 日期：2026-05-09
> 状态：待开发
> 预计工作量：1.5 天

---

## 1. 现状与问题

### 当前回复流程

```
用户发消息
  → POST /api/projects/{id}/chat（HTTP 请求）
  → ChatAssistantAgent.chat()
      → chat_with_tools()（ReAct 循环）
          → _call_anthropic_tools()（等待全部 token 生成完）
          → 工具执行（若有）
          → 再次 _call_anthropic_tools()（等待）
          → ...
      → 返回完整回复字符串
  → HTTP 响应（一次性返回全部内容）
  → 前端一次性渲染
```

**问题**：对于长回复（代码示例、分析报告），用户等待数秒后内容才全部出现，体验差。LLM 实际上是 token-by-token 生成的，只是后端没有把这个过程传递给前端。

---

## 2. 目标架构

```
用户发消息
  → POST /api/projects/{id}/chat/stream（HTTP，返回 text/event-stream）
  → 后端边生成边推 SSE 事件：
      event: text_delta    {"delta": "不"}
      event: text_delta    {"delta": "一"}
      event: tool_start    {"tool": "git_log", "label": "📜 查提交历史", "args_hint": "(branch: main)"}
      event: tool_done     {"tool": "git_log", "summary": "最近 10 条提交: de0b18f..."}
      event: text_delta    {"delta": "根"}
      event: text_delta    {"delta": "据"}
      ...
      event: action        {"type": "confirm_requirement", "title": "...", ...}
      event: message_done  {"thinking_steps": [...], "session_id": "..."}
  → 前端 ReadableStream 接收，逐字追加到气泡
```

---

## 3. SSE 事件协议

| 事件名 | 数据结构 | 说明 |
|--------|----------|------|
| `text_delta` | `{"delta": "字符串"}` | LLM 生成的文本片段（1-4字符） |
| `tool_start` | `{"tool": "name", "label": "显示名", "args_hint": "..."}` | 开始调用工具（同时更新思考面板） |
| `tool_done` | `{"tool": "name", "summary": "..."}` | 工具调用完成 |
| `action` | `{type, title, ...}` | 需要渲染的 action 卡片（confirm_requirement 等） |
| `error` | `{"message": "..."}` | 出错 |
| `message_done` | `{"thinking_steps": [...], "session_id": "..."}` | 本轮对话完成，含完整思考步骤 |

> 思考面板事件（`tool_start`/`tool_done`）与现有 `chat_thinking_log` SSE 合并，
> 不再需要单独的思考日志频道。

---

## 4. 后端实现

### 4.1 `llm_client.py` — 新增 `_call_anthropic_tools_stream()`

```python
async def _call_anthropic_tools_stream(
    self, messages, tools, system, temperature, max_tokens
) -> AsyncGenerator[dict, None]:
    """
    流式 Anthropic tool_use 调用。
    yield 事件类型：
      {"type": "text_delta", "delta": "..."}
      {"type": "tool_use_block", "id": "...", "name": "...", "input": {...}}
      {"type": "stop", "stop_reason": "end_turn" | "tool_use", "usage": {...}}
    """
    payload = {..., "stream": True}
    async with httpx.AsyncClient(timeout=self.timeout) as client:
        async with client.stream("POST", url, headers=..., json=payload) as resp:
            async for line in resp.aiter_lines():
                if not line.startswith("data: "): continue
                event = json.loads(line[6:])
                etype = event.get("type")

                if etype == "content_block_delta":
                    delta = event["delta"]
                    if delta["type"] == "text_delta":
                        yield {"type": "text_delta", "delta": delta["text"]}
                    elif delta["type"] == "input_json_delta":
                        # tool input 累积（不 yield，等 content_block_stop 拼完）
                        ...

                elif etype == "content_block_stop":
                    # tool_use block 结束，yield 完整 tool 调用
                    if current_block and current_block["type"] == "tool_use":
                        yield {"type": "tool_use_block", ...}

                elif etype == "message_delta":
                    yield {"type": "stop",
                           "stop_reason": event["delta"].get("stop_reason"),
                           "usage": event.get("usage", {})}
```

### 4.2 `llm_client.py` — 新增 `chat_with_tools_stream()`

```python
async def chat_with_tools_stream(
    self, messages, tools, tool_executor, system, ...
) -> AsyncGenerator[dict, None]:
    """
    带工具的 ReAct 流式循环。
    yield 同一套事件类型，工具调用时暂停文本流，执行后继续。
    """
    history = list(messages)
    for round_no in range(max_rounds):
        current_text = ""
        tool_calls = []

        async for event in self._call_anthropic_tools_stream(history, tools, system, ...):
            if event["type"] == "text_delta":
                current_text += event["delta"]
                yield event  # 直接推给前端

            elif event["type"] == "tool_use_block":
                tool_calls.append(event)
                # 推 tool_start 事件（思考面板）
                yield {"type": "tool_start", "tool": event["name"], ...}
                # 执行工具
                result = await tool_executor.execute(event["name"], event["input"])
                yield {"type": "tool_done", "tool": event["name"], "summary": ...}

            elif event["type"] == "stop":
                if event["stop_reason"] == "end_turn":
                    return  # 对话结束
                # tool_use：继续下一轮
                history = _append_tool_results(history, current_text, tool_calls, results)
                break
```

### 4.3 `api/chat.py` — 新增流式端点

```python
@router.post("/stream")
async def chat_stream(project_id: str, req: ChatRequest):
    """流式聊天端点，返回 text/event-stream"""

    async def generate():
        executor = _ChatToolExecutor(agent, project_id)
        full_text = ""
        thinking_steps = []

        async for event in llm_client.chat_with_tools_stream(..., tool_executor=executor):
            yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
            if event["type"] == "text_delta":
                full_text += event["delta"]

        # 流结束后保存消息
        thinking_steps = executor.thinking_steps
        await _save_chat_message(project_id, "assistant", full_text,
                                 action=executor.primary_action_result,
                                 thinking=thinking_steps, session_id=...)
        yield f"event: message_done\ndata: {json.dumps({'thinking_steps': thinking_steps})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"X-Accel-Buffering": "no"})
```

### 4.4 ChatAssistant action 卡片处理

工具调用结果里 `type=confirm_requirement` 等卡片通过 `action` 事件推出：

```python
# tool_done 之后，检查 executor.primary_action_result
if executor.primary_action_result:
    yield {"type": "action", **executor.primary_action_result}
```

---

## 5. 前端实现

### 5.1 `sendChatMessage()` 改用 `fetch` + `ReadableStream`

```javascript
async function sendChatMessage() {
    // ...原有准备逻辑...

    // 创建空气泡，准备逐字填入
    const bubbleEl = appendChatBubble('assistant', '', null, null, [], [], []);
    const bubbleContent = bubbleEl.querySelector('.chat-msg-bubble');
    _chatThinkingBegin();

    let fullText = '';
    const url = `/api/projects/${currentProjectId}/chat/stream`;
    const resp = await fetch(url, { method: 'POST', body: JSON.stringify(payload), ... });

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();  // 未完成的行留在 buffer

        let eventName = '';
        for (const line of lines) {
            if (line.startsWith('event: ')) { eventName = line.slice(7); continue; }
            if (!line.startsWith('data: ')) continue;
            const data = JSON.parse(line.slice(6));

            if (eventName === 'text_delta') {
                fullText += data.delta;
                bubbleContent.innerHTML = formatChatContent(fullText);
                scrollChatToBottom();

            } else if (eventName === 'tool_start') {
                _chatThinkingAppend({ step: 'start', tool: data.tool, args_hint: data.args_hint });

            } else if (eventName === 'tool_done') {
                _chatThinkingAppend({ step: 'done', tool: data.tool, summary: data.summary });

            } else if (eventName === 'action') {
                renderActionCard(bubbleEl, data);

            } else if (eventName === 'message_done') {
                _chatThinkingFinish(data.thinking_steps?.length || 0);
                chatHistory.push({ role: 'assistant', content: fullText });
            }
        }
    }
}
```

### 5.2 兼容性

- 流式端点失败时自动 fallback 到原 `/chat` 非流式端点
- 全局聊天（无 project_id）同样添加 `/api/chat/stream` 端点
- 工单 AI 对话（DevAgent 等）继续走非流式（对话内容复杂，流式收益有限）

---

## 6. Markdown 渲染问题

流式输出时，`formatChatContent(fullText)` 每次 delta 都重新解析 Markdown，可能有性能问题。

**方案**：
- 文字阶段：直接 `textContent` 追加，不解析 Markdown（快）
- `message_done` 收到后：对完整文本执行一次完整 Markdown 渲染（准确）
- 代码块 / 表格 在 `message_done` 后才渲染（防止不完整语法闪烁）

---

## 7. Phase 拆分

| Phase | 内容 | 估时 |
|-------|------|------|
| 1 | `_call_anthropic_tools_stream()` + `chat_with_tools_stream()` in llm_client | 0.5 天 |
| 2 | 流式 API 端点 `/chat/stream` + ChatAssistant 接入 | 0.5 天 |
| 3 | 前端 ReadableStream 接收 + 逐字渲染 + Markdown 延迟渲染 | 0.5 天 |

**合计**：~1.5 天

---

## 8. 与现有思考面板的关系

| | 现在 | 流式改造后 |
|--|------|------------|
| 思考日志来源 | 独立 SSE 频道（`chat_thinking_log`） | 合并进流式 SSE（`tool_start`/`tool_done`） |
| 项目内聊天 | SSE event_manager | 流式端点内联 |
| 全局聊天 | `/chat/thinking-stream` 独立连接 | 流式端点内联 |
| 刷新后恢复 | `thinking_json` 列 | 不变 |

改造后可以**废除独立的 `thinking-stream` 端点**，思考步骤和文本流合并在同一个 SSE 连接里，更简洁。
