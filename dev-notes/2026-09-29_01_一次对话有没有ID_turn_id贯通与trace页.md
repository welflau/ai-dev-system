# 一次对话有没有 ID：从半死的 `msg_group_key` 到能画出来的时间轴

2026-09-29

## 起因

想给聊天做一个「看某次对话背后跑了哪些 LLM 和工具」的可视化页面。第一件事
不是画图，是**先回答：一次对话有没有一个稳定的 ID？**

抓着 `chat_messages`、`llm_conversations`、`tool_audit_log` 三张表去 JOIN 的
时候发现：**没有**。字段名 `msg_group_key` 是有的，注释还写着「每次发送唯一」，
但顺着代码一路读到端点：

```python
_msg_group_key = req.msg_group_key or _sid
```

前端只有 CLI 任务面板那几个入口传 `msg_group_key`，其余路径一律回落成
`session_id`。于是「一次对话」和「整个会话」共用同一个 key，后台任务面板里
几十轮全挤成一组，LLM 调用和工具调用表根本就没这个字段。

字段是有的。行为是错的。这种更难发现 —— grep 得到的结果说明「这里做过设计」，
但对着数据看会发现「设计没真落地」。

所以这次的三步全在做一件事：**让「一次对话」变成一个真实存在的东西**。

## 一、把 turn_id 变成真的

### 1. 服务端生成，不听前端

回落到 `session_id` 是原罪，把 `req.msg_group_key or _sid` 换成端点自己发：

```python
# 本轮对话的 turn_id：服务端生成，一次发送唯一。
# 不能用 `req.msg_group_key or _sid` —— 前端只有 CLI 任务那几个入口传
# msg_group_key，其余路径一律回落成 session_id，于是「一次对话」和
# 「整个会话」同一个 key，后台任务面板里几十轮全挤成一组，也没法用它
# 去 JOIN LLM/工具记录。key 是每轮唯一才有意义，那就服务端自己发。
_msg_group_key = _gen_id("TURN")
```

前端传来的 `msg_group_key` 保留但只当展示标签，Field 描述加 `已废弃`。

### 2. 前端已经用 sess_<ts> 分组了 —— 让它换旗

不能简单地让服务端生成完事：前端任务面板早就按自己生成的 `sess_<ts>` 分组
挂了几十个任务。如果服务端另发一个 key，两套 ID 就永远对不上，最简单的「点
一个任务跳到对应 turn」都做不到。

方案：加一个 `turn_begin` SSE 事件，前端收到就把本组的 key 换成后端的：

```javascript
/** 用后端下发的 turn_id 替换本轮分组 key（含已登记任务的回填） */
function _cliSessionAdoptTurnId(turnId) {
    if (!turnId || !_cliCurrentSession) return;
    const old = _cliCurrentSession.key;
    if (old === turnId) return;
    _cliCurrentSession.key = turnId;
    for (const t of Object.values(_CLI_TASKS_MEM)) {
        if (t.session_key === old) t.session_key = turnId;
    }
}
```

**关键在回填。** 有些工具的 `tool_start` 事件可能先于 `turn_begin` 到达
（理论上不会，但流式事件顺序不值得赌），要能把已登记的任务从旧 key 抹到新 key。

### 3. 三张表都要落 turn_id，但只有工具那张是隐式取

`llm_conversations` 和 `tool_audit_log` 都加了 `turn_id` 列。落库时：

- **LLM 记录**：调用点显式 `set_llm_context(turn_id=...)` 到 contextvars。
- **工具记录**：不动调用点，`audit_log_hook` 里从 `_llm_ctx` 取。

```python
# turn_id 直接从 _llm_ctx 取：工具在触发它的那次 LLM 循环的同一个
# 协程里跑，contextvars 看得见。hook context 里不另加字段，免得每个
# 调用点都要记着传。
```

工具调用有几十个触发点，一个个改要炸的。协程隔离 + contextvars 天然满足需求。

### 4. 同 turn ≠ 同 action —— Compaction 的坑

写单测的时候踩到一个细节：一次用户对话里，Compaction（历史压缩）也会调 LLM，
它必须**共享同一个 turn_id**（否则 JOIN 出来是断的），但必须**靠 `action` 
区分**（否则那 4000 个压缩 token 会算到用户那次调用头上）。

这是「同 turn ≠ 同 action」，测试里钉死：

