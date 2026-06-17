---
name: review
description: "代码评审：Scope Drift 检测 + Two-Pass Review + Fix-First"
---

获取 `git diff origin/main` 做两轮评审：
- Pass 1 (CRITICAL)：安全边界、外部数据校验、竞态条件
- Pass 2 (INFORMATIONAL)：死代码、魔法数字、测试缺口

AUTO-FIX 直接应用，ASK 项批量询问用户，BLOCK 项必须修复才能继续。
输出 Review Readiness Dashboard，CLEARED 后可运行 `/done`。
