# ADS AI 助手改进方案：对标 Claude Code 基础设施

> 日期：2026-05-16  
> 参考框架：`20260516_09_对标ClaudeCode的AI助手基础设施清单.md`  
> 分析对象：`backend/agents/chat_assistant.py` + 相关基础设施  
> 目标：按 L1-L10 十层框架评估 ADS ChatAssistantAgent 的缺口，输出可执行的改进方案

---

## 一、当前状态总览

### 1.1 已完成的基础设施（不重复建设）

| 模块 | 状态 | 说明 |
|------|------|------|
| QueryEngine | ✅ 完整 | `backend/query_engine/engine.py`，Pre/Post Hooks、Budget 全部集成 |
| Hooks 体系 | ✅ 完整 | `audit_log / shell_rate_limit / failure_library / chat_alert` 四个内置 Hook |
| Budget 三维约束 | ✅ 完整 | Token / 轮次 / 时间，可通过 `.env` 配置 |
| PermissionGate | ✅ 完整 | 高风险 Shell/Git 操作异步挂起等待审批，SSE 推前端 |
| 30+ Chat Actions | ✅ 完整 | Traits 过滤、作用域白名单、MCP 集成 |
| Skills 懒加载 | ✅ 完整 | `load_skill` 按需触发，system prompt 仅注入索引 |
| 流式对话 | ✅ 完整 | `chat_stream()` 走 QueryEngine，非流式 `chat()` 未统一 |

### 1.2 各层得分（满分 10）

| 层 | 得分 | 主要缺口 |
|----|------|---------|
| **L1** QueryEngine | 7 | 无 Diminishing Returns；max_tokens 直接截断不续写；无 Side Query |
| **L2** Tool & Permission | 7 | 无文件状态 hash 缓存；无 session 内文件撤销快照 |
| **L3** Context Assembly | **3** | system prompt 全混一块，稳定/动态内容未分区；工具排序不稳定 |
| **L4** Compaction | **2** | 完全缺失；历史仅靠 `history[-N:]` 硬截，context 满则报错 |
| **L5** Memory & Knowledge | **3** | `rules/global.md` 存在但未注入；Memory 无类型；无语义召回 |
| **L6** Hooks | 6 | 缺 UserPromptSubmit（重要）、Stop inject、InstructionsLoaded |
| **L7** Budget | 6 | 无 USD 费用追踪；无 Diminishing Returns；无 nudgeMessage |
| **L8** Multi-Agent | 5 | `dispatch_subtask` 已有；缺并行；缺 worktree 隔离 |
| **L9** Feature Flags | 4 | 仅静态 `settings` 配置；无运行时 per-session 开关 |
| **L10** Security | 7 | PermissionGate 覆盖高风险 Shell；缺 Plan Mode；缺 Scratchpad |

**综合均值：5.5 / 10**（对比文档 09 中 WorkBuddy 的均值 5.3，相近但侧重不同）

---

## 二、P0 — 阻塞性缺口（1 周内，影响可靠性）

### P0-1 L5：Rules 层注入（1 天）

**问题**

`skills/rules/global.md` 是全局编码准则（语言一致性 / 命名 / 安全红线等），DevAgent/ReviewAgent 通过 ActionNode 的 `_resolve_skills_prompt()` 可以拿到，但 `ChatAssistantAgent._build_system_prompt()` **完全没有读取**。这是一个纯遗漏 bug——文件写了，但对 ChatAssistant 是死文件。

**修复方案**

在 `_build_system_prompt()` 中读取并注入 rules 内容。Rules 内容相对稳定，放在 system prompt **最前面**，对 Prompt Cache 友好。

```python
# backend/agents/chat_assistant.py  _build_system_prompt()

async def _build_system_prompt(self, project: dict, context: dict) -> str:
    # --- 新增：读取 Rules 层 ---
    rules_content = ""
    try:
        from skills.loader import skill_loader as _sl
        rules_content = _sl.build_rules_prompt(traits=project_traits)
    except Exception:
        pass
    rules_section = f"<rules>\n{rules_content}\n</rules>\n\n" if rules_content else ""

    # ... 其余现有逻辑不变 ...

    return f"""{rules_section}你是 AI 自动开发系统的智能助手...
```

`build_rules_prompt()` 在 `skills/loader.py` 中实现：读取 `skills/rules/global.md`，按 frontmatter `traits_match` 过滤项目特定规则（如 `ue5.md` 仅对 UE 项目注入）。

**收益**：全局编码规范、安全红线终于对 ChatAssistant 生效，AI 不再生成中文变量名、硬编码密钥等违规代码。

---

