# Everything Claude Code 对 ADS 的启发与借鉴方案

> 日期：2026-05-13
> 研究对象：`F:\A_Works\everything-claude-code`（ECC v2.0.0-rc.1，Anthropic Hackathon 获奖项目）
> 定位：架构决策文档，面向 ADS 技术负责人

---

## 一、研究背景

Everything Claude Code（简称 ECC）是一套针对 AI 代码助手的**生产级性能优化插件集**，历经 10+ 个月密集开发，积累了：

- **60 个**专属 Agent 定义
- **228 个**工作流 Skill
- **75 个**斜线命令
- 完整的 Hook 拦截体系（PreToolUse / PostToolUse）
- AgentShield 安全防护层（独立 npm 包 `ecc-agentshield`）
- `ecc2/` Rust 控制平面 alpha

ECC 与 ADS 的**定位差异**决定了启发的性质：ECC 是"如何让 Claude Code 更好地工作于任意项目"的**元工具层**；ADS 是"让 AI 代理自主完成软件开发任务"的**执行平台**。两者解决的问题不同，但 ECC 在以下几个子系统上的工程实践对 ADS 有直接参考价值。

---

## 二、ADS 现状速览（作为对比基线）

| 子系统 | ADS 现状 | 成熟度 |
|--------|---------|-------|
| 多 Agent 编排 | Orchestrator + SOP YAML 状态机，6 Role | ★★★ |
| Skill 注入 | 三层过滤（inject_to / traits_match / paths） + 主动触发 | ★★★ |
| 失败记忆 | Failure Library（跨工单检索 + Reflexion 反思） | ★★★ |
| Hook 体系 | PRE/POST_TOOL_USE + TOOL_ERROR，内置 3 个 hook | ★★ |
| 记忆持久化 | save_memory 工具（AI 主动调用） | ★★ |
| 成功经验沉淀 | 有方案（20260509_04），未实现 | ★ |
| 沙箱执行验证 | 规划中（v1.0 阶段九） | ★ |
| Shell 安全防护 | 关键词白名单 | ★ |
| 跨 Harness 支持 | 单一系统 | ★ |

---

## 三、ECC 核心能力解构

### 3.1 Hook 流水线（最核心的运行时架构）

ECC 的 Hook 架构远超简单的回调注册，它是一套**分层、可分级、运行时可控**的拦截体系：

```
工具调用请求
    ↓
PreToolUse Hooks（阻塞，<200ms，按 matcher 分发）
    ├── pre:bash:dispatcher          # 危险命令拦截（GateGuard）
    ├── pre:write:doc-file-warning   # 文档文件写入警告
    ├── pre:edit-write:suggest-compact # 手动压缩提示
    ├── pre:observe:continuous-learning (async) # 连续学习观察
    └── pre:governance-capture       # 治理事件捕获（secrets/policy）
    ↓
工具执行
    ↓
PostToolUse Hooks（阻塞/异步）
    ├── post:auto-commit             # 自动提交
    ├── post:format-on-edit          # 格式化
    └── post:session-persist         # 会话持久化
    ↓
Stop Hooks（会话结束）
    └── session memory export
```

**关键设计：`run-with-flags.js` 包装器**

所有 Hook 通过统一包装器执行，支持：
- `ECC_HOOK_PROFILE=standard|strict`：运行时分级（标准 vs 严格模式）
- `ECC_DISABLED_HOOKS=hook-id1,hook-id2`：运行时禁用特定 Hook
- 每个 Hook 声明自己支持哪些 profile（`standard,strict`），不匹配则跳过

```js
// 调用示例（hooks.json 内）
"command": "node scripts/hooks/run-with-flags.js pre:bash:dispatcher scripts/hooks/pre-bash-dispatcher.js standard,strict"
```

### 3.2 GateGuard：Token 级危险命令防护

ECC 的 Shell 安全不是简单的关键词黑名单，而是对 Bash 命令做**词法分析级**解析：

