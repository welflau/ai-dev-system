---
name: onboard
description: "项目上下文快速对齐（读持久化文档 + 增量分析）"
---

# /onboard — 项目快速上下文

快速对齐项目上下文，适合新会话开始时执行。

## Step 1: 静默读取核心文档

依次读取（如存在）：
- `README.md` — 项目概览、技术栈、常用脚本
- `AGENTS.md` — AI 工作流约定、架构红线
- `CURRENT_PLAN.md` — 当前执行计划状态
- `DESIGN_BRIEF.md` — 当前设计简报状态
- `CHANGELOG.md` — 最近 5 个版本（了解演进方向）

## Step 2: 增量分析

```bash
git log --oneline -10      # 最近提交
git diff --stat HEAD~3     # 近期变更范围
git status                 # 当前工作区状态
```

## Step 3: 输出上下文摘要

```
项目：{名称} v{版本}
技术栈：{栈}
当前计划：{IDLE / IN PROGRESS — Wave X}
近期提交：{最近 3 条}
工作区：{clean / N 个未提交变更}
```

## Step 4: 识别待办

- 若 `CURRENT_PLAN.md` 有进行中任务 → "检测到未完成计划，建议运行 `/execute` 继续"
- 若工作区有未提交变更 → "检测到未提交变更，建议先运行 `/done` 收尾"
- 若一切干净 → "项目状态干净，可运行 `/think` 开始新需求"