### P0-2 L1：Diminishing Returns 检测（半天）

**问题**

`Budget` 有 Token/轮次/时间三重约束，但没有"原地踏步"检测。Agent stuck 时会把 `max_turns=50` 全跑完，浪费大量 token。

Claude Code 的实现：连续 3 轮每轮新增 token < 500 → 判定 diminishing returns → 强制停止。

**修复方案**

在 `Budget` 类加滑动窗口；在 `QueryEngine` 主循环的 `budget.consume()` 后调用检测。

```python
# backend/query_engine/budget.py

@dataclass
class Budget:
    max_tokens:  int   = 200_000
    max_turns:   int   = 50
    max_seconds: float = 600.0
    diminishing_threshold: int = 500   # 新增：每轮增量低于此值视为无效
    diminishing_window:    int = 3     # 新增：连续 N 轮无效才触发

    _used_tokens:   int   = field(default=0, init=False, repr=False)
    _used_turns:    int   = field(default=0, init=False, repr=False)
    _start_time:    float = field(default_factory=time.monotonic, init=False, repr=False)
    _token_deltas:  list  = field(default_factory=list, init=False, repr=False)  # 新增

    def consume(self, tokens: int = 0, turns: int = 0) -> None:
        self._used_tokens += tokens
        self._used_turns  += turns
        # 记录本轮 token 增量（滑动窗口，只保留最近 N 轮）
        self._token_deltas.append(tokens)
        if len(self._token_deltas) > self.diminishing_window:
            self._token_deltas.pop(0)

    def is_diminishing(self) -> bool:
        """连续 N 轮每轮增量 < threshold → 原地踏步"""
        if len(self._token_deltas) < self.diminishing_window:
            return False
        return all(d < self.diminishing_threshold for d in self._token_deltas)

    def check(self) -> str | None:
        if self._used_tokens >= self.max_tokens:
            return f"Token 上限已达到（{self._used_tokens:,} / {self.max_tokens:,}）"
        if self._used_turns >= self.max_turns:
            return f"轮次上限已达到（{self._used_turns} / {self.max_turns}）"
        elapsed = time.monotonic() - self._start_time
        if elapsed >= self.max_seconds:
            return f"时间上限已达到（{elapsed:.1f}s / {self.max_seconds:.0f}s）"
        # 新增：diminishing returns 检测
        if self.is_diminishing():
            return f"连续 {self.diminishing_window} 轮增量过低（< {self.diminishing_threshold} tokens），停止执行"
        return None
```

**收益**：消除"Agent 卡住原地转圈"场景，节省无效 token 消耗。

---

### P0-3 L3：Prompt Cache 分区（1 天）

**问题**

`_build_system_prompt()` 返回一整块字符串，结构大致是：

```
[项目信息] + [UE意图路由] + [知识库] + [需求列表] + [工单概况]
+ [文件树] + [关键文档] + [产出物] + [Skills索引] + [能力说明]
```

其中"需求列表"、"工单概况"每轮对话都可能变化——一变，整个 system prompt 的 Prompt Cache 全部失效，每次都要重新计算所有 input token。

Claude Code 的解决思路：稳定内容（Rules + 项目基本信息 + Skills 索引）和动态内容（需求/工单状态）分区，稳定段打 `cache_control: ephemeral`，Anthropic 对此段启用 5 分钟 Prompt Cache。

同时，工具 schemas 每次由 `_exposed_tool_schemas()` 动态拼装，顺序不稳定，导致 Anthropic 工具列表的缓存也频繁失效。

**修复方案**

**步骤 1：工具排序稳定化**

```python
# backend/agents/chat_assistant.py  _exposed_tool_schemas()

def _exposed_tool_schemas(self, scope="project", traits=None):
    schemas = [...]   # 现有逻辑不变
    # 新增：按 name 字典序排序，保证 Prompt Cache 前缀稳定
    schemas.sort(key=lambda s: s.get("name", ""))
    return schemas
```

**步骤 2：system prompt 拆分为稳定段 + 动态段**

```python
async def _build_system_prompt(self, project: dict, context: dict) -> str:
    # ── 稳定段（Rules + 项目基本信息 + Skills 索引）──────────────
    # 这部分内容在同一会话内基本不变，适合 Prompt Cache
    stable_section = f"""
{rules_section}
## 项目信息
- 名称：{project['name']}
- 描述：{project.get('description') or '无描述'}
- 技术栈：{project.get('tech_stack') or '未指定'}
- Git 仓库：{project.get('git_repo_path') or '未配置'}
{traits_line}
{ue_routing}
{skills_section}
{ability_section}
"""

    # ── 动态段（需求 / 工单 / 文件树）────────────────────────────
    # 这部分每轮可能变化，放到稳定段之后，不影响稳定段的缓存
    dynamic_section = f"""
## 当前需求状态
{req_summary}

## 工单概况
{ticket_summary}

## 项目文件树
{file_tree}

## 产出物列表
{artifacts_summary}
{knowledge_section}
"""
    return stable_section + dynamic_section
```

