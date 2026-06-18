---
description: 六阶段开发闭环模型 — think → plan → execute → review → done → retro。定义每个阶段的职责、产出物和衔接规则。
title: Sprint Lifecycle
impact: HIGH
impactDescription: 确保完整开发闭环，防止跳过评审或复盘阶段
tags: workflow, lifecycle, sprint, think, plan, execute, review, done, retro
alwaysApply: false
globs: ["CURRENT_PLAN.md", "DESIGN_BRIEF.md"]
enabled: true
updatedAt: 2026-03-19
---

# 六阶段开发闭环

```
think → plan → execute → review → done → retro
  │       │       │         │       │       │
  │       │       │         │       │       └─ 复盘：git 数据分析 + 改进点
  │       │       │         │       └─ 收尾：文档同步 + CHANGELOG + 版本号
  │       │       │         └─ 评审：Two-pass code review + Fix-First
  │       │       └─ 执行：Wave 串行/并行编码 + 测试
  │       └─ 规划：架构设计 + Wave 拆分 + `CURRENT_PLAN.md`
  └─ 产品思维：Forcing Questions + Premise Challenge + 备选方案
```

## 阶段定义

| # | 阶段 | 命令 | 产出物 | 强制性 |
|---|------|------|--------|--------|
| 1 | Think | `/think` | `DESIGN_BRIEF.md` | 推荐（可跳过直接 `/plan`） |
| 2 | Plan | `/plan` | `CURRENT_PLAN.md` | **强制** |
| 3 | Execute | `/execute` | 代码变更 + 测试通过 | **强制** |
| 4 | Review | `/review` | Review Dashboard（Pass/Fail） | 推荐（`/done` 会检查） |
| 5 | Done | `/done` | CHANGELOG + 文档同步 + commit | **强制** |
| 6 | Retro | `/retro` | `.agents/memory/retros/` 快照 | 推荐（sprint 结束时） |

## 衔接规则

1. **Think → Plan**：`/plan` 会自动检查是否存在 `DESIGN_BRIEF.md`，如有则读取并交叉参考
2. **Plan → Execute**：`/execute` 读取当前权威计划文件 `CURRENT_PLAN.md`，如不存在或为空则拒绝执行
3. **Execute → Review**：`/execute` 完成后提示运行 `/review`（非强制）
4. **Review → Done**：`/done` 的 Step 1 后检查 Review Readiness（轻量变更可跳过）
5. **Done → Retro**：`/done` 完成后提示运行 `/retro`（非强制，建议在 sprint 或里程碑结束时运行）

## 评审路由矩阵

根据变更类型自动选择评审维度：

| 变更涉及目录 | 评审维度 |
|-------------|---------|
| `apps/web/` | 前端架构 + UI 规范 + 可访问性 |
| `apps/server/` | 后端架构 + API 契约 + 安全 |
| `apps/runtime/` | 运行时安全 + 沙箱隔离 + 平台兼容 |
| `packages/*` | 类型安全 + 跨包一致性 + 向后兼容 |
| `.agents/` | 规则/技能格式规范 + 命令衔接 |
| `docs/` | 文档-代码一致性 |

## 快捷路径

对于简单修复（单文件 < 50 行改动），允许简化流程：

```
plan → execute → done
```

省略 think、review、retro。但 `/done` 仍为强制步骤。
