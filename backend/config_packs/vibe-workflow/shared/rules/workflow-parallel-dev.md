---
description: 多 Agent 并行开发的 Wave 拆分规则 — 任务依赖分析、文件边界划分、串行/并行判定、执行策略选择。执行 /plan 或涉及多模块需求拆分时必读。
title: Parallel Dev Wave Rules
impact: HIGH
impactDescription: 防止并行 Agent 文件冲突、确保前置依赖就绪
tags: workflow, parallel, worktree, subagent, wave, task-split
alwaysApply: false
globs: ["CURRENT_PLAN.md"]
enabled: true
updatedAt: 2026-03-27
---

# 多 Agent 并行开发规则

## IDE 识别

AI 通过系统提示词自动识别当前 IDE（如 "You operate in Cursor."）。
- **Cursor**：支持 Worktree + Subagent
- **CodeBuddy**：仅支持 Subagent（无 Worktree）

## Wave 模型

任务按 Wave 分阶段，Wave 间串行，Wave 内可并行：

```
Wave 0 (串行) → Wave 1 (并行) → Wave 2 (串行)
前置依赖         独立开发         集成验证
```

| Wave 类型 | 执行模式 | 典型内容 |
|-----------|---------|---------|
| 前置 Wave | 串行 | 共享类型 (`packages/*`)、接口协议、数据库 schema |
| 并行 Wave | 并行 | 前端 / 后端 / 运行时各自独立开发 |
| 集成 Wave | 串行 | 联调、`pnpm typecheck`、`pnpm test`、E2E |

## 并行拆分条件（全部满足才可并行）

1. 各 Agent 的**目录范围无交集**
2. 各 Agent **不互相依赖**对方的产出（共享依赖在前置 Wave 完成）
3. 每个 Agent 的任务**自包含**，可独立运行测试验证

不满足时退化为串行。

## 并行执行策略

| 策略 | 与主目录隔离 | Agent 间隔离 | 手动操作 | IDE 支持 | 适用场景 |
|------|:-----------:|:-----------:|:-------:|---------|---------|
| **Local + Subagent** | ❌ | ❌ | 自动 | 通用 | **`/execute` 默认路径**；Cursor / CodeBuddy 通用 |

选择规则：
- 普通 `/execute` → Local + Subagent（Cursor / CodeBuddy 均如此）
- 只有 1 个并行 Agent → 退化为串行

## 项目天然拆分边界

```
apps/web/        ← 前端 Agent（vue-tsc 类型检查）
apps/server/     ← 后端 Agent（tsc 类型检查）
apps/runtime/    ← 运行时 Agent（tsc 类型检查）
packages/*       ← 共享类型（前置 Wave，先完成再并行）
```

## CURRENT_PLAN.md 格式要求

- 项目根 `CURRENT_PLAN.md` 采用以下格式
- 每个 Wave 标题标注执行模式：`## Wave N: 描述（串行）` 或 `（并行）`
- 并行 Wave 按 `### Agent X: 角色 · 目录范围` 分组
- 每个 Agent 标注两层文件信息：
  - **目录范围**（硬约束）：Agent 只能在此目录内操作，如 `apps/web/`
  - **已有文件**（参考）：列出需要修改的现有文件，帮助理解上下文
  - Agent 可在目录范围内**自由新增文件**，无需预先穷举
## Subagent Prompt 动态合成

`/execute` 在运行时从项目根 `CURRENT_PLAN.md` 的 Agent 分组信息（任务清单 + 目录范围 + 约束）**动态合成** Subagent Prompt。无需在计划文件中手写附录。

每个 Agent Prompt 自动包含：
- 只在指定目录范围内操作（可修改已有文件、可新增文件）
- 不要触碰其他 Agent 目录范围内的文件
- 完成后运行 `pnpm typecheck` 和测试
- 将自己负责的任务在当前权威计划文件中打勾 `[x]`

## ⚠️ Worktree 已知陷阱

### 陷阱 1：detached HEAD 导致 commit/push 失败

**问题**：Cursor Worktree 中运行的 Chat 处于 **detached HEAD** 状态。在此状态下执行 `git commit` 会创建孤立 commit，`git push` 会失败或推到错误位置。

**检测方法**：`git branch --show-current` — 输出为空即为 detached HEAD。

**正确做法**：
1. Worktree Chat 中**只做代码修改**，不 commit、不 push
2. 修改完成后点击 Cursor 的 **Apply** 将变更合回主分支
3. 回到主分支 Chat 执行 `/done`（含 commit & push）

**如果已经在 Worktree 中误 commit 了**：
1. 记录 commit hash：`git log --oneline -1`
2. 回到主仓库分支
3. 执行 `git cherry-pick <commit-hash>` 将 commit 合入主分支
4. 再 `git push`

> `/done` 命令的 **Commit & Push** 步骤已内置 detached HEAD 检测，会自动拦截并提示。

### 陷阱 2：Worktree 中 `.cursor/rules` 缺失，AI 无法加载项目规则