**步骤 3：对 LLM 调用加 `cache_control`（可选，需 Anthropic beta 支持）**

```python
# backend/llm_client.py
# 在构造 messages 时对稳定的 userContext 消息加 cache_control
user_context_msg = {
    "role": "user",
    "content": [{
        "type": "text",
        "text": stable_knowledge,
        "cache_control": {"type": "ephemeral"}   # Anthropic Prompt Cache
    }]
}
```

**收益**：长会话场景下 API input token 成本降低 30–50%；工具列表变化不再使项目知识缓存失效。

---

### P0-4 L2：File State Cache（1 天）

**问题**

ChatAssistant 有 `read_files`、`git_read_file`、`glob`、`grep` 等读取工具，也有 `shell`（可以写文件）。但没有"读后状态追踪"：用户在对话中让 AI 读了某文件，外部编辑后，AI 再基于旧内容操作 → 静默覆盖，数据丢失。

**修复方案**

在 `_ChatToolExecutor` 里加 `_file_state: dict[str, str]`（path → content_hash），`read_files` / `git_read_file` 执行后登记 hash，`shell` 执行前若涉及已登记路径则校验。

```python
# backend/agents/chat_assistant.py  _ChatToolExecutor

import hashlib

class _ChatToolExecutor:
    def __init__(self, ...):
        ...
        self._file_state: dict[str, str] = {}   # path → md5 hash

    async def execute(self, tool_name: str, tool_input: Any) -> str:
        ...
        result_json = await action.run(ctx)

        # 读文件后登记 hash
        if tool_name in ("read_files", "git_read_file", "read_local_file"):
            self._register_file_hash(tool_input, result_json)

        # 写操作前校验 hash
        if tool_name == "shell":
            cmd = tool_input.get("command", "")
            self._verify_file_hashes(cmd)

        return result_json

    def _register_file_hash(self, tool_input: dict, content: str):
        path = tool_input.get("path") or ""
        if path:
            self._file_state[path] = hashlib.md5(content.encode()).hexdigest()

    def _verify_file_hashes(self, command: str):
        for path, old_hash in self._file_state.items():
            if path in command:
                try:
                    current = Path(path).read_text(encoding="utf-8", errors="ignore")
                    current_hash = hashlib.md5(current.encode()).hexdigest()
                    if current_hash != old_hash:
                        raise RuntimeError(
                            f"文件 {path} 自上次读取后已被外部修改，"
                            "请重新读取后再操作，避免覆盖新内容。"
                        )
                except FileNotFoundError:
                    pass
```

**收益**：防止 AI 用过时内容覆盖用户的新修改，消除数据丢失风险。

---

## 三、P1 — 体验关键缺口（2 周，明显影响使用质量）

### P1-1 L4：基础 Context Compaction（3 天）

**问题**

当前没有任何压缩机制。`api/chat.py` 对历史消息做硬截断（`history[-8:]`、`history[-20:]`）——前期上下文直接丢失，前后不连贯；更长的会话超过 context window 时 LLM 直接报 400/413。

**修复方案**

在 `_assemble_messages()` 里加入"触发阈值检测 + 摘要压缩"：

```python
# backend/agents/chat_assistant.py  _assemble_messages()

MAX_HISTORY_TOKENS_ESTIMATE = 60_000   # 字符数粗估（1 token ≈ 4 chars）

def _assemble_messages(self, history, user_message, images):
    history_msgs = self._convert_history(history or [])

    # 估算历史大小
    history_size = sum(len(str(m.get("content", ""))) for m in history_msgs)

    if history_size > MAX_HISTORY_TOKENS_ESTIMATE:
        # 触发压缩：保留最近 6 条原文 + 更早历史的摘要
        history_msgs = self._compact_history(history_msgs, keep_recent=6)

    messages = history_msgs + [self._build_user_msg(user_message, images)]
    return messages

async def _compact_history(self, history_msgs: list, keep_recent: int) -> list:
    """
    将早期历史压缩为一条摘要消息：
    1. 取 history_msgs[:-keep_recent] 作为待压缩段
    2. 用 haiku 模型生成摘要（轻量侧调用）
    3. 返回 [summary_msg] + history_msgs[-keep_recent:]
    """
    to_compress = history_msgs[:-keep_recent]
    recent      = history_msgs[-keep_recent:]

    if not to_compress:
        return history_msgs

    from llm_client import llm_client
    summary_prompt = (
        "以下是一段对话历史，请用 300 字以内的中文摘要，"
        "重点保留用户意图、已完成的操作、待确认的事项：\n\n"
        + "\n".join(
            f"[{m['role']}]: {str(m.get('content',''))[:400]}"
            for m in to_compress
        )
    )
    summary = await llm_client.simple_chat(
        summary_prompt,
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
    )

    summary_msg = {
        "role": "user",
        "content": f"[对话历史摘要（早期）]\n{summary}"
    }
    return [summary_msg] + recent
```

