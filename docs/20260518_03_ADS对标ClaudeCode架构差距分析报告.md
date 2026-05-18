# ADS 对标 Claude Code 架构差距分析报告

> 日期：2026-05-18  
> 参考文档：`F:\A_Works\claude-code\Docs\20260515_08_ClaudeCode与WorkBuddy架构深度对比.md`  
> ADS 代码基准：`backend/`（当前 main 分支）  
> 分析方法：逐模块对比 Claude Code 源码机制 与 ADS 实际实现

---

## 一、总览评分

| 模块 | Claude Code 满分 | ADS 现状 | 得分 | 优先级 |
|---|:---:|:---:|:---:|:---:|
| Commands / 斜杠指令 | 10 | 1 | ★★☆☆☆ | P1 |
| Skills 触发机制 | 10 | 5 | ★★★☆☆ | P1 |
| Memory 分类与召回 | 10 | 4 | ★★☆☆☆ | P2 |
| 知识库层级结构 | 10 | 3 | ★★☆☆☆ | P2 |
| Extended Thinking | 10 | 7 | ★★★★☆ | P1 |
| Context Compaction | 10 | 4 | ★★☆☆☆ | P2 |
| 消息预处理管线 | 10 | 3 | ★★☆☆☆ | P3 |

---

## 二、Commands / 斜杠指令系统

### Claude Code 机制
```
用户输入 → processUserInput()
  if input.startsWith('/') → processSlashCommand()
    命令优先匹配（~50 个） → 无匹配回退 SkillTool
  else → processTextPrompt()
```
约 50 个内置命令（`/compact`、`/memory`、`/commit`、`/review`、`/fast` 等），均可扩展。

### ADS 现状
**frontend/app.js** 中仅有一个斜杠命令拦截：
```javascript
if (val.startsWith('/test')) {   // line 12159
    _handleSlashTest(val);       // 仅用于 Agent 单元测试
    return;
}
```
后端无 Command 路由机制，所有自然语言通过 LLM 识别意图 → Action。

### 差距
- ❌ 无 `/ue-bp-gen`、`/ue-auto` 等功能性命令入口
- ❌ Skills 无法通过斜杠直接触发（只能靠 AI 识别意图）
- ❌ 无 `/compact`（手动触发历史压缩）、`/memory`（查看记忆）等管理命令

### 建议方案
**前端**：扩展 `handleChatKeydown` 的 `/` 前缀拦截：
```
/command args → POST /api/commands/{command}?args=...
```
**后端**：新建 `api/commands.py`，读取 `skills/commands/*.md` 定义，路由到对应 Action/Agent。

**工期估计**：5-7 天（含基础框架 + 迁移现有 UE 命令）

---

## 三、Skills 触发机制

### Claude Code 机制
- Bundled Skills 编译进二进制（13 个），Disk Skills 从目录加载
- 执行模式：`inline`（注入当前对话 system prompt）vs `fork`（独立子 Agent）
- `whenToUse` 字段供模型自动判断何时触发
- 用户可用 `/skillname args` 直接触发

