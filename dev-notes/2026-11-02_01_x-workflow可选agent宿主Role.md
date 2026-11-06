# x-workflow 可选 agent：只选宿主 Role，不定义 Agent 类（2026-11-02）

2026-11-02

前置：`docs/20261015_01_能力自描述与动态组装框架方案.md`（决策 2：新能力不新增 Agent）
对照：`dev-notes/2026-10-15_11_orchestrator的SkillAgent分支.md`
触发：Director 套件落地后，确认「插件没有 Agent 定义」→ 讨论是否不灵活 → 开一个小口。

## 一、问题

插件接新流水线的路径是 `SKILL.md` + Action，灵活。但 `workflow_composer.skill_to_stage` 把每个 skill stage 的 `agent` **写死成 SkillAgent**：

```python
SKILL_AGENT = "SkillAgent"
# skill_to_stage: "agent": SKILL_AGENT
```

`parse_workflow_skill` 不读 `x-workflow.agent`。SOP fragment（UE 的 DevAgent / UEEditorAgent 等）可以点名宿主 Role，skill 链不行。

两条错误的开口：

1. **插件自带 Agent 类** —— 破坏「接能力 = SKILL.md，零 Python Role」。插件目录一旦能定义 `VideoDirectorAgent`，就会有第二套调度、第二套结果分支、第二套 inject_to。
2. **只改 stage["agent"] = PlannerAgent** —— orchestrator 会调 `PlannerAgent.execute("skill_director_brief")`。PlannerAgent 只认识 `write_prd`，返回「未知任务」，再被 `_handle_agent_result` 的 `status==error` 写成 blocked。skill **根本跑不起来**。

真正要开的口：skill 可以**点名一个已经存在的宿主工单 Role**，用来改时间轴归属、LLM `agent_type`、inject_to 知识。执行引擎仍是 SkillRunner。

## 二、不允许什么

| 不允许 | 原因 |
|---|---|
| 插件定义 Agent 类 | 决策 2 没变。Role 仍只住在 `backend/agents/` + `agent_registry` |
| 未知名字静默变 SkillAgent | 写错 `agent: Planner` 会看起来「能跑」，实际没吃到策划知识 |
| 未知名字新建 Agent | 注册表之外的字符串不能变成可调度对象 |
| `agent: ChatAssistant` | 会话 Role，不是工单 stage 执行器 |
| 宿主 Role 自己 execute skill action | DevAgent / PlannerAgent 的 `execute` 不跑 SkillRunner |
| skill 结果只认 `agent_name == "SkillAgent"` | PlannerAgent 跑完的 skill 会落到通用 `else`，状态不推进，无限重跑烧 token |

## 三、做了什么

### 1. 解析期白名单

`executable_loader.PIPELINE_HOST_AGENTS`：12 个工单 Role（含 SkillAgent，不含 ChatAssistant）。

- 缺省 / 空白 → `SkillAgent`
- 合法宿主名 → 写入 `WorkflowSkill.agent`
- 非法（未知、ChatAssistant、非字符串、大小写不对）→ ERROR + skill **出局**（与缺 `stage_id` 同一档，不降级）

白名单与 `agent_registry` 内置表用测试锁死：`PIPELINE_HOST_AGENTS ⊆ registry`，且 ChatAssistant 在注册表里但不在白名单里。漏登合法 Role → skill 写出局；多登不存在的名字 → 运行期 missing-agent blocked。

### 2. 组装期写入 SOP

`skill_to_stage` 用 `skill.agent` 填 `stage.agent`，config 多一个 `_run_as_agent`。action 仍是 `skill_{stage_id}`，**仍然不设 `reject_goto`**（失败不自动重试，与 10-15 决策同一面）。

`sop_to_transition_rules` 会把宿主名写进规则表，orchestrator 按规则派单时 `assigned_agent` / 时间轴是 PlannerAgent，不是 SkillAgent。

### 3. 运行期两处拦截

**执行**：`TicketOrchestrator._execute_assigned_agent`

```
sop_config.skill_id 有值 → 调 SkillAgent.execute（SkillRunner）
否则 → 调 SOP 点名的那个 Role.execute
```

`process_ticket` 的调用点从 `agent.execute(action, context)` 换成这个方法。LLM context 仍是 `set_llm_context(agent_type=SOP上的名字)`，`_build_context` 的 `agent_type` 也是宿主名。

**收尾**：`is_skill_run_result(agent_name, result)`

```
agent_name == SkillAgent
或 result 带 skill_id / skill_status
→ _handle_skill_agent_result
```

不能只看名字。`waiting_human` / `skipped` / budget 豁免 / 不自动重试，全部仍然走这条分支，否则人审门会断。