**收益**：长会话不再断裂，不再因 context 满而报错；摘要成本低（haiku 模型）。

---

### P1-2 L5：Memory 类型分类系统（2 天）

**问题**

`save_memory` 写入 `agent_memory` 表，只有 `key/value` 两字段，无类型、无描述、无结构。查询只能全量扫。无法按类型过滤，无法实现"project 类随项目删除"等策略。

**修复方案**

**步骤 1：`agent_memory` 表加类型字段**

```sql
ALTER TABLE agent_memory ADD COLUMN memory_type TEXT DEFAULT 'project';
-- memory_type: user | feedback | project | reference
ALTER TABLE agent_memory ADD COLUMN description TEXT DEFAULT '';
ALTER TABLE agent_memory ADD COLUMN project_id  TEXT DEFAULT NULL;
```

**步骤 2：`MemoryWriteAction` 增加 type 参数**

```python
# backend/actions/chat/memory_write.py

tool_schema = {
    "name": "save_memory",
    "description": "保存一条记忆，供未来对话召回",
    "input_schema": {
        "type": "object",
        "properties": {
            "title":       {"type": "string", "description": "记忆标题（简短）"},
            "content":     {"type": "string", "description": "记忆内容"},
            "memory_type": {
                "type": "string",
                "enum": ["user", "feedback", "project", "reference"],
                "description": (
                    "user=用户偏好/背景；feedback=对 AI 行为的评价/纠正；"
                    "project=项目决策/里程碑；reference=外部系统指针"
                ),
            },
            "description": {
                "type": "string",
                "description": "一行描述，用于后续语义检索判断相关性"
            },
        },
        "required": ["title", "content", "memory_type"],
    }
}
```

**步骤 3：system prompt 注入格式化记忆摘要**

```python
# _build_system_prompt() 中追加记忆段（动态段）

memory_rows = await db.fetch_all(
    "SELECT title, content, memory_type FROM agent_memory "
    "WHERE project_id=? ORDER BY created_at DESC LIMIT 20",
    (project_id,)
)
if memory_rows:
    memory_by_type = {}
    for r in memory_rows:
        memory_by_type.setdefault(r["memory_type"], []).append(
            f"  - **{r['title']}**: {r['content'][:100]}"
        )
    memory_lines = []
    for t, items in memory_by_type.items():
        memory_lines.append(f"\n### [{t}]\n" + "\n".join(items))
    memory_section = "\n## 记忆\n" + "".join(memory_lines)
```

**类型说明（对应 Claude Code 的 4 类型）**

| 类型 | 含义 | 示例 |
|------|------|------|
| `user` | 用户角色、偏好、背景 | "用户是 UE5 资深美术，不熟悉 C++" |
| `feedback` | 对 AI 行为的纠正或确认 | "不要自动提交代码，要等用户确认" |
| `project` | 项目决策、里程碑、技术选型 | "已决定用 GAS 实现技能系统" |
| `reference` | 外部系统指针 | "Bug 追踪在 Linear GAME-xxx 项目" |

**收益**：记忆可检索、可管理、可按类型展示；为后续语义召回奠定基础。

---

### P1-3 L6：Stop Hook（inject + continue）（1 天）

**问题**

QueryEngine 有 `SESSION_END` Hook（用于审计日志），但没有 Claude Code 意义上的 Stop Hook——即：模型停止输出后，Hook 可以**向对话注入新内容并让模型继续**。这是自动记忆提取的触发点。

**修复方案**

在 `QueryEngine.run()` 的 `MessageDoneEvent` 前，加 Stop Hook 阶段：

