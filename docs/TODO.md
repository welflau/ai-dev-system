# AI Dev System — 待办清单

> 最后更新: 2026-07-22

---

## 🎯 待办（未完成）

### 工单后台任务专用窗口

**背景**：工单执行过程中有大量 CLI 任务（UBT 编译、Playtest、Deploy 等），输出只能在全局后台任务面板看到，无法按工单过滤查看完整命令行输出。

**需求**：
- 工单详情页加"后台任务"区（或 Tab），只显示该工单相关的 CLI 任务
- 每个任务可展开查看完整命令行输出（复用 `cli_task_log` 表，filter by ticket_id / session_key）
- 和工单会话面板打通，AI 对话时可引用这些输出作为上下文

**参考实现**：
- 后端：`cli_task_log` 表已有 `session_key` 字段，可按工单 session 过滤
- 前端：在工单抽屉"进展时间轴"下方加"后台任务"折叠区，复用现有 `_renderCliTaskOutput()`

---

### OpenSpec 灰色状态说明（低优先）

工单会话三层总览栏中，规范层 Propose/Apply/Verify/Archive 全灰时，当前只有 `○ 待进行` 图例，用户需要更明确的提示。

**需求**：全灰时在规范层行末加一个小提示「未触发 OpenSpec 流程」，或加 tooltip 说明原因（未安装/未触发 Propose）。

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

## 🎯 待办（未完成）

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
