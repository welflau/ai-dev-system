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

## 七、待做（A 方向剩余）

| 优先级 | 项目 | 预计得分 |
|--------|------|---------|
| P1 | L6 Hooks 缺 UserPromptSubmit / Stop / InstructionsLoaded | 6→7 |
| P2 | L7 Budget 费用追踪（USD 累计）| 6→6.5 |
| P2 | L8 并行子任务（dispatch 现在是串行的）| 5→6 |
| P2 | L9 Feature Flags 运行时 per-session 开关 | 4→5 |