```
命令字符串
    ↓
Tokenizer（识别管道/重定向/子命令嵌套/引号）
    ↓
命令树提取
    ↓
每个原子命令独立过滤
    ├── 直接命令：检查命令名
    ├── $(...) 子命令嵌套：递归检查
    ├── | 管道末端：独立检查
    └── > 重定向目标：检查目标路径
    ↓
任意命令触发规则 → exit code 2（阻塞）
全部通过 → exit code 0（放行）
```

与 ADS 关键词白名单的本质差异：
- ADS：`if "rm -rf" in command: block` → 可被 `rm  -rf`（双空格）或 `$(rm -rf /)` 绕过
- ECC：先 tokenize，再对每个 token 独立判断 → 防绕过

### 3.3 Observe Runner：异步连续学习

ECC 的每次工具调用（不区分成功/失败）都会触发一个**异步观察 Hook**：

```
每次工具调用（async, timeout=10s）
    ↓
observe-runner.js
    ↓
记录：tool_name / input / output / duration / success
    ↓
定期批量分析：模式提炼
    ↓
候选 Skill 文件写入 ~/.claude/skills/
（自动命名：observed-pattern-{hash}.md）
```

与 ADS 的关键区别：ECC 在**每次工具调用**时都在学习，不依赖 acceptance_passed 触发点。模式识别是持续的，低延迟的。

### 3.4 Verification Loop 设计哲学

ECC 的 `skills/verification-loop/SKILL.md` 系统化描述了验证循环的设计模式，涵盖：

| 概念 | ECC 定义 | 适用场景 |
|------|---------|---------|
| Checkpoint Eval | 在流水线特定节点运行完整测试套件 | 阶段性验收 |
| Continuous Eval | 每次 LLM 输出后立即验证 | 实时质量监控 |
| pass@k | 采样 k 次，取通过率而非单次结果 | 非确定性代码生成 |
| Grader 分层 | Unit → Integration → E2E → LLM-as-Judge | 成本/精度权衡 |
| Oracle Grader | 对比黄金标准输出 | 有参考答案时 |
| Heuristic Grader | 规则打分（行数/复杂度/lint） | 快速初筛 |

### 3.5 Memory Persistence：Hook 驱动 vs 工具调用驱动

ECC 的记忆持久化通过 **session 级 Hook** 自动执行，不依赖 AI 决策：

```
SessionStart Hook → 加载 ~/.claude/memory/*.md → 注入 system prompt
                                                        ↓
                                                   对话进行中
                                                        ↓
PostToolUse Hook（save_memory 触发条件命中）→ 自动写文件
                                                        ↓
SessionStop Hook → 扫描对话关键实体 → 写入 memory/ → 下次可用
```

ADS 当前模式：`save_memory` 是一个工具，LLM 必须主动决策调用，存在遗漏风险。

### 3.6 Skill 治理策略（SKILL-PLACEMENT-POLICY）

ECC 有一份正式的 Skill 放置策略文档，将 Skill 按来源和性质分类：

```
skills/（已审核，随系统发布）
    ↑ 人工 review + PR 合并

~/.claude/skills/（用户安装 / 系统生成）
    ├── 从 marketplace 安装的 Skill
    └── observe-runner 自动生成的候选 Skill（未审核）
```

关键规则：**自动生成的 Skill 不直接进入 `skills/`**，必须经过人工确认才能提升。

---

## 四、ADS 可借鉴的具体方向

### 4.1 Hook 体系：增加 Profile 分级机制

**当前问题**

`hooks/builtin.py` 中 `shell_rate_limit_hook` 的阈值（50次/ticket）写死，无法按项目类型调整。对 UE 项目（大量编译命令）和 Web 项目（轻量 shell）一刀切。

**借鉴方案**

引入 `HookProfile` 枚举，在 `hooks/registry.py` 中支持按 profile 动态包含/排除 Hook：