```python
check("嵌套的 Compaction 调用靠 action 区分，不被当成同一次",
      sorted(r["action"] for r in llms) == ["chat_stream", "compact_history"])
check("token 各自独立记账（压缩那 4000 不会记到用户那次上）",
      sorted(r["input_tokens"] for r in llms) == [120, 4000])
```

### 5. 顺手补的两个不相关 bug

改这里的时候看到两个明显的坑，一起修了：

- **`total_tokens` 在 `message_done` 里被丢了。** SSE payload 里根本没这字段，
  前端拿到的永远是 0。加上。
- **早退路径不 emit SESSION_END。** 三条路径 —— budget 超限 / CLI 单轮 /
  `finish` 工具 —— 直接 `return`，`tool_audit_log` 里连 `query_engine:done`
  都没有。**这三种恰好是事后最想看的结束方式**（预算杀掉、最常用路径、显式
  finish），全没痕迹。三处都补上。

## 二、CLI 模式的 token 是 NULL 不是空

第 2 步的目标本来只是「让 CLI 记录带 token 和耗时」。挖下去发现问题比这大。

### 1. NULL 不是没记录，是**没记录 token 但预算也没在管**

`_call_cli_stream` 结尾这一段：

```python
try:
    await self._save_conversation(
        messages, full_text,
        {"input_tokens": None, "output_tokens": None},
        0,
    )
```

字段名叫 `usage`，实际传的是 `None`。耗时字段是硬编码的 `0`。表里就是这样
一路空过来的。

但更麻烦的是：**这条路径上 `Budget.consume()` 从来没被调用过。**
`QueryEngine.run()` 的 CLI 分支从 `_call_cli_stream` 拿一段文本就 `return`，
不走后面的 `budget.consume()`。默认模型 `deepseek-v4-pro-ioa` 就是走这条路
的，等于**预算的 token 维度对最常用的模型完全无效，只剩超时兜底**。

有个 skill 声明 `max_seconds: 300`，实测跑了 938 秒 —— 那次就是这个坑。

### 2. CLI 自己会报 —— 只是我们没接

`--output-format stream-json` 的结尾 `result` 行是这样：

```json
{"type": "result",
 "usage": {"input_tokens": 12, "output_tokens": 34,
           "cache_read_input_tokens": 5678, ...},
 "total_cost_usd": 0.0123,
 "duration_ms": 8123}
```

用量数据一直都在，读完就丢。加一个 `_normalize_cli_usage` 抽出来：

```python
def _normalize_cli_usage(obj: dict) -> Optional[Dict[str, Any]]:
    """cache_read/cache_creation 算进 input：计费和上下文占用上它们都是真实
    输入，只记 input_tokens 会把一次几万 token 的调用记成十几个。"""
    inp = _i("input_tokens") + _i("cache_read_input_tokens") + _i("cache_creation_input_tokens")
    out = _i("output_tokens")
```

**cache_read 不能丢** —— Anthropic 的计费和上下文占用都把它当输入。只记
`input_tokens` 会把一次几万 token 的长对话记成十几个 token，账全错。

### 3. 顺手差点越界 —— `_emit_assistant_stop`

在补 SESSION_END 的时候，本来想把 `_emit_assistant_stop` 一起补上，反正一行。
grep 一下发现 `ASSISTANT_STOP` 是 `nudge_hook` 消费的，**那个 hook 会往聊天
面板推用户可见的消息**。第一步的题目是「补审计记录」，不是「改用户看到的东西」，
撤掉，加注释说明。

```python
# 只补 SESSION_END，不补 ASSISTANT_STOP —— 后者挂着 nudge_hook
# 会往聊天面板推消息，那是另一件事，别顺手改了用户看得见的行为。
```

**范围纪律 > 补丁「更完整」。**

## 三、started_at 只能倒推

要画时间轴就得有起点。表里只有 `created_at`（结束时间）和 `duration_ms`。
落库时机是在**调用完成之后**，代码里已经拿不到「开始时的时间戳」了。

只能倒推：

```python
def iso_before(ms: float, base_iso: str = "") -> str:
    """把时间往前推 ms 毫秒。started_at 只能这样算：记录都是跑完之后才落
    库的，手里只有 created_at 和 duration_ms，起点只能倒推。"""
```

