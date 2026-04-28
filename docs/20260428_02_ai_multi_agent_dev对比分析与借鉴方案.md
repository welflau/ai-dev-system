# ai_multi_agent_dev 对比分析与借鉴方案

> 分析日期：2026-04-28
> 被分析项目：`G:\B_OA\AI\ai_multi_agent_dev\`
> 来源：`G:\B_OA\AI\ai_multi_agent_dev\` + 腾讯 KM《如何让 AI 分工帮我做游戏（三）》
> 结论：自动化程度低于我方，但记忆系统、效率追踪、Insight 主动注入、Unity HTML 原型管线四个方向有借鉴价值

---

## 一、被分析系统概述

`ai_multi_agent_dev` 是一套以 **CodeBuddy IDE** 为运行环境、**TypeScript** 为主要语言的多 Agent 开发辅助框架。核心设计思想是"三层解耦"：

```
Core 层（框架无关 YAML）
    ↓ Adapter 转换
Adapter 层（CodeBuddy / CrewAI / LangGraph）
    ↓ 实例化
具体项目（软链接 + 个性化规则）
```

当前处于 **Phase 1**（CodeBuddy IDE 内人工辅助验证），Phase 2 计划迁移到 CrewAI/LangGraph 全自动化。

五个核心 Agent 角色（YAML 定义，框架无关）：

| 角色 | 推理范式 | 核心职责 |
|------|---------|---------|
| 技术负责人 | Plan-and-Execute | 需求分析、任务拆解、验收标准定义 |
| 后端开发 | CoT / ReAct | API 实现、TDD、数据库设计 |
| 前端开发 | CoT | 页面实现、组件开发、API 对接 |
| 测试工程师 | CoT + ReAct | 测试用例设计前置、E2E / 接口验收 |
| 知识工程师 | CoT | 知识资产沉淀、Skill 封装、Rule 归纳 |

---

## 二、全面对比

### 2.1 整体定位

| 维度 | ai_multi_agent_dev | 我方系统 |
|------|-------------------|---------|
| **自动化程度** | 人工辅助（IDE 内手动触发） | 全自动流水线（无人值守） |
| **运行环境** | CodeBuddy IDE | FastAPI 后端服务 |
| **主语言** | TypeScript | Python |
| **当前阶段** | Phase 1（验证中） | v0.19（生产可用） |
| **Agent 数量** | 5 个固定角色 | 7 个（含 ChatAssistant） |
| **垂直领域** | 通用 Web | 通用 + UE 游戏深度支持 |

### 2.2 流程编排

| 维度 | ai_multi_agent_dev | 我方系统 |
|------|-------------------|---------|
| **流程定义** | YAML（框架无关） | YAML（_core.yaml + fragments） |
| **动态组装** | 无 | Trait-first，按项目类型自动组合 |
| **人工门禁** | 🚦 每个阶段均有 | 仅创建需求、确认项目时有 |
| **并行开发** | 支持（CDD 契约先行） | 不支持（串行流水线） |
| **失败重试** | 人工介入 | Reflexion 自动反思重试 |

### 2.3 知识与记忆

| 维度 | ai_multi_agent_dev | 我方系统 |
|------|-------------------|---------|
| **Skill 载体** | Markdown 文件（软链接复用） | YAML + LLM prompt 注入 |
| **知识检索** | 无（静态文件，靠 IDE 上下文） | FTS5 全文检索（中英文 trigram）|
| **运行时记忆** | 结构化 Markdown 文件（持久化） | Python 内存（重启丢失）|
| **Agent 交接** | HANDOFF.md 标准化交接物 | orchestrator 工单状态隐式传递 |
| **技术决策日志** | DECISIONS.md（可查询为什么） | 仅有 dev-notes（非结构化）|

### 2.4 测试体系

| 维度 | ai_multi_agent_dev | 我方系统 |
|------|-------------------|---------|
| **测试前置** | ✅ 测试工程师在开发前设计用例 | ❌ 测试在开发后 |
| **CDD** | ✅ API 契约先行，前后端并行 | ❌ 后端先，前端后 |
| **E2E 测试** | ✅ Playwright 脚本自动生成 | ❌ 无 |
| **自测** | 单元测试（TDD） | SelfTestAction（静态规则 + 编译）|
| **UE 测试** | 无 | ✅ UEPlaytestAction headless |

### 2.5 效率与可观测性

| 维度 | ai_multi_agent_dev | 我方系统 |
|------|-------------------|---------|
| **研发效率统计** | ✅ 自动时间戳采集 + 聚合报告 | ❌ ticket_logs 有原始数据但无聚合 |
| **工单实时进度** | 无 | ✅ SSE 推送 + drawer 进度区 |
| **AI 诊断** | 无 | ✅ GetBuildLogsAction AI 自动诊断 |
| **跨端协作** | ✅ CodeBuddy + OpenClaw 多端 | ❌ 单端 |

---

## 三、可借鉴点深度分析

### 3.1 ✅ 高价值：结构化 Memory 持久化

**他们怎么做**

```
core/memory/runtime/
├── ACTIVE_WORKERS.md    每个 Agent 当前状态 + 任务
├── DECISIONS.md         技术决策日志（为什么这样设计）
├── PROJECT_STATUS.md    迭代进度快照
└── HANDOFF.md           Agent 交接上下文（携带什么继续）
```

每次 Agent 完成工作，写入对应文件；下一个 Agent 启动前读取交接物。文件由 Git 管理，永不丢失。

**我们的问题**

- `cause_by` 关系链在内存中，重启即消失
- Orchestrator 传递上下文靠函数参数，跨进程无法查询"这个工单为什么被打回"
- ChatAssistant 无法回答"当初这个架构设计为什么这样"

**借鉴方案**

不完全照搬文件方案（我们已有 SQLite），而是在现有 DB 上增加 `agent_memory` 表，语义对齐他们的四个文件：

```sql
CREATE TABLE agent_memory (
    id          TEXT PRIMARY KEY,
    type        TEXT,  -- 'decision' | 'handoff' | 'project_status' | 'active_worker'
    project_id  TEXT,
    ticket_id   TEXT,
    content     TEXT,  -- JSON
    created_at  TEXT,
    expires_at  TEXT   -- 可空，NULL 表示永久保留
);
```

**投入产出**：1 天，解决已知技术债，同时让 ChatAssistant 能回答"为什么"类问题。

---

### 3.2 ✅ 中等价值：研发效率统计

**他们怎么做**

`dev-efficiency-tracker` Skill 在每轮 AI 对话自动打时间戳，按需求 / 迭代 / Agent 聚合，生成报告："武器系统需求总耗时 4.2h，DevAgent 占 2.8h，Reflexion 重试 3 次"。

**我们的问题**

`ticket_logs` 表有所有操作日志，但没有聚合层。用户无法直观看到"这个项目每个需求平均多久交付"、"哪个 Agent 最耗时"。

**借鉴方案**

基于现有 `ticket_logs` 做聚合查询，新增 `GET /api/projects/{id}/efficiency` 端点和前端效率看板页。不需要新增打点，数据已经有了。

**投入产出**：1 天后端 + 0.5 天前端。

---

### 3.3 ✅ 高价值：Insight 主动注入（来源：腾讯 KM）

**他们怎么做**

`vibecli insight search` 在开发者开始编码前自动搜索匹配经验库，命中的 Insight 主动注入 prompt：
```
DevAgent 开始编码前
    → 自动搜索 "event,lifecycle,unity"
    → 命中："事件订阅必须在 OnDestroy 中取消"（高置信度）
    → AI 输出中附注：已在 OnDestroy 中添加 Unsubscribe