```python
class HookProfile(str, Enum):
    CAUTIOUS = "cautious"    # 严格校验，适合生产项目
    STANDARD = "standard"   # 默认
    CREATIVE = "creative"   # 宽松限制，适合快速原型

# Hook 注册时声明支持的 profile
@hook(event=HookEvent.PRE_TOOL_USE, profiles=[HookProfile.STANDARD, HookProfile.CAUTIOUS])
async def shell_rate_limit_hook(ctx: ToolHookContext):
    ...
```

项目创建时选择 profile，写入 `project.hook_profile`，Orchestrator 在 dispatch 工具调用时从环境变量注入：

```python
env["ADS_HOOK_PROFILE"] = project.hook_profile or "standard"
```

**预期收益**

- UE 项目用 `creative` profile，shell 限制放宽，减少误拦截
- 敏感项目用 `cautious` profile，额外启用 governance_capture 类 Hook
- 无需修改 Hook 实现，只改注册元数据

---

### 4.2 GateGuard 思路：强化 Shell 安全到 Token 级

**当前问题**

ADS `shell` 工具目前使用关键词白名单，可被以下方式绕过：
- 双空格：`rm  -rf /`
- 子命令嵌套：`ls $(rm -rf /tmp/important)`
- 变量展开（若允许 eval）：`cmd="rm -rf /"; $cmd`

这在 v1.0 沙箱执行中风险更大，DevAgent 生成的代码可能包含危险命令。

**借鉴方案**

在 `tools/shell_tool.py`（或对应 Action）增加 token 级预扫描：

```python
import shlex

BLOCKED_COMMANDS = {"rm", "mkfs", "dd", "chmod", "chown", "kill", "shutdown", "reboot"}
BLOCKED_PATHS = {"/", "/etc", "/usr", "/sys", "/proc"}

def _tokenize_command(cmd: str) -> list[str]:
    """提取命令串中所有原子命令（含管道/子命令嵌套）"""
    tokens = []
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return [cmd]  # 解析失败视为可疑，上层决策
    for part in parts:
        # 提取 $(...) 子命令
        subcommands = re.findall(r'\$\(([^)]+)\)', part)
        for sub in subcommands:
            tokens.extend(_tokenize_command(sub))
        # 提取管道分段
        if '|' in cmd:
            for segment in cmd.split('|'):
                tokens.extend(_tokenize_command(segment.strip()))
    tokens.append(parts[0] if parts else cmd)
    return tokens

def check_shell_safety(cmd: str) -> tuple[bool, str]:
    """返回 (safe, reason)"""
    atom_commands = _tokenize_command(cmd)
    for atom in atom_commands:
        if atom in BLOCKED_COMMANDS:
            return False, f"blocked command: {atom}"
    return True, ""
```

**预期收益**

- 防止 `$(rm -rf /)` 类嵌套绕过
- 管道末端命令独立检查
- 为 v1.0 沙箱执行提供更可靠的安全基线

---

### 4.3 成功经验沉淀：与现有方案的差异对齐

ADS 在 `20260509_04_系统自进化_Skill自动沉淀方案.md` 中已有完整设计，与 ECC observe-runner 的主要差异：

| 对比维度 | ADS 现有方案 | ECC observe-runner | 建议 |
|---------|------------|-------------------|------|
| 触发时机 | acceptance_passed（工单验收通过） | **每次工具调用**（异步） | 保留 acceptance_passed 为主触发，补充工具级观察 |
| 学习粒度 | 工单级（全轨迹分析） | 工具调用级（单次操作） | 双粒度并行 |
| 人工介入 | 草案 → 人工确认 → 生效 | 自动写入（用户定期 review） | ADS 的审核模式更安全，保留 |
| 失败案例 | failure_library（跨工单检索） | 无独立实现 | ADS 已领先 |
| 成功案例 | 待实现 | 核心能力 | 补足缺口 |

**具体补充建议**：在现有方案基础上增加一个**工具调用级微观观察层**：