### ADS 现状
**backend/skills/loader.py** 实现了完整的三层过滤：
```python
# 1. inject_to: [AgentName]           Agent 级
# 2. traits_match: {all_of/any_of}    项目级
# 3. paths: [glob, ...]               文件级
```
**backend/skills/use_skills/** 存放 Skill 文档，注入 LLM system prompt。

`backend/actions/chat/load_skill.py` 提供 `load_skill` Action，但：
- 只能通过 AI 识别意图调用，无斜杠触发
- 无 inline vs fork 执行模式区分
- 无 `whenToUse` 语义提示

### 差距
- ⚠️ Skills 只能被动注入，不能主动触发
- ❌ 无 fork 执行模式（目前所有 Skill 都是 inline）
- ❌ 无斜杠直接调用（如 `/ue-bp-gen BP_WaveSpawner`）

### 建议方案
1. 在 Skill frontmatter 加 `trigger: /ue-bp-gen`、`context: fork|inline`
2. Command 机制建好后，Skill 命令自动注册为可触发命令

---

## 四、Memory 分类与召回

### Claude Code 机制
**4 种强制类型**（`user / feedback / project / reference`）+ MEMORY.md 索引：
```
~/.claude/projects/<slug>/memory/
├── MEMORY.md              ← 索引，始终注入 system prompt（200行/25KB）
├── user_role.md           ← type: user
├── feedback_testing.md    ← type: feedback
└── project_deadline.md    ← type: project
```
**动态召回**：每轮 query 时 Sonnet 侧调用语义筛选最相关 5 个记忆文件（实验性）。

### ADS 现状
**backend/database.py:664-707** `agent_memory` 表：
```sql
CREATE TABLE agent_memory (
    id TEXT, project_id TEXT, agent_type TEXT,
    memory_type TEXT,  -- decision/handoff/project_status/insight（4种，但非 CC 的分类）
    title TEXT, body TEXT, ...
)
```
**agent_memory_fts**（FTS5）已有，支持语义搜索。

`backend/actions/chat/save_memory.py` / `get_memory.py` 已实现。

### 差距
- ❌ 类型分类不对齐：ADS 是领域类型（decision/insight），CC 是用途类型（user/feedback/project/reference）
- ❌ 无 MEMORY.md 索引机制（无索引，context 压力大）
- ❌ 无自动注入到 system prompt（需要 AI 主动调 get_memory 工具才能看到）
- ❌ 无语义侧调用召回（全量搜索，相关性依赖 FTS5 关键词）

### 建议方案
1. 新增 Memory 类型：`user_profile`、`behavior_feedback`、`project_context`、`external_ref`
2. 在 `_build_system_prompt` 动态部分加 MEMORY.md 摘要注入（已有 3 条注入，可优化为索引格式）
3. 实现语义召回（当前 FTS5 已够，可加 LLM 侧筛选）

---

## 五、Extended Thinking（重点）

### Claude Code 机制
三种模式：`adaptive`（默认）/ `enabled: budgetTokens` / `disabled`
- 默认 `adaptive`：模型自主决定是否思考
- `ultrathink` 关键字 → 最大 token 预算 + 彩虹动画
- 精确模型支持检测：`modelSupportsAdaptiveThinking()`

### ADS 现状（已实现较好）
**backend/llm_client.py:16-25**：
```python
_THINKING_CAPABLE_MODELS = {"claude-3-7-sonnet", "claude-opus-4", "claude-sonnet-4"}
def _model_supports_thinking(model_id: str) -> bool: ...
```
**backend/agents/chat_assistant.py:521-527**：
```python
engine = QueryEngine(
    ...
    enable_thinking=_model_supports_thinking(llm_client.model),
    thinking_budget=8000,  # 固定预算
)
```
**已实现**：`thinking_delta` / `thinking_done` 流式推送，前端 💭 面板展示（J-3 已完成）。

### 差距
- ⚠️ 无 `adaptive` 模式：ADS 要么全开（模型支持）要么全关，没有让模型自主决策
- ❌ 无 `ultrathink` 关键字触发最大预算
- ❌ 无 per-session thinking budget 设置（L9 Feature Flags 有 budget_tokens 但不影响 thinking）
- ⚠️ thinking budget 硬编码为 8000，不可调

### 建议方案
1. 把 `enable_thinking` 改为三态：`adaptive` / `enabled` / `disabled`
2. 在 `handleChatKeydown` 检测 `ultrathink` 关键字，设置最大 budget
3. L9 Feature Flags 加 `thinking_budget` 和 `thinking_mode` 参数

**工期估计**：1-2 天

---

## 六、Context Compaction（历史压缩）

### Claude Code 机制
- `/compact` 命令手动触发：LLM 生成摘要 → 替换历史
- 自动触发：接近上下文限制时自动压缩
- `KAIROS` 模式：长期助手的 append-only 日记 + 夜间蒸馏

### ADS 现状
**backend/agents/chat_assistant.py** 已有 LLM 摘要压缩（L4 已实现）：
```python
async def _compact_history_with_llm(self, history, ...) -> list:
    # 历史 > 20 条时触发，旧消息 LLM 压缩成摘要
```
History 窗口：前端 20 条，后端 `HISTORY_KEEP_RECENT_N = 10`，`HISTORY_MAX_TOTAL_CHARS = 30000`。

### 差距
- ⚠️ 无手动 `/compact` 命令（用户无法主动触发）
- ❌ 无 token-aware 窗口（按字符数截断，不按实际 token 预算）
- ❌ Orchestrator Agent 无压缩机制（每个 Action 都是独立调用，无历史）

### 建议方案
1. 加 `/compact` 命令（调现有 `_compact_history_with_llm`）
2. 压缩触发条件改为 token 估算（`input_tokens` > 80% of budget）

---

## 七、消息预处理管线

### Claude Code 机制
**6 步线性管线**：图片处理 → ultraplan检测 → 附件提取 → 路由分发 → UserPromptSubmit Hooks → 图片metadata追加

### ADS 现状
**api/chat.py** 基本线性流程：
```python
# 接收请求 → 构建 history → 调 chat_stream → 处理 SSE 事件
```
Hooks 系统已有（L6 完成）：`USER_PROMPT_SUBMIT`、`ASSISTANT_STOP` 均已实现。

### 差距
- ⚠️ 无 `@file` 引用展开（`@/path/to/file` 注入文件内容）
- ❌ 无消息排队机制（并发请求直接报错）
- ❌ 无 Bridge 安全过滤（外部消息来源校验）

---

## 八、ADS 特有优势（Claude Code 没有的）

| 特性 | ADS | Claude Code |
|---|---|---|
| **工单状态机** | ✅ Orchestrator + SOP | ❌ |
| **多 Agent 并行** | ✅ L8 并行子任务 | ❌（单线程） |
| **打包流水线** | ✅ RunUAT BuildCookRun | ❌ |
| **前端 UI** | ✅ 完整 Web UI | CLI only |
| **费用追踪** | ✅ cost_usd 实时显示 | ❌ |
| **FTS5 语义搜索** | ✅ 知识库+工单+记忆 | ❌ |
| **Prompt Cache 分区** | ✅ CACHE_BOUNDARY | 部分实现 |

---

## 九、优先级行动计划

### P1（近期，1-2 周）

| 项目 | 内容 | 工期 |
|---|---|---|
| **Commands 基础框架** | 前端 `/` 路由 + 后端 `api/commands.py` | 3天 |
| **thinking 三态模式** | adaptive/enabled/disabled + ultrathink 关键字 | 1天 |
| **`/compact` 命令** | 暴露现有压缩能力给用户 | 半天 |
| **Skills 斜杠触发** | UE Skill 注册为可触发命令（基于 Command 框架）| 2天 |

### P2（中期，2-4 周）

| 项目 | 内容 | 工期 |
|---|---|---|
| **Memory 类型对齐** | 新增 4 类型 + MEMORY.md 摘要注入 | 3天 |
| **`@file` 引用展开** | 消息预处理加文件引用 | 2天 |
| **token-aware 窗口** | 按 token 数而非字符数触发压缩 | 2天 |
| **知识库层级** | 加 User-level / Local-override 层 | 3天 |

### P3（长期，按需）

| 项目 | 内容 |
|---|---|
| 消息排队机制 | 并发请求排队（参考 WorkBuddy [1800] 拦截器）|
| Sonnet 语义记忆召回 | 替代全量注入 |
| KAIROS 日记模式 | 长期会话的 append-only 日记 |

---

## 十、结论

ADS 在 **工单驱动的开发运维流程** 上远超 Claude Code，在 **Thinking 展示**、**Prompt Cache**、**费用追踪** 上已对齐或超越。

核心差距集中在 **用户体验层**：没有斜杠命令让用户直接驱动强大的后端能力，Skills/UE 工具只能靠 AI 识别意图触发，效率和可靠性均低于直接命令。

**最高价值的单一改进**：建立 Commands 机制（P1），让 `/ue-bp-gen`、`/compact`、`/memory` 等命令直接可用，立即提升使用体验。
