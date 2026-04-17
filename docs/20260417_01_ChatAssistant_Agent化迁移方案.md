# ChatAssistant Agent 化迁移方案

> 日期: 2026-04-17 | 对标: MetaGPT Role+Action 模式 + 本系统 `BaseAgent`

---

## 一、背景与动机

### 1.1 现状诊断

`backend/api/chat.py`（AI 助手对话入口）在本系统架构中是个**伪 Agent**：

| 要素 | BaseAgent 子类（DevAgent / ProductAgent 等） | chat.py 当前状态 |
|---|---|---|
| 继承 `BaseAgent` | ✅ | ❌（就是 FastAPI router） |
| 注册到 `agent_registry` | ✅（6 个） | ❌ |
| Action 类（独立 `run()`） | ✅ 每能力一 Action | ❌ 硬编码在 `_execute_*` 函数 |
| 状态机 / ReactMode | ✅ SINGLE/BY_ORDER/REACT | ❌ 单次请求-响应 |
| watch / subscribe | ✅ `watch_actions` | ❌ |
| Memory | ✅ `self._memory` | ❌ 靠 `chat_messages` 表临时拼 history |

它实际运行方式：**路由处理器 → 拼系统提示词 → 调一次 llm → 用正则抓 `[ACTION:XXX]` 文本标记 → 分发到执行函数**。日志里虽然挂了 `agent_type="ChatAssistant"` 的牌子，但那只是日志标签，没有架构实体。

### 1.2 伪 Agent 模式带来的具体问题

- **解析器脆弱**：2026-04-17 出现 bug——AI 一条回复里发两个 `[ACTION:...]` 块，贪婪正则 `\{.*\}` 跨越多个块，JSON 解析失败，所有 action 都不执行。
- **prompt 臃肿**：`_build_system_prompt` 要给 LLM 塞整套 `[ACTION:XXX]` 文本协议说明，占用大量 token。
- **"说到做到"失败**：LLM 容易只说"让我查看 XX"但忘记附 `[ACTION:...]`，导致"光说不做"。
- **无法复用 Agent 基础设施**：不能注册到 agent_registry、不能被群聊 tab 发现、没有 memory、无法被 orchestrator 调度。
- **能力散落**：`_execute_generate_document`、`_execute_git_action` 等函数是事实上的 Action，但没继承 `ActionBase`，不能单测也不能被其他 Agent 复用。

### 1.3 对标 MetaGPT

MetaGPT 公式：`Agent = LLM + Observation + Thought + Action + Memory`
MetaGPT 做法：**Role 持有 Actions，Action 是能力一等公民，Agent 通过 tool_use 让 LLM 动态选择**。

本系统已经移植了 `BaseAgent` / `ActionBase` 并在 6 个 Agent 上落地，chat.py 是唯一的"漏网之鱼"。

---

## 二、目标架构

### 2.1 核心原则

1. **Action 是一等公民**：chat 的每个能力（确认需求、Git 操作、生成文档、管理需求状态）独立为 `ActionBase` 子类。
2. **ChatAssistantAgent 继承 BaseAgent**：`react_mode = REACT`，LLM 动态选择 action。
3. **用 tool_use 替代文本协议**：直接调 `llm_client.chat_with_tools`（已有，`llm_client.py:447`），彻底抛弃 `[ACTION:XXX] {...} [/ACTION]` 正则协议。
4. **路由层瘦身**：`chat.py` 只管 HTTP、上下文构建、消息持久化，不再做能力分发。

### 2.2 目标文件结构

```
backend/
  agents/
    chat_assistant.py              ← 新增 ChatAssistantAgent(BaseAgent)
  actions/
    chat/                          ← 新增目录
      __init__.py
      confirm_requirement.py       # 返回确认卡片（不直接创建）
      confirm_bug.py
      pause_requirement.py
      resume_requirement.py
      close_requirement.py
      generate_document.py
      git_log.py
      git_list_branches.py
      git_switch_branch.py
      git_read_file.py
      git_merge.py
  api/
    chat.py                        ← 瘦身：路由 + 上下文 + 调 agent
```

### 2.3 核心代码骨架

**Action 带 tool_schema**（Anthropic tool-use 格式）：

```python
# actions/chat/git_log.py
class GitLogAction(ActionBase):
    @property
    def name(self) -> str: return "git_log"

    @property
    def description(self) -> str:
        return "查看当前分支最近的提交记录"

    @property
    def tool_schema(self) -> dict:
        return {
            "name": "git_log",
            "description": "查看当前分支最近的 git 提交记录。用户问『最近提交了什么』『git log』时调用。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "返回条数，默认 10"}
                },
                "required": [],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        project_id = context["project_id"]
        limit = context.get("limit", 10)
        # ... 实际 git log 逻辑
        return ActionResult(success=True, data={"commits": [...]})
```