```python
# backend/query_engine/engine.py  run() 方法

# 在 no tool_calls → 准备结束时：
if not tool_calls:
    # ── Stop Hook：允许注入额外上下文并继续 ──────────────
    if self.hooks:
        injection = await self._run_stop_hooks(context, full_text, round_count)
        if injection:
            # 注入内容 → 追加 user 消息 → 让模型再跑一轮
            current_messages.append({
                "role": "user",
                "content": injection
            })
            # 不 yield MessageDoneEvent，继续循环
            continue

    # 正常结束
    yield MessageDoneEvent(...)
    return

async def _run_stop_hooks(self, context, full_text, rounds) -> str | None:
    """执行 Stop Hook，返回要注入的额外上下文（None 表示不注入）"""
    if not self.hooks:
        return None
    from hooks.types import HookEvent, StopHookContext
    stop_ctx = StopHookContext(
        event=HookEvent.STOP,
        full_text=full_text,
        rounds=rounds,
        project_id=context.get("project_id"),
        agent_type=context.get("agent_type"),
    )
    injections = []
    for fn in self.hooks._hooks:
        if not hasattr(fn, "_is_stop_hook"):
            continue
        try:
            result = await fn(stop_ctx)
            if result:
                injections.append(result)
        except Exception as e:
            logger.warning("Stop Hook %s 失败: %s", fn.__name__, e)
    return "\n".join(injections) if injections else None
```

**收益**：Stop Hook 是自动记忆提取（P2-3）的依赖；也可用于"对话完成后自动总结"等场景。

---

### P1-4 L6：UserPromptSubmit Hook（2 天）

**问题**

文档 §6 中评为"特别重要"。这是在用户消息进入 LLM 之前的最后拦截点，可以：
- 完全阻断（`blockingError`）：合规过滤、敏感词拦截
- 追加上下文（`additionalContexts`）：自动补全需求模板、注入项目规范
- 阻止执行但保留 prompt（`preventContinuation`）：等待外部系统确认

当前 ADS 完全没有这个入口。

**修复方案**

在 `api/chat.py` 流式端点入口处、QueryEngine 启动前插入：

```python
# backend/api/chat.py  stream_chat() 端点

from hooks.registry import hook_registry
from hooks.types import HookEvent, UserPromptHookContext

@router.post("/stream")
async def stream_chat(req: ChatRequest, project_id: str):
    # ── UserPromptSubmit Hook ──────────────────────────────
    prompt_ctx = UserPromptHookContext(
        event=HookEvent.USER_PROMPT_SUBMIT,
        message=req.message,
        project_id=project_id,
        chat_session_id=req.chat_session_id,
    )
    hook_result = await _run_user_prompt_hooks(hook_registry, prompt_ctx)

    if hook_result.blocking_error:
        # 直接返回错误，不进入 LLM
        async def error_stream():
            yield f"data: {json.dumps({'type':'error','message': hook_result.blocking_error})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    # 追加额外上下文到消息末尾
    actual_message = req.message
    if hook_result.additional_contexts:
        actual_message += "\n\n[系统注入]\n" + "\n".join(hook_result.additional_contexts)

    # ... 正常进入 QueryEngine ...
```

**Hook Result 数据类**

```python
# backend/hooks/types.py  新增

@dataclass
class UserPromptHookResult:
    blocking_error:        str | None = None   # 非空 → 拦截并返回错误
    prevent_continuation:  bool = False         # 停止但保留 prompt
    additional_contexts:   list[str] = field(default_factory=list)  # 追加上下文

@dataclass
class UserPromptHookContext:
    event:           HookEvent
    message:         str
    project_id:      str | None = None
    chat_session_id: str | None = None
```

**内置示例 Hook：需求模板补全**

```python
# backend/hooks/builtin.py  新增

async def requirement_template_hook(ctx: UserPromptHookContext) -> UserPromptHookResult | None:
    """当用户消息疑似是需求描述时，自动追加需求模板提示"""
    if ctx.event != HookEvent.USER_PROMPT_SUBMIT:
        return None
    keywords = ["做个", "实现", "添加功能", "开发", "需要一个"]
    if any(kw in ctx.message for kw in keywords) and len(ctx.message) < 100:
        return UserPromptHookResult(
            additional_contexts=[
                "（系统提示：以上内容疑似需求描述，请先调用 confirm_requirement 生成草稿让用户确认，不要直接开始实现）"
            ]
        )
    return None
```

**收益**：为合规审查、自动上下文补全、前置校验提供统一入口。

---

### P1-5 L7：Cost Tracker + nudgeMessage（1 天）

**问题**

Budget 只数 token，不算美元成本。模型不知道自己消耗了多少资源，也不知道"还有多少余量"——高轮次任务里 LLM 会无节制地调工具。

**修复方案**

**步骤 1：LLMClient 累计 USD 成本**