```python
# 在 audit_log_hook 中复用已有的工具调用记录，定期触发微提炼
async def _micro_observe(ctx: ToolHookContext):
    """audit_log_hook 的扩展：记录调用的输入摘要，供批量模式分析"""
    if not ctx.success:
        return  # 失败案例已由 failure_library_hook 处理
    
    # 只关注高价值工具（文件写入、Git 操作、Shell 成功执行）
    HIGH_VALUE_TOOLS = {"write_file", "shell", "git_commit", "create_module"}
    if ctx.tool_name not in HIGH_VALUE_TOOLS:
        return
    
    await db.execute(
        "INSERT INTO tool_observations (tool_name, input_digest, project_type, ticket_id, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (ctx.tool_name, _digest(ctx.input), ctx.project_type, ctx.ticket_id, now_iso())
    )
```

每天/每次工单批量完成后，`SkillExtractorAction` 同时从 `pending_skills`（工单级）和 `tool_observations`（工具级）各提取一次。

---

### 4.4 Verification Loop：指导 v1.0 沙箱设计

ECC 的 pass@k 思路对 ADS 阶段九的设计有直接参考价值。

**当前规划（阶段九 9.5）**

```
构建/测试失败 → 打回 DevAgent → 最多 3 次重试
```

**ECC 启发的改进**

不是简单"失败 → 打回"，而是保留每次重试的完整上下文，实现**累积错误上下文注入**：

```python
class RetryContext:
    """跨重试轮次的上下文积累"""
    attempts: list[AttemptRecord]  # 每次尝试的完整记录
    
class AttemptRecord:
    attempt_num: int
    stdout: str
    stderr: str
    exit_code: int
    files_changed: list[str]
    test_failures: list[TestFailure]
    dev_analysis: str              # DevAgent 自己的根因分析

# DevAgent 重试时注入历史上下文
def _build_retry_prompt(ctx: RetryContext) -> str:
    history = ""
    for attempt in ctx.attempts:
        history += f"""
## 第 {attempt.attempt_num} 次尝试
**错误输出**：
```
{attempt.stderr[-2000:]}  # 截断防止 prompt 过长
```
**测试失败**：{[f.name for f in attempt.test_failures]}
**DevAgent 分析**：{attempt.dev_analysis}
---"""
    return f"以下是历次失败记录，请在此基础上给出新方案：\n{history}"
```

ECC 的 pass@k 建议：对于**非确定性生成任务**（如生成测试用例、接口设计），可以同时生成 k=3 个版本，取最优的继续执行，而不是顺序重试：

```python
# 适用于 TestAgent 生成测试用例
async def generate_tests_pass_at_k(spec: str, k: int = 3) -> list[TestSuite]:
    tasks = [generate_test_suite(spec) for _ in range(k)]
    results = await asyncio.gather(*tasks)
    return sorted(results, key=lambda r: r.coverage_score, reverse=True)

best = await generate_tests_pass_at_k(spec, k=3)
selected = best[0]
```

**分层 Grader 设计**（直接对应 ADS TestAgent 的 5 层测试）：

```
Level 1: Heuristic Grader（快速）
  ↓ 通过
Level 2: Unit Test Grader（执行 pytest）
  ↓ 通过
Level 3: Integration Grader（启动服务 + HTTP 调用）
  ↓ 通过
Level 4: E2E Grader（Playwright / curl）
  ↓ 通过
Level 5: LLM-as-Judge（对生成代码做语义质量评分）
```

只有前一层通过才进入下一层，失败立即打回，节省沙箱资源。

---

### 4.5 记忆持久化：补充 Hook 驱动的自动保存

**当前问题**

`save_memory` 依赖 LLM 决策调用，以下场景会导致记忆丢失：
- 对话过长导致上下文压缩，AI 忘记调用
- 用户强行关闭聊天窗口
- 工具调用超时，会话异常终止

**借鉴方案**

在 `POST_TOOL_USE` Hook 中增加**关键实体自动检测**，触发条件命中时无需 AI 决策直接写入：

