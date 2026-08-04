# 通用 Skill 执行框架（SkillRunner）设计方案

日期：2026-08-02
状态：阶段 1–3 已实现（工作区，未提交），端到端 LLM 验证待做
关联开发记录：`dev-notes/2026-08-02_01_OpenSpec可见性修复与时间轴后台任务增强.md` §四

---

## 一、背景与动机

### 问题
ADS 接三方工具集（OpenSpec / 未来的其它 CLI 工具集）的方式是**把工具流程用 Python 硬编码**。以 OpenSpec 为例，`agents/architect.py` 里的 `_run_openspec_propose` + `_fill_openspec_4_artifacts` 固定写死了：

```
openspec-cn new change → 对每件套 { instructions → llm_client.generate 写内容 → write_text } → validate
```

每接一个新工具集，就得再写一个 `_run_xxx`。这条路不可持续：
- 硬编码流程僵硬（LLM 只能填内容，不能自主编排）；
- 与 Claude Code 的 `opsx` skill 能力割裂 —— `opsx` 是"让 LLM 读说明书、自主调工具"，ADS 却退化成"固定脚本 + LLM 填空"；
- 工具流程散落在各 Agent 里，无统一入口。

### 目标
做一个**通用 skill 执行引擎**：给它一个 skill 定义（声明"用哪些工具、达成什么目标"），它就驱动 LLM 自主调用工具（CLI / MCP）完成任务，并把过程接进工单流程（时间轴 / DB / SSE）。**接新工具集 = 写一个 SKILL.md + 一个 SOP fragment，零 Python 改动。**

### 关键洞察
ADS **已有**成熟的 REACT + QueryEngine 工具调用循环（`query_engine/`），本身就是"给 LLM 一批工具 + 任务，它自主循环调用完成"的通用内核。**缺的不是引擎，是把 skill 定义 + 通用 CLI 工具动态喂给引擎的适配层。** 所以本方案不造新引擎，只补适配层。

---

## 二、架构总览

```
                        ┌─────────────────────────────────────────────┐
   SOP fragment         │  工单流转（orchestrator.process_ticket）      │
   stage.config         │    rule = SOP[status]                         │
   .skill_id ───────────┼──► context["sop_config"]["skill_id"]          │
                        │    agent.execute(action, context)             │
                        └───────────────┬─────────────────────────────┘
                                        ▼
                              ┌──────────────────┐
                              │    SkillAgent     │  读 skill_id
                              └────────┬─────────┘
                                        ▼
   SKILL.md (x-runner) ──► ┌──────────────────────────────────────┐
   声明工具/目标/产出       │            SkillRunner                 │
                          │  1. 组装 actions（GenericCLIAction /   │
                          │     WriteFileAction / mcp__）           │
                          │  2. tools = schemas + done             │
                          │  3. system = skill.body + 工单上下文    │
                          │  4. QueryEngine.run() ← 复用现有引擎    │
                          │  5. on_tool 回调 → 写时间轴             │
                          │  6. _collect_outputs 按 glob 回收产出   │
                          └────────────────┬─────────────────────┘
                                            ▼
                              ┌──────────────────────────┐
                              │  QueryEngine (query_engine/) │  ← 未改动，直接复用
                              │  LLM tool_use 循环 + Budget   │
                              └──────────────────────────┘
```

**核心原则**：QueryEngine 不动；SkillRunner 是"skill 定义 → 引擎输入"的适配器；SkillAgent 是"工单流程 → SkillRunner"的接线员。

---

## 三、组件设计

### 3.1 Skill 定义格式（复用 SKILL.md + `x-runner` 命名空间）
不发明新格式。复用现有 SKILL.md 的 YAML frontmatter（`skills/loader.py:_parse_frontmatter` 用 `yaml.safe_load`，任意字段可解析），额外挂一个 `x-runner`：

```yaml
---
name: openspec-propose
description: ...
inject_to: [ArchitectAgent]
x-runner:
  version: 1
  availability: [has_openspec]          # capability_check.* 函数名，全 True 才可用
  cli_tools:
    - name: openspec_new_change
      command_template: "{cli} new change {change_id} --description {desc} --goal {goal}"
      description: ...
      timeout: 60
  builtin_tools: [write_file]           # write_file / shell / mcp__server__tool
  outputs:
    root: "openspec/changes/{change_id}"
    globs: ["proposal.md","specs.md","design.md","tasks.md"]
  budget: {max_rounds: 14, max_seconds: 300, max_tokens: 120000}
---
# <body 正文 = 给 LLM 的 system：编号步骤 + 约束>
```

- `command_template` 用 `{占位符}`：context 预填主干参数（cli/change_id/goal/desc），LLM 只能填模板剩余的自由槽（如 `artifact`）——这是"零硬编码接新工具"的安全前提。
- `outputs.globs` 空 → 该 skill 无产出（如只读校验类），不触发 partial 判定。
- 来源优先级：项目级 `.claude/packs/*/skills/<id>/` > backend 内置 `skills/executable_skills/<id>/`。

