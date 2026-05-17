# A 方向：AI 助手对标 Claude Code 改进

> 日期：2026-05-17  
> 参考方案：`docs/20260516_01_AI助手对标ClaudeCode改进方案.md`  
> 提交范围：`fb1909b` → `1d01596`（5 个提交）  
> 评分变化：5.5 / 10 → 6.5 / 10

---

## 一、P0-1 Rules 层注入（L5: 3 → 4.5 分）

### 问题
`skills/rules/global.md` 存在（包含语言一致性、命名规范、安全红线），
但 `ChatAssistantAgent._build_system_prompt()` 完全没有读取，
是一个**纯遗漏 bug**——对 Orchestrator Agent 有效，对聊天助手是死文件。

### 修复
`_build_system_prompt` 和 `_build_global_system_prompt` 都读取
`skill_loader.get_rules_for_context(traits)` 并注入到 system prompt **最前面**。

```
{rules_section}你是 AI 自动开发系统的智能助手...
```

**效果**：AI 助手现在会遵守全局编码准则——禁止中文变量名、
Commit message 第一行英文、命名 / 文档 / 安全红线等。

---

## 二、P0-2 Diminishing Returns 检测（L1: 7 → 7.5 分）

### 问题
Budget 有 Token/轮次/时间约束，但没有"原地踏步"检测。
Agent 卡住时会把 max_turns=50 全跑完，浪费大量 token。

### 修复
`Budget` 加滑动窗口：

```python
diminishing_threshold: int = 500   # 每轮增量低于此值视为无效
diminishing_window:    int = 3     # 连续 3 轮无效才触发
```

`check()` 在每轮前也检测空转，返回原因字符串：
```
检测到原地踏步（连续 3 轮每轮增量 [100, 100, 100] < 500 token）
```

---

## 三、P1 Prompt Cache 分区（L3: 3 → 4 分）

### 问题
system prompt 是纯字符串，动态内容（需求状态、文件树）每次不同，
导致 Anthropic Prompt Cache 永远 miss，每次请求都要重新处理 3000+ token。

### 修复
System prompt 重组，以 `<!--CACHE_BOUNDARY-->` 分隔：

```
[稳定部分（缓存命中）]
Rules + 项目基本信息 + Skills + 能力描述 + 搜索规则 + 判断准则

<!--CACHE_BOUNDARY-->

[动态部分（不缓存）]
知识库 / 当前需求 / 工单概况 / 文件树 / 产出物
```

`llm_client._call_anthropic_tools_stream` 检测标记，稳定部分加
`cache_control: {"type": "ephemeral"}`，动态部分不加。

**预期收益**：稳定部分约 3000-5000 token，每次命中节省约 $0.01。

---

## 四、P1 Compaction 对话压缩（L4: 2 → 5 分）

### 问题
历史消息最多只发 10 条（前端），后端硬截到 8000 字符。
长对话会因 context 超限报错，且截断丢失语义。

### 修复

**限制放宽：**
- 前端 history 窗口 10 → 20 条
- `HISTORY_KEEP_RECENT_N` 6 → 10
- `HISTORY_MAX_TOTAL_CHARS` 8000 → 30000（≈7500 tokens）

**LLM 摘要 Compaction：**
历史条数超过 20 条时，把旧消息（前 N-10 条）送 LLM 压缩成一条摘要：

```
[之前对话历史摘要]
用户询问了 ThunderStrike 项目进度，AI 报告了 6 个需求正在进行中...
```

插入历史队列最前方，最近 10 条原文保留。LLM 失败时降级为字符截断（静默）。

---

## 五、P2 语义 Memory 召回（L5: 4.5 → 6 分）

### 问题
`agent_memory` 表只有 LIKE 搜索，不精准，且无主动注入——
用户需要显式调 `get_memory` 工具才能看到历史记忆，AI 不会主动感知。

### 修复

**1. FTS5 索引**
`agent_memory_fts` 虚拟表（trigram tokenizer）+ 三个触发器自动同步。

**2. GetMemoryAction 升级**
优先 FTS5（`ORDER BY rank` 相关性排序），降级 LIKE。

**3. 主动注入**
`_build_system_prompt` 在动态部分自动查询最近 3 条记忆：

