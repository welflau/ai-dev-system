---
name: execute
description: "按 Wave 阶段全自动执行编码"
argument-hint: "[wave编号 | 空=全自动]"
---

读取 `CURRENT_PLAN.md`，从第一个含 `[ ]` 的 Wave 开始，全自动执行直到所有 Wave 完成。

串行 Wave 直接编码 + 测试；并行 Wave 通过 Task 工具派发 Subagent 并行执行。
每完成一个任务立即打勾 `[x]`。全部完成后提示运行 `/review`。