### 3.2 SkillRunner（`skills/runner.py`）
仿 `agents/base.py:_react_with_think_inner` 的三段式骨架，但不绑 BaseAgent（输入是 skill 定义而非 agent，可独立测试）。核心：

```
execute(context, on_tool) -> SkillRunResult{status, outputs, rounds, message}:
  1. 组装 actions（cli_tools→GenericCLIAction；write_file→WriteFileAction；mcp__→executor 转发）
  2. tools = [tool_schema...] + DONE_SCHEMA (+ 声明的 mcp schema)
  3. executor = SkillToolExecutorAdapter（复刻 OrchestratorToolExecutorAdapter，加 mcp__ 分支）
  4. budget = Budget(**skill.budget)；engine = QueryEngine(...)
  5. async for ev in engine.run(): ToolDone→on_tool 回调；MessageDone/BudgetExceeded/Error→收集状态
  6. _collect_outputs 按 outputs.globs 扫盘；产出 < expected → status=partial
```

- **不碰 DB**：时间轴落盘通过 `on_tool` 回调交给调用方，保持可独立测试。
- `is_available`：反射调用 `x-runner.availability` 里的 `capability_check.*` 函数。

### 3.3 GenericCLIAction（`actions/generic_cli.py`）
把一条声明过的 CLI 命令安全暴露成 LLM 工具。**不继承 ShellAction**（参数 schema 不同），但复用其执行内核与安全设施。安全四重：
1. 命令主干白名单（LLM 选不了模板外的命令）；
2. LLM 只能填模板预留的自由槽（预填槽 LLM 填了也忽略）；
3. LLM 填入值 `shlex.quote`；
4. 渲染后整串过 `_DANGEROUS_PATTERNS` 黑名单复查 + cwd 锁 `repo_path`（复用 `shell_exec` 的 `relative_to` 校验）。
外加 per-tool 超时、5000 字符输出截断。

### 3.4 WriteFileAction（`actions/write_file.py`）
受限写文件：只写 `_skill_output_root` 目录下、扩展名白名单（.md）、自动去 ``` 围栏（搬自原 `_fill_openspec_4_artifacts` 清洗逻辑）、越界校验。避免让 LLM 用 shell 的 `echo >` 不可控写文件。

### 3.5 SkillAgent（`agents/skill_agent.py`）
`BaseAgent` 子类，`react_mode=SINGLE`，重写 `execute` 直接驱动 SkillRunner（不走 Action 组合）。从 `context["skill_id"]` 或 `context["sop_config"]["skill_id"]` 取 skill，`on_tool` 复用 `BaseAgent._emit_react_tool` 写 `react_tool` 时间轴。已注册进 `agent_registry`（现 12 个 agent）。

---

## 四、触发链（SOP 驱动，零硬编码）

```
SOP fragment  stage: {agent: SkillAgent, action: run_skill, config: {skill_id: xxx}}
  → sop_to_transition_rules  rule["config"] = stage["config"]（原样保留 skill_id）
  → orchestrator.process_ticket  context["sop_config"] = rule.config   (orchestrator.py:1483)
  → SkillAgent._resolve_skill_id  读出 skill_id
  → SkillRunner.execute
