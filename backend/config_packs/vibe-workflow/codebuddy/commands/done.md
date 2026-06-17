---
name: done
description: "任务收尾：文档同步 + CHANGELOG + 版本号 + commit"
argument-hint: "[--skip-review]"
---

收尾流程：
1. 校验 CURRENT_PLAN.md 无未完成任务
2. 检查是否通过 /review（轻量变更可跳过）
3. 审计文档是否需要同步（事实性直接修改，叙述性询问）
4. 更新 CHANGELOG.md（用"现在可以…"格式，内部改进放子段）
5. 重置 CURRENT_PLAN.md 为 IDLE
6. 确认后 git add -A && git commit && git push