```python
# 在 audit_log_hook 旁边新增 auto_memory_hook
MEMORY_TRIGGER_PATTERNS = [
    (r"我们决定|决定用|选择了|采用了", "decision"),
    (r"不要|禁止|避免|不能用", "constraint"),
    (r"项目类型|技术栈|框架是", "tech_stack"),
    (r"deadline|截止|发布日期|上线", "deadline"),
]

async def auto_memory_hook(ctx: ToolHookContext) -> None:
    if ctx.event != HookEvent.POST_TOOL_USE:
        return
    if ctx.tool_name != "chat_response":  # 只分析 AI 回复内容
        return
    
    response_text = ctx.output.get("content", "")
    for pattern, memory_type in MEMORY_TRIGGER_PATTERNS:
        if re.search(pattern, response_text):
            # 提取相关句子，不调用 LLM，直接写入
            sentences = _extract_matching_sentences(response_text, pattern)
            await memory_service.auto_save(
                content=sentences,
                memory_type=memory_type,
                project_id=ctx.project_id,
                source="auto_hook",
            )
```

SessionStop 时还可增加一次**结构化摘要**：

```python
async def session_stop_hook(session_id: str, project_id: str) -> None:
    """会话结束时批量提取关键信息存入 agent_memory"""
    messages = await db.fetch_session_messages(session_id)
    if len(messages) < 3:
        return
    # 使用轻量 LLM（Haiku）做摘要，而非 Sonnet，控制成本
    summary = await llm.summarize(
        messages=messages,
        model="claude-haiku-4-5",
        prompt="提取本次对话中的技术决策、约束条件和关键发现，用 JSON 格式输出"
    )
    await memory_service.batch_save(summary, project_id=project_id)
```

**预期收益**

- 消除因 AI 遗忘导致的记忆丢失
- 会话摘要使用 Haiku 而非 Sonnet，额外 LLM 成本极低
- 对话历史越长，自动记忆越丰富，形成正向循环

---

### 4.6 Skill 治理：建立放置策略规范

**当前问题**

随着 ADS Skill 体系增长（已有 packs/ use_skills/ marketplace/ 三层），缺少明确的治理规范：
- 自动生成的 Skill 草案（pending_skills）确认后写到哪里？
- 用户从 marketplace 安装的 Skill 和系统内置的如何区分优先级？
- 哪些 Skill 可以热更新，哪些需要重启？

**借鉴 ECC 的 Skill 放置策略**

| Skill 类型 | 放置位置 | 审核要求 | 热重载 |
|-----------|---------|---------|-------|
| 系统内置（随版本发布） | `backend/skills/packs/` | 需 PR + review | 重启生效 |
| 用户手动安装（marketplace） | `backend/skills/use_skills/` | 用户自负 | 热重载 ✓ |
| 项目专属 | `.Agent/skills/`（项目目录下） | 项目负责人 | 热重载 ✓ |
| 自动生成草案（AI 提炼） | `backend/skills/pending/`（新增） | 人工确认后升级 | 确认后热重载 |
| 拒绝的草案 | `backend/skills/rejected/`（新增，归档） | — | — |

关键规则：**pending/ 中的 Skill 不参与注入**，只有人工 `CONFIRM` 后才升级到 use_skills/。

---

### 4.7 跨 Harness 适配：前瞻性思考

ECC 的跨 Harness 架构：同一套 Skill 打包成多种格式（Claude Code Markdown + OpenAI YAML），部署到不同 AI IDE 时自动适配。

ADS 当前是单一系统，但随着"ADS 升级为完整 Harness 平台"（20260513_06）目标推进，以下设计值得提前考虑：

```
ADS Skill（统一描述层）
    ↓ 适配器（Adapter）
    ├── ADS 原生格式（当前）
    ├── Claude Code skills/ 格式（YAML frontmatter + Markdown）
    ├── OpenAI agents/yaml 格式（ECC .agents/skills/*/agents/openai.yaml）
    └── MCP Resource 格式（未来）
```

具体来说，`backend/skills/loader.py` 的 `SkillLoader` 在导出时可增加 `export_for_harness(harness_type)` 方法，把现有 Skill 定义翻译成目标格式——这样 ADS 沉淀的 Skill 知识可以反向输出给 Claude Code 等工具使用。

---