```python
# backend/llm_client.py

MODEL_PRICE_PER_1K = {
    "claude-sonnet-4-6": {"input": 0.003, "output": 0.015,
                          "cache_read": 0.0003, "cache_write": 0.00375},
    "claude-haiku-4-5-20251001": {"input": 0.0008, "output": 0.004},
}

def calculate_cost(model: str, usage: dict) -> float:
    price = MODEL_PRICE_PER_1K.get(model, {})
    total = (
        usage.get("input_tokens",  0) / 1000 * price.get("input",  0) +
        usage.get("output_tokens", 0) / 1000 * price.get("output", 0) +
        usage.get("cache_read_input_tokens",  0) / 1000 * price.get("cache_read",  0) +
        usage.get("cache_creation_input_tokens", 0) / 1000 * price.get("cache_write", 0)
    )
    return round(total, 6)
```

**步骤 2：Budget 新增 USD 追踪和 nudgeMessage**

```python
# backend/query_engine/budget.py

@dataclass
class Budget:
    max_budget_usd: float = 1.0   # 新增：美元上限（0 = 不限）
    _used_usd: float = field(default=0.0, init=False, repr=False)

    def consume(self, tokens=0, turns=0, usd=0.0):
        ...
        self._used_usd += usd

    def get_nudge_message(self) -> str | None:
        """token 使用率 > 70% 时返回提示，注入 user 消息提醒模型"""
        if self.max_tokens <= 0:
            return None
        ratio = self._used_tokens / self.max_tokens
        if ratio > 0.9:
            return f"[系统提示：已消耗 {ratio:.0%} 的 token 预算，请尽快给出最终答复]"
        if ratio > 0.7:
            return f"[系统提示：已消耗 {ratio:.0%} 的 token 预算，请精简工具调用]"
        return None
```

**步骤 3：QueryEngine 在每轮后注入 nudgeMessage**

```python
# backend/query_engine/engine.py

# consume 预算后，若有 nudge 则追加到 tool_results 末尾
nudge = self.budget.get_nudge_message()
if nudge and tool_calls:
    tool_results.append({
        "type": "tool_result",
        "tool_use_id": "nudge",
        "content": nudge,
    })
```

**收益**：美元成本可见（前端 `/cost` 查询）；模型感知预算余量，自动精简输出。

---

## 四、P2 — 完整性缺口（3 周，对标 Claude Code 全功能）

### P2-1 L1：Side Query 基础设施（2 天）

**价值**

Side Query 是语义记忆召回（P2-2）和自动记忆提取（P2-3）的共同基础设施。它允许用轻量模型（haiku）发起不污染主会话历史的独立 LLM 调用，用于分类、筛选、摘要等辅助任务。

**实现**

```python
# backend/llm_client.py  新增方法

async def side_query(
    self,
    prompt: str,
    *,
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 500,
    output_schema: dict | None = None,   # JSON Schema 结构化输出
    query_source: str = "side_query",
) -> str | dict:
    """
    独立轻量侧查询，不进入主会话历史，不触发 Hooks，不消耗主 Budget。
    返回：output_schema 为 None 时返回文本，否则返回 dict。
    """
    messages = [{"role": "user", "content": prompt}]
    tools = []
    if output_schema:
        tools = [{
            "name": "output",
            "description": "输出结构化结果",
            "input_schema": output_schema,
        }]

    result = await self._call_anthropic(
        messages=messages,
        model=model,
        max_tokens=max_tokens,
        tools=tools if tools else None,
        system="你是一个精准的分类助手，只返回所要求格式的内容。",
    )

    if output_schema:
        # 提取 tool_use 块的 input 作为结构化输出
        for block in result.get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == "output":
                return block.get("input", {})
        return {}
    return result.get("text", "")
```

---

### P2-2 L5：语义记忆召回（2 天，依赖 P2-1 + P1-2）

**实现**

每次对话开始时（在 `_build_system_prompt()` 里），用 Side Query 扫描 `agent_memory` 表的 title + description，选出最相关的记忆注入本轮 context：

```python
# backend/agents/chat_assistant.py  _build_system_prompt()

async def _recall_relevant_memories(
    self, user_message: str, project_id: str, top_k: int = 5
) -> list[dict]:
    """用 haiku Side Query 语义筛选最相关的记忆"""
    from database import db
    from llm_client import llm_client

    all_memories = await db.fetch_all(
        "SELECT id, title, description, memory_type, content FROM agent_memory "
        "WHERE project_id=? ORDER BY created_at DESC LIMIT 50",
        (project_id,)
    )
    if not all_memories:
        return []

    manifest = "\n".join(
        f"[{i}] ({m['memory_type']}) {m['title']}: {m.get('description','')}"
        for i, m in enumerate(all_memories)
    )

    result = await llm_client.side_query(
        f"用户消息：{user_message[:200]}\n\n可用记忆列表：\n{manifest}\n\n"
        f"请选出最相关的至多 {top_k} 条记忆的编号，JSON 格式：{{\"selected\": [0,2,...]}}",
        output_schema={
            "type": "object",
            "properties": {"selected": {"type": "array", "items": {"type": "integer"}}},
            "required": ["selected"],
        },
        query_source="memory_recall",
    )
    selected_idx = result.get("selected", [])[:top_k]
    return [all_memories[i] for i in selected_idx if i < len(all_memories)]
```