**ChatAssistantAgent**：

```python
# agents/chat_assistant.py
class ChatAssistantAgent(BaseAgent):
    action_classes = [
        ConfirmRequirementAction,
        ConfirmBugAction,
        PauseRequirementAction,
        ResumeRequirementAction,
        CloseRequirementAction,
        GenerateDocumentAction,
        GitLogAction,
        GitListBranchesAction,
        GitSwitchBranchAction,
        GitReadFileAction,
        GitMergeAction,
    ]
    react_mode = ReactMode.REACT
    max_react_loop = 3   # 聊天场景不需太多轮

    @property
    def agent_type(self) -> str: return "ChatAssistant"

    async def chat(self, user_message: str, project_ctx: dict, history: list) -> dict:
        """入口：路由层调用此方法"""
        system_prompt = self._build_system_prompt(project_ctx)  # 瘦身版
        tools = [a.tool_schema for a in self._actions.values()]
        messages = self._build_messages(history, user_message)

        result = await llm_client.chat_with_tools(
            messages=messages,
            tools=tools,
            tool_executor=self,   # 需实现 async execute(name, input)
            system=system_prompt,
            max_rounds=self.max_react_loop,
        )
        return self._format_reply(result)

    async def execute(self, tool_name: str, tool_input: dict) -> str:
        """tool_executor 协议：dispatch 到对应 Action"""
        action = self._actions.get(tool_name)
        if not action:
            return f"未知工具: {tool_name}"
        result = await action.run({**tool_input, **self._ambient_context})
        return json.dumps(result.to_dict(), ensure_ascii=False)
```

**chat.py 瘦身后**：

```python
@global_chat_router.post("/{project_id}/message")
async def send_message(project_id: str, req: ChatRequest):
    project = await db.fetch_one(...)
    project_ctx = await _build_project_context(project_id, project)
    history = await _load_history(project_id)

    agent = agent_registry.get("ChatAssistant")
    reply = await agent.chat(req.message, project_ctx, history)

    await _persist_message(...)  # 原有持久化
    return ChatResponse(reply=reply["text"], action=reply.get("action"))
```

---

## 三、分阶段实施计划

### P1 — 抽 Action（机械性重构，风险低）

**目标**：把 `chat.py` 里的 `_execute_*` 函数搬成独立的 `ActionBase` 子类，暂不接入 agent 体系。

**步骤**：
1. 新建 `backend/actions/chat/` 目录
2. 逐个迁移：
   - `_execute_create_requirement` → `CreateRequirementAction`（内部用）
   - `_execute_pause_requirement` → `PauseRequirementAction`
   - `_execute_resume_requirement` → `ResumeRequirementAction`
   - `_execute_close_requirement` → `CloseRequirementAction`
   - `_execute_generate_document` → `GenerateDocumentAction`
   - `_execute_git_action` 按 5 种子操作拆成 5 个 Action
   - `CONFIRM_REQUIREMENT` / `CONFIRM_BUG` → 返回确认卡片的 Action
3. 每个 Action 补上 `tool_schema` 属性
4. `chat.py` 里 `_parse_and_execute_action` 改调新 Action（保留旧正则协议）
5. **单测**：每个 Action 写一个最小测试

**产出**：11 个 Action 类 + 单测；chat.py 行数下降但逻辑等价。

**工期**：0.5–1 天。

---

### P2 — 新建 ChatAssistantAgent（双轨运行，风险低）

**目标**：agent 跑起来，但**不切换**入口——仍走旧正则协议，用 feature flag 在少数会话上试用 agent 路径。

**步骤**：
1. 新建 `agents/chat_assistant.py`
2. 注册到 `agent_registry`
3. `chat.py` 加一个 feature flag（环境变量 `CHAT_USE_AGENT=1`）：
   - flag=on：走 `agent.chat(...)` + tool_use
   - flag=off：走旧路径
4. 在自己的项目上开 flag，观察 1–2 天

**产出**：可切换的双路径；日志里对比 tool_use vs 文本协议的成功率。

**工期**：0.5 天 + 1–2 天观察。

---

### P3 — 切换到 tool_use（风险中）

**目标**：默认走 agent 路径，旧路径降级兜底。

**步骤**：
1. `CHAT_USE_AGENT` 默认 `=1`
2. 监控：Action 执行成功率、LLM token 消耗、响应延迟
3. 任何 tool_use 失败自动 fallback 到旧文本协议（保留 `_parse_and_execute_action` 作 backup）
4. 系统提示词 `_build_system_prompt` 删除 `## 操作指令格式` 整段（LLM 改从 `tools` schema 认识能力）
5. 观察 3–5 天

**产出**：主路径为 tool_use；提示词瘦身显著（省下可观 token）。

**工期**：0.5 天 + 3–5 天观察。