**问题**：Cursor 的 rules/commands/skills 通过 `.cursor/` 目录下的软链加载。主仓库通过 `link-ide.sh` 创建了 `.cursor/rules -> ../.agents/rules` 等软链，但 Worktree 是独立的工作目录，不会继承这些软链。导致 **Worktree Chat 中 AI 完全无法感知项目级规则**（如 commit 拦截、编码拦截等）。

**防护机制**（已实现）：
- `worktrees.json` 的 `setup-worktree` 包含 `./scripts/link-ide.sh`，新建 Worktree 时自动创建软链
- `link-ide.sh` 在主仓库执行时（`pnpm install` 触发），自动扫描 `~/.cursor/worktrees/<project>/*/` 下的已有 Worktree 并补建软链

**如果发现 Worktree 中规则未生效**：手动在主仓库执行 `npm run link-ide` 即可修复。

## 编码完成后的集成监督（C-lite supervisor）

并行开发下，**冲突与集成风险**由 **C-lite supervisor** 统一闸门语义治理；内置的低风险自动求解器只作为其**受控子能力**，不单独作为唯一入口。

### 三段式触发（必须覆盖）

| 阶段 | 典型时机 | Supervisor 关注点 |
|------|----------|-------------------|
| **Apply** | Worktree / Subagent 产出合回主工作区后；并行 Wave 全部 Apply 完毕、进入下一 Wave 或集成验证前 | 工作区是否出现跨目录边界变更、重复编辑同一文件、与计划目录范围不符的 diff；是否需在集成前先做 `typecheck` / 定向测试 |
| **push** | `.agents/commands/done.md` 的 `Commit & Push` 中，**真正执行 `git push` 之前** | 与远端/主干是否分叉、是否存在未解决合并冲突、push 是否会将高风险变更送出 |
| **PR** | 用户明确提出「提 MR / PR / merge request」或创建/更新 PR 之前 | 分支相对基线的冲突预检、是否满足 MR 硬门禁前的集成状态、是否需先 push 再开 PR |

补充：若本地已处于 `rebase` / `merge` 冲突未解决状态，**任一**触发阶段均应先进入 supervisor，**禁止**跳过闸门直接 `push` 或开 PR。

### Supervisor 角色（C-lite）

Supervisor 负责 **风险分层与编排决策**，而非替代人类审查：

1. **归类**：将当前变更与冲突映射到风险层（见下节）。
2. **路由**：低风险且落在当前自动求解白名单内 → 可编排调用内置 resolver 自动尝试；中高风险 → **阻断**并输出原因与建议动作（人工解决、拆 PR、回滚部分 Apply 等）。
3. **验证门禁**：任何自动 resolve 路径必须在 supervisor 语义下要求 **`pnpm typecheck` + 约定测试**（与 `workflow-guardrails`、`.ci/test-gate.yaml` MR 硬门禁口径一致），失败则保持阻断。
4. **与 `/execute` / `/done` 衔接**：并行 Wave 结束后的集成监督见 `.agents/commands/execute.md`；收尾 push 见 `.agents/commands/done.md`。

**入口约定（实现由仓库脚本/流水线落地）**：统一以 supervisor 为闸门，例如 `pnpm supervisor apply`、`pnpm supervisor push`、`pnpm supervisor pr`（具体脚本名以根 `package.json` 为准）。AI 执行时**不得**绕过 supervisor 直接调用底层求解器，除非仓库尚未落地 supervisor 且用户明确授权降级（降级须在回复中声明并仍完成同等检查清单）。

### 风险分层（与当前自动求解边界对齐）

- **L0 · 可自动尝试（当前自动求解白名单内）**  
  - 目录：`apps/web/src/`、`apps/server/src/`、`apps/runtime/src/`  
  - 条件：单文件、低风险文本/导入/局部实现冲突；且 supervisor 判定无跨 Agent 目录违约  
  - 动作：supervisor 编排执行内置低风险求解与验证

- **L1 · 阻断（须人工或专项流程）**  
  - 路径示例：`packages/shared-types/`、`packages/sse-protocol/`、`packages/sandbox-protocol/`、`pnpm-lock.yaml`、根 `package.json`、`.ci/`、`apps/server/src/db/`、`apps/server/src/publish/`、`apps/server/src/api/`、`apps/server/src/security/`  
  - 以及：多文件纠缠、协议/契约冲突、安全与发布相关变更

### 内置求解器与 supervisor 的关系

```
[ 三段式触发: Apply | push | PR ]
           ↓
   C-lite supervisor（风险分层 + 编排 + 验证要求）
           ↓
   ├─ L0 → 内置低风险求解器（detect → collect → resolve → verify）
   └─ L1 → 阻断，不自动合并
```

### 执行要求（继承并加强）

- 不允许在检测到远端或主干冲突后直接重试 `push`
- 不允许跳过上下文收集与风险分层直接做文本拼接式合并
- 不允许在验证失败后继续 `push` 或合并 MR/PR
- 高风险或超出 L0 范围的冲突必须保持阻断状态，由 supervisor 输出可操作的下一步，而不是勉强自动合并

### 非触发范围

除上述 **Apply / push / PR** 与显式冲突场景外，日常本地 Git 操作**不默认**拉起完整 supervisor；若用户显式要求「集成检查」「合并前检查」，应按 **push** 或 **PR** 语义选用对应闸门。