---

### P2-3 L5：自动记忆提取（2 天，依赖 P2-1 + P1-3）

**实现**

Stop Hook 触发后，异步用 Side Query 分析本轮对话，判断有无值得持久化的信息：

```python
# backend/hooks/memory_extract_hook.py

async def auto_extract_memory_hook(ctx) -> str | None:
    """Stop Hook：分析对话，自动提取并保存有价值的记忆"""
    if ctx.event != HookEvent.STOP or not ctx.project_id:
        return None

    from llm_client import llm_client

    result = await llm_client.side_query(
        f"以下是一轮 AI 助手对话的输出：\n{ctx.full_text[:800]}\n\n"
        "请判断其中是否包含值得记忆的信息（用户偏好/行为反馈/项目决策/外部资源指针），"
        "有则输出，没有则 items 为空数组。",
        output_schema={
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title":       {"type": "string"},
                            "content":     {"type": "string"},
                            "memory_type": {"type": "string",
                                            "enum": ["user","feedback","project","reference"]},
                            "description": {"type": "string"},
                        },
                        "required": ["title", "content", "memory_type"],
                    }
                }
            }
        },
        query_source="auto_extract_memory",
    )

    items = result.get("items", [])
    if not items:
        return None

    from database import db
    from utils import generate_id, now_iso
    for item in items[:3]:   # 每轮最多提取 3 条
        await db.execute(
            "INSERT OR IGNORE INTO agent_memory "
            "(id, project_id, memory_type, title, content, description, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (generate_id(), ctx.project_id, item["memory_type"],
             item["title"], item["content"], item.get("description",""), now_iso())
        )
    return None  # Stop Hook 不需要注入
```

---

### P2-4 L2：File History Snapshots（1 天）

**实现**

在 `_ChatToolExecutor` 里加 session 级别的文件快照（内存，对话结束后丢弃）：

```python
# backend/agents/chat_assistant.py  _ChatToolExecutor

class _ChatToolExecutor:
    def __init__(self, ...):
        ...
        self._file_snapshots: dict[str, str] = {}   # path → content_before

    async def execute(self, tool_name, tool_input):
        # 写操作前保存快照
        if tool_name == "shell":
            cmd = tool_input.get("command", "")
            self._snapshot_affected_files(cmd)
        ...

    def _snapshot_affected_files(self, command: str):
        """从 shell 命令推断可能被修改的文件，提前快照"""
        import re
        # 简单匹配：> file、>> file、tee file 等写入模式
        for pattern in [r'>\s*(\S+)', r'>>\s*(\S+)', r'tee\s+(\S+)']:
            for match in re.finditer(pattern, command):
                path = match.group(1)
                if path not in self._file_snapshots:
                    try:
                        self._file_snapshots[path] = Path(path).read_text(
                            encoding="utf-8", errors="ignore"
                        )
                    except FileNotFoundError:
                        self._file_snapshots[path] = ""  # 新文件，快照为空

    def undo_last_write(self) -> list[str]:
        """回滚所有已快照文件（暴露给 /undo 命令）"""
        restored = []
        for path, content in self._file_snapshots.items():
            try:
                Path(path).write_text(content, encoding="utf-8")
                restored.append(path)
            except Exception:
                pass
        self._file_snapshots.clear()
        return restored
```

---

### P2-5 L10：Plan Mode（写操作全量审批）（2 天）

**实现**

ChatAssistant 接受 `plan_mode: bool` 参数时，所有写类工具进入 PermissionGate 等待审批：

```python
# backend/permissions/gate.py  detect_risk() 扩展

# Plan Mode 下的写工具列表（优先级高于常规高风险规则）
_PLAN_MODE_WRITE_TOOLS = {
    "shell", "generate_document", "confirm_save_doc",
    "git_merge", "create_github_repo",
}

def detect_risk(tool_name: str, tool_input: dict, plan_mode: bool = False) -> str | None:
    if plan_mode and tool_name in _PLAN_MODE_WRITE_TOOLS:
        return f"Plan Mode：{tool_name} 写操作需要确认"
    # ... 原有高风险规则 ...
```