```
## 项目历史记忆（最近 3 条）
  [decision] 选择 Phaser 3 框架（2026-05-14）
  [insight]  波次系统需要独立配置文件（2026-05-14）
  [handoff]  道具系统已完成，等待 UI 联调（2026-05-15）
如需详情请调用 get_memory 工具。
```

---

## 六、评分总结

| 层 | 改进前 | 改进后 | 主要变化 |
|----|--------|--------|---------|
| L1 QueryEngine | 7 | 7.5 | Diminishing Returns 检测 |
| L3 Context Assembly | 3 | 4 | Prompt Cache 分区，稳定/动态分离 |
| L4 Compaction | 2 | 5 | LLM 摘要 + 窗口 20 + 30000 字上限 |
| L5 Memory | 3 → 4.5 | **6** | Rules 注入 + FTS5 + 主动注入 |
| **综合均值** | **5.5** | **6.5** | +1.0 分 |

---

## 七、P1 L6 Hooks 生命周期补全（L6: 6 → 7 分）

> 提交：`7c17003`

### 新增 HookEvent

```python
USER_PROMPT_SUBMIT  = "UserPromptSubmit"   # 用户消息到达，LLM 调用前
ASSISTANT_STOP      = "AssistantStop"      # AI 回复完成，MessageDone 后
```

`ToolHookContext` 新增字段：`user_message`、`assistant_reply`、`rounds`

### QueryEngine 新增 emit 点

- **开头**：emit `USER_PROMPT_SUBMIT`（带最后一条用户消息前 500 字）
- **MessageDone 前**：emit `ASSISTANT_STOP`，调 `_emit_assistant_stop()`

### nudge_hook（新内置 Hook）

触发时机：`ASSISTANT_STOP`

逻辑：
1. 查询项目未完成需求数（`requirements WHERE status NOT IN completed/cancelled`）
2. 有未完成需求 → 推 SSE `assistant_nudge` 到项目频道
3. 前端监听 → 聊天面板底部显示柔性提示 8s 后淡出

效果：
```
💡 项目还有 6 个需求正在进行中，输入「查看进度」了解详情。
```

### 当前注册的内置 Hook（5 个）

```
audit_log_hook       POST_TOOL_USE/TOOL_ERROR/SESSION_END → tool_audit_log
shell_rate_limit_hook PRE_TOOL_USE → ShellAction 超 50 次中断
failure_library_hook  TOOL_ERROR → ticket_logs error 记录
chat_alert_hook       TOOL_ERROR（关键）→ AI 聊天面板红色通知
nudge_hook            ASSISTANT_STOP → 未完成需求提示（新）
```

---

## 八、当前评分（截至 2026-05-17）

| 层 | 改进前 | 改进后 | 主要变化 |
|----|--------|--------|---------|
| L1 QueryEngine | 7 | 7.5 | Diminishing Returns 检测 |
| L3 Context Assembly | 3 | 4 | Prompt Cache 分区 |
| L4 Compaction | 2 | 5 | LLM 摘要 + 窗口扩大 |
| L5 Memory | 3 | 6 | Rules 注入 + FTS5 + 主动注入 |
| L6 Hooks | 6 | **7** | UserPromptSubmit + AssistantStop + nudge_hook |
| **综合均值** | **5.5** | **7.0** | +1.5 分 |

---

## 九、P2 L7 USD 费用追踪（L7: 6 → 7.5 分）

> 提交：`c75745a`

### 问题
LLM 调用只记录 token 数，没有换算成 USD 费用，
无法感知每次对话的成本，也不知道今天花了多少钱。

### 修复

**`llm_client.py` 定价表**
```python
_MODEL_PRICING = {
    "claude-opus-4":    (15.0, 75.0),   # $/1M tokens (in, out)
    "claude-sonnet-4":  (3.0,  15.0),
    "claude-haiku-4":   (0.8,  4.0),
    ...
}
```

**写入 DB**
`llm_conversations.cost_usd` 新列，每次对话写入估算费用：
- `_save_conversation`：普通 chat 调用
- `_save_tools_conversation`：tool_use 调用

**`/api/metrics` 新增 `cost_today_usd`**
从 `llm_conversations` 累加今日费用。

**前端指标条新增 `💰 今日`**
```
💰 今日  $0.0123    ← 正常绿色
💰 今日  $1.234     ← 黄色警告（>$1）
💰 今日  $6.78      ← 红色危险（>$5）
```

