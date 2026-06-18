---
description: Git 提交规范 — commit message 格式、语言、分支命名等。所有涉及 git 操作时自动生效。
title: Git Conventions
tags: git, commit, convention
alwaysApply: true
globs: []
enabled: true
updatedAt: 2026-03-18
---

# Git 提交规范

## Commit Message

### 语言

Commit message **必须使用中文**撰写（类型前缀保留英文）。

### 格式

采用 Conventional Commits 格式：

```
<type>(<scope>): <中文描述>

<可选的详细说明>
```

**类型前缀**：

| 前缀 | 用途 |
|------|------|
| `feat` | 新功能 |
| `fix` | 缺陷修复 |
| `refactor` | 重构（不改变外部行为） |
| `docs` | 文档变更 |
| `style` | 代码格式（不影响逻辑） |
| `perf` | 性能优化 |
| `test` | 测试相关 |
| `chore` | 构建/工具/依赖变更 |
| `wip` | Wave 间 checkpoint（不触发 `/done`） |

**scope**：可选，标注影响范围（如 `web`、`server`、`runtime`、`workflow`、`agents`）。

### 示例

```
feat(web): 新增游戏预览全屏模式
fix(server): 修复 SSE 连接超时未重连的问题
refactor(runtime): 统一场景管理器的生命周期钩子
docs: 更新架构文档中的 L2 编排层描述
wip: 完成 Wave 0 基础设施搭建
```