时间轴、评论、SSE 的 `agent` 改记宿主 Role。执行引擎叫 SkillAgent 是实现细节，不应覆盖 SOP 声明。

### 4. SkillRunner 注入宿主知识

`SkillRunner._build_system` 按 `context.agent_type` 调 `skill_loader.build_prompt_for_agent`。否则 `agent: PlannerAgent` 只换了标签，LLM 看不到策划侧 inject_to。

默认 SkillAgent 时，也会把 `inject_to: SkillAgent` 的知识（如 director-knowledge）送进 runner。以前这块只在 BaseAgent._skills_prompt 里，SkillAgent.execute 根本不用它。

## 四、为什么必须两处都改

只改组装、不改执行：PlannerAgent「未知任务」→ blocked。
只改执行、不改分发：结果落到 `_handle_agent_result` 末尾 `else: new_status = current_status` → 死循环烧 token。这就是 10-15 那次假绿 #7 的同类坑。

只改分发条件、测试仍只派 `agent_name="SkillAgent"`：宿主 Role 路径测不到。所以加了 `_call_via_dispatcher(..., agent_name="PlannerAgent")`。

## 五、假绿风险（本轮针对的）

| # | 形态 | 怎么锁 |
|---|---|---|
| 1 | 只测 `parse` 通过，compose 仍写死 SkillAgent | `test_skill_to_stage_honors_host_agent` + compose 集成：rules[trigger].agent == PlannerAgent |
| 2 | 非法 agent 静默变 SkillAgent，测试只断言「skill 还在」 | 非法名 → `parse` 返回 None；compose 断言 stage 不出现 |
| 3 | 测内部 `_handle_skill_agent_result`，不测分发语句 | `_call_via_dispatcher` + 宿主 Role 一条 |
| 4 | 分发认了 PlannerAgent，但 `write_prd` 也被当成 skill | `is_skill_run_result("PlannerAgent", {status: success})` 必须 False |
| 5 | 分发对了，execute 仍调宿主 | `_execute_assigned_agent`：Host.execute 被调用则失败；另锁 `process_ticket` 源码不再 `agent.execute(action, context)` |
| 6 | 白名单手写一份，与 registry 漂 | `PIPELINE_HOST_AGENTS ⊆ get_registry()` |

源码断言（#5 后半）不漂亮，但 `process_ticket` 太重，用 `__new__` 绕开 `__init__` 又测不到那一行。这是和 10-15「必须走真实入口」同一标准下的折中：分发走真实 `_handle_agent_result`，execute 走被 process_ticket 调用的那一个方法，再钉调用点字符串。

## 六、没做什么

- Director 七条 skill **没有**改 `agent:`，默认仍是 SkillAgent。开口是可选的，不把视频链绑死到 PlannerAgent。
- 没有插件 Agent 类，没有 `agents/plugins/`。
- 没有做步 D（LibTV / dreamina / Drama 加固）。
- 自定义 `agents/custom/` 里的 Role 暂不进白名单。要接的话应显式扩 `PIPELINE_HOST_AGENTS`，而不是 `get_registry()` 全放行（避免 ChatAssistant 或实验 Agent 被 skill 点到）。

## 七、怎么用

```yaml
x-workflow:
  stage_id: director_brief
  agent: PlannerAgent    # 可选。默认 SkillAgent
  consumes: ...
  produces: ...
```

选 Role 的原则：这个阶段的 **inject_to 知识** 和 **LLM 配置** 该像谁。不要为了时间轴好看把视频生成 skill 写成 DevAgent——会把 fastapi-dev / react-dev 一整锅灌进 SkillRunner。

## 八、改动清单

```
backend/skills/executable_loader.py     PIPELINE_HOST_AGENTS + parse agent
backend/sop/workflow_composer.py        stage.agent / _run_as_agent
backend/orchestrator.py                 is_skill_run_result
                                         _execute_assigned_agent
                                         skill 分发不再只认 SkillAgent
                                         时间轴记宿主 Role
backend/skills/runner.py                注入宿主 Role 知识
backend/tests/skills/test_workflow_discovery.py
backend/tests/sop/test_workflow_composer.py
backend/tests/sop/test_compose_sop_skills.py
backend/tests/agents/test_orchestrator_skill_branch.py
backend/tests/skills/test_runner_outputs.py
backend/tests/plugins/test_director_plugin.py
```

## 九、验证

```bash
cd backend
python -m pytest tests/skills/test_workflow_discovery.py tests/sop/test_workflow_composer.py tests/sop/test_compose_sop_skills.py tests/agents/test_orchestrator_skill_branch.py tests/skills/test_runner_outputs.py tests/plugins/test_director_plugin.py -q
```
