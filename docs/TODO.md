# AI Dev System — 待办清单

> 最后更新: 2026-10-19
> 对照：`dev-notes/2026-08` ~ `2026-10`、`docs/202610*.md`、前端 `app.js` / 后端工单与产物总线。

---

## 🎯 待办（未完成）

### OpenSpec 灰色状态说明（低优先）

工单会话三层总览栏中，规范层 Propose/Apply/Verify/Archive 全灰时，当前只有 `○ 待进行` 图例。

**现状**（2026-10-19 对照 `frontend/app.js` `_buildThreeLayerBar`）：`openspec_stage` 为空时四个节点都是 `tlb-pending`，没有额外说明。

**需求**：全灰时在规范层行末加一个小提示「未触发 OpenSpec 流程」，或加 tooltip 说明原因（未安装/未触发 Propose）。

---

### 工单后台任务：对话引用输出（剩余）

按工单过滤查看、展开完整命令行输出已经落地（见下方已完成）。还没做的是：AI 对话时把该工单的后台任务输出引用进上下文。

---

### 能力自描述与动态组装 · 明确不做 / 历史债务

主线已交付（见已完成）。方案 `docs/20261017_01` §7.2 记下、代码未改的：

- 阶段间并行被压成串行。拓扑能表达「A、B 并行后汇入 C」，orchestrator 的 `transition_rules` 是单链，出路是阶段内 `dispatch_subtask`。
- 3 处 trait 拼写漂移（`i18n` / `multiplayer:true` / `prototype:html`）和 11 项库内 trait 漂移。防漂测试只拦住新增，已知项在白名单里。
- 上游 producer skipped 后，下游 required consumer 仍会启动。当前只在 prompt 里标 `_artifacts_missing`。
- 同一工单返工会覆盖旧产物文件，没有版本回溯。

---

### 群聊 Phase 2

PM 循环和话题分支已可用（见已完成）。`dev-notes/2026-10-14_01` 留下：

- 验收点完成度精确版（PM 显式输出每条状态；现在是关键词启发式）
- `reply_to` @引用高亮
- `agent_stream` 每字符滚动节流
- 更多 Role Agent 入群聊 roster
- 进行中实时打断、Agent 私聊（成本高，独立评估）

---

### 外部会话：不绑项目的全局浏览

Cursor / CodeBuddy / Claude Code 的项目内浏览、导入为 ADS 会话已落地。`docs/20261009_01` 阶段 2 还挂着：当前 API 都在 `/api/projects/{pid}` 下，全局 AI 助手要另加 `/api/external-sessions`。

---

## ✅ 已完成（2026-10）

### ✅ 能力自描述与动态组装（2026-10-15~17）

接新能力从「fragment + skills.json + SKILL.md」收成一个 `SKILL.md`（新 kind 再登记 `artifacts/kinds.yaml`）。`consumes` / `produces` 拓扑排序，产物走 ArtifactStore。测试 290 → 322。真实 CLI 跑通 demo-outline / demo-draft / demo-cover（含 4.3MB PNG）。顺带修了 LightAI key 被进程环境旧值盖过 `.env`。

方案：`docs/20261015_01`、回顾：`docs/20261017_01`。DevNote：`dev-notes/2026-10-15_01` ~ `2026-10-17_01`。

### ✅ 多 Agent 群聊（2026-10-12~14）

黑板 Phase 1、PM 决策循环（目标提炼、用户介入、纪要）、话题分支（continue / resume / new，归档上限 8）。

方案：`docs/20261012_01`、`docs/20261013_02`。DevNote：`2026-10-12_07`、`2026-10-13_01`、`2026-10-13_02`、`2026-10-14_01`。
`docs/20261013_03` 文头仍写「待实现」，实现以 10-14 DevNote 为准。

### ✅ 外部会话浏览器（2026-10-09~12）

项目内浏览 Cursor / CodeBuddy / Claude Code 会话：时间戳、图片、代码块、FilesChanged 行内 diff、滚动与选中记忆、导入为 ADS 聊天会话。

方案：`docs/20261009_01`。DevNote：`dev-notes/2026-10-10_*`、`2026-10-12_01` ~ `2026-10-12_06`。

### ✅ Agent 级 LLM 配置（2026-10-11）

每个 Agent 可单独配 API 或 CLI。AI 助手头像打开配置。方案：`docs/20261011_01`。DevNote：`2026-10-11_01`。