```

已用 synthetic stage 端到端验证 skill_id 正确透传。

---

## 五、OpenSpec 重构（第一个落地）

`_run_openspec_propose` 从"硬编码 subprocess + llm_client.generate 写四件套"改为"load skill → SkillRunner.execute"：
- LLM 自主按 SKILL.md 步骤：`new_change` → 逐件 `instructions` + `write_file` → `validate` → `done`；
- 删除 `_fill_openspec_4_artifacts`；
- **全部可见性保留**：`openspec_propose_started` / `openspec_artifact` / `openspec_propose` / `_partial` 日志 + milestone + react_tool 时间轴，前端时间轴 action 名不变，无需改前端；
- **向后兼容**：签名 / 触发点（architect design 后触发、`api/tickets.py` create-direct 钩子）不变；openspec 未装静默跳过。

产出回收按磁盘 glob：即便 LLM 漏调 validate / 顺序乱 / 提前 done，仍如实回收已落盘文件并判 partial —— 比原每件超时更鲁棒。

---

## 六、演进阶段

| 阶段 | 成果 | 验证方式 |
|------|------|---------|
| 1 MVP | SkillRunner + GenericCLIAction + WriteFileAction + executable_loader；OpenSpec 走引擎 | dry-run 组装/free_slots/output_root 全绿 |
| 2 泛化 | 加 `openspec-validate`（只读校验，无 write_file/outputs），**零 .py 改动** | mtime + 加载 dry-run 证明 SkillRunner 无改动即吃下新 skill |
| 3 触发 | SkillAgent + SOP `skill_id` 链路 | synthetic stage 端到端 skill_id 解析单测 |
| B CLI 工具 | openspec MCP server + CLI 条件注入 | `_build_settings_args` 单测：有 openspec→注入，无→不注入 |

---

## 六.5、关键架构约束：CLI 模式 vs API 模式的工具调用（重要）

ADS 的 LLM 有两种运行模式（`LLM_API_FORMAT`），**工具循环的控制权归属不同**：

| | API 模式（anthropic/openai） | CLI 模式（codebuddy/claude CLI） |
|---|---|---|
| 工具循环控制权 | **ADS 的 QueryEngine** | **CLI 自己的 agentic 循环** |
| tools schema | QueryEngine 把 SkillRunner 组装的 `openspec_*` 工具传给 LLM（engine.py:375 带 tools） | **不传 tools**（engine.py:264 `_call_cli_stream` 无 tools 参数）；CLI 用自己的原生工具（Bash/Write/TaskCreate） |
| skill 的自定义工具是否生效 | ✅ GenericCLIAction/WriteFileAction 白名单生效 | ❌ 被无视；CLI 读 SKILL.md body 后用原生工具代劳 |
| 让 skill 工具被命名调用的手段 | 直接生效 | **MCP**：CLI 支持 `--mcp-config`，把工具包成 MCP server 才能被 CLI 以 `mcp__<server>__<tool>` 命名调用 |

**结论**：CLI 模式下"skill 本身能执行"（body 作为 system 传给 CLI），但"skill 声明的自定义工具不生效"——必须走 MCP。这是阶段 B 的由来。

**双模式兼容策略**：
- SKILL.md body 引导 LLM "优先用 OpenSpec 命名工具（`openspec_*` 或 `mcp__openspec__*`），不要用原生 Bash 拼命令"——两种命名都覆盖。
- API 模式：SkillRunner 的 `openspec_*` GenericCLIAction 生效。
- CLI 模式：`llm_client._build_settings_args` 条件注入 `openspec_mcp_server.py`（`backend/openspec_mcp_server.py`，FastMCP，工具 new_change/instructions/write_artifact/validate/status），CLI 以 `mcp__openspec__*` 调用，安全边界在 MCP server。仅当 `<cwd>/openspec/` 存在且 CLI 可用时注入，不污染普通项目。

---

## 七、"接一个新三方工具集"的标准动作（本框架交付的能力）

以后接入任意 CLI 型工具集，只需：
1. 写 `skills/executable_skills/<id>/SKILL.md`：`x-runner` 声明 CLI 命令模板、可用性、产出 glob、预算；body 写给 LLM 的步骤。
2. （若要工单流程自动触发）写 `sop/fragments/<id>.yaml`：`stage.agent=SkillAgent` + `config.skill_id=<id>`，`insert_after` 指定插在哪个阶段。

**无需改任何 .py。** 阶段 2 已证明这一点。

---

## 八、风险与权衡

- **LLM 自主循环 vs 确定性硬编码**：原实现顺序固定但僵硬；SkillRunner 让 LLM 自主编排，可能漏步/乱序/提前 done。缓解：SKILL.md body 编号步骤 + "全部完成才 done"；产出按 glob 兜底判 partial；后续可加"结束前查产出齐全否则催补"。
- **安全**：GenericCLIAction 是核心风险点，靠"命令主干白名单 + 只填预留槽 + shlex.quote + 黑名单复查 + 目录锁"四重防护；OpenSpec skill 不放 `shell`，只白名单 CLI + write_file。GenericCLIAction 接权限门（`permissions/gate`）为后续增强。
- **预算**：整体 Budget（轮数/秒数/token）替代原每件 90s 超时；`OPENSPEC_ARTIFACT_TIMEOUT` 语义映射到 skill.budget。
- **向后兼容**：全程保留旧调用点签名、时间轴 action 名、DB 字段；前端零改动。

---

## 九、待办

- **端到端 LLM 验证（最关键）**：重启后端 + 装了 openspec 的项目建工单，确认 LLM 真能自主跑通四件套生成、时间轴出现完整工具调用链。
- 挂真实 fragment 到 SOP（挂哪个 skill、插哪个阶段由业务决定，会改变对应项目工单流，需谨慎）。
- GenericCLIAction 接权限门；项目级 `.claude/packs/` 可执行 skill 发现（loader 已留查找逻辑）；SkillRunner "结束前强制查产出齐全"。

---

## 十、涉及文件

**新增**
```
backend/skills/executable_loader.py          # x-runner 解析 → ExecutableSkill/CliToolSpec
backend/skills/runner.py                      # SkillRunner + SkillToolExecutorAdapter
backend/actions/generic_cli.py                # GenericCLIAction
backend/actions/write_file.py                 # WriteFileAction
backend/agents/skill_agent.py                 # SkillAgent
backend/skills/executable_skills/openspec-propose/SKILL.md
backend/skills/executable_skills/openspec-validate/SKILL.md
```
**修改**
```
backend/agents/architect.py     # _run_openspec_propose 走 SkillRunner，删 _fill_openspec_4_artifacts
backend/agent_registry.py       # 注册 SkillAgent
```
**复用未改**
```
backend/query_engine/*          # QueryEngine / Budget / events / executor
backend/actions/chat/shell_exec.py   # _DANGEROUS_PATTERNS / MAX_OUTPUT_CHARS / _get_project_base
backend/skills/loader.py        # _parse_frontmatter
backend/capability_check.py     # has_openspec / get_openspec_cli / _short_ticket_id
```