```

**我们的问题**

知识库搜索只在 ChatAssistant 用户对话时触发，DevAgent 写代码时从不查知识库。过去踩的坑、历史工单的解决方案，不会自动阻止下次再踩。

**借鉴方案**

DevAgent 的 `develop` / `fix_issues` 入口处，用任务标题 + project traits 自动查一次 `search_knowledge` + `search_ticket_history`，把命中的 Insight 追加到 ActionNode 的 system prompt 头部。FTS5 基础设施已有，只需在 `_build_context()` 里加一次调用。

**投入产出**：0.5 天，零新增基础设施，直接复用现有知识库。

---

### 3.4 ✅ 高价值：Unity HTML 原型 → Prefab 管线（来源：腾讯 KM）

**他们怎么做**

先用 HTML 跑通核心玩法逻辑（1-2 天），通过后再进 Unity 开发；HTML 原型不丢弃，而是通过 Baker 工具转换为 Unity Prefab 骨架：

```
HTML 原型（AI 擅长 Web，热重载快）
        │ SelfTest 验证玩法逻辑
        │ 通过
        ▼
Baker：HTML Layout → DOM 解析 → 资源 JSON → Unity Prefab + ButtonBinder 脚本
        │
        ▼
Unity 开发（基于已验证的结构还原，省去手搭 Prefab）
```

**对我们的价值**

`engine:unity` 项目有两层收益：
1. **验证成本降低**：Unity 启动慢、热重载复杂，HTML 原型 1-2 天验证玩法方向，错了损失小
2. **UI 开发提速**：HTML UI → Unity Prefab 的自动转换，省去手搭 Panel / Button 层级的重复劳动，AI 写 HTML 质量远高于直接写 Unity UI 代码

**借鉴方案**

两阶段实现：

**Phase 1：html_prototype SOP fragment**（`engine:unity` 项目注入）
- `architecture` 之后插入 `html_prototype` stage
- DevAgent 生成 HTML 版玩法原型
- SelfTestAction 在浏览器中运行验证核心循环
- 通过后写入 `html_prototype_passed`，携带 HTML 产物进入 `development`

**Phase 2：HtmlToUnityAction（Baker 等价物）**
- 解析 HTML DOM 结构（div / button / span 层级）
- 生成对应的 Unity Prefab C# 脚本骨架（Panel / Button binding）
- 输出 `Assets/UI/` 目录结构，DevAgent 在此基础上实现游戏逻辑

**投入产出**：Phase 1 约 2 天，Phase 2 约 3 天，总计 ~5 天。前置：Unity `engine:unity` trait 基础支持完善。

---

### 3.5 ⬜ 低优先级：CDD（契约驱动开发）

**他们怎么做**

在 Architect 之后插入 `api_contract` 阶段：TL 输出 OpenAPI 接口定义，前端 mock、后端实现同步进行，不等后端完成再做前端。

**我们的问题**

Web 项目前后端串行，DevAgent 先做后端 API 再做前端页面，总耗时更长。

**借鉴方案**

新增 SOP fragment `api_contract.yaml`，仅对 `platform:web + category:app` 项目注入，在 `architecture` 之后、`development` 之前增加 API 契约生成阶段，将 DevAgent 的工单拆为"后端组"和"前端组"并行执行。

**前置条件**：并发调度完成后才有意义。暂不做，记录为 v0.20+ 候选。

---

## 四、不建议借鉴的

| 项目 | 原因 |
|------|------|
| 框架无关 Core YAML | 我们深度绑定 Python / FastAPI / Anthropic，迁移需求为零，解耦只增加维护成本 |
| 软链接 Skill 复用 | 我们用 FTS5 知识库检索，比软链接更灵活且支持语义搜索 |
| 人工确认门禁 | 我们的目标是全自动，人工门禁是退步而非进步 |
| Phase 1 → Phase 2 迁移路线 | 我们已经在 Phase 2+，不需要这条路线图 |
| vibecli CLI 工具本身 | 我们是服务端自动流水线，不需要开发者手动触发命令 |

---

## 五、开发计划

### 阶段一：Memory 持久化（P1，~1.5 天）

**目标**：解决重启丢失问题，让 ChatAssistant 能查询历史决策。

```
Day 1
  上午：DB 迁移（agent_memory 表 + 索引）
  下午：Orchestrator 写入时机（architecture_done / acceptance_rejected / deployed）

