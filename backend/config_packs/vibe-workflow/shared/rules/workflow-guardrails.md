---
description: 开发流程强制拦截规则 — 提交拦截、编码拦截、状态感知、UI 守卫。所有对话中始终生效，违反即为严重缺陷。
title: Workflow Guardrails
impact: CRITICAL
impactDescription: 防止跳过流程直接提交或编码，确保文档-代码一致性
tags: workflow, guardrail, commit, plan, done, review
alwaysApply: true
globs: []
enabled: true
updatedAt: 2026-03-27
---

# 开发流程强制拦截规则

以下规则具有**最高优先级**，必须在每次交互中时刻保持警惕并强制执行。

---

## 1. 提交拦截 (Auto-Done Hook)

**触发词**："提交代码" / "commit" / "push" / "写 commit message" / "任务做完了"

**强制动作**：
- 检查项目根目录 `CURRENT_PLAN.md` 是否存在且有未完成任务 `[ ]`。
- **如果有未完成计划**：绝对不允许直接提交。必须先完成真实 `/review` 与 `/done` 链路，再进入提交。
- **如果没有未完成计划**：仅当变更满足轻量规则（见 `review-routing.md`）时，才允许跳过 `/review` 直接提交；否则仍必须先完成 `/review` 与 `/done`。
- **`git push` 语义**：凡经 `/done` 或等价收尾流程推送代码，**必须先过 C-lite supervisor 的 push 段**（见 `.agents/commands/done.md`），不得跳过 supervisor 直接执行底层求解流程。

**例外 — Wave 间 checkpoint commit**：当当前权威计划文件采用 Wave 分阶段结构，且当前串行 Wave 已全部完成、即将进入下一个并行 Wave 时，允许一次轻量 checkpoint commit（commit message 前缀 `wip:`），无需触发 `/done` 完整逻辑。

---

## 2. 编码拦截 (Auto-Plan Hook)

**触发条件**：用户直接丢来一个大需求（如"帮我开发一个登录功能"、"修复支付页面的 bug"），而没有使用 `/plan`。

**强制动作**：绝对不允许直接写业务代码。必须先引导：
> "我注意到这是一个新需求。为了保证架构一致性，我们需要先进行规划。我将为您执行 `/plan` 流程..."

然后按 `/plan` 逻辑读取 `/docs/arch/` 规范并生成项目根 `CURRENT_PLAN.md`。

---

## 3. 状态感知 (Context Awareness)

### 3a. 新对话自动感知（替代手动 `/onboard`）

**触发条件**：对话的**第一条用户消息**到达时。

**静默动作**（无需用户指示，AI 自动执行）：
1. 检查当前权威计划文件是否存在且有未完成任务 `[ ]`
2. 如有未完成计划，在回复开头用一句话告知用户当前进度（如"当前有进行中的计划：XXX，进度 5/8"），然后正常响应用户请求
3. 如无未完成计划，无需额外输出，直接响应用户请求

> 无需手动执行 `/onboard`。AGENTS.md 已由 IDE 自动加载，项目上下文在对话开始时即已具备。

### 3b. 开发阶段锁定

如果当前权威计划文件存在且有未打勾 `[ ]` 的任务，当前处于"开发执行阶段"。所有回答和代码修改必须严格围绕未完成的计划展开，不要偏离主线。

---

## 4. 评审门控 (Auto-Review Hook)

**触发词**："review" / "评审" / "代码审查" / "看看代码" / "检查一下" / "merge 前"

**强制动作**：
- 加载 `/review` 命令执行完整的代码评审流程。
- 如果当前存在权威计划上下文（`CURRENT_PLAN.md` 存在，且包含已完成 `[x]` 或未完成 `[ ]` 任务），自动进入 **Scope Drift Detection** 模式：对比计划 vs 实际 diff。
- 如果没有权威计划上下文，进入 **Standalone Review** 模式：只审当前 staged changes。

---

## 4b. PR / MR 前置门禁（C-lite supervisor）

**触发词**："提 MR" / "提 PR" / "创建 PR" / "merge request" / "pull request"

**语义**：PR/MR 的唯一门禁是 **C-lite supervisor** 的 **PR 段**；低风险自动求解只是其中一个受控子步骤。

**强制动作**：
1. **先进入 supervisor PR 入口**（实现侧如 `pnpm supervisor pr`，以仓库脚本为准）：完成相对基线的冲突预检、风险分层（L0 可编排 resolver / L1 阻断）、以及 PR 创建前应有的集成状态核对。
2. **在 supervisor 判定可继续且需要自动求解时**，由 supervisor 内部编排对应求解步骤；**不得**绕过 supervisor 把底层求解当作唯一门禁。
3. 解析结果（JSON 或统一输出格式）：
   - **`state` 为 `verified`（或 supervisor 定义的等价「允许继续」）**：确保当前分支已 **push** 到远端后，再执行 `gh pr create` 或更新现有 PR / MR。
   - **`state` 为 `blocked`**：禁止创建或更新 PR / MR；向用户报告 **supervisor 给出的阻断原因**与建议（人工合并、拆 PR、回滚部分变更等）。
4. **推荐顺序固定为**：`pnpm supervisor pr`（含风险分层与必要自动求解）→ `git push`（若尚未推送）→ `gh pr create` / 更新 PR。

**与 Apply / push 闸门的对齐**：并行 Wave 或 Worktree 合入后的检查见 `.agents/rules/workflow-parallel-dev.md`（**Apply** 段）；`/done` 中推送前检查见 **push** 段。三段式共同构成 MR 前的完整监督面，而非仅 PR 单点。

---

## 5. UI 规范守卫 (UI Rules Guard)

**触发条件**：任务涉及界面开发、页面布局、视觉设计、前端组件、样式调整、动效与交互或任何用户可见的 Web 页面或 UI 元素。

**强制动作**：必须先读取并严格遵循 `.agents/rules/ui-visual-design.md` 中的 UI 设计规范。不得使用与规范冲突的样式方案；若用户需求与规范冲突，应优先按规范实现并说明原因。

---

## 6. 写库操作固定流程 (DB Write Protocol)

**触发条件**：任何会导致环境数据变化的操作，包括但不限于：
- 调用会写入数据的 API（`POST/PUT/PATCH/DELETE`，或会触发创建/更新的 `POST /api/chat`）
- 运行会写库的 E2E/curl 脚本
- 通过脚本/工具直接写 MySQL/Wuji/Redis/COS 持久化数据

**强制动作（必须按顺序执行）**：
1. **先征得用户同意（硬门禁）**：在执行前明确告知将写入哪些数据与影响范围，未得到用户明确同意前，禁止执行写操作。
2. **使用测试标识**：测试数据必须使用可检索前缀（如 `e2e-temp-` / `ai-test-`），便于回收。
3. **执行后立刻回报**：写操作完成后，向用户回报实际写入结果（创建/更新/删除了什么）。
4. **默认回收清理**：测试验证结束后，默认执行清理（删除测试项目及关联会话/消息/制品等）；仅当用户明确要求“保留测试数据”时才保留。
5. **清理可验证**：清理后必须做二次校验（如返回 404 或列表中不存在），并将校验结果回报给用户。

**禁止项**：
- 未告知、未同意即写库
- 使用真实业务数据做不可回收测试
- 写完不清理且不告知用户残留范围