## 五、优先级与实施建议

### 5.1 按价值/成本矩阵排序

| 启发方向 | 实施成本 | 预期收益 | 优先级 | 建议时机 |
|---------|---------|---------|-------|---------|
| **4.3 成功经验微观层** | 低（复用 audit_log_hook + 现有方案） | 高（Skill 自增长飞轮） | P0 | 现在（20260514） |
| **4.4 Verification Loop pass@k** | 中（改 v1.0 沙箱重试逻辑） | 高（v1.0 核心质量） | P0 | v1.0 设计阶段 |
| **4.5 记忆自动持久化** | 中（新增 auto_memory_hook） | 中（Chat 体验） | P1 | v1.0 期间 |
| **4.1 Hook Profile 分级** | 中（改 registry.py + 数据库） | 中（灵活性） | P1 | v1.1 |
| **4.2 GateGuard Token 级防护** | 中（Python shlex tokenizer） | 高（v1.0 安全基线） | P1 | v1.0 沙箱前 |
| **4.6 Skill 治理规范** | 低（文档 + 目录约定） | 中（长期可维护性） | P2 | 现在（文档先行） |
| **4.7 跨 Harness 适配** | 高（需要 Adapter 抽象层） | 中（平台化方向） | P3 | v1.1+ |

### 5.2 最快路径：P0 工作拆解

**Task A：工具调用微观观察层**（预计 1 天）

1. `backend/database.py` 新增 `tool_observations` 表
2. `hooks/builtin.py` 中 `audit_log_hook` 增加 `_micro_observe()` 调用（仅高价值工具）
3. `SkillExtractorAction` 增加对 `tool_observations` 的批量分析入口
4. 测试：成功 shell 执行后，`tool_observations` 表有记录

**Task B：Verification Loop 分层 Grader 设计文档**（预计 0.5 天）

在阶段九开发前，先出一份 Grader 分层设计文档，作为沙箱执行的架构基础。明确：
- 5 层测试每层的 Grader 类型和通过条件
- 重试上下文的数据结构（`RetryContext` + `AttemptRecord`）
- pass@k 的适用范围（仅 TestAgent 生成阶段）

---

## 六、ECC 不值得直接借鉴的部分

以下 ECC 特性**不适合**照搬到 ADS：

| ECC 特性 | 原因 |
|---------|------|
| `suggest-compact.js`（提示手动压缩） | ADS 有后端管理的会话生命周期，不需要提示用户手动操作 |
| `ecc2/` Rust TUI 控制平面 | ADS 已有 Web UI 看板，TUI 重复 |
| `legacy-command-shims/`（旧命令兼容层） | ADS 没有需要兼容的历史命令格式 |
| 多 harness 打包（npm publish）| ADS 当前不是开源工具包，无需打包分发 |
| `ecc status --markdown --write` | ADS 的工单看板已覆盖这个信息，不需要额外 CLI |

---

## 七、总结

ECC 最值得 ADS 借鉴的**不是具体功能，而是三个工程设计哲学**：

1. **Hook 是可分级的运行时策略，不是写死的回调**
   — 对应 ADS：把 Hook 从内置逻辑升级为 Profile 驱动的可配置层

2. **学习是连续的，不只发生在失败时**
   — 对应 ADS：在现有 Failure Library 的对称位置建立 Success Observation，让每次成功工具调用都成为学习素材

3. **验证不是"运行一次"，而是"多粒度、多次采样的置信度建立过程"**
   — 对应 ADS：v1.0 沙箱的 Grader 分层 + pass@k + 累积错误上下文，让验收从"通过/失败"二元判断升级为可信度渐进建立

---

> 关联文档：
> - `20260509_04_系统自进化_Skill自动沉淀方案.md`（成功经验沉淀现有方案）
> - `20260513_06_ADS升级为完整Harness平台战略方案.md`（Harness 平台化背景）
> - `20260420_02_失败案例库实现方案.md`（Failure Library 对称参考）
> - `ROADMAP.md` 阶段九（沙箱执行 v1.0 设计依据）