---

### P4 — 清理（风险低）

**目标**：删除旧协议代码。

**步骤**：
1. 删除 `chat.py` 中：`_parse_and_execute_action`、`_try_fix_json`、所有旧 `_execute_*` 包装
2. 删除系统提示词里关于 `[ACTION:XXX]` 的任何残留
3. 删除 feature flag，统一走 agent

**产出**：chat.py 从当前 ~1300 行瘦到约 300–400 行。

**工期**：0.5 天。

---

## 四、权限模型：Action 即权限

这是 Agent 化除"解耦、可测、可复用"之外的另一个关键价值点——**AI 助手能做什么，完全由 `action_classes` 列表决定**。

### 4.1 现状：权限散落两处，必须双向同步

当前 `chat.py` 的"权限"其实藏在两个地方：

1. **系统提示词**：`_build_system_prompt` 里列出 `## 操作指令格式`，告诉 LLM 可以发哪些 `[ACTION:XXX]`
2. **解析器白名单**：`_parse_and_execute_action` 里的 `if/elif` 链（`chat.py:1180` 开始）
   ```python
   if action_type == "CONFIRM_REQUIREMENT": ...
   elif action_type == "CONFIRM_BUG": ...
   elif action_type.startswith("GIT_"): ...
   # 未列出的 action_type 最终走到 logger.warning("未知操作类型")
   ```

两处必须同步维护：
- 加能力 → 改 prompt + 加 elif 分支
- 去能力 → 删 prompt + 删 elif 分支
- **任一处漏改**：要么 LLM 不知道这能力存在，要么它发了但执行不到

### 4.2 迁移后：Action 集合即权限，单一真源

```python
class ChatAssistantAgent(BaseAgent):
    action_classes = [
        GitLogAction,
        ConfirmRequirementAction,
        GenerateDocumentAction,
        # ...
    ]
```

调用 LLM 时 tools 自动生成：

```python
tools = [a.tool_schema for a in self._actions.values()]
```

**LLM 只看得到这些工具的 schema，其他能力它压根不知道存在**——这是 Anthropic tool_use 的原生机制，比"prompt 里说有 + 解析器查白名单"的双保险更强：
- LLM 无法幻觉出一个不存在的工具名（schema 里没有就没法发）
- 即使幻觉出来了，也进不了执行路径（没注册就没法 dispatch）

### 4.3 新的能力管理语义

| 操作 | 现状（旧） | 迁移后（新） |
|---|---|---|
| 加能力 | 改 prompt + 加 elif + 写 `_execute_xxx` | 写一个 Action 类 + 加到 `action_classes` |
| 去能力 | 改 prompt + 删 elif（易漏） | 从 `action_classes` 移除一行 |
| 禁用某能力（不删代码） | 只能注释 elif（LLM 仍会去发） | 从 `action_classes` 移除，LLM 立即看不见 |
| 按环境裁剪 | 需要多份 prompt + 运行时判断 | `action_classes` 按 env 拼装 |

### 4.4 按环境差异化 Agent（未来价值）

```python
# 生产环境：去掉 GitMergeAction，避免 AI 误合分支
class ProdChatAgent(ChatAssistantAgent):
    action_classes = [a for a in ChatAssistantAgent.action_classes if a is not GitMergeAction]

# 只读查看 Agent：只保留查询类
class ReadOnlyChatAgent(ChatAssistantAgent):
    action_classes = [GitLogAction, GitListBranchesAction, GitReadFileAction]
```

同样的 agent 内核，通过 `action_classes` 剪裁得到不同权限的变体——这在旧架构里做不到（prompt 和 parser 都要改两份）。

### 4.5 审计与可观测

- `agent_registry` 里列出 Agent + 列 Actions → 可以在运维面板上直接看"这个 Agent 能干哪些事"
- Action 调用次数、成功率天然可按 action_name 聚合（已有 `ticket_logs` / `llm_conversations` 表）
- 权限变更可追溯到 git 里 `action_classes` 的 diff，而不是散落在 prompt 字符串中

---

## 五、附带收益

1. **群聊无缝接入**：`ChatAssistantAgent` 注册后，群聊 tab 可以直接像调用 DevAgent 一样调用它。
2. **单测可写**：每个 Action 独立，可针对 Git 操作、需求确认写精细单测。
3. **Memory 规范化**：可复用 `BaseAgent._memory` + `watch_actions`，替代目前用 `chat_messages` 表临时拼 history 的做法——agent 可以"记得"用户上次讨论过哪些需求。
4. **tool_use 天然鲁棒**：
   - 不会有"两个 action 撞车"的正则 bug
   - 不会有"说到做到"失败（tool_use 没喊出来就是没调）
   - LLM 可在同一轮内**多次**调工具并根据结果调整（REACT 的真正价值）
