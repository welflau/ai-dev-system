---
name: onboard
description: "项目快速对齐：读文档 + git 状态 + 输出摘要"
---

读取 README.md、AGENTS.md、CURRENT_PLAN.md、CHANGELOG 最近 5 版，运行 `git log --oneline -10` 和 `git status`。
输出项目摘要（版本、技术栈、当前计划状态、近期提交、工作区状态）并识别待办。
