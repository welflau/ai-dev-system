---
name: think
description: "需求深度思考与设计简报，产出 DESIGN_BRIEF.md（严禁写代码）"
argument-hint: "[需求描述]"
---

同 `/think` Claude 版。产出 `DESIGN_BRIEF.md`（状态 APPROVED + 选定路径）后引导运行 `/plan`。

需求思考四阶段：
1. 读取 git log 和现有计划文件了解上下文
2. 追问需求真实性、现状分析、最小楔子（Feature）或快速诊断（Bugfix/Refactor）
3. 前提挑战：换框架是否更简单？现有代码已解决多少？
4. 产出 2-3 条实现路径，让用户选定后写入 DESIGN_BRIEF.md