---

## 十、当前评分（截至 2026-05-17 晚）

| 层 | 改进前 | 改进后 | 主要变化 |
|----|--------|--------|---------|
| L1 QueryEngine | 7 | 7.5 | Diminishing Returns 检测 |
| L3 Context Assembly | 3 | 4 | Prompt Cache 分区 |
| L4 Compaction | 2 | 5 | LLM 摘要 + 窗口扩大 |
| L5 Memory | 3 | 6 | Rules 注入 + FTS5 + 主动注入 |
| L6 Hooks | 6 | 7 | UserPromptSubmit + AssistantStop + nudge_hook |
| L7 Budget | 6 | **7.5** | USD 费用追踪 + 指标条显示 |
| **综合均值** | **5.5** | **7.3** | +1.8 分 |

---

## 十一、P2 L9 Feature Flags 运行时开关（L9: 4 → 5 分）

> 提交：本次

### 问题
AI 行为（compaction / nudge / 最大 token / 最大轮次）全部硬编码在 config 里，
用户如果需要调试某个行为（如关掉 compaction 对比效果），必须改配置并重启服务。
Claude Code 的 `/toggle` 命令则支持运行时即时切换。

### 修复

**`backend/actions/chat/set_session_flag.py`（新文件）**

Session 级别的内存 flag 表，支持 5 个开关：

```
compaction     on/off   — LLM 摘要压缩（默认 on）
nudge          on/off   — AI 回复后未完成需求提示（默认 on）
verbose        on/off   — 详细回复模式（默认 off）
max_turns      1-200    — 当前 session 最大工具轮次（默认 50）
budget_tokens  10k-2M   — 当前 session token 上限（默认 300000）
list                    — 查看当前所有设置
```

重启后重置为默认值（设计如此——session 级别不做持久化）。

**`ChatAssistantAgent` 集成**

1. `SetSessionFlagAction` 加入 `action_classes` → 暴露为 AI 工具
2. `_CROSS_SCOPE_TOOLS` 加入 `set_session_flag` → 全局 + 项目聊天都可用
3. `_TOOL_LABELS_PY` 加入 `"🎛 调整 AI 行为设置"` → 思考步骤显示友好标签
4. `args_hint` 提取器加入 `"set_session_flag": "flag"` → 思考日志显示 flag 名
5. `chat_stream` / `chat_global_stream` 里 Budget 改为读 session flag：
   ```python
   _sid = session_id or "default"
   budget = Budget(
       max_tokens=get_session_flag(_sid, "budget_tokens") or _cfg.CHAT_MAX_TOKENS,
       max_turns=get_session_flag(_sid, "max_turns") or _cfg.CHAT_MAX_TURNS,
       max_seconds=_cfg.CHAT_MAX_SECONDS,
   )
   ```
6. `_assemble_messages` 传入 `session_id` → compaction flag 生效
7. `_ChatToolExecutor.execute` 注入 `session_id` 到 ctx → SetSessionFlagAction 能读到

**使用示例**
```
用户：关掉 compaction 让我看完整历史
AI 调用：set_session_flag(flag="compaction", value="off")
AI 回复：✅ 已设置 compaction = False（本 session 有效）
```

---

## 十二、当前评分（截至 2026-05-17 深夜）

| 层 | 改进前 | 改进后 | 主要变化 |
|----|--------|--------|---------|
| L1 QueryEngine | 7 | 7.5 | Diminishing Returns 检测 |
| L3 Context Assembly | 3 | 4 | Prompt Cache 分区 |
| L4 Compaction | 2 | 5 | LLM 摘要 + 窗口扩大 |
| L5 Memory | 3 | 6 | Rules 注入 + FTS5 + 主动注入 |
| L6 Hooks | 6 | 7 | UserPromptSubmit + AssistantStop + nudge_hook |
| L7 Budget | 6 | 7.5 | USD 费用追踪 + 指标条显示 |
| L9 Feature Flags | 4 | **5** | per-session 运行时开关 |
| **综合均值** | **5.5** | **7.4** | +1.9 分 |

---

## 十三、待做（A 方向剩余）

| 优先级 | 项目 | 预计得分 |
|--------|------|---------|
| P2 | L8 并行子任务（dispatch 现在是串行的）| 5→6 |