5. **Token 成本下降**：砍掉 `## 操作指令格式` 整段，每次对话节省 ~800–1000 token。

---

## 六、风险与权衡

| 风险 | 缓解 |
|---|---|
| tool_use 在代理（api-skynetyu.woa.com）上兼容性未知 | P2 双轨运行时做对照；`llm_client.chat_with_tools` 已验证过其他 Agent 正常工作 |
| 原有前端依赖 `action` 字段的结构（如 `confirm_requirement` 卡片） | Action 的返回格式保持与现有 `_execute_*` 一致，前端不改 |
| REACT 模式的 loop 成本（一次对话可能 2–3 次 LLM 调用） | `max_react_loop=3` 限死；监控 token；必要时降级 `max_react_loop=1` 变相等价 SINGLE |
| Memory 引入可能改变对话语义 | P1–P4 期间保持用现有 history 拼法，Memory 是 P4 之后的独立增强 |

---

## 七、不在本方案范围

- **群聊的 GroupChat 改造**（`GroupChatRequest` / `_AGENT_CONFIG`）：本方案只处理单 Agent 对话；群聊后续独立评估。
- **chat_messages 表 schema 变更**：保持不变，history 机制不动。
- **SSE / WebSocket 推送**：原样保留。

---

## 八、P0 代理兼容性验证（已完成 · 2026-04-17）

### 8.1 验证背景

迁移方案依赖 Anthropic 原生 `tool_use` 机制（请求体带 `tools` 字段、响应含 `tool_use` block、`stop_reason=tool_use`）。代码 `llm_client.chat_with_tools` 虽已实现，但在企业代理 `api-skynetyu.woa.com/anthropic` 上从未被调用过，需先验证代理是否透传 `tools` 字段并正确返回 `tool_use` 响应。

另一个担忧：前面出现过 `context_management: Extra inputs are not permitted` 这种代理对未知字段严格拒绝的前科，`tools` 作为相对新的字段也可能遭遇类似问题。

### 8.2 验证脚本

`backend/_test_tool_use.py`——独立脚本，不依赖数据库/事件总线/agent_registry，仅跑一轮最小 ReAct：
- 定义 1 个假工具 `get_weather`（输入 `{city}`，返回固定 `{temp: "22°C", weather: "晴"}`）
- 用户消息："帮我查一下北京现在的天气怎么样？"
- 预期：LLM 触发 `tool_use` → 执行器返回结果 → LLM 基于结果出最终自然语言回复

运行命令：
```bash
cd backend
PYTHONIOENCODING=utf-8 python _test_tool_use.py
```

### 8.3 验证结果

| 指标 | 期望 | 实测 | 结论 |
|---|---|---|---|
| HTTP 状态 | 200 | 200 × 2（两轮各一次） | ✅ |
| `stop_reason` | `tool_use` → `end_turn` | 第 1 轮 tool_use、第 2 轮 end_turn | ✅ |
| `tool_use` block 数 | ≥ 1 | 1 | ✅ |
| `tool_result` block 数 | ≥ 1 | 1 | ✅ |
| LLM 基于工具结果作答 | 是 | "温度 22°C、晴……阳光明媚，是个外出活动的好天气" | ✅ |
| 总轮数 | ≤ max_rounds (5) | 2 | ✅ |

**判定**：企业代理 `api-skynetyu.woa.com/anthropic` 对 Anthropic 原生 `tools` 字段**完全兼容**，tool_use 请求-响应-续发全链路可用。

### 8.4 结论与影响

- 迁移方案的 **P1（抽 Action）/ P2（ChatAssistantAgent + tool_use）/ P3（切换默认路径）可按原计划推进**，不需要降级为"保留文本协议 + Action 结构化"的备选路线。
- 之前见到的 `context_management: Extra inputs are not permitted` 报错与本后端 → 代理的链路无关——那是 Claude Code 客户端自己发到代理的请求里带的字段，代理对该字段单独拒绝，不影响本项目的 API 调用。
- `_test_tool_use.py` 保留在仓库作为回归验证脚本：如果后续代理升级或切换其他 LLM 后端，可再次运行快速确认 tool_use 仍可用。

---

## 九、开工前 Checklist

- [x] 确认 `llm_client.chat_with_tools` 在当前 LLM 代理（`api-skynetyu.woa.com/anthropic`）上稳定——**已于 2026-04-17 通过 `_test_tool_use.py` 验证**（见第八章）
- [ ] 确认前端 `action` 字段消费点（应在 `frontend/` 的 chat 组件），记录现有契约
- [ ] 备份 `chat.py` 当前版本（git 已有）
- [ ] 选定一个测试项目（建议 HelloWorld）作为 P2 双轨观察对象

---

**建议起点**：P1 机械抽取（低风险、可分提交），每抽一个 Action 就 commit 一次，方便回退。
