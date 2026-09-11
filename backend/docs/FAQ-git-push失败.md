---
title: Git Push 失败 — 引导修复手册
type: howto
feature: git-ops
role: pm
tags: [git, push, 排障, 引导]
---

# Git Push 失败：不要让用户自己找原因

系统流水线（Planner `write_prd` / Dev 提交等）会 **commit 成功、push 失败**。
正确做法是：**分类原因 → 给出下一步按钮**，而不是「请检查仓库是否存在及网络连通性」。

本地提交一般已经成功，工单可以继续。缺的是远端同步。

## 归类（这类知识放哪）

| 知识类型 | 放哪 | 不要放哪 |
|---|---|---|
| **通用排障手册**（本文） | 全局知识库 `docs/` / FAQ | 项目 wiki、单次工单 |
| **这一次失败** | `ticket_logs`（`git_push_failed` / `ToolError:git:push_failed`） | 当作成品需求文档 |
| **某项目特有环境**（私有镜像、特殊 remote） | 项目知识库 `已知问题/` 或 `.ads/wiki/` | 全局 FAQ |
| **运行时按钮**（重试推送 / 创建仓库） | 代码 `classify_push_failure` + `/git/push` API | 只写在 Markdown 里点不了 |

失败案例库 `failure_cases` 面向 **编译/测试/返工** 的相似坑，不适合当 Git 运维手册。

## 原因 → 下一步

| reason | 含义 | 用户下一步 |
|---|---|---|
| `blocked_main` | Agent 禁止直推 main/master | 「推送到远端」（用户确认后允许推主干） |
| `no_remote` | 没有 origin | 「创建 GitHub 仓库并推送」或去仓库设置填地址 |
| `repo_missing` | 远端仓库不存在或没权限 | 「创建仓库并重试推送」 |
| `auth` | gh / token / 写权限 | 本机 `gh auth login` 后「重试推送」 |
| `rejected` | 远端更新，非快进 | 「拉取后推送」 |
| `network` | DNS / 超时 / 连不上 | 检查网络后「重试推送」 |

## 助手怎么用

用户问「push 失败怎么办 / 代码没到 GitHub」时：

1. `search_knowledge` 查本手册
2. 说明 **本地已提交、远端未同步**
3. 引导点聊天里的修复按钮，或打开 **设置 → 仓库配置**
4. 不要只回「检查网络和仓库是否存在」
