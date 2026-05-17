# AI Dev System — 待办清单

> 最后更新: 2026-05-17

---

## 🎯 新增待办

### J. AI 思考过程对标 Claude Code（P1/P2）✅ J-1/J-2/J-3 已完成（2026-05-17）

**背景**：A 方向改进后对 ChatAssistantAgent 做了全面升级（评分 5.5→7.5），但思考过程展示与 Claude Code 仍有差距。详细分析见 `docs/20260517_02_A方向改进成果观测指南.md` 第六节。

**当前差距（思考过程部分）**：
- ❌ **无 Extended Thinking**：未使用 Anthropic 原生 `thinking` 块（`budget_tokens`），用户只能看到"AI 做了什么"，看不到"AI 在想什么"（推理链/scratchpad）
- ❌ **无每步耗时**：`ToolDoneEvent.duration_ms` 已有但未传到前端展示
- ⚠️ **摘要质量低**：工具结果截取前 120 字符，无结构化格式（读文件→行数，搜索→匹配数）

**待做子项（按优先级）**：

#### J-1. 每步耗时显示（P1，改动量小）

`ToolDoneEvent.duration_ms` 已在 `query_engine/events.py` 中，只需：
1. `chat_assistant.py` `_emit_thinking()` 把 `duration_ms` 写入 `thinking_steps` 条目
2. 前端 `ctp-step` 行尾加 `(42ms)` 灰色小字

预期效果：`📄 读取文件  (path: main.py)  ✓ 返回 87 行代码  (38ms)`

---

#### J-2. 结构化工具摘要（P1，改动量中）

按工具类型格式化摘要，替换粗暴的 120 字截断：