精度损失可以接受（毫秒级），但真实开始时间和倒推值可能差个几十到几百毫秒
（落库本身有排队）。这个精度对「哪一步耗了 40 秒、哪两步是并行的」这个粒度
足够了。

## 四、`/trace` 接口和一个必须补的字段

三张表齐了，第 3 步要写 `GET /chat/sessions/{id}/trace`。写的时候发现：

**`chat_messages` 表里没有 `turn_id`。**

第 1 步的三张表指的是 `llm_conversations`、`tool_audit_log`、`cli_task_log` —— 
只覆盖了 Agent 的行为，没覆盖用户消息本身。要把「用户这句话之后跑了哪些 LLM/
工具」串起来，只有两个选择：

- **A：给 `chat_messages` 也加 `turn_id`**（一次迁移，5 个持久化调用点各加一
  行参数）
- **B：按时间窗口猜哪个 LLM 属于哪条消息**（同一秒发两条就散架）

选 A。第 1 步已经把「同轮 = 同 turn_id」立为不变量，这里延续。前端在 `message_done` 
里也已经拿到 `turn_id`，改起来干净。

`/trace` 接口的行为约定，写在测试里：

```
1. 消息、LLM、工具按 turn_id JOIN 出完整一轮，不串到别的 turn
2. 嵌套 Compaction 挂同一个 turn_id，total_input_tokens 要把它一起算
3. SESSION_END（query_engine:done）单独拎出来当 turn 结束标记，
   不混进 tool_calls
4. 未挂 turn_id 的旧消息不丢，落进 orphan_messages
5. turn 按 started_at 排序（不按 id，避免异步落库时序偏差）
```

15 个断言全绿。

## 五、页面挂在哪儿：不是「新聊天」，是「反查」

一开始想过挂在 Agent 分组下，和「Agent 监控」并列。用户选了「设置」下面，
和统计面板并列。挑对了：

- **Agent 监控**是 realtime，看**现在**跑什么。
- **对话追踪**是 replay，看**过去某次**跑了什么。
- **统计面板**是聚合，看**一段时间**跑了什么。

三者都是「反查」类，语义一致。「对话追踪」放中间刚好。

## 遗留

**没做过浏览器验证。** 后端 API 有单测，前端渲染纯 DOM 拼字符串，语法过
（`node --check` 干净），但 CSS 布局、折叠动画、长文本截断的目视效果没验。
起服务打开就能看，等真实数据跑一轮再回来打磨。

**MCP 面板文案。** 之前提过「🔒 需在 Client 侧授权」在 CLI 路径下会误导
（CLI 子进程走 MERGE 语义，宿主的 MCP 服务实际是可用的），没改。

**`--channels` per-plugin gating in SOP。** 明确不做。

## 附录：文件清单

后端：
- `database.py` — 三条迁移：`llm_conversations.turn_id / started_at`、
  `tool_audit_log.turn_id / started_at`、`chat_messages.turn_id`
- `llm_client.py` — `_llm_ctx` 加 `turn_id`；`_call_cli_stream` 计时 + 
  usage 捕获；`_normalize_cli_usage` 处理 cache 令牌；`_save_conversation` 
  / `_save_tools_conversation` 加 `started_at`
- `query_engine/engine.py` — CLI 分支的 `_cli_input/_cli_output` + 
  `budget.consume`；三条早退路径补 SESSION_END
- `hooks/builtin.py` — 两处 INSERT 加 `turn_id / started_at`
- `api/chat.py` — 两个流式端点生成 `_msg_group_key = _gen_id("TURN")`，
  6 个 `_save_chat_message` 调用点传 `turn_id`；新增 
  `GET /chat/sessions/{id}/trace`
- `utils.py` — `iso_before(ms, base_iso)`

前端：
- `index.html` — 「设置」分组加「🗂 对话追踪」；`tab-chat-trace` 面板骨架
- `app.js` — `_cliSessionAdoptTurnId`；`turn_begin` SSE 处理；
  `loadChatTrace` / `renderChatTrace` / `_renderTraceTurn / Event / Message`
- `styles.css` — 追加约 200 行 `.trace-*` 样式

测试：
- `_test_turn_id.py` — 23 断言，覆盖 contextvars、并发隔离、JOIN、
  端点行为、SESSION_END on early returns
- `_test_chat_trace.py` — 15 断言，覆盖 turn 隔离、嵌套 Compaction 记账、
  SESSION_END 拎出、orphan、started_at 排序、404