Day 2 上午
  ChatAssistant 新增 get_memory 工具（查 decision / handoff 类型）
  smoke 测试 + 验收
```

**交付物**：
- `agent_memory` 表（4 种类型）
- Orchestrator 在关键节点自动写入决策摘要和交接物
- `GetMemoryAction`：ChatAssistant 可查"这个需求当初为什么这样设计"

---

### 阶段二：研发效率统计（P2，~1.5 天）

**目标**：基于现有 `ticket_logs` 数据，提供可视化效率报告。

```
Day 1
  上午：后端聚合查询（按需求/Agent/时间段统计耗时和重试次数）
  下午：GET /api/projects/{id}/efficiency + GET /api/projects/{id}/requirements/{id}/stats

Day 2 上午
  前端效率页（折线图：每个需求交付周期 / 柱状图：各 Agent 占比 / 表格：重试次数排行）
```

**交付物**：
- 效率统计 API（需求交付周期、Agent 耗时占比、Reflexion 重试次数）
- 前端效率看板（项目级 + 需求级两个视图）

---

### 阶段三：Insight 主动注入（P1，~0.5 天）

**目标**：DevAgent 编码前自动查知识库，过去踩的坑不再重复踩。

在 `orchestrator._build_context()` 里，调 `SearchKnowledgeAction` + `SearchTicketHistoryAction` 各一次，结果拼入 DevAgent context 的 `prior_insights` 字段，ActionNode 构建 prompt 时自动带入。

**交付物**：DevAgent develop / fix_issues 自动携带相关历史经验，无需用户触发。

---

### 阶段四：Unity HTML 原型管线（P2，~5 天，前置：engine:unity 基础完善）

**目标**：Unity 项目先用 HTML 验证玩法，再用 Baker 生成 Prefab 骨架，降低方向错误成本 + UI 开发提速。

```
Phase 1（~2 天）：html_prototype SOP fragment
  - html_prototype stage（engine:unity 自动注入）
  - DevAgent 生成 HTML 原型
  - SelfTestAction 浏览器验证核心玩法循环

Phase 2（~3 天）：HtmlToUnityAction
  - HTML DOM → Unity Prefab 骨架（Panel/Button/Text 层级）
  - 自动生成 ButtonBinder / PanelController C# 脚本
  - 输出 Assets/UI/ 目录，DevAgent 在此基础上实现逻辑
```

---

### 阶段五：CDD 并行开发（v0.20+，前置：并发调度完成）

占位，待并发调度完成后详细设计。核心思路：`api_contract` SOP fragment + DevAgent 工单按前后端分组并行执行。

---

## 六、总结

```
立即做（低成本高回报）    近期做               中期做            长期
──────────────────────  ─────────────────   ──────────────   ───────
Memory 持久化            研发效率统计         Unity HTML       CDD 并行
（解决技术债）            （已有数据补视化）    原型管线          开发
1.5 天                   1.5 天              5 天             v0.20+

Insight 主动注入
（零新增基础设施）
0.5 天
```

两个来源（`ai_multi_agent_dev` + 腾讯 KM）共提炼出四条可落地建议。最快的是 Insight 主动注入（0.5 天，复用现有 FTS5），最有战略价值的是 Unity HTML 原型管线（打通 Web → Unity 的低成本迭代路径）。