| 工具 | 现在 | 改后 |
|---|---|---|
| `read_files` | `{"content": "import...` | `main.py · 87 行` |
| `grep` | `[{"path": "src/...`, ...` | `23 处匹配 · src/api.py:14` |
| `shell` | `stdout: Compiling...` | `exit 0 · 3.2s` |
| `search_knowledge` | `[{"title": "...` | `5 条结果 · 最相关：xxx` |

改动位置：`backend/query_engine/engine.py` `_extract_result_summary()` 新增函数（按 tool_name 分支格式化）。

---

#### J-3. Extended Thinking 原生推理链（P2，改动量大）

使用 Anthropic 的 `thinking` 参数让模型输出推理过程：

```python
# llm_client.py
extra_params = {}
if model_supports_thinking(model):
    extra_params["thinking"] = {"type": "enabled", "budget_tokens": 8000}
```

前端新增推理链展示区（折叠，灰色斜体，与工具步骤分离显示）。

**前置条件**：
- 当前模型 `claude-sonnet-4-5` 支持 thinking（需确认 API 版本）
- thinking 块会增加约 8000 token 成本，需评估 cost_usd 影响
- 与 Prompt Cache 分区可能冲突（thinking 块不能缓存）

---

#### J-4. Agent REACT 模式接入 Diminishing Returns（P1，改动量小）

见 `docs/20260517_02_A方向改进成果观测指南.md` 第六节。
`base.py:_react_with_think_inner` 的 QueryEngine 已有 Budget，只需在循环里调用 `budget.check()` 的 diminishing 分支即可（QueryEngine 内部已处理，实际可能已生效——需验证）。

#### J-3b. 思考过程按轮次分组展示（P2）

**背景**：参考某 AI 助手展示方式——每轮推理文字与该轮工具调用绑定展示，而非两个独立面板。

**当前**：推理链面板（蓝） + 工具步骤面板（紫）分离，看不出哪段推理对应哪次工具调用。

**目标效果**：
```
● 第1轮  💭 "需要搜索排行榜信息..."    [展开]
          └ 🌐 联网搜索 ✓ 8条结果 (1240ms)
● 第2轮  💭 "换关键词继续搜..."         [展开]
          └ 🌐 联网搜索 ✓ 5条结果 (980ms)
```

**方案文档**：`docs/20260517_03_思考过程分组展示方案.md`

**改动量**：~150 行，约半天，涉及 6 个文件（events.py / engine.py / chat_assistant.py / chat.py / app.js / styles.css）

---

### I. 分屏思考面板不显示（P1）

**问题**：进入分屏模式后，主格（主会话）的思考面板不显示，非分屏正常显示。

**调试结论**：克隆有效（Console 已确认 `[split] 克隆完成: 4 条消息, 1 个思考面板`），
但思考面板在分屏容器内仍不可见——非 DOM 缺失问题，疑为渲染/CSS 问题。

**已尝试**：
- innerHTML 克隆 → 无效
- cloneNode(true) 克隆 → 无效
- 强制加 ctp-expanded → 无效
- 改用 API 重新加载 → 无效（老消息 thinking_json=NULL）

**下一步排查**：用 DevTools Elements 检查分屏格的 `.chat-thinking-panel` 元素实际的 computed style，确认是否有 `display:none`、`opacity:0`、`height:0` 等导致不可见的 CSS 规则。

---

### H. 系统自进化：成功经验自动沉淀为 Skill（P2）

**问题**：当前自进化闭环（Reflexion → FailureLibrary → Skill注入）中，Skills 内容需人工维护，成功案例无法自动提炼为新 Skill。系统会"记住失败"但不会"总结成功"。

**方案**：工单验收通过后，系统自动分析本次开发轨迹，提取可复用的技术模式，生成 Skill 草案写入 DB，等人工确认后合入 skills.json。

**核心链路**：
```
工单验收通过（acceptance_passed）
    ↓
SkillExtractorAgent 分析工单全轨迹（PRD + 架构 + 代码 + Reflection）
    ↓
提取：解决了什么问题 / 用了什么技术模式 / 适用于什么项目类型
    ↓
生成 Skill 草案（pending_skills 表，status=draft）
    ↓
AI 助手对话中展示草案，人工确认 → 自动写入 skills.json + 热重载
```

**价值**：把"人工总结 → AI 执行"升级为"AI 草稿 → 人工确认"，把自进化从 L2 推向 L3。

**详细方案**：`docs/20260509_系统自进化_Skill自动沉淀方案.md`

**前置**：Failure Library 已完成，Skills 三层过滤已完成（2026-05-08）

---

### G. Reflexion UE uproject 自愈（P2）

**问题**：当 Playtest 因"game module could not be loaded"失败时，当前 Reflexion 只会改 C++ 代码，不会识别是 `.uproject` 缺插件声明导致的。

**方案**：
- Reflexion 分析 play_test_failed log，检测 "module could not be loaded" 关键词
- 自动扫描 Build.cs 的 `PublicDependencyModuleNames`，把模块名映射到插件名（StateTreeModule→StateTree 等）
- 自动补写 `.uproject` 的 `Plugins` 段
- 重触发编译 + 重测

**价值**：AI 全自动运行需求时，`.uproject` 配置不完整会卡住整个工单流程，自愈后无需人工介入。

**前置**：v0.20 UE MCP Phase 1-5 已完成（2026-05-07）

---

## ✅ 已完成（2026-05-04 ~ 05-07）

- **F. AI 助手多会话管理**（2026-05-04）：＋新建对话 / 🕐历史面板，全局+项目内均支持，消息写入 DB
- **A. Memory 持久化系统**（已完成，今日确认）：`agent_memory` 表 + `GetMemoryAction` + Orchestrator 写入
- **B. Insight 主动注入**（已完成，今日确认）：`_fetch_prior_insights` FTS5 查知识库+工单，注入 DevAgent context
- **C. 研发效率统计前端**（2026-05-06）：交付周期 / Agent LLM 耗时+Token / Reflexion 返工排行；顺带修复 `chat_with_tools` token 未记录 bug
- **v0.20 UE MCP Phase 1-5**（2026-05-06~07）：UCP TCP 客户端 / Skill Pack / 模板集成 / Reflexion 增强 / Editor 双按钮 / 启动日志 / 构建日志持久化；顺带修复 `_write_uproject` 缺插件声明 bug

---

## 🎯 新增待办

### F. AI 助手多会话管理（~2 天，P1）

**来源**：用户需求，参考 CodeBuddy/Cursor 的对话历史 UI 设计。

**问题**：全局 AI 助手和项目内 AI 助手只有单一会话，无法新建对话、查看历史记录。

**方案**：

**UI 交互**（参考截图）：
- 顶栏右侧加两个按钮：`+`（新建对话）和 `🕐`（历史记录）
- 点 `+` → 清空当前对话，开始新会话
- 点 `🕐` → 打开历史对话面板（侧拉或展开），按时间分组（今天/本周/更早）
- 每条历史对话显示首条消息摘要，可点击切换，支持删除/全部删除
- 适用范围：**全局 AI 助手** 和**项目内 AI 助手**均支持

**后端变更**：
- 新增 `chat_sessions` 表（id / project_id / title / created_at / updated_at）
- `chat_messages` 加 `session_id` 列，关联所属会话
- 新增 API：
  - `GET  /api/chat/sessions?project_id=`（列出会话）
  - `POST /api/chat/sessions`（新建会话）
  - `DELETE /api/chat/sessions/{id}`（删除会话）
  - `GET  /api/chat/sessions/{id}/messages`（获取会话消息）
- 现有 `chat_messages` 默认 `session_id=default`（向后兼容）

**前端变更**：
- AI 助手面板顶栏加 `+` 和历史图标按钮
- 历史记录面板（类 CodeBuddy 样式）：按日期分组、首条消息作标题、支持单条删除和全部清空
- 全局聊天 localStorage 改为按 session_id 分别存储

---

## ✅ 下一主线（已全部完成，2026-05-06）

### ✅ A. Memory 持久化系统（已完成）

`agent_memory` 表 + `_write_memory()` + `GetMemoryAction`，ChatAssistant 可回答"当初为什么这样设计"。

### ✅ B. Insight 主动注入（已完成）

`orchestrator._fetch_prior_insights()` FTS5 查知识库+历史工单，注入 DevAgent context 的 `prior_insights` 字段。

### ✅ C. 研发效率统计（已完成，2026-05-06）

`GET /api/projects/{id}/efficiency` + 前端看板（交付周期 / Agent LLM 耗时+Token / Reflexion 返工排行）。
顺带修复：`chat_with_tools` token 未记录到 `llm_conversations` 的 bug。

### D. Unity HTML 原型管线（~5 天，P2，前置：engine:unity 基础完善）

**来源**：腾讯 KM《如何让 AI 分工帮我做游戏（三）》HTML 原型 → Unity 管线。详见 `docs/20260428_02_ai_multi_agent_dev对比分析与借鉴方案.md §3.4`。

**问题**：Unity 启动慢、热重载重，开发一个方向错误的功能损失 1-2 周；AI 写 HTML 质量远高于直接写 Unity UI 代码。

**方案**：
- Phase 1（2 天）：`html_prototype` SOP fragment（engine:unity 注入），DevAgent 先生成 HTML 原型，SelfTestAction 浏览器验证玩法循环，通过后进入 Unity 开发
- Phase 2（3 天）：`HtmlToUnityAction`，解析 HTML DOM → 生成 Unity Prefab 骨架 + ButtonBinder / PanelController C# 脚本

### E. v0.19 三合一 + CI/CD 浏览器实操验收（需手动，随时）

代码已就绪，等浏览器跑一遍验收后 commit。见 `🔄 v0.19 三合一` 和 `✅ v0.19.x CI/CD` 节。

---

## ✅ DevAgent UE 自测 Layer 2（已完成 2026-04-28）

SOP `stage_overrides` 机制 + `engine_compile.yaml` 自动为 UE 项目开启 `ue_precompile: true`（UBT -SingleFile 30-90s）。详见 `dev-notes/2026-04-28_UE自测Layer2_SOP_stage_overrides.md`。

## ✅ DevAgent UE 自测 Layer 1（已完成 2026-04-26）

7 条静态规则（`actions/ue_lint/rules.py`）：R1 GENERATED_BODY · R2 OnRep 禁 UFUNCTION · R3 include 路径 · R4 Build.cs 模块白名单 · R5 .uproject Modules 同步 · R6 Target.cs IncludeOrderVersion · R7 常用类型必需 header  
接入 `SelfTestAction`，`self_test_failed → DevAgent.fix_issues` 回跳。

## ✅ 工单面板「当前进度」区（已完成 2026-04-26）

`tickets.current_action*` 4 列 + orchestrator 心跳 + SSE `ticket_action_progress` + drawer 进度区（活性 🟢🟡🔴⚪）。

---

## 🔄 v0.19 三合一（代码就绪，未真机实操 + 未 commit，2026-04-25）

详见 `docs/20260424_04_v019三合一工作安排.md`。6/6 交付 + 76/76 smoke：

- **①a** 对话一键流：UE 项目建完自动弹 propose 方案卡（server-side 持久化）
- **①b** action state 持久化：`chat_messages.action_state` 列 + PATCH 端点，4 个 confirm_* 卡片刷新后显示摘要不再重复可点
- **②**  UE `run_playtest`：Automation Framework headless + 日志解析 + SOP 派生 `play_test_failed → fix_issues` + Reflexion UE 专属 prompt + SSE 事件
- **③a** 文件浏览器：二进制占位 + `.uproject/.Build.cs/.Target.cs` 语法高亮
- **③b** Commit Diff：`GET /git/commit/{sha}` + 内嵌行级 diff + 未变化大段折叠
- **③c** 分支树形：`list_branches_enriched` + 基于命名约定的 parent 推断 + ahead/behind 徽标

**剩余工作**：浏览器实操验收 / 真机 UE playtest / commit 拆分策略 / ②D Functional Test 脚手架自动生成延后 / ③b 真 side-by-side 分栏 diff 延后

---

## 🎯 v0.20+ 候选：UE 编辑态 MCP 集成

详细选型分析：`docs/20260425_01_UE编辑态MCP集成选型分析.md`

调研了两个候选：

| 项目 | 结论 |
|---|---|
| [flopperam/unreal-engine-mcp](https://github.com/flopperam/unreal-engine-mcp) (851★) | 成熟 demo，有 `create_town`/`construct_mansion` 等高层 DSL；过于 opinionated，不适合作 SDK |
| [Italink/UnrealClientProtocol](https://github.com/Italink/UnrealClientProtocol) (105★) | **推荐方向**：reflection-based 原子 + NodeCode 文本 IR + 零 engine 修改；契合我们 Agent 架构 |

**价值**（按优先级排）：
1. Reflexion 时查 editor 现状（当前盲猜）
2. 改 BP 变量默认值 / 材质参数（当前需重编）
3. 批量改资产 / 生成测试场景 actor
4. BP 图编辑（NodeCode 文本 IR）

**不立即做的理由**：
- v0.19 UE playtest 还没真机实操
- 常驻 editor 进程（~4GB 内存 / 启动 30s+）是个大子系统
- TestFPS 纯 C++ 项目，价值未被验证
- MCP 生态未稳，观察 3-6 个月

**前置条件**（任一满足可启动）：
- 用户有 BP/Asset 重度项目
- v0.19 离线链路真项目跑稳 ≥ 3 轮
- 官方或 1k+★ 替代品出现

**若动手，~9.5 天** 8 个 Phase（详见分析文档 §7.3）

---

## ✅ v0.19.x CI/CD 环境管理合并 + trait-first pipeline（已完成 2026-04-26）

详见 `docs/20260425_02_CICD环境合并与项目类型感知Pipeline方案.md`。Phase A-E 全部交付 + 30/30 smoke：

- **Phase A** `CIStrategy` 抽象 + Loader + Web 策略（委托老 ci_pipeline 零侵入）+ Default 兜底 + 3 新端点（pipeline-definition / strategies / environments）
- **Phase B** 前端「🚀 交付 & 环境」页合并 + 按 strategy 动态渲染 + 原 "环境管理" 导航撤下
- **Phase C** `UECIStrategy`（priority=100）+ `UEPackageAction`（RunUAT BuildCookRun）+ UE 独有环境
- **Phase D** SOP fragments `deploy_web.yaml` / `deploy_ue.yaml` + `DeployAgent.run_ci_deploy` 统一调度
- **Phase E** `_test_v019_ci_phase_abcd.py` 30/30 smoke 通过

**剩余**：浏览器实操 + commit

---

## 其他候选方向

- v0.19 `generate_assets` + ArtistAgent（AIGC 资产生成）
- 全局聊天直接串联"创建项目 → 生成骨架"一条龙（已做 ①a，差串联全局）
- 跨平台 UE 引擎检测 (Mac/Linux)
- **v0.20+ UE 编辑态 MCP 集成**（见上方 §v0.20+ 候选）

---

## ✅ v0.18 UE 深耕（已完成 2026-04-24）

7/8 Phase 完成 + 24/24 smoke 测试通过，详见 `dev-notes/2026-04-24_v0.18_完结总结.md`。
核心交付：UE 引擎检测 / 模板实例化 / UBT 编译 + 错误解析 / Reflexion 自动修复 /
Skill Packs / 项目 UE 配置持久化 / 对话式 UE 框架生成。

---

## 🎯 上一主线：Trait-First 多项目类型支持（v0.17，已完成）

支持网页 / 客户端 / 游戏 / UE / Godot / Unity / 微信小程序等多种项目类型。从 flat enum 升级到**trait + preset 混合架构**，skill/SOP/agent/mcp 按 traits 动态组装。详见：

- `docs/20260423_01_项目类型分类体系与对话式识别方案.md`（trait 体系 + 对话式识别）
- `docs/20260423_02_TraitFirst动态组装方案.md`（SOP fragments 组合 + Preview API，**最终方案**）

**~14.5 天 roadmap，分 7 个 Phase**（A-F + C'）：

| Phase | 内容 | 估时 |
|---|---|---|
| A | DB 迁移 + trait_taxonomy + presets.yaml + confirm_project traits 必填 + 对话历史压缩 + preset 关键词推荐 | 2.5 天 |
| B | SkillLoader 三层过滤（inject_to + traits_match + paths）+ rules/global.md + 现有 4 个 skill 重构（加 vcs:git trait）+ Skill 分组特化压制 | 4.5 天 |
| C | SOP base+fragments 组合器 + Action/Agent 加 available_for_traits + ticket_type 维度 | 3.5 天 |
| C' | POST /api/projects/preview-assembly 只读端点 | 1 天 |
| D | ProjectTypeDetectorAction（导入链路自动探测）| 1.5 天 |
| E | 前端「项目特征」子 Tab（编辑 traits + 生效配置展示）| 1 天 |
| F | MCP 加 enabled_for_traits | 0.5 天 |

**推荐节奏**：A+B+C+C'（~11.5 天）一批跑通核心垂直切片，D+E+F（~3 天）二批补全。

**阻塞 / 并吞的 TODO 项**：
- 本栏目下方"ChatAssistantAgent 默认化"P2 → trait-first 里的 ChatAssistant 反问规则会一起实现
- 本栏目下方"前端 SOP 拖拽编辑器"P2 → trait-first 的 fragments 组合器是它的前置 + 替代
- 本栏目下方"DeployAgent 读项目类型"P2 → trait-first 落地后直接靠 traits 读取
- 本栏目下方"ArchitectAgent 缺 SOP 配置读取"P2 → fragments 组合器覆盖

---

## Action 池（已完成 v0.15.0，2026-04-16）

| Action | 说明 | 状态 |
|--------|------|------|
| `CodeReviewAction` | 读取实际代码做审查（解决盲审） | ✅ |
| `DecomposeAction` | 需求拆单 ActionNode（读已有代码） | ✅ |
| `PlanCodeChangeAction` | 先规划再精准增量修改（解决全文件重写） | ✅ |
| `SummarizeCodeAction` | 代码摘要 | ✅ |
| `DebugErrorAction` | 分析错误日志，定位根因 | ⬜ P1 |
| `ResearchAction` | 联网搜索 + 竞品调研 | ⬜ P2 |
| `WritePRDAction` / `WriteTestAction` / `ExecuteCodeAction` 等 | 长期 P2 | ⬜ P2 |

---

## ActionNode 迁移（已全部完成，v0.15.0，2026-04-16）

| Agent | 状态 |
|-------|------|
| ArchitectAgent | ✅ ActionNode + Watch |
| DevAgent | ✅ ActionNode + BY_ORDER + PlanCodeChange/WriteCode 智能分发 |
| ProductAgent 拆单 + 验收 | ✅ ActionNode + DecomposeOutput Schema |
| TestAgent | ✅ 委托 CodeReviewAction |
| ReviewAgent | ✅ ActionNode 实审（非盲审） |
| DeployAgent | 🔄 legacy 保留（特殊逻辑），P2 迁移 |
| REACT 模式 | ✅ LLM 动态选择 Action（`_react_with_think`） |

## 盲审修复

| 优先级 | Agent | 问题 | 修复内容 | 状态 |
|--------|-------|------|---------|------|
| ✅ | ProductAgent 拆单 | 不看已有代码就拆单 | orchestrator 触发前注入 existing_files/code；AgentMemory.get_code_context() 复用 | **完成 2026-04-21** |
| ✅ | ReviewAgent | 完全盲审/从未被调用 | 抽成独立 SOP 阶段（dev → code_review → acceptance）+ CodeReviewAction 读实际代码 + ActionNode + SOP 配置；详见 `docs/20260421_03_盲审修复P0实现方案.md` | **完成 2026-04-21** |
| ✅ | DevAgent SelfTest | 不读 Git 仓库实际文件 | run() 开头预落盘 + check 6 磁盘落地验证；SOP `verify_disk_files` 开关；详见 `docs/20260422_02_SelfTest读Git实际文件.md` | **完成 2026-04-22** |
| P2 | DeployAgent | 不读代码，部署配置通用化 | 读取项目类型生成针对性部署配置 |
| P2 | ArchitectAgent | 缺 SOP 配置读取 | 使用 sop_config 中的参数 |

## 架构改进

| 优先级 | 项目 | 说明 |
|--------|------|------|
| P1 | 前端 SOP 拖拽编辑器 | 可视化编辑流程，不用手改 YAML |
| ✅ | **需求 Pipeline 可视化由 SOP 驱动** | **已完成 2026-04-17**：新增 `pipeline_view` 配置节 + `sop/loader.py:build_pipeline_stages()` 派生函数；消除 3 处硬编码（`api/requirements.py:283` 的 STAGE_DEFS/PAST/PRE + 观测 Action 的二次硬编码）。现在改流程只要改 yaml 一处，UI 和观测 Action 同步更新 |
| P2 | Memory 持久化索引 | cause_by 索引目前在内存，重启丢失 |
| P2 | 前端 Agent 配置页 | 可切换 ReactMode、启用/禁用 Action |
| P2 | **仓库文件显示 / diff 展示优化** | 文件浏览器：大文件截断策略 / 语法高亮对齐 / 二进制文件占位符；diff 视图：左右分栏 / 行级高亮 / 折叠未变化的大段 / 跳转相关文件 |
| P2 | **仓库分支管理页显示树形关系** | 当前分支列表是扁平平铺；改成展示 `feat/* → develop → main` 的父子树形 + 每分支的 ahead/behind 数 + 最近一次 commit，一眼看清分支结构 |
| 🔄 | **ChatAssistantAgent 默认化** | 已推进大半：v0.16.5 全局聊天也迁到 Agent + tool_use（详见 `docs/20260422_03_全局AI助手新建项目链路分析与Agent化方案.md`）。剩余：观察期后清理 `_global_chat_legacy` + `_parse_global_action` + `[ACTION:CREATE_PROJECT]` prompt 文本协议（~100 行代码） |
| ✅ | **ChatAssistant 观测能力** | **已完成 2026-04-17**：新增 `GetRequirementPipelineAction` / `GetTicketStatusAction` / `GetRequirementLogsAction` 三个 Action。AI 现在能回答"XX 卡在哪""最近发生了什么"，直接给出根因（例："被打回 5 次 → 强制通过"）而非猜测 |

## Phase 3: v0.15 — 智能增强

| 优先级 | 版本 | 内容 | 状态 |
|--------|------|------|------|
| P0 | v0.15.0 | 多 LLM 支持（Ollama + 降级链） | 待开发 |
| P1 | v0.15.1 | 并发调度（多工单并行） | 待开发 |
| P1 | v0.15.2 | ResearchAgent 竞品分析 | 待开发 |
| P2 | v0.15.3 | 前端 SOP 拖拽编辑器 | 待开发 |

## Phase 4: v0.16 — 平台化

| 优先级 | 版本 | 内容 | 状态 |
|--------|------|------|------|
| P1 | v0.16.0 | 插件市场 | 待开发 |
| P2 | v0.16.1 | 多项目协作 | 待开发 |
| P2 | v0.16.2 | Data Interpreter | 待开发 |

## Bug 修复记录（已完成 16 个）

| 日期 | 问题 | 根因 | 修复 |
|------|------|------|------|
| 04-22 | 工单 AI 对话 `content.replace is not a function` | v0.15.2 后 tool_use 消息的 content 是 list of blocks 不是字符串 | 后端加 `_content_to_display_text` 展平 + 前端 `formatChatContent` 加类型兜底 (v0.16.4) |
| 04-22 | 属性面板点「AI 对话」关闭面板 | onclick 里有 closeDrawer() | 去掉 closeDrawer() 调用 (v0.16.4) |
| 04-15 | 工单卡在 success 状态 | ActionResult.to_dict() 覆盖 data 中的 status | 不覆盖已有 status |
| 04-15 | 验收死循环 53 次 | BY_ORDER files 覆盖 + 盲审 | 修 files 合并 + 加 max_retries 5 |
| 04-15 | 产出文件在仓库找不到 | BY_ORDER 后续 Action 覆盖前面的 files | pop files 后再 update |
| 04-15 | 验收说缺 index.html 但实际存在 | 验收只看 dev_result 不看仓库 | 传入 existing_files + code |
| 04-15 | 需求创建卡片不显示 | JSON 中文引号/未转义双引号解析失败 | _try_fix_json 三策略修复 |
| 04-15 | 截图路径错误 | MD 中用完整路径而非相对路径 | 改为 screenshots/xxx.png |
| 04-15 | 截图不生成 | Playwright 浏览器未安装 + 文件未落盘 | Chrome headless 兜底 + flush_files |
| 04-15 | MD 预览不显示图片 | 仓库文件浏览器不支持图片渲染 | file-raw API + 相对路径自动转换 |
| 04-14 | 分支没创建 | subtasks 字符串/dict 格式不兼容 | 兼容两种格式 |
| 04-14 | LLM 返回截断 | max_tokens=4096 不够 | 提升到 16000 + 精简 prompt |
| 04-14 | CI lint 失败 | orchestrator 缺 pathlib.Path import | 添加 import |
| 03-30 | 删除项目失败 | ci_builds 未级联删除 + DB locked | 加 ci_builds 删除 + busy_timeout |
| 03-30 | llm_conversations ticket_id 为 NULL | 全局单例 context 并发覆盖 | 改用 contextvars |
| 03-30 | 代码生成废模板 | fallback 生成中文类名空壳 | 改为可运行的 index.html |

## 新功能想法

- ReportAgent：每日自动汇总项目进展生成日报
- 安全扫描 Agent：检查代码安全漏洞
- 性能测试 Agent：页面加载速度、API 响应时间
- 数据库迁移路径更新工具：换机器时批量更新 git_repo_path

---

*待办清单由 AI Dev System 团队维护*
