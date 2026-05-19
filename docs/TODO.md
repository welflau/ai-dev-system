# AI Dev System — 待办清单

> 最后更新: 2026-05-19

---

## 🎯 待办（未完成）

### ✅ K. AI 助手无法访问系统内多类数据（已完成 2026-05-19）

**P1（实用性高，优先补）**：

| 缺失工具 | 对应数据 | 用途 |
|---|---|---|
| `get_bugs` | `bugs` 表 | 查看项目 Bug 列表、状态、优先级 |
| `get_ci_builds` | `ci_builds` 表 | 查看真实 CI 构建记录 |
| `get_failure_cases` | `failure_cases` 表 | 查看失败案例库 |

**P2（需要但不急）**：

| 缺失工具 | 对应数据 |
|---|---|
| `get_milestones` | `milestones` 表（项目里程碑）|
| `search_design_knowledge` | `design_knowledge` / `ux_knowledge` 表 |
| `search_art_assets` | `art_assets` 表（美术资产库 33000+ 条）|

---

### J-4. Agent REACT 模式接入 Diminishing Returns 验证（P1）

`base.py:_react_with_think_inner` 的 QueryEngine 已有 Budget，需验证 `is_diminishing()` 实际是否触发。

---

### I. 分屏思考面板不显示（P1）

进入分屏模式后，主格思考面板不显示，非分屏正常显示。
疑为 CSS 问题，需用 DevTools 检查 computed style。

---

### H. 系统自进化：成功经验自动沉淀为 Skill（P2）

工单验收通过后，AI 自动提炼可复用技术模式，生成 Skill 草案（draft），人工确认后写入 skills.json。
详见：`docs/20260509_系统自进化_Skill自动沉淀方案.md`

---

### G. Reflexion UE uproject 自愈（P2）

Playtest 因 "module could not be loaded" 失败时，自动检测缺失插件声明并补写 `.uproject`，重触发编译+重测。

---

### J-3b. 思考过程按轮次分组展示改进（P2）

方案文档：`docs/20260517_03_思考过程分组展示方案.md`（已完成基础实现，可继续优化）

---

## ✅ 已完成

### ✅ NextPhase 系列（2026-05-18~19）

**方向 A：基础设施（对标 Claude Code）**
- A-1 Commands 斜杠命令框架（7 个命令 + 补全 UI）
- A-2 Thinking 三态（adaptive/on/off）+ BaseAgent 能力下沉
- A-3 Memory 4 类型对齐 + MEMORY.md 索引注入
- A-4 @file 引用展开

**方向 B：UE 创作能力**
- B-0 UE Python 桥接（ue_python_bridge）
- B-1 BlueprintGenAction（LLM 生成 BP）
- B-2 LevelGenAction（LLM 生成关卡布局）
- B-3 UEEditorAgent + SOP 接入

**ADSDir 系列（2026-05-19）**
- P1 `.ads/rules/` 项目级规则支持
- P2 `.ads/skills/` 替代 `.Agent/skills/`
- P3 memory.md 导入/导出（`/memory-export`、`/memory-import`）
- P4 `.ads/config.json` + `/ads-init` 命令 + 新建项目自动初始化

**其他（2026-05-18~19）**
- J-1/J-2/J-3 思考过程对标 Claude Code（耗时/结构化摘要/推理链）
- J-3b 思考过程按轮次分组展示
- 记忆管理面板（🧠 按钮）
- 全局 AI 助手全量工具开放
- 工具描述修复（任意路径访问）
- 输入历史持久化 + 斜杠命令补全键盘操作
- `confirm_project` 卡片流式回复后不显示修复
- `get_build_logs` SQL 列名错误修复（tl.message→tl.detail）

---

### ✅ A 方向（2026-05-17）

L1 Diminishing Returns / L3 Prompt Cache / L4 Compaction / L5 Rules+FTS5+Memory /
L6 Hooks（nudge_hook）/ L7 USD 费用追踪 / L8 并行子任务 / L9 Feature Flags
评分 5.5 → 7.5（+2.0 分）

---

### ✅ .ads 目录规范

方案文档：`docs/20260519_04_ADS项目目录规范_ads目录设计方案.md`

---

### ✅ 早期完成项（v0.15~v0.21，2026-04 ~ 05）

- **F** AI 助手多会话管理（2026-05-04）
- **A/B/C** Memory 持久化 / Insight 主动注入 / 研发效率统计（2026-05-06）
- **v0.20** UE MCP Phase 1-5 / Skills 市场双目录 / AI 助手流式统一
- **v0.19.x** UE 自动编译 + Playtest / Viewport 截图 / CI/CD 合并
- **v0.18** UE 引擎检测 / 模板实例化 / UBT 编译 + 错误解析 / Reflexion 自动修复
- **v0.17** Trait-First 动态 Skill 注入 / 多会话管理 / SOP 可视化
- **v0.16** ChatAssistant 全面升级 / Skill 主动触发 / 盲审修复
- **v0.15** MetaGPT 移植（ActionNode / 状态机 / REACT 模式）
- **v0.13~14** SOP 配置化 / 事件驱动 / 流程查看器

---

*详细变更见 `dev-notes/` 目录*