前端在发起请求时可通过 `?plan_mode=true` 参数开启，AI 助手在 Plan Mode 下只读不写，所有写操作挂起等待用户点击"确认执行"。

---

## 五、P3 — 战略性特性（按需）

### P3-1 L4：多策略压缩

在基础 Compaction（P1-1）之上扩展：
- **Micro Compact**：仅压缩工具调用链，保留用户/助手对话原文（用于精确 debug）
- **Auto Compact**：context window 使用率 > 80% 时自动触发，不需用户手动 `/compact`
- **Session Memory Compact**：压缩时顺便触发 P2-3 的记忆提取（复用 Side Query）

### P3-2 L8：并行子 Agent + Worktree 隔离

`dispatch_subtask` 已实现顺序派发。扩展为：
- 并行创建多个子 Ticket，Orchestrator 并发执行
- 每个子 Agent 在独立 git worktree 分支操作，合入时走标准 PR 流程

### P3-3 L9：运行时 Feature Flag

每次 chat 请求携带 `features: dict` 字段，可覆盖 `settings` 中的静态开关，支持按会话灰度测试新能力（如新版 Memory 召回、Plan Mode、新工具集）。

---

## 六、优先级总表与工作量估算

| 优先级 | 改进项 | 层 | 工作量 | 核心收益 |
|--------|--------|-----|--------|---------|
| **P0** | Rules 层注入 | L5 | 1 天 | 全局规范对 ChatAssistant 生效 |
| **P0** | Diminishing Returns 检测 | L1 | 半天 | 防 token 无效空转 |
| **P0** | Prompt Cache 分区 + 工具排序 | L3 | 1 天 | API 成本降 30-50% |
| **P0** | File State Cache | L2 | 1 天 | 防文件静默覆盖 |
| **P1** | 基础 Context Compaction | L4 | 3 天 | 长会话不断裂 |
| **P1** | Memory 类型分类 | L5 | 2 天 | 记忆可检索可管理 |
| **P1** | Stop Hook（inject+continue）| L6 | 1 天 | 支撑记忆自动提取 |
| **P1** | UserPromptSubmit Hook | L6 | 2 天 | 合规拦截/上下文注入入口 |
| **P1** | Cost Tracker + nudgeMessage | L7 | 1 天 | 费用可见 + 模型感知余量 |
| **P2** | Side Query 基础设施 | L1 | 2 天 | 语义召回的依赖 |
| **P2** | 语义记忆召回 | L5 | 2 天 | 记忆真正被使用 |
| **P2** | 自动记忆提取 | L5 | 2 天 | 记忆自动积累 |
| **P2** | File History Snapshots | L2 | 1 天 | session 内可撤销 |
| **P2** | Plan Mode（写操作审批）| L10 | 2 天 | 精确控制写操作 |
| **P3** | 多策略压缩 | L4 | 3 天 | 长期稳定性 |
| **P3** | 并行子 Agent + Worktree | L8 | 大 | 任务并发能力 |
| **P3** | 运行时 Feature Flag | L9 | 中 | 灰度能力 |

---

## 七、预期效果

| 完成阶段 | 综合得分 | 主要收益 |
|---------|---------|---------|
| 当前 | 5.5 / 10 | — |
| P0 完成后 | 6.5 / 10 | API 成本降 30%，Rules 生效，防数据丢失 |
| P1 完成后 | 7.5 / 10 | 长会话可用，记忆有结构，费用透明 |
| P2 完成后 | 8.5 / 10 | 记忆自动积累，对标 Claude Code 主要特性 |
| P3 完成后 | 9.0 / 10 | 并发、灰度、多策略压缩，企业级稳定性 |

---

## 八、参考文档索引

| 文档 | 内容 |
|------|------|
| `20260516_09_对标ClaudeCode的AI助手基础设施清单.md` | 10 层框架定义与 WorkBuddy 对标分析（本文的框架来源）|
| `20260513_05_ADS补全Harness缺失特性方案.md` | P0-4 File State Cache、P1-1 Compaction 的详细实现背景 |
| `20260513_06_ADS升级为完整Harness平台战略方案.md` | Harness 三圈层模型，P0-1 Rules 注入的战略位置 |
| `20260513_07_ADS进化路线图-综合启发.md` | P1-2 Memory 分类、P2-3 自动记忆提取的完整灵感来源 |
| `20260515_08_ClaudeCode与WorkBuddy架构深度对比.md` | P2-1 Side Query、L3 Prompt Cache 分区的参考实现 |