---

## ✅ 已完成（2026-08 ~ 09）

### ✅ 工单后台任务按工单过滤（2026-08-02，后续补命令落库）

工单聊天头部「📟 后台任务」→ `_openTicketTasksPanel`，`_tasksTicketFilter` 只显示该工单。输出复用 `_renderCliTaskOutput`。真命令在 `ticket_command_log`，`GET /tickets/{id}/command-logs`，与从日志合成的任务按 `log_id` 去重。

DevNote：`2026-08-02_01`、`2026-09-20_03`。

### ✅ OpenSpec 可见性、Apply、Checkpoint、壳层与知识库（2026-08）

- OpenSpec propose 过程可见、Apply 接入、change_id 前后端一致、非代码工单跳过 UE 编译
- 工单 Checkpoint 快照 / 时间轴还原 / CLI 钩子与 GC
- 壳层工作区、主舞台文件查看器、知识库统一查看器与 FTS 浏览
- Cursor CLI 接入

DevNote：`2026-08-02_01`、`2026-08-06_*`、`2026-08-07_*`、`2026-08-11_01`、`2026-08-24_*`、`2026-08-25_01`。

### ✅ UE 工单闭环、Test/Artist、对话追踪（2026-09）

UE 工单流转闭环、TestAgent UE 静态分析、ArtistAgent、时间轴日志双向定位、turn_id 贯通与 trace 页。

DevNote：`2026-09-10_*`、`2026-09-11_*`、`2026-09-19_01`、`2026-09-29_01`、`2026-10-01_01`。

---

## ✅ 已完成（2026-07 三层融合系列）

### ✅ 三层融合（OpenSpec × Superpowers × Harness）2026-07-21~22

完整实现三层架构、可观测性、变更触发机制：
- Superpowers Pack 套件（14 SKILL.md）+ DevAgent 铁律注入
- OpenSpec Propose/Verify/Archive 自动集成
- 工单能力提示横幅 + 三层状态总览栏 + OpenSpec 内容面板
- 时间轴三层颜色标注 + 工单卡片印章
- ChangeImpactAnalyzer + Tweak/Partial/Breaking 三种变更流
- 项目三层仪表盘 + Specs 版本历史 UI
- 详见 `dev-notes/2026-07-21_*.md`

### ✅ 工单会话窗口完整执行流 2026-07-22

`get_ticket_conversations` 合并 `ticket_logs` 编排事件，工单会话窗口显示完整执行日志流（Agent 接单 / LLM 推理 / 工具调用 / 阶段完成），按时间排序。

### ✅ UI 体验修复系列 2026-07-22

进度面板静默感知（呼吸动画 + 动作说明）/ 气泡折叠 / 报错文件路径可点击 / LLM 推理 vs 本地工具日志区分 / 错误卡片工单链接 / 三层总览栏修复

---

*详细变更见 `dev-notes/` 目录*


---

## ✅ 已完成（2026-05）

### ✅ H. 系统自进化：成功经验自动沉淀为 Skill（已完成 2026-05-22）

工单验收通过后异步触发 SkillExtractorAction，LLM 分析工单轨迹提取草案，
人工通过 `confirm_skill` 工具确认后写入 skills.json 并热重载。
提交：`7e72802` | DevNote：`2026-05-22_02_Evolve_TODOH_Skill自动沉淀.md`

---

### ✅ G. Reflexion UE uproject 自愈（已完成 2026-05-22）

Playtest 因 "module could not be loaded" 失败时，自动检测缺失插件声明并补写 `.uproject`，重触发编译+重测。
提交：`4550be2` | DevNote：`2026-05-22_03_Evolve_TODOG_UEuproject自愈.md`

---

### ✅ J-3b. 思考过程按轮次分组展示（已实现）

`query_engine/events.py` RoundStartEvent、`api/chat.py` J-3b 分组存储、前端 `crp-round*` 分组渲染均存在。基础功能完整，如需进一步优化可独立排期。

---

### ✅ UE Skill 自适配（已实现）

`read_local_file` + `load_skill` + `ue_call` 三个 Action 均已存在并注册到 ChatAssistantAgent。
AI 可运行时读取 SKILL.md → 理解 API → 调用 `ue_call` 执行，无需为每个 Skill 写代码。

---

### ✅ QueryEngine 抽象（已实现）

`backend/query_engine/` 完整实现（engine.py 548行），ChatAssistant 流式/非流式、BaseAgent REACT 模式均已接入 QueryEngine 统一路径。

---

## ✅ 已完成

### ✅ ClaudeCompat 系列（2026-05-21~22）

ADS 兼容 Claude Code 目录结构（`.ads/` + `.claude/` 双目录共存）：

- **Phase A** 规则加载：`.claude/rules/` + `CLAUDE.md` + `.ads/rules/` + `ADS.md` 四路合并
- **Phase B** MCP 配置：`.claude/settings.json mcpServers` + `.ads/mcp_servers.json` 两路合并
- **Phase C** 命令加载：`.claude/commands/` + `.ads/commands/` 合并到前端补全
- **Phase D** `.claude/agents/` 项目 Agent 定义注入 memory_prompt
- **Phase E** `ads-init` 扩展模式 + `--claude` 参数 + `ADS.md` 模板生成

---

### ✅ Commands 系列（2026-05-22）

对标 Claude Code 补齐 9 个命令，命令总数 16 → 26：

新增：`/doctor` `/cost` `/diff` `/config` `/commit` `/context`
别名：`/review`（→`/aicr-check`）`/mcp`（→`/mcp-config`）`/init`（→`/ads-init`）

---

### ✅ Harness 增强系列（2026-05-21）

- **Phase 1** 规则精细化（`paths:` 文件匹配 + 分层规则 + `scene:` 字段）
- **Phase 2** AICR 自动代码审查（AutoAICR + PreCommit 两场景）
- **Phase 3** 知识库三层架构（wiki_index + `/save-to-knowledge` + `/search-knowledge`）
- **Phase 4** rules-bridge-mcp（外部 IDE 规则服务）
- **Phase 5** 工程质量体系（skill_audit + `/harness-audit`）
- **Phase 6** MCP 配置分层（项目级 `.ads/mcp_servers.json`，`/mcp-config`）

---

### ✅ K. AI 助手无法访问系统内多类数据（已完成 2026-05-19）

新增工具：`get_bugs` / `get_ci_builds` / `get_failure_cases` / `get_milestones` / `search_design_knowledge` / `search_art_assets`

---

### ✅ J-4. Agent REACT 模式接入 Diminishing Returns 验证（已验证 2026-05-19）

`QueryEngine.run()` → `budget.check()` → `is_diminishing()` 链路已通。

---

### ✅ I. 分屏思考面板不显示（已修复 2026-05-20）

根本原因：克隆节点时 `.crp-rounds-panel` 带有 `crp-collapsed` class 未移除。

---

### ✅ NextPhase 系列（2026-05-18~19）

**方向 A（基础设施）**：A-1 Commands / A-2 Thinking 三态 / A-3 Memory 4 类型 / A-4 @file 引用
**方向 B（UE 创作）**：B-0 Python 桥接 / B-1 Blueprint 生成 / B-2 关卡生成 / B-3 UEEditorAgent

---

### ✅ ADSDir 系列（2026-05-19）

P1 `.ads/rules/` / P2 `.ads/skills/` / P3 memory 导入导出 / P4 `config.json` + `ads-init`

---

### ✅ A 方向（2026-05-17）

L1~L9：Diminishing Returns / Prompt Cache / Compaction / Rules+FTS5+Memory / Hooks / USD 费用追踪 / 并行子任务 / Feature Flags
评分 5.5 → 7.5（+2.0 分）

---

### ✅ 早期完成项（v0.15~v0.21，2026-04~05）

- **F** AI 助手多会话管理
- **A/B/C** Memory 持久化 / Insight 主动注入 / 研发效率统计
- **v0.20** UE MCP Phase 1-5 / Skills 市场双目录
- **v0.19.x** UE 自动编译 + Playtest / Viewport 截图 / CI/CD
- **v0.18** UE 引擎检测 / UBT 编译 + 错误解析 / Reflexion 自动修复
- **v0.17** Trait-First 动态 Skill 注入 / 多会话管理 / SOP 可视化
- **v0.16** ChatAssistant 全面升级 / Skill 主动触发
- **v0.15** MetaGPT 移植（ActionNode / 状态机 / REACT 模式）

---

*详细变更见 `dev-notes/` 目录*
